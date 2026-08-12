import pytest

from rlr_maintenance.contracts import (
    MAINTENANCE_EVENT_SCHEMA,
    MaintenanceContractError,
    build_maintenance_event,
    validate_maintenance_event,
)


def _common_event_kwargs():
    return {
        "event_type": "contract_failure",
        "component": "l0_restore",
        "severity": "blocking",
        "rlr_revision": "a" * 40,
        "observed": {"error_code": "L0_RESTORE_ARTIFACT_HASH_MISMATCH"},
        "expected_contract": "l0_restore_fail_closed",
        "evidence_refs": [
            {
                "kind": "rlr_artifact",
                "ref": "08_Audit/round_manifests/example.json",
                "sha256": "b" * 64,
            }
        ],
    }


def test_maintenance_event_schema_and_stable_identity_ignore_observation_time():
    kwargs = _common_event_kwargs()
    first = build_maintenance_event(
        observed_at="2026-08-13T00:00:00Z",
        **kwargs,
    )
    second = build_maintenance_event(
        observed_at="2026-08-13T01:00:00Z",
        **kwargs,
    )

    assert first["schema_version"] == MAINTENANCE_EVENT_SCHEMA
    assert first["event_id"] == second["event_id"]
    assert first["dedup_fingerprint"] == second["dedup_fingerprint"]
    assert first["observed_at"] != second["observed_at"]
    assert validate_maintenance_event(first) == first


def test_maintenance_event_identity_changes_when_stable_facts_change():
    kwargs = _common_event_kwargs()
    first = build_maintenance_event(
        observed_at="2026-08-13T00:00:00Z",
        **kwargs,
    )
    changed = dict(kwargs)
    changed["observed"] = {"error_code": "L0_RESTORE_ARTIFACT_MISSING"}
    second = build_maintenance_event(
        observed_at="2026-08-13T00:00:00Z",
        **changed,
    )

    assert first["event_id"] != second["event_id"]
    assert first["dedup_fingerprint"] != second["dedup_fingerprint"]


def test_absolute_rlr_artifact_reference_is_rejected():
    kwargs = _common_event_kwargs()
    kwargs["evidence_refs"] = [
        {"kind": "rlr_artifact", "ref": "D:/private/data.csv"}
    ]

    with pytest.raises(MaintenanceContractError, match="relative"):
        build_maintenance_event(
            observed_at="2026-08-13T00:00:00Z",
            **kwargs,
        )


def test_unknown_event_type_fails_closed():
    kwargs = _common_event_kwargs()
    kwargs["event_type"] = "architecture_drift"

    with pytest.raises(MaintenanceContractError, match="event_type"):
        build_maintenance_event(
            observed_at="2026-08-13T00:00:00Z",
            **kwargs,
        )


def test_invalid_revision_and_hash_fail_closed():
    kwargs = _common_event_kwargs()
    kwargs["rlr_revision"] = "not-a-sha"

    with pytest.raises(MaintenanceContractError, match="rlr_revision"):
        build_maintenance_event(
            observed_at="2026-08-13T00:00:00Z",
            **kwargs,
        )

    kwargs = _common_event_kwargs()
    kwargs["evidence_refs"][0]["sha256"] = "bad"
    with pytest.raises(MaintenanceContractError, match="sha256"):
        build_maintenance_event(
            observed_at="2026-08-13T00:00:00Z",
            **kwargs,
        )
