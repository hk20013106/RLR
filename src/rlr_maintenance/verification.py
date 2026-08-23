"""Deterministic execution of RLR maintenance verification profiles."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .bounded_process import DEFAULT_MAX_OUTPUT_BYTES, run_bounded_process
from .profiles import get_profile


VERIFICATION_RECEIPT_SCHEMA = "RLRVerificationReceipt/v2"
VERIFICATION_RECEIPT_FILENAME = "verification_receipt.json"
VERIFICATION_COMMAND_TIMEOUT = 3600.0


@dataclass(frozen=True)
class VerificationStepResult:
    step_id: str
    command: tuple[str, ...]
    required: bool
    returncode: int
    terminal_state: str
    duration_seconds: float
    timed_out: bool
    output_truncated: bool
    stdout_sha256: str
    stdout_bytes: int
    stderr_sha256: str
    stderr_bytes: int
    stdout_evidence: str
    stderr_evidence: str


@dataclass(frozen=True)
class VerificationReceipt:
    schema_version: str
    profile_id: str
    passed: bool
    started_at: str
    ended_at: str
    failed_step_id: str | None
    failure_reason: str | None
    steps: tuple[VerificationStepResult, ...]
    unexecuted_step_ids: tuple[str, ...]
    receipt_path: Path
    receipt_sha256: str


def _digest_text(value: str | None) -> tuple[str, int]:
    data = (value or "").encode("utf-8")
    return hashlib.sha256(data).hexdigest(), len(data)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_tail(value: str | None, max_bytes: int) -> str:
    data = (value or "").encode("utf-8")
    if max_bytes <= 0:
        return ""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace")
    return data[-max_bytes:].decode("utf-8", errors="replace")


def _step_result(
    *,
    step: object,
    returncode: int,
    terminal_state: str,
    duration_seconds: float,
    stdout: str,
    stderr: str,
    stdout_bytes: int | None,
    stderr_bytes: int | None,
    stdout_truncated: bool,
    stderr_truncated: bool,
    max_output_bytes: int,
    stdout_evidence: str | None = None,
    stderr_evidence: str | None = None,
) -> VerificationStepResult:
    stdout_sha, captured_stdout_bytes = _digest_text(stdout)
    stderr_sha, captured_stderr_bytes = _digest_text(stderr)
    return VerificationStepResult(
        step_id=str(getattr(step, "step_id")),
        command=tuple(str(token) for token in getattr(step, "command")),
        required=bool(getattr(step, "required")),
        returncode=int(returncode),
        terminal_state=str(terminal_state),
        duration_seconds=max(0.0, float(duration_seconds)),
        timed_out=terminal_state == "timed_out",
        output_truncated=bool(stdout_truncated or stderr_truncated),
        stdout_sha256=stdout_sha,
        stdout_bytes=int(stdout_bytes) if stdout_bytes is not None else captured_stdout_bytes,
        stderr_sha256=stderr_sha,
        stderr_bytes=int(stderr_bytes) if stderr_bytes is not None else captured_stderr_bytes,
        stdout_evidence=(
            stdout_evidence
            if stdout_evidence is not None
            else _bounded_tail(stdout, max_output_bytes)
        ),
        stderr_evidence=(
            stderr_evidence
            if stderr_evidence is not None
            else _bounded_tail(stderr, max_output_bytes)
        ),
    )


def _receipt_payload(receipt: VerificationReceipt) -> dict[str, object]:
    payload = asdict(receipt)
    payload["receipt_path"] = str(receipt.receipt_path)
    payload["steps"] = [
        {**asdict(step), "command": list(step.command)} for step in receipt.steps
    ]
    payload["unexecuted_step_ids"] = list(receipt.unexecuted_step_ids)
    # The hash is kept outside the JSON body because hashing a file that
    # contains its own hash would be self-referential.
    payload.pop("receipt_sha256", None)
    return payload


def _persist_receipt(receipt: VerificationReceipt) -> tuple[Path, str]:
    path = receipt.receipt_path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        _receipt_payload(receipt), ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path, hashlib.sha256(data).hexdigest()


def run_profile(
    profile_id: str,
    repo_root: str | Path,
    *,
    runner: Callable[..., object] | None = None,
    timeout: float = VERIFICATION_COMMAND_TIMEOUT,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    receipt_path: str | Path | None = None,
) -> VerificationReceipt:
    """Run one immutable profile and persist a PASS or FAIL receipt."""
    profile = get_profile(profile_id)
    root = Path(repo_root)
    destination = Path(receipt_path) if receipt_path is not None else root / VERIFICATION_RECEIPT_FILENAME
    results: list[VerificationStepResult] = []
    passed = True
    failed_step_id: str | None = None
    failure_reason: str | None = None
    if timeout <= 0:
        raise ValueError("verification timeout must be positive")
    started_monotonic = time.monotonic()
    started_at = _now()
    steps = tuple(profile.required_validation)
    unexecuted: list[str] = []

    for index, step in enumerate(steps):
        remaining = timeout - (time.monotonic() - started_monotonic)
        if remaining <= 0:
            passed = False
            failure_reason = f"verification budget exhausted before step {step.step_id}"
            unexecuted.extend(item.step_id for item in steps[index:])
            break

        step_started = time.monotonic()
        try:
            if runner is None:
                completed = run_bounded_process(
                    list(step.command),
                    timeout=remaining,
                    cwd=root,
                    max_output_bytes=max_output_bytes,
                )
            else:
                completed = runner(
                    list(step.command),
                    cwd=root,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    shell=False,
                    timeout=remaining,
                )
        except Exception as exc:
            result = _step_result(
                step=step,
                returncode=127,
                terminal_state="launch_failed",
                duration_seconds=time.monotonic() - step_started,
                stdout="",
                stderr=f"{type(exc).__name__}: {exc}",
                stdout_bytes=0,
                stderr_bytes=None,
                stdout_truncated=False,
                stderr_truncated=False,
                max_output_bytes=max_output_bytes,
            )
            results.append(result)
            passed = False
            failed_step_id = result.step_id
            failure_reason = "verification command could not be launched"
            unexecuted.extend(item.step_id for item in steps[index + 1 :])
            break

        terminal_state = str(getattr(completed, "terminal_state", "completed"))
        stdout_truncated = bool(getattr(completed, "stdout_truncated", False))
        stderr_truncated = bool(getattr(completed, "stderr_truncated", False))
        output_truncated = stdout_truncated or stderr_truncated
        raw_returncode = getattr(completed, "returncode", None)
        if terminal_state == "timed_out":
            returncode = 124
        elif raw_returncode is None:
            returncode = 1
        else:
            returncode = int(raw_returncode)
            if output_truncated and returncode == 0:
                returncode = 1
        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        result = _step_result(
            step=step,
            returncode=returncode,
            terminal_state=terminal_state,
            duration_seconds=time.monotonic() - step_started,
            stdout=stdout,
            stderr=stderr,
            stdout_bytes=getattr(completed, "stdout_bytes", None),
            stderr_bytes=getattr(completed, "stderr_bytes", None),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            max_output_bytes=max_output_bytes,
            stdout_evidence=getattr(completed, "stdout_tail", None),
            stderr_evidence=getattr(completed, "stderr_tail", None),
        )
        results.append(result)
        if step.required and returncode != 0:
            passed = False
            failed_step_id = result.step_id
            failure_reason = (
                "verification step timed out"
                if result.timed_out
                else "required verification output truncated"
                if result.output_truncated and returncode != 0
                else "required verification step failed"
            )
            unexecuted.extend(item.step_id for item in steps[index + 1 :])
            break

    ended_at = _now()
    receipt = VerificationReceipt(
        schema_version=VERIFICATION_RECEIPT_SCHEMA,
        profile_id=profile.profile_id,
        passed=passed,
        started_at=started_at,
        ended_at=ended_at,
        failed_step_id=failed_step_id,
        failure_reason=failure_reason,
        steps=tuple(results),
        unexecuted_step_ids=tuple(unexecuted),
        receipt_path=destination,
        receipt_sha256="",
    )
    persisted_path, digest = _persist_receipt(receipt)
    return replace(receipt, receipt_path=persisted_path, receipt_sha256=digest)
