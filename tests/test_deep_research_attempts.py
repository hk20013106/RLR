import json
import os
import sys
from pathlib import Path

import pytest

from research_loop import deep_research_task as dr_task
from research_loop.provider_runtime_observability import run_observed_provider


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex_jsonl.py"


def _task_dir(project: Path, task_id: str) -> Path:
    return project / "08_Audit" / "deep_research_runtime" / "tasks" / task_id


def _request(project: Path, task_id: str) -> dict:
    return {
        "schema_version": dr_task.TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "working_directory": str(project),
        "handler_args": {
            "project_dir": str(project),
            "cand_id": "C1",
            "node": "L1",
        },
    }


def _prepare_task(tmp_path: Path, task_id: str = "dr-attempts") -> Path:
    project = tmp_path / "project"
    project.mkdir()
    task_dir = _task_dir(project, task_id)
    task_dir.mkdir(parents=True)
    (task_dir / "request.json").write_text(
        json.dumps(_request(project, task_id)), encoding="utf-8"
    )
    (task_dir / "status.json").write_text(
        json.dumps({
            "schema_version": dr_task.TASK_SCHEMA_VERSION,
            "task_id": task_id,
            "state": "running",
        }),
        encoding="utf-8",
    )
    return project


def _write_status(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _prepare_status_pair(
        tmp_path: Path,
        *,
        task_state: str = "running",
        attempt_state: str = "running",
        task_id: str = "dr-status",
        attempt_id: str = "attempt-0001",
        attempt_path: str = "attempts/attempt-0001",
) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    task_dir = _task_dir(project, task_id)
    attempt_status_path = task_dir / "attempts" / attempt_id / "status.json"
    _write_status(task_dir / "status.json", {
        "schema_version": "DeepResearchDetachedTask/v2",
        "status_schema": "ProviderRuntimeStatus/v1",
        "task_id": task_id,
        "state": task_state,
        "attempt_id": attempt_id,
        "attempt_path": attempt_path,
    })
    _write_status(attempt_status_path, {
        "schema_version": "ProviderRuntimeStatus/v1",
        "task_schema_version": "DeepResearchDetachedTask/v2",
        "task_id": task_id,
        "attempt_id": attempt_id,
        "state": attempt_state,
    })
    return project, task_dir, attempt_status_path


@pytest.mark.parametrize("attempt_state", [
    "provider_failed",
    "job_timed_out",
    "waiting_external",
])
def test_running_task_reports_current_attempt_runtime_state(tmp_path, attempt_state):
    project, _, _ = _prepare_status_pair(
        tmp_path, attempt_state=attempt_state
    )

    assert dr_task.get_status(project, "dr-status")["state"] == attempt_state


def test_running_task_does_not_promote_succeeded_attempt(tmp_path):
    project, _, _ = _prepare_status_pair(
        tmp_path, attempt_state="succeeded"
    )

    assert dr_task.get_status(project, "dr-status")["state"] == "running"


def test_succeeded_task_remains_authoritative_over_succeeded_attempt(tmp_path):
    project, _, _ = _prepare_status_pair(
        tmp_path, task_state="succeeded", attempt_state="succeeded"
    )

    assert dr_task.get_status(project, "dr-status")["state"] == "succeeded"


def test_status_without_attempt_pointer_keeps_legacy_behavior(tmp_path):
    project = tmp_path / "project"
    task_dir = _task_dir(project, "dr-legacy")
    legacy = {
        "schema_version": dr_task.TASK_SCHEMA_VERSION,
        "task_id": "dr-legacy",
        "state": "running",
    }
    _write_status(task_dir / "status.json", legacy)

    assert dr_task.get_status(project, "dr-legacy") == legacy


def test_attempt_id_and_path_must_identify_the_same_attempt(tmp_path):
    project, task_dir, _ = _prepare_status_pair(tmp_path)
    task_status_path = task_dir / "status.json"
    task_status = json.loads(task_status_path.read_text(encoding="utf-8"))
    task_status["attempt_path"] = "attempts/attempt-0002"
    _write_status(task_status_path, task_status)

    with pytest.raises(dr_task.DetachedTaskError):
        dr_task.get_status(project, "dr-status")


def test_attempt_status_task_id_must_match_task(tmp_path):
    project, _, attempt_status_path = _prepare_status_pair(tmp_path)
    attempt_status = json.loads(attempt_status_path.read_text(encoding="utf-8"))
    attempt_status["task_id"] = "dr-other"
    _write_status(attempt_status_path, attempt_status)

    with pytest.raises(dr_task.DetachedTaskError):
        dr_task.get_status(project, "dr-status")


def test_attempt_status_attempt_id_must_match_current_pointer(tmp_path):
    project, _, attempt_status_path = _prepare_status_pair(tmp_path)
    attempt_status = json.loads(attempt_status_path.read_text(encoding="utf-8"))
    attempt_status["attempt_id"] = "attempt-0002"
    _write_status(attempt_status_path, attempt_status)

    with pytest.raises(dr_task.DetachedTaskError):
        dr_task.get_status(project, "dr-status")


@pytest.mark.parametrize("attempt_path", [
    "../attempt-0001",
    "C:/outside/attempt-0001",
])
def test_attempt_path_rejects_escape_and_absolute_paths(tmp_path, attempt_path):
    project, _, _ = _prepare_status_pair(
        tmp_path, attempt_path=attempt_path
    )

    with pytest.raises(dr_task.DetachedTaskError):
        dr_task.get_status(project, "dr-status")


@pytest.mark.parametrize("contents", [None, "{"])
def test_attempt_status_missing_or_corrupt_fails_closed(tmp_path, contents):
    project, _, attempt_status_path = _prepare_status_pair(tmp_path)
    attempt_status_path.unlink()
    if contents is not None:
        attempt_status_path.write_text(contents, encoding="utf-8")

    with pytest.raises(dr_task.DetachedTaskError):
        dr_task.get_status(project, "dr-status")


def test_repeated_worker_attempts_keep_independent_stderr_and_current_pointer(tmp_path):
    project = _prepare_task(tmp_path)
    task_id = "dr-attempts"

    def first_failure(_args):
        print("original attempt failure", file=__import__("sys").stderr)
        return 15

    def second_failure(_args):
        print("fresh attempt timeout", file=__import__("sys").stderr)
        return 15

    assert dr_task.run_worker(project, task_id, first_failure) == 15
    assert dr_task.run_worker(project, task_id, second_failure) == 15

    attempts = sorted((_task_dir(project, task_id) / "attempts").iterdir())
    assert [path.name for path in attempts] == ["attempt-0001", "attempt-0002"]
    assert (attempts[0] / "worker_stderr.log").read_text(encoding="utf-8").strip() == "original attempt failure"
    assert (attempts[1] / "worker_stderr.log").read_text(encoding="utf-8").strip() == "fresh attempt timeout"

    current = json.loads((_task_dir(project, task_id) / "status.json").read_text(encoding="utf-8"))
    assert current["state"] == "failed"
    assert current["attempt_id"] == "attempt-0002"
    assert current["attempt_path"] == "attempts/attempt-0002"
    assert json.loads((attempts[0] / "status.json").read_text(encoding="utf-8"))["attempt_id"] == "attempt-0001"


def test_fresh_attempt_timeout_has_independent_runtime_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "timeout")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.15")
    project = _prepare_task(tmp_path, task_id="dr-timeout")
    task_id = "dr-timeout"

    def timeout_handler(_args):
        runtime_dir = Path(os.environ["RLR_DEEP_RESEARCH_TASK_DIR"])
        result = run_observed_provider(
            command=[sys.executable, str(FIXTURE), "exec", "--json"],
            prompt="timeout attempt",
            runtime_dir=runtime_dir,
            backend="codex",
            task_id=task_id,
            candidate_id="C1",
            node="L1",
            job_timeout=0.6,
            observer_interval=0.02,
        )
        assert result.final_status == "job_timed_out"
        return 15

    assert dr_task.run_worker(project, task_id, timeout_handler) == 15
    assert dr_task.run_worker(project, task_id, timeout_handler) == 15

    attempts = sorted((_task_dir(project, task_id) / "attempts").iterdir())
    receipts = [
        json.loads((attempt / "runtime_receipt.json").read_text(encoding="utf-8"))
        for attempt in attempts
    ]
    assert [receipt["attempt_id"] for receipt in receipts] == [
        "attempt-0001", "attempt-0002"
    ]
    assert all(receipt["final_status"] == "job_timed_out" for receipt in receipts)
    assert all(receipt["timed_out"] is True for receipt in receipts)
