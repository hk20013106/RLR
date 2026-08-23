import json
import os
import sys
from pathlib import Path

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
