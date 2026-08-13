from types import SimpleNamespace

from rlr_maintenance.verification import (
    VERIFICATION_RECEIPT_SCHEMA,
    run_profile,
)


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
