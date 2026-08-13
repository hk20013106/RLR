"""Deterministic execution of RLR maintenance verification profiles."""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .profiles import get_profile


VERIFICATION_RECEIPT_SCHEMA = "RLRVerificationReceipt/v1"


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
    runner: Callable[..., object] = subprocess.run,
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

    for step in profile.required_validation:
        completed = runner(
            list(step.command),
            cwd=root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            shell=False,
        )
        returncode = int(getattr(completed, "returncode"))
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
