import subprocess
import sys
from pathlib import Path

from rlr_maintenance.observer import observe_process_failure
from rlr_maintenance.profiles import get_profile, profile_for_event


REVISION = "a" * 40
WHEN = "2026-08-13T00:00:00Z"


def test_seeded_bad_wrapper_reproduces_lost_nonzero_exit_code(tmp_path):
    canonical = tmp_path / "canonical_stub.py"
    canonical.write_text("def main():\n    return 3\n", encoding="utf-8")
    bad_wrapper = tmp_path / "bad_wrapper.py"
    bad_wrapper.write_text(
        "from canonical_stub import main\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )

    canonical_result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from canonical_stub import main; sys.exit(main())",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    wrapper_result = subprocess.run(
        [sys.executable, str(bad_wrapper)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert canonical_result.returncode == 3
    assert wrapper_result.returncode == 0


def test_historical_runtime_failure_routes_from_contract_to_l0_profile():
    event = observe_process_failure(
        component="root_entrypoint",
        command=["python", "run_loop.py"],
        exit_code=0,
        expected_contract="runner_nonzero_propagation",
        rlr_revision=REVISION,
        observed_at=WHEN,
    )

    profile = profile_for_event(event)

    assert event["event_type"] == "runtime_failure"
    assert event["expected_contract"] == "runner_nonzero_propagation"
    assert profile.profile_id == "l0_state_integrity"


def test_l0_profile_reuses_existing_root_entrypoint_regression():
    profile = get_profile("l0_state_integrity")
    by_id = {step.step_id: step for step in profile.required_validation}

    assert "root_entrypoint_regression" in by_id
    assert "tests/test_root_run_loop_entrypoint.py" in by_id[
        "root_entrypoint_regression"
    ].command
