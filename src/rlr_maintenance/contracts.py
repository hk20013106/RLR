"""Provider-neutral contracts for the RLR software-maintenance boundary.

The maintenance boundary records compact software/runtime facts.  It does not
interpret scientific results, mutate RLR state, or depend on LoopX internals.
Structural validation reuses RLR's existing JSON-Schema dependency; a small
semantic layer owns privacy, repository-path safety, and content identities.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

import jsonschema


MAINTENANCE_EVENT_SCHEMA = "RLRMaintenanceEvent/v1"
_MAX_OBSERVED_BYTES = 16 * 1024
_RAW_PRIVATE_KEYS = {
    "stdout",
    "stderr",
    "raw_log",
    "raw_logs",
    "transcript",
    "transcripts",
    "credential",
    "credentials",
    "secret",
    "secrets",
    "token",
    "tokens",
    "authorization",
}

_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "enum": ["rlr_artifact", "github_check", "test", "pilot"],
        },
        "ref": {"type": "string", "minLength": 1, "maxLength": 4096},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "required": ["kind", "ref"],
    "additionalProperties": False,
}

MAINTENANCE_EVENT_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schema_version": {"const": MAINTENANCE_EVENT_SCHEMA},
        "event_id": {"type": "string", "pattern": "^rme-[0-9a-f]{20}$"},
        "event_type": {
            "enum": [
                "contract_failure",
                "runtime_failure",
                "verification_failure",
                "ci_failure",
                "acceptance_failure",
            ]
        },
        "component": {"type": "string", "minLength": 1, "maxLength": 256},
        "severity": {"enum": ["blocking", "warning", "info"]},
        "observed_at": {"type": "string", "format": "date-time"},
        "rlr_revision": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "project_ref": {"type": "string", "minLength": 1, "maxLength": 512},
        "candidate_ref": {"type": "string", "minLength": 1, "maxLength": 512},
        "round_ref": {"type": "string", "minLength": 1, "maxLength": 512},
        "observed": {"type": "object", "maxProperties": 64},
        "expected_contract": {"type": "string", "minLength": 1, "maxLength": 256},
        "evidence_refs": {
            "type": "array",
            "maxItems": 64,
            "items": _REF_SCHEMA,
        },
        "source_receipts": {
            "type": "array",
            "maxItems": 64,
            "items": _REF_SCHEMA,
        },
        "dedup_fingerprint": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "suggested_route": {"enum": ["repair", "investigate", "monitor"]},
    },
    "required": [
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
    ],
    "additionalProperties": False,
}

_EVENT_VALIDATOR = jsonschema.Draft202012Validator(
    MAINTENANCE_EVENT_JSON_SCHEMA,
    format_checker=jsonschema.FormatChecker(),
)


class MaintenanceContractError(ValueError):
    """Raised when maintenance-boundary data violates its declared contract."""


def canonical_json(value: object) -> str:
    """Return deterministic strict JSON for hashes and compact-size checks."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MaintenanceContractError(f"value is not canonical JSON: {exc}") from exc


def _json_path(error: jsonschema.ValidationError) -> str:
    return "/".join(str(part) for part in error.absolute_path) or "<root>"


def _schema_error(error: jsonschema.ValidationError) -> MaintenanceContractError:
    where = _json_path(error)
    if error.validator == "additionalProperties":
        return MaintenanceContractError(f"unexpected fields at {where}: {error.message}")
    if error.validator == "format" and where == "observed_at":
        return MaintenanceContractError("observed_at must be timezone-aware ISO-8601 date-time")
    return MaintenanceContractError(f"{where}: {error.message}")


def _validate_schema(event: Mapping[str, Any]) -> None:
    errors = sorted(
        _EVENT_VALIDATOR.iter_errors(dict(event)),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        raise _schema_error(errors[0])


def _safe_repository_ref(ref: str) -> bool:
    posix = PurePosixPath(ref)
    windows = PureWindowsPath(ref)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        return False
    return ".." not in posix.parts and ".." not in windows.parts


def _walk_keys(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).lower()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _validate_semantics(event: Mapping[str, Any]) -> None:
    observed = event["observed"]
    private_keys = sorted(set(_walk_keys(observed)) & _RAW_PRIVATE_KEYS)
    if private_keys:
        raise MaintenanceContractError(
            f"observed contains raw/private fields: {', '.join(private_keys)}"
        )

    observed_bytes = len(canonical_json(observed).encode("utf-8"))
    if observed_bytes > _MAX_OBSERVED_BYTES:
        raise MaintenanceContractError(
            f"observed must remain compact (<= {_MAX_OBSERVED_BYTES} UTF-8 bytes)"
        )

    for field in ("evidence_refs", "source_receipts"):
        for index, ref in enumerate(event[field]):
            if ref["kind"] == "rlr_artifact" and not _safe_repository_ref(ref["ref"]):
                raise MaintenanceContractError(
                    f"{field}[{index}].ref for rlr_artifact must be repository-relative "
                    "and may not traverse parent directories"
                )

    canonical_json(event)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _dedup_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    """Facts defining one underlying failure across repeated observations."""
    keys = (
        "schema_version",
        "event_type",
        "component",
        "rlr_revision",
        "observed",
        "expected_contract",
        "project_ref",
        "candidate_ref",
        "round_ref",
    )
    return {key: event[key] for key in keys if key in event}


def _occurrence_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    """All immutable occurrence content except the derived event id itself."""
    return {key: event[key] for key in sorted(event) if key != "event_id"}


def _expected_dedup(event: Mapping[str, Any]) -> str:
    return _sha256(_dedup_payload(event))


def _expected_event_id(event: Mapping[str, Any]) -> str:
    return f"rme-{_sha256(_occurrence_payload(event))[:20]}"


def validate_maintenance_event(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on malformed, unsafe, or identity-inconsistent events."""
    if not isinstance(value, Mapping):
        raise MaintenanceContractError("maintenance event must be an object")

    event = dict(value)
    _validate_schema(event)
    _validate_semantics(event)

    expected_dedup = _expected_dedup(event)
    if event["dedup_fingerprint"] != expected_dedup:
        raise MaintenanceContractError("dedup_fingerprint does not match stable failure facts")

    expected_event_id = _expected_event_id(event)
    if event["event_id"] != expected_event_id:
        raise MaintenanceContractError("event_id does not match immutable event occurrence")

    return event


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
    """Build one immutable observation plus a stable underlying-failure id."""
    event: dict[str, Any] = {
        "schema_version": MAINTENANCE_EVENT_SCHEMA,
        "event_id": "rme-" + "0" * 20,
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
    if project_ref is not None:
        event["project_ref"] = project_ref
    if candidate_ref is not None:
        event["candidate_ref"] = candidate_ref
    if round_ref is not None:
        event["round_ref"] = round_ref

    # Validate caller-controlled structure and privacy before deriving identity.
    _validate_schema(event)
    _validate_semantics(event)

    event["dedup_fingerprint"] = _expected_dedup(event)
    event["event_id"] = _expected_event_id(event)
    return validate_maintenance_event(event)
