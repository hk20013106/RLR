from rlr_maintenance.observer import (
    observe_acceptance_failure,
    observe_ci_failure,
    observe_contract_failure,
    observe_process_failure,
    observe_verification_failure,
)


REVISION = "a" * 40
WHEN = "2026-08-13T00:00:00Z"


def test_contract_failure_is_fact_not_patch_proposal():
    event = observe_contract_failure(
        component="l0_restore",
        error_code="L0_RESTORE_ARTIFACT_HASH_MISMATCH",
        detail="03_Source_Data/input.csv",
        expected_contract="l0_restore_fail_closed",
        rlr_revision=REVISION,
        evidence_refs=[],
        observed_at=WHEN,
    )

    assert event["event_type"] == "contract_failure"
    assert event["observed"]["error_code"] == "L0_RESTORE_ARTIFACT_HASH_MISMATCH"
    assert event["observed"]["detail"] == "03_Source_Data/input.csv"
    assert "fix" not in event


def test_process_failure_keeps_exit_code_without_raw_logs():
    event = observe_process_failure(
        component="root_entrypoint",
        command=["python", "run_loop.py", "run", "PROJECT", "CANDIDATE"],
        exit_code=3,
        expected_contract="runner_nonzero_propagation",
        rlr_revision=REVISION,
        observed_at=WHEN,
    )

    assert event["event_type"] == "runtime_failure"
    assert event["observed"]["exit_code"] == 3
    assert event["observed"]["command"] == [
        "python",
        "run_loop.py",
        "run",
        "PROJECT",
        "CANDIDATE",
    ]
    assert "stdout" not in event["observed"]
    assert "stderr" not in event["observed"]


def test_verification_failure_records_validator_identity():
    event = observe_verification_failure(
        component="verification",
        check_id="l0_contract_regression",
        outcome="failed",
        returncode=1,
        expected_contract="l0_restore_fail_closed",
        rlr_revision=REVISION,
        observed_at=WHEN,
    )

    assert event["event_type"] == "verification_failure"
    assert event["observed"] == {
        "check_id": "l0_contract_regression",
        "outcome": "failed",
        "returncode": 1,
    }


def test_ci_failure_records_stable_check_fact_and_keeps_run_id_in_evidence():
    event = observe_ci_failure(
        component="github_ci",
        check_id="CI / Test / Windows / Python 3.13",
        conclusion="failure",
        expected_contract="runner_nonzero_propagation",
        rlr_revision=REVISION,
        evidence_refs=[
            {"kind": "github_check", "ref": "workflow-run:31622141836"}
        ],
        observed_at=WHEN,
    )

    assert event["event_type"] == "ci_failure"
    assert event["observed"] == {
        "check_id": "CI / Test / Windows / Python 3.13",
        "conclusion": "failure",
    }
    assert event["evidence_refs"] == [
        {"kind": "github_check", "ref": "workflow-run:31622141836"}
    ]
    assert "stdout" not in event["observed"]
    assert "stderr" not in event["observed"]


def test_acceptance_failure_keeps_compact_condition_only():
    event = observe_acceptance_failure(
        component="root_entrypoint",
        acceptance_id="meta-rlr-exit-code",
        failing_condition="root_exit_code_expected_3_observed_0",
        expected_contract="runner_nonzero_propagation",
        rlr_revision=REVISION,
        evidence_refs=[{"kind": "pilot", "ref": "meta-rlr-exit-code"}],
        observed_at=WHEN,
    )

    assert event["event_type"] == "acceptance_failure"
    assert event["observed"] == {
        "acceptance_id": "meta-rlr-exit-code",
        "failing_condition": "root_exit_code_expected_3_observed_0",
    }
