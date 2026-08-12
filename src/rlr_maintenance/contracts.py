"""Provider-neutral contracts for the RLR software-maintenance boundary.

This module owns maintenance observations only. It must not interpret scientific
results, mutate RLR state, or depend on LoopX implementation modules.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping


MAINTENANCE_EVENT_SCHEMA = "RLRMaintenanceEvent/v1"

_ALLOWED_EVENT_TYPES = {
    "contract_failure",
    "runtime_failure",
    "verification_failure",
    "ci_failure",
    "acceptance_failure",
}
_ALLOWED_SEVERITIES = {"blocking", "warning", "info"}
_ALLOWED_REF_KINDS = {"rlr_artifact", "github_check", "test", "pilot"}
_ALLOWED_ROUTES = {"repair", "investigate", "monitor"}
_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class MaintenanceContractError(ValueError):
    """Raised when maintenance-boundary data violates its declared contract."""


def canonical_json(value: object) -> str:
    """Return deterministic JSON suitable for content-derived identities."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise MaintenanceContractError(f"value is not canonical JSON: {exc}") from exc


def _require_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MaintenanceContractError(f"{field} must be a non-empty string")
    return value


def _require_sha(value: object, field: str, pattern: re.Pattern[str]) -> str:
    text = _require_nonempty_string(value, field)
    if not pattern.fullmatch(text):
        raise MaintenanceContractError(f"{field} must be a hexadecimal SHA")
    return text.lower()


def _is_absolute_path(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _validate_evidence_refs(value: object, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MaintenanceContractError(f"{field} must be a list")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise MaintenanceContractError(f"{field}[{index}] must be an object")
        kind = _require_nonempty_string(raw.get("kind"), f"{field}[{index}].kind")
        if kind not in _ALLOWED_REF_KINDS:
            raise MaintenanceContractError(
                f"{field}[{index}].kind must be one of {sorted(_ALLOWED_REF_KINDS)}"
            )
        ref = _require_nonempty_string(raw.get("ref"), f"{field}[{index}].ref")
        if kind == "rlr_artifact" and _is_absolute_path(ref):
            raise MaintenanceContractError(
                f"{field}[{index}].ref for rlr_artifact must be repository-relative"
            )

        item: dict[str, Any] = {"kind": kind, "ref": ref}
        if raw.get("sha256") not in (None, ""):
            item["sha256"] = _require_sha(
                raw.get("sha256"), f"{field}[{index}].sha256", _HEX64
            )
        normalized.append(item)
    return normalized


def _stable_identity_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: event[key]
        for key in sorted(event)
        if key not in {"event_id", "dedup_fingerprint", "observed_at"}
    }


def _fingerprint(event: Mapping[str, Any]) -> str:
    payload = canonical_json(_stable_identity_payload(event)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_maintenance_event(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize an ``RLRMaintenanceEvent/v1`` mapping.

    Validation is fail-closed. The function verifies the content-derived event
    identity rather than trusting caller-supplied identifiers.
    """
    if not isinstance(value, Mapping):
        raise MaintenanceContractError("maintenance event must be an object")

    required = {
        "schema_version",
        "event_id",
        "event_type",
        "component",
        "severity",
        "observed_at",
        "rlr_revision",
        "observed",
        "expected_contract",
        "evidence_refs",
        "source_receipts",
        "dedup_fingerprint",
        "suggested_route",
    }
    missing = sorted(required - set(value))
    if missing:
        raise MaintenanceContractError(f"maintenance event missing fields: {missing}")

    if value.get("schema_version") != MAINTENANCE_EVENT_SCHEMA:
        raise MaintenanceContractError(
            f"schema_version must be {MAINTENANCE_EVENT_SCHEMA}"
        )

    event_type = _require_nonempty_string(value.get("event_type"), "event_type")
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise MaintenanceContractError(
            f"event_type must be one of {sorted(_ALLOWED_EVENT_TYPES)}"
        )

    severity = _require_nonempty_string(value.get("severity"), "severity")
    if severity not in _ALLOWED_SEVERITIES:
        raise MaintenanceContractError(
            f"severity must be one of {sorted(_ALLOWED_SEVERITIES)}"
        )

    route = _require_nonempty_string(value.get("suggested_route"), "suggested_route")
    if route not in _ALLOWED_ROUTES:
        raise MaintenanceContractError(
            f"suggested_route must be one of {sorted(_ALLOWED_ROUTES)}"
        )

    observed = value.get("observed")
    if not isinstance(observed, Mapping):
        raise MaintenanceContractError("observed must be an object")

    normalized: dict[str, Any] = {
        "schema_version": MAINTENANCE_EVENT_SCHEMA,
        "event_id": _require_nonempty_string(value.get("event_id"), "event_id"),
        "event_type": event_type,
        "component": _require_nonempty_string(value.get("component"), "component"),
        "severity": severity,
        "observed_at": _require_nonempty_string(value.get("observed_at"), "observed_at"),
        "rlr_revision": _require_sha(value.get("rlr_revision"), "rlr_revision", _HEX40),
        "observed": dict(observed),
        "expected_contract": _require_nonempty_string(
            value.get("expected_contract"), "expected_contract"
        ),
        "evidence_refs": _validate_evidence_refs(value.get("evidence_refs"), "evidence_refs"),
        "source_receipts": _validate_evidence_refs(value.get("source_receipts"), "source_receipts"),
        "dedup_fingerprint": _require_sha(
            value.get("dedup_fingerprint"), "dedup_fingerprint", _HEX64
        ),
        "suggested_route": route,
    }

    for optional in ("project_ref", "candidate_ref", "round_ref"):
        if optional in value and value.get(optional) not in (None, ""):
            normalized[optional] = _require_nonempty_string(value.get(optional), optional)

    expected_fingerprint = _fingerprint(normalized)
    if normalized["dedup_fingerprint"] != expected_fingerprint:
        raise MaintenanceContractError("dedup_fingerprint does not match event content")
    expected_event_id = f"rme-{expected_fingerprint[:20]}"
    if normalized["event_id"] != expected_event_id:
        raise MaintenanceContractError("event_id does not match event content")

    canonical_json(normalized)
    return normalized


def build_maintenance_event(
    *,
    event_type: str,
    component: str,
    severity: str,
    observed_at: str,
    rlr_revision: str,
    observed: Mapping[str, Any],
    expected_contract: str,
    evidence_refs: Iterable[Mapping[str, Any]] = (),
    source_receipts: Iterable[Mapping[str, Any]] = (),
    suggested_route: str = "repair",
    project_ref: str | None = None,
    candidate_ref: str | None = None,
    round_ref: str | None = None,
) -> dict[str, Any]:
    """Build a validated maintenance event from compact authoritative facts."""
    event: dict[str, Any] = {
        "schema_version": MAINTENANCE_EVENT_SCHEMA,
        "event_id": "pending",
        "event_type": event_type,
        "component": component,
        "severity": severity,
        "observed_at": observed_at,
        "rlr_revision": rlr_revision,
        "observed": dict(observed),
        "expected_contract": expected_contract,
        "evidence_refs": [dict(item) for item in evidence_refs],
        "source_receipts": [dict(item) for item in source_receipts],
        "dedup_fingerprint": "0" * 64,
        "suggested_route": suggested_route,
    }
    if project_ref:
        event["project_ref"] = project_ref
    if candidate_ref:
        event["candidate_ref"] = candidate_ref
    if round_ref:
        event["round_ref"] = round_ref

    # Normalize all caller-controlled fields before deriving identity.
    provisional = dict(event)
    provisional["event_id"] = "rme-" + "0" * 20
    provisional["dedup_fingerprint"] = "0" * 64

    # Reuse the same field validators without requiring the derived values to
    # match yet.
    if provisional["schema_version"] != MAINTENANCE_EVENT_SCHEMA:
        raise MaintenanceContractError("invalid schema_version")
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise MaintenanceContractError(
            f"event_type must be one of {sorted(_ALLOWED_EVENT_TYPES)}"
        )
    if severity not in _ALLOWED_SEVERITIES:
        raise MaintenanceContractError(
            f"severity must be one of {sorted(_ALLOWED_SEVERITIES)}"
        )
    if suggested_route not in _ALLOWED_ROUTES:
        raise MaintenanceContractError(
            f"suggested_route must be one of {sorted(_ALLOWED_ROUTES)}"
        )
    _require_nonempty_string(component, "component")
    _require_nonempty_string(observed_at, "observed_at")
    event["rlr_revision"] = _require_sha(rlr_revision, "rlr_revision", _HEX40)
    _require_nonempty_string(expected_contract, "expected_contract")
    if not isinstance(observed, Mapping):
        raise MaintenanceContractError("observed must be an object")
    event["evidence_refs"] = _validate_evidence_refs(event["evidence_refs"], "evidence_refs")
    event["source_receipts"] = _validate_evidence_refs(event["source_receipts"], "source_receipts")
    canonical_json(event["observed"])

    fingerprint = _fingerprint(event)
    event["dedup_fingerprint"] = fingerprint
    event["event_id"] = f"rme-{fingerprint[:20]}"
    return validate_maintenance_event(event)
