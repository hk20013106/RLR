"""Normalize authoritative software/runtime facts into maintenance events."""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

from .contracts import build_maintenance_event


def _basename(token: str) -> str:
    text = str(token)
    if PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute():
        return PureWindowsPath(text).name or PurePosixPath(text).name
    return text


def _compact_command(command: Sequence[str]) -> list[str]:
    """Keep program identity while excluding task-specific/private arguments."""
    if not command:
        raise ValueError("command must contain at least one argv token")

    first = _basename(str(command[0]))
    identity = [first]
    if first.lower().startswith("python") and len(command) > 1:
        second = _basename(str(command[1]))
        identity.append(second)
        if second == "-m" and len(command) > 2:
            identity.append(_basename(str(command[2])))
    return identity


def observe_contract_failure(
    *,
    component: str,
    error_code: str,
    expected_contract: str,
    rlr_revision: str,
    observed_at: str,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    severity: str = "blocking",
) -> dict[str, Any]:
    """Record only the stable contract error code; details remain in evidence refs."""
    return build_maintenance_event(
        event_type="contract_failure",
        component=component,
        severity=severity,
        observed_at=observed_at,
        rlr_revision=rlr_revision,
        observed={"error_code": str(error_code)},
        expected_contract=expected_contract,
        evidence_refs=evidence_refs,
        source_receipts=source_receipts,
        suggested_route="repair",
    )


def observe_process_failure(
    *,
    component: str,
    command: Sequence[str],
    exit_code: int,
    expected_contract: str,
    rlr_revision: str,
    observed_at: str,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    severity: str = "blocking",
) -> dict[str, Any]:
    return build_maintenance_event(
        event_type="runtime_failure",
        component=component,
        severity=severity,
        observed_at=observed_at,
        rlr_revision=rlr_revision,
        observed={
            "command": _compact_command(command),
            "exit_code": int(exit_code),
        },
        expected_contract=expected_contract,
        evidence_refs=evidence_refs,
        source_receipts=source_receipts,
        suggested_route="repair",
    )


def observe_provider_runtime_failure(
    *,
    component: str,
    task_id: str,
    provider_state: str,
    termination_reason: str,
    worker_exit_code: int,
    expected_contract: str,
    rlr_revision: str,
    observed_at: str,
    candidate_ref: str | None = None,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    severity: str = "blocking",
) -> dict[str, Any]:
    """Normalize the durable provider-runtime facts used by Phase 3.

    Raw logs stay outside the event. Task/candidate identity is retained only as
    structured provenance needed to resume the same detached scientific task.
    """
    return build_maintenance_event(
        event_type="runtime_failure",
        component=component,
        severity=severity,
        observed_at=observed_at,
        rlr_revision=rlr_revision,
        observed={
            "task_id": str(task_id),
            "provider_state": str(provider_state),
            "termination_reason": str(termination_reason),
            "worker_exit_code": int(worker_exit_code),
        },
        expected_contract=expected_contract,
        evidence_refs=evidence_refs,
        source_receipts=source_receipts,
        suggested_route="repair",
        candidate_ref=candidate_ref,
    )


def observe_verification_failure(
    *,
    component: str,
    check_id: str,
    outcome: str,
    returncode: int,
    expected_contract: str,
    rlr_revision: str,
    observed_at: str,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    severity: str = "blocking",
) -> dict[str, Any]:
    return build_maintenance_event(
        event_type="verification_failure",
        component=component,
        severity=severity,
        observed_at=observed_at,
        rlr_revision=rlr_revision,
        observed={
            "check_id": str(check_id),
            "outcome": str(outcome),
            "returncode": int(returncode),
        },
        expected_contract=expected_contract,
        evidence_refs=evidence_refs,
        source_receipts=source_receipts,
        suggested_route="repair",
    )


def observe_ci_failure(
    *,
    component: str,
    check_id: str,
    conclusion: str,
    expected_contract: str,
    rlr_revision: str,
    observed_at: str,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    severity: str = "blocking",
) -> dict[str, Any]:
    """Record stable CI failure facts; run identity stays in evidence refs."""
    return build_maintenance_event(
        event_type="ci_failure",
        component=component,
        severity=severity,
        observed_at=observed_at,
        rlr_revision=rlr_revision,
        observed={
            "check_id": str(check_id),
            "conclusion": str(conclusion),
        },
        expected_contract=expected_contract,
        evidence_refs=evidence_refs,
        source_receipts=source_receipts,
        suggested_route="repair",
    )


def observe_acceptance_failure(
    *,
    component: str,
    acceptance_id: str,
    failing_condition: str,
    expected_contract: str,
    rlr_revision: str,
    observed_at: str,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    severity: str = "blocking",
) -> dict[str, Any]:
    return build_maintenance_event(
        event_type="acceptance_failure",
        component=component,
        severity=severity,
        observed_at=observed_at,
        rlr_revision=rlr_revision,
        observed={
            "acceptance_id": str(acceptance_id),
            "failing_condition": str(failing_condition),
        },
        expected_contract=expected_contract,
        evidence_refs=evidence_refs,
        source_receipts=source_receipts,
        suggested_route="repair",
    )
