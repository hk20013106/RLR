import pytest

from rlr_maintenance.observer import (
    observe_acceptance_failure,
    observe_ci_failure,
    observe_contract_failure,
    observe_process_failure,
    observe_provider_runtime_failure,
    observe_verification_failure,
)


REVISION = "a" * 40
WHEN = "2026-08-13T00:00:00Z"


def test_contract_failure_records_stable_error_code_only():
    event = observe_contract_failure(
        component="l0_restore",
        error_code="L0_RESTORE_ARTIFACT_HASH_MISMATCH",
        expected_contract="l0_restore_fail_closed",
        rlr_revision=REVISION,
        evidence_refs=[
            {
                "kind": "rlr_artifact",
                "ref": "08_Audit/round_manifests/example.json",
            }
        ],
        observed_at=WHEN,
    )

    assert event["event_type"] == "contract_failure"
    assert event["observed"] == {
        "error_code": "L0_RESTORE_ARTIFACT_HASH_MISMATCH"
    }
    assert "fix" not in event


def test_contract_failure_rejects_freeform_detail_channel():
    with pytest.raises(TypeError):
        observe_contract_failure(
            component="l0_restore",
            error_code="L0_RESTORE_ARTIFACT_HASH_MISMATCH",
            detail="D:/private/research/project/file.csv",
            expected_contract="l0_restore_fail_closed",
            rlr_revision=REVISION,
            observed_at=WHEN,
        )


def test_process_failure_keeps_program_identity_not_task_arguments_or_raw_logs():
    event = observe_process_failure(
        component="root_entrypoint",
        command=["python", "run_loop.py", "run", "PRIVATE_PROJECT", "CANDIDATE"],
        exit_code=3,
        expected_contract="runner_nonzero_propagation",
        rlr_revision=REVISION,
        observed_at=WHEN,
    )

    assert event["event_type"] == "runtime_failure"
    assert event["observed"]["exit_code"] == 3
    assert event["observed"]["command"] == ["python", "run_loop.py"]
    assert "PRIVATE_PROJECT" not in str(event)
    assert "stdout" not in event["observed"]
    assert "stderr" not in event["observed"]


def test_module_process_identity_keeps_python_module_not_following_arguments():
    event = observe_process_failure(
        component="test_runner",
        command=["python", "-m", "pytest", "PRIVATE_TEST_SELECTOR"],
        exit_code=1,
        expected_contract="runner_nonzero_propagation",
        rlr_revision=REVISION,
        observed_at=WHEN,
    )

    assert event["observed"]["command"] == ["python", "-m", "pytest"]
    assert "PRIVATE_TEST_SELECTOR" not in str(event)


def test_provider_runtime_failure_keeps_compact_resume_provenance_not_raw_logs():
    event = observe_provider_runtime_failure(
        component="deep_research_provider:L4B",
        task_id="dr-test",
        provider_state="provider_failed",
        termination_reason="provider_exit_nonzero",
        worker_exit_code=3,
        expected_contract="provider_runtime_execution_integrity",
        rlr_revision=REVISION,
        observed_at=WHEN,
        candidate_ref="C-test",
        evidence_refs=[
            {
                "kind": "rlr_artifact",
                "ref": "08_Audit/deep_research_runtime/tasks/dr-test/status.json",
            }
        ],
    )

    assert event["event_type"] == "runtime_failure"
    assert event["candidate_ref"] == "C-test"
    assert event["observed"] == {
        "task_id": "dr-test",
        "provider_state": "provider_failed",
        "termination_reason": "provider_exit_nonzero",
        "worker_exit_code": 3,
    }
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
