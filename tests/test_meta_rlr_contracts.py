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


def test_dedup_identity_ignores_evidence_occurrence_and_route():
    kwargs = _common_event_kwargs()
    first = build_maintenance_event(
        observed_at="2026-08-13T00:00:00Z",
        suggested_route="repair",
        **kwargs,
    )

    second_kwargs = _common_event_kwargs()
    second_kwargs["evidence_refs"] = [
        {"kind": "github_check", "ref": "workflow-run:second-observation"}
    ]
    second = build_maintenance_event(
        observed_at="2026-08-13T02:00:00Z",
        suggested_route="investigate",
        **second_kwargs,
    )

    assert first["event_id"] == second["event_id"]
    assert first["dedup_fingerprint"] == second["dedup_fingerprint"]
    assert first["evidence_refs"] != second["evidence_refs"]
    assert first["suggested_route"] != second["suggested_route"]


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


def test_absolute_or_parent_traversal_rlr_artifact_reference_is_rejected():
    for unsafe_ref in ("D:/private/data.csv", "../private/data.csv"):
        kwargs = _common_event_kwargs()
        kwargs["evidence_refs"] = [
            {"kind": "rlr_artifact", "ref": unsafe_ref}
        ]

        with pytest.raises(MaintenanceContractError, match="repository-relative"):
            build_maintenance_event(
                observed_at="2026-08-13T00:00:00Z",
                **kwargs,
            )


def test_raw_log_keys_are_rejected_at_the_event_boundary():
    kwargs = _common_event_kwargs()
    kwargs["observed"] = {
        "error_code": "X",
        "stderr": "private raw diagnostic",
    }

    with pytest.raises(MaintenanceContractError, match="raw/private"):
        build_maintenance_event(
            observed_at="2026-08-13T00:00:00Z",
            **kwargs,
        )


def test_unbounded_observed_payload_is_rejected():
    kwargs = _common_event_kwargs()
    kwargs["observed"] = {
        "error_code": "X",
        "detail": "x" * 20000,
    }

    with pytest.raises(MaintenanceContractError, match="compact"):
        build_maintenance_event(
            observed_at="2026-08-13T00:00:00Z",
            **kwargs,
        )


def test_unknown_top_level_and_evidence_fields_fail_closed():
    valid = build_maintenance_event(
        observed_at="2026-08-13T00:00:00Z",
        **_common_event_kwargs(),
    )
    with_extra = dict(valid)
    with_extra["fix"] = "weaken the gate"

    with pytest.raises(MaintenanceContractError, match="unexpected fields"):
        validate_maintenance_event(with_extra)

    kwargs = _common_event_kwargs()
    kwargs["evidence_refs"] = [
        {
            "kind": "rlr_artifact",
            "ref": "08_Audit/example.json",
            "raw_log": "do not copy me",
        }
    ]
    with pytest.raises(MaintenanceContractError, match="unexpected fields"):
        build_maintenance_event(
            observed_at="2026-08-13T00:00:00Z",
            **kwargs,
        )


def test_observed_at_requires_timezone_aware_iso8601():
    with pytest.raises(MaintenanceContractError, match="ISO-8601"):
        build_maintenance_event(
            observed_at="2026-08-13 00:00:00",
            **_common_event_kwargs(),
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
