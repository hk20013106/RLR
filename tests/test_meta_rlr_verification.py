import json
import os
from types import SimpleNamespace
import time

from rlr_maintenance.bounded_process import BoundedProcessResult

from rlr_maintenance.verification import (
    VERIFICATION_RECEIPT_SCHEMA,
    run_profile,
)
from rlr_maintenance.profiles import get_profile


AUTOWAKE_RETRY_GUARD_ENV = "RLR_META_RLR_AUTOWAKE_RETRY"


def test_required_failure_makes_receipt_fail(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        rc = 1 if len(calls) == 3 else 0
        return SimpleNamespace(returncode=rc, stdout="ok", stderr="")

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)

    assert receipt.schema_version == VERIFICATION_RECEIPT_SCHEMA
    assert receipt.passed is False
    assert len(receipt.steps) == 3
    assert receipt.steps[-1].returncode == 1
    assert all(item[1]["cwd"] == tmp_path for item in calls)
    assert all(item[1]["shell"] is False for item in calls)
    assert all(item[1]["encoding"] == "utf-8" for item in calls)


def test_required_failure_stops_later_steps(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        rc = 1 if len(calls) == 2 else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr="failed")

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)

    assert receipt.passed is False
    assert len(calls) == 2
    assert len(receipt.steps) == 2


def test_receipt_hashes_logs_instead_of_storing_raw_text(tmp_path):
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="secret-ish stdout", stderr="diagnostic")

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)
    first = receipt.steps[0]

    assert receipt.passed is True
    assert first.stdout_bytes == len("secret-ish stdout".encode("utf-8"))
    assert first.stderr_bytes == len("diagnostic".encode("utf-8"))
    assert len(first.stdout_sha256) == 64
    assert len(first.stderr_sha256) == 64
    assert not hasattr(first, "stdout")
    assert not hasattr(first, "stderr")


def test_required_verification_timeout_marks_receipt_failed(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return BoundedProcessResult(
            returncode=0,
            terminal_state="timed_out",
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            stdout_bytes=0,
            stderr_bytes=0,
            timeout_seconds=0.2,
            process_tree_cleanup={},
        )

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)

    assert receipt.passed is False
    assert len(calls) == 1
    assert receipt.steps[-1].returncode == 124
    assert receipt.failed_step_id == receipt.steps[-1].step_id
    assert receipt.steps[-1].timed_out is True


def test_verification_timeout_is_profile_wide_remaining_budget(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, *, timeout, cwd, env, max_output_bytes):
        calls.append(timeout)
        time.sleep(0.05)
        return SimpleNamespace(
            returncode=0,
            terminal_state="completed",
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
        )

    monkeypatch.setattr("rlr_maintenance.verification.run_bounded_process", fake_run)
    receipt = run_profile("l0_state_integrity", tmp_path, timeout=10.0)

    assert receipt.passed is True
    assert len(calls) >= 2
    assert calls[0] <= 10.0
    assert calls[0] > 9.9
    assert calls[1] < calls[0]


def test_verification_stops_when_profile_budget_exhausted(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, *, timeout, cwd, env, max_output_bytes):
        calls.append(timeout)
        time.sleep(0.2)
        return SimpleNamespace(
            returncode=0,
            terminal_state="completed",
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
        )

    monkeypatch.setattr("rlr_maintenance.verification.run_bounded_process", fake_run)
    receipt = run_profile("l0_state_integrity", tmp_path, timeout=0.05)

    assert receipt.passed is False
    assert len(calls) == 1
    assert receipt.steps[-1].returncode == 0
    assert receipt.failed_step_id is None
    assert receipt.unexecuted_step_ids == tuple(
        step.step_id for step in get_profile("l0_state_integrity").required_validation[1:]
    )


def test_verification_persists_durable_receipt_with_step_observability(tmp_path):
    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            terminal_state="completed",
            stdout="verification ok",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
        )

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)
    receipt_path = tmp_path / "verification_receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert receipt.receipt_path == receipt_path
    assert receipt.receipt_sha256
    assert payload["profile_id"] == "l0_state_integrity"
    assert payload["passed"] is True
    assert payload["failed_step_id"] is None
    assert payload["started_at"] < payload["ended_at"]
    assert payload["unexecuted_step_ids"] == []
    assert len(payload["steps"]) == len(get_profile("l0_state_integrity").required_validation)
    step = payload["steps"][0]
    assert set(step) >= {
        "step_id", "command", "required", "returncode", "terminal_state",
        "duration_seconds", "timed_out", "stdout_bytes", "stderr_bytes",
        "stdout_sha256", "stderr_sha256", "output_truncated",
        "stdout_evidence", "stderr_evidence",
    }
    assert step["stdout_evidence"] == "verification ok"


def test_failed_verification_persists_failure_step_and_bounded_evidence(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if len(calls) == 2:
            return SimpleNamespace(
                returncode=23,
                terminal_state="completed",
                stdout="failed stdout",
                stderr="specific verifier failure",
                stdout_truncated=False,
                stderr_truncated=False,
            )
        return SimpleNamespace(
            returncode=0,
            terminal_state="completed",
            stdout="ok",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
        )

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)
    payload = json.loads((tmp_path / "verification_receipt.json").read_text(encoding="utf-8"))

    assert receipt.passed is False
    assert payload["failed_step_id"] == payload["steps"][-1]["step_id"]
    assert payload["failure_reason"] == "required verification step failed"
    assert len(payload["steps"]) == 2
    assert payload["unexecuted_step_ids"]
    failed = payload["steps"][-1]
    assert failed["returncode"] == 23
    assert failed["terminal_state"] == "completed"
    assert failed["timed_out"] is False
    assert failed["stdout_evidence"] == "failed stdout"
    assert failed["stderr_evidence"] == "specific verifier failure"


def test_verifier_launch_failure_is_durable_and_fail_closed(tmp_path):
    def fake_run(command, **kwargs):
        raise FileNotFoundError("test verifier executable missing")

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)
    payload = json.loads((tmp_path / "verification_receipt.json").read_text(encoding="utf-8"))

    assert receipt.passed is False
    assert payload["failed_step_id"] == payload["steps"][0]["step_id"]
    assert payload["steps"][0]["terminal_state"] == "launch_failed"
    assert payload["steps"][0]["returncode"] == 127
    assert "test verifier executable missing" in payload["steps"][0]["stderr_evidence"]


def test_verification_uses_process_reader_tail_when_output_was_bounded(tmp_path):
    def fake_run(command, **kwargs):
        return BoundedProcessResult(
            returncode=9,
            terminal_state="completed",
            stdout="captured prefix",
            stderr="captured error prefix",
            stdout_truncated=True,
            stderr_truncated=True,
            stdout_bytes=1000,
            stderr_bytes=1000,
            timeout_seconds=1.0,
            process_tree_cleanup={},
            stdout_tail="actual stdout tail",
            stderr_tail="actual stderr tail",
        )

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)

    assert receipt.steps[0].stdout_evidence == "actual stdout tail"
    assert receipt.steps[0].stderr_evidence == "actual stderr tail"
    assert receipt.steps[0].output_truncated is True


def test_verification_child_environment_isolates_meta_rlr_retry_guard(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(AUTOWAKE_RETRY_GUARD_ENV, "1")
    monkeypatch.setenv("RLR_VERIFICATION_KEEP_ME", "preserve")
    child_environments = []

    def fake_run(command, **kwargs):
        child_environments.append(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    run_profile("l0_state_integrity", tmp_path, runner=fake_run)

    assert len(child_environments) == len(
        get_profile("l0_state_integrity").required_validation
    )
    assert all(AUTOWAKE_RETRY_GUARD_ENV not in env for env in child_environments)
    assert all(env["RLR_VERIFICATION_KEEP_ME"] == "preserve" for env in child_environments)
    assert os.environ[AUTOWAKE_RETRY_GUARD_ENV] == "1"
