"""Deterministic execution of RLR maintenance verification profiles."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .bounded_process import DEFAULT_MAX_OUTPUT_BYTES, run_bounded_process
from .profiles import get_profile


VERIFICATION_RECEIPT_SCHEMA = "RLRVerificationReceipt/v1"
VERIFICATION_COMMAND_TIMEOUT = 3600.0


@dataclass(frozen=True)
class VerificationStepResult:
    step_id: str
    command: tuple[str, ...]
    required: bool
    returncode: int
    stdout_sha256: str
    stdout_bytes: int
    stderr_sha256: str
    stderr_bytes: int


@dataclass(frozen=True)
class VerificationReceipt:
    schema_version: str
    profile_id: str
    passed: bool
    steps: tuple[VerificationStepResult, ...]


def _digest_text(value: str | None) -> tuple[str, int]:
    data = (value or "").encode("utf-8")
    return hashlib.sha256(data).hexdigest(), len(data)


def run_profile(
    profile_id: str,
    repo_root: str | Path,
    *,
    runner: Callable[..., object] | None = None,
    timeout: float = VERIFICATION_COMMAND_TIMEOUT,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> VerificationReceipt:
    """Run one immutable verification profile from an explicit repository root.

    The verifier is deliberately non-cognitive: it executes declared argv in
    order, records bounded digests, and stops after a required failure. Repair,
    retry, and policy changes belong outside this boundary.
    """
    profile = get_profile(profile_id)
    root = Path(repo_root)
    results: list[VerificationStepResult] = []
    passed = True
    if timeout <= 0:
        raise ValueError("verification timeout must be positive")
    started = time.monotonic()

    for step in profile.required_validation:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            results.append(
                VerificationStepResult(
                    step_id=step.step_id,
                    command=step.command,
                    required=step.required,
                    returncode=124,
                    stdout_sha256=_digest_text("")[0],
                    stdout_bytes=0,
                    stderr_sha256=_digest_text("")[0],
                    stderr_bytes=0,
                )
            )
            passed = False
            break
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
        terminal_state = getattr(completed, "terminal_state", "completed")
        output_truncated = bool(
            getattr(completed, "stdout_truncated", False)
            or getattr(completed, "stderr_truncated", False)
        )
        if terminal_state == "timed_out":
            returncode = 124
        else:
            returncode = int(getattr(completed, "returncode"))
            if output_truncated and returncode == 0:
                returncode = 1
        stdout_sha, stdout_bytes = _digest_text(getattr(completed, "stdout", ""))
        stderr_sha, stderr_bytes = _digest_text(getattr(completed, "stderr", ""))
        results.append(
            VerificationStepResult(
                step_id=step.step_id,
                command=step.command,
                required=step.required,
                returncode=returncode,
                stdout_sha256=stdout_sha,
                stdout_bytes=stdout_bytes,
                stderr_sha256=stderr_sha,
                stderr_bytes=stderr_bytes,
            )
        )
        if step.required and returncode != 0:
            passed = False
            break

    return VerificationReceipt(
        schema_version=VERIFICATION_RECEIPT_SCHEMA,
        profile_id=profile.profile_id,
        passed=passed,
        steps=tuple(results),
    )
