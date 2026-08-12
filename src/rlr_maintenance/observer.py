"""Normalize authoritative software/runtime facts into maintenance events."""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

from .contracts import build_maintenance_event


def _compact_command(command: Sequence[str]) -> list[str]:
    compact: list[str] = []
    for token in command:
        text = str(token)
        if PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute():
            compact.append(PureWindowsPath(text).name or PurePosixPath(text).name)
        else:
            compact.append(text)
    return compact


def observe_contract_failure(
    *,
    component: str,
    error_code: str,
    detail: str,
    expected_contract: str,
    rlr_revision: str,
    observed_at: str,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    severity: str = "blocking",
) -> dict[str, Any]:
    observed = {"error_code": str(error_code)}
    if detail:
        observed["detail"] = str(detail)
    return build_maintenance_event(
        event_type="contract_failure",
        component=component,
        severity=severity,
        observed_at=observed_at,
        rlr_revision=rlr_revision,
        observed=observed,
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
