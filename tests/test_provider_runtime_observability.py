from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from research_loop import deep_research_task
from research_loop.provider_runtime_observability import run_observed_provider


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex_jsonl.py"


def _wait_for(predicate, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition was not observed before timeout")


def _status(runtime_dir: Path) -> dict:
    try:
        return json.loads((runtime_dir / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _run(runtime_dir: Path, *, timeout: float = 3.0):
    return run_observed_provider(
        command=[sys.executable, str(FIXTURE), "exec", "--json"],
        prompt="fixture prompt",
        runtime_dir=runtime_dir,
        backend="codex",
        task_id="dr-fixture",
        candidate_id="C1",
        node="L1",
        job_timeout=timeout,
        observer_interval=0.05,
    )


def test_events_and_current_item_are_visible_before_provider_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.30")
    runtime = tmp_path / "runtime"
    holder = {}
    thread = threading.Thread(target=lambda: holder.setdefault("result", _run(runtime)))
    thread.start()

    status = _wait_for(lambda: (
        value if (value := _status(runtime)).get("current_item", {}).get("id") == "item-1" else None
    ))
    assert (runtime / "events.jsonl").stat().st_size > 0
    assert status["revision"] >= 3
    assert status["last_provider_event_at"]
    assert status["current_item"]["type"] == "command_execution"
    assert status["current_item"]["command"] == "fixture command"
    assert thread.is_alive(), "progress must be visible before provider completion"

    thread.join(5)
    assert holder["result"].final_status == "succeeded"


def test_silent_provider_keeps_observer_heartbeat_separate_from_provider_event(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "silent")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.25")
    runtime = tmp_path / "runtime"
    thread = threading.Thread(target=lambda: _run(runtime))
    thread.start()

    first = _wait_for(lambda: (
        value if (value := _status(runtime)).get("last_provider_event", {}).get("type") == "turn.started" else None
    ))
    event_time = first["last_provider_event_at"]
    heartbeat = first["observer_heartbeat_at"]
    later = _wait_for(lambda: (
        value if (value := _status(runtime)).get("observer_heartbeat_at") != heartbeat else None
    ))
    assert later["provider_alive"] is True
    assert later["last_provider_event_at"] == event_time
    assert later["observer_heartbeat_at"] != event_time

    thread.join(5)


def test_unfinished_mcp_item_is_reported_as_exact_wait_point(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stuck_mcp")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.20")
    runtime = tmp_path / "runtime"
    holder = {}
    thread = threading.Thread(
        target=lambda: holder.setdefault("result", _run(runtime, timeout=0.7))
    )
    thread.start()

    status = _wait_for(lambda: (
        value if (value := _status(runtime)).get("current_item", {}).get("type") == "mcp_tool_call" else None
    ))
    assert status["state"] == "waiting_external"
    assert status["current_item"] == {
        "id": "item-1",
        "type": "mcp_tool_call",
        "status": "in_progress",
        "server": "fixture-mcp",
        "tool": "search",
    }
    assert status["last_provider_event"]["type"] == "item.started"

    thread.join(5)
    assert holder["result"].final_status == "job_timed_out"


def test_job_timeout_preserves_partial_logs_and_process_cleanup_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "timeout")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.15")
    runtime = tmp_path / "runtime"

    result = _run(runtime, timeout=0.6)

    assert result.final_status == "job_timed_out"
    assert (runtime / "events.jsonl").stat().st_size > 0
    assert "fixture diagnostic" in (runtime / "stderr.log").read_text(encoding="utf-8")
    receipt_path = runtime / "runtime_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "ProviderRuntimeReceipt/v1"
    assert receipt["termination_reason"] == "job_timeout"
    assert receipt["timed_out"] is True
    assert receipt["process_tree_cleanup"]["attempted"] is True
    assert receipt["process_tree_cleanup"]["provider_alive_after_cleanup"] is False
    assert result.runtime_receipt_sha256
    assert result.runtime_receipt_sha256 == hashlib.sha256(receipt_path.read_bytes()).hexdigest()


def test_event_stream_and_final_structured_output_are_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.05")
    runtime = tmp_path / "runtime"

    result = _run(runtime)

    events = [json.loads(line) for line in (runtime / "events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    final = json.loads((runtime / "final_output.json").read_text(encoding="utf-8"))
    assert any(event["type"] == "item.started" for event in events)
    assert final["schema_version"] == "1.0"
    assert not any(event == final for event in events)
    assert json.loads(result.final_output)["papers"][0]["doi"] == "10.1000/fixture"


def test_status_reader_keeps_v1_detached_task_compatibility():
    legacy = {
        "schema_version": "DeepResearchDetachedTask/v1",
        "task_id": "dr-old",
        "state": "running",
        "updated_at": "2026-08-05T00:00:00+00:00",
    }
    deep_research_task._validate_status(legacy, "dr-old")


def test_runtime_status_never_exposes_reasoning_text(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.05")
    runtime = tmp_path / "runtime"
    result = _run(runtime)
    assert result.final_status == "succeeded"
    serialized = json.dumps(_status(runtime), ensure_ascii=False)
    assert "reasoning" not in serialized or '"type": "reasoning"' in serialized
    assert "text" not in _status(runtime).get("current_item", {})


def test_terminal_status_keeps_existing_revision_monotonic(tmp_path, monkeypatch):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "status.json").write_text(json.dumps({
        "schema_version": "ProviderRuntimeStatus/v1",
        "task_schema_version": "DeepResearchDetachedTask/v2",
        "task_id": "dr-revision",
        "state": "running",
        "revision": 310,
        "provider_alive": True,
    }), encoding="utf-8")
    monkeypatch.setenv("RLR_DEEP_RESEARCH_TASK_DIR", str(task_dir))

    terminal = deep_research_task._status(
        "dr-revision", "succeeded", run_id="run-fixture"
    )

    assert terminal["revision"] == 311
    assert terminal["state"] == "succeeded"


def test_worker_diagnostics_cannot_mutate_provider_stderr_after_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    task_id = "dr-stderr-ownership"
    task_dir = (
        tmp_path / "08_Audit" / "deep_research_runtime" / "tasks" / task_id
    )
    task_dir.mkdir(parents=True)
    (task_dir / "request.json").write_text(json.dumps({
        "schema_version": deep_research_task.TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "handler_args": {
            "project_dir": str(tmp_path.resolve()),
            "cand_id": "C1",
            "node": "L1",
            "backend": "codex",
        },
    }), encoding="utf-8")
    (task_dir / "status.json").write_text(json.dumps({
        "schema_version": deep_research_task.TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "state": "running",
    }), encoding="utf-8")

    def handler(_args):
        result = run_observed_provider(
            command=[sys.executable, str(FIXTURE), "exec", "--json"],
            prompt="fixture prompt",
            runtime_dir=task_dir,
            backend="codex",
            task_id=task_id,
            candidate_id="C1",
            node="L1",
            job_timeout=3,
            observer_interval=0.01,
        )
        assert result.final_status == "succeeded"
        print("post-provider worker diagnostic", file=sys.stderr, flush=True)
        return 3

    assert deep_research_task.run_worker(tmp_path, task_id, handler) == 3

    receipt = json.loads((task_dir / "runtime_receipt.json").read_text(encoding="utf-8"))
    provider_stderr = task_dir / "stderr.log"
    actual_hash = hashlib.sha256(provider_stderr.read_bytes()).hexdigest()
    assert receipt["artifacts"]["stderr"]["sha256"] == actual_hash
    worker_stderr = task_dir / "worker_stderr.log"
    assert worker_stderr.is_file()
    assert "post-provider worker diagnostic" in worker_stderr.read_text(encoding="utf-8")


def test_recoverable_error_event_does_not_claim_terminal_provider_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "recoverable_error")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.15")
    runtime = tmp_path / "runtime"
    holder = {}
    thread = threading.Thread(target=lambda: holder.setdefault("result", _run(runtime)))
    thread.start()

    status = _wait_for(lambda: (
        value if (
            (value := _status(runtime)).get("last_provider_event", {}).get("type") == "error"
        ) else None
    ))
    assert status["provider_alive"] is True
    assert status["state"] != "provider_failed"

    thread.join(5)
    assert holder["result"].final_status == "succeeded"


def test_worker_failure_after_provider_success_becomes_validation_failed(tmp_path, monkeypatch):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "status.json").write_text(json.dumps({
        "schema_version": "ProviderRuntimeStatus/v1",
        "task_schema_version": "DeepResearchDetachedTask/v2",
        "task_id": "dr-validation",
        "state": "succeeded",
        "revision": 310,
        "provider_alive": False,
        "run_id": "run-fixture",
    }), encoding="utf-8")
    monkeypatch.setenv("RLR_DEEP_RESEARCH_TASK_DIR", str(task_dir))

    failed = deep_research_task._status(
        "dr-validation",
        "failed",
        error="L1 evidence lacks located Results extract",
    )

    assert failed["state"] == "validation_failed"
    assert failed["legacy_state"] == "failed"
    assert failed["revision"] == 311
