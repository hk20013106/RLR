from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from research_loop import deep_research
from research_loop import deep_research_task
from research_loop import provider_runtime_observability as runtime_observability
from research_loop.provider_runtime_observability import run_observed_provider


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex_jsonl.py"


def _wait_for(predicate, timeout: float = 10.0):
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


def _frozen_artifact_bytes(receipt_path: Path) -> dict[str, bytes]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    return {
        "runtime_receipt.json": receipt_path.read_bytes(),
        **{
            record["path"]: (receipt_path.parent / record["path"]).read_bytes()
            for record in receipt["artifacts"].values()
        },
    }


def _receipt_reference(root: Path, receipt_path: Path) -> dict:
    return {
        "schema": runtime_observability.RECEIPT_SCHEMA,
        "path": receipt_path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }


def _rewrite_frozen_receipt(root: Path, receipt_path: Path, mutate) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    mutate(receipt)
    receipt_bytes = (
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    rewritten_dir = receipt_path.parent.with_name(receipt_sha256)
    rewritten_dir.mkdir()
    for name in ("events.jsonl", "stderr.log", "final_output.json"):
        (rewritten_dir / name).write_bytes((receipt_path.parent / name).read_bytes())
    rewritten_receipt = rewritten_dir / "runtime_receipt.json"
    rewritten_receipt.write_bytes(receipt_bytes)
    return _receipt_reference(root, rewritten_receipt)


def test_sequential_invocations_preserve_first_immutable_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    runtime = tmp_path / "runtime"

    first = _run(runtime)
    first_bytes = _frozen_artifact_bytes(first.runtime_receipt_path)
    for name, content in first_bytes.items():
        assert (runtime / name).read_bytes() == content
    second = _run(runtime)
    second_bytes = _frozen_artifact_bytes(second.runtime_receipt_path)

    assert first.runtime_receipt_path != second.runtime_receipt_path
    assert first.runtime_receipt_path.parent.parent.name == "provider_runtime"
    assert first.runtime_receipt_path.parent.name == first.runtime_receipt_sha256
    assert _frozen_artifact_bytes(first.runtime_receipt_path) == first_bytes
    for name in ("events.jsonl", "stderr.log", "final_output.json"):
        assert second_bytes[name] == first_bytes[name]
    runtime_observability.validate_runtime_receipt_reference(
        tmp_path,
        _receipt_reference(tmp_path, first.runtime_receipt_path),
        require_success=True,
    )


def test_skill_receipt_references_invocation_work_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    runtime = (
        tmp_path / "08_Audit" / "deep_research_runtime" / "tasks" / "dr-snapshot"
    )
    method_work = tmp_path / "method_support_001_M01"
    legacy_final = tmp_path / "legacy_final.json"
    prompt = "immutable receipt fixture prompt"
    command = [
        sys.executable,
        str(FIXTURE),
        "exec",
        "--json",
        "--output-last-message",
        str(legacy_final),
    ]
    context = {
        "runtime_dir": runtime,
        "project_dir": tmp_path,
        "task_id": "dr-snapshot",
        "candidate_id": "C1",
        "node": "L4",
        "backend": "codex",
        "execution": None,
    }
    token = runtime_observability._CONTEXT.set(context)
    try:
        deep_research.build_invocation(
            deep_research.RuntimeSpec(
                "codex", "codex", model="fixture-model", timeout=3
            ),
            "L4",
            "fixture question",
            "fixture claim",
            method_work,
        )
        completed = deep_research.execute_provider_invocation(
            command,
            {"input": prompt},
            timeout=3,
        )
        receipt = deep_research.skill_receipt(
            "codex",
            command,
            prompt,
            "fixture",
            exit_code=completed.returncode,
            stdout_hash=hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
            model="fixture-model",
        )
    finally:
        runtime_observability._CONTEXT.reset(token)

    frozen_path = tmp_path / receipt["runtime_receipt"]["path"]
    assert frozen_path == context["execution"].runtime_receipt_path
    assert frozen_path.parent.parent == method_work / "provider_runtime"
    assert frozen_path.parent.name == receipt["runtime_receipt"]["sha256"]
    assert frozen_path != runtime / "runtime_receipt.json"


@pytest.mark.parametrize(
    "damage",
    ["missing_artifact", "wrong_artifact_bytes", "wrong_receipt_hash", "malformed_receipt"],
)
def test_runtime_receipt_snapshot_validation_fails_closed(
    tmp_path, monkeypatch, damage
):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    result = _run(tmp_path / "runtime")
    reference = _receipt_reference(tmp_path, result.runtime_receipt_path)
    receipt = json.loads(result.runtime_receipt_path.read_text(encoding="utf-8"))

    if damage == "missing_artifact":
        (result.runtime_receipt_path.parent / receipt["artifacts"]["events"]["path"]).unlink()
    elif damage == "wrong_artifact_bytes":
        (result.runtime_receipt_path.parent / receipt["artifacts"]["stderr"]["path"]).write_bytes(
            b"tampered"
        )
    elif damage == "wrong_receipt_hash":
        reference["sha256"] = "0" * 64
    else:
        result.runtime_receipt_path.write_text("{", encoding="utf-8")
        malformed_sha256 = hashlib.sha256(
            result.runtime_receipt_path.read_bytes()
        ).hexdigest()
        malformed_dir = result.runtime_receipt_path.parent.with_name(malformed_sha256)
        result.runtime_receipt_path.parent.rename(malformed_dir)
        reference = _receipt_reference(
            tmp_path,
            malformed_dir / "runtime_receipt.json",
        )

    with pytest.raises(
        runtime_observability.ProviderRuntimeIntegrityError,
        match="runtime receipt",
    ):
        runtime_observability.validate_runtime_receipt_reference(
            tmp_path,
            reference,
            require_success=True,
        )


@pytest.mark.parametrize(
    ("expected_key", "wrong_value"),
    [
        ("expected_candidate_id", "C-FOREIGN"),
        ("expected_backend", "foreign-backend"),
        ("expected_prompt_sha256", "0" * 64),
        ("expected_command_sha256", "1" * 64),
        ("expected_final_output_sha256", "2" * 64),
    ],
)
def test_runtime_receipt_snapshot_is_bound_to_expected_invocation(
    tmp_path, monkeypatch, expected_key, wrong_value
):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    result = _run(tmp_path / "runtime")
    reference = _receipt_reference(tmp_path, result.runtime_receipt_path)

    with pytest.raises(
        runtime_observability.ProviderRuntimeIntegrityError,
        match="runtime receipt.*mismatch",
    ):
        runtime_observability.validate_runtime_receipt_reference(
            tmp_path,
            reference,
            require_success=True,
            **{expected_key: wrong_value},
        )


@pytest.mark.parametrize("damage", ["missing_field", "boolean_exit_code"])
def test_runtime_receipt_snapshot_rejects_malformed_contract(
    tmp_path, monkeypatch, damage
):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    result = _run(tmp_path / "runtime")

    def mutate(receipt):
        if damage == "missing_field":
            del receipt["candidate_id"]
        else:
            receipt["exit_code"] = False

    reference = _rewrite_frozen_receipt(
        tmp_path,
        result.runtime_receipt_path,
        mutate,
    )
    with pytest.raises(
        runtime_observability.ProviderRuntimeIntegrityError,
        match="runtime receipt.*invalid",
    ):
        runtime_observability.validate_runtime_receipt_reference(
            tmp_path,
            reference,
            require_success=True,
        )


def test_partial_snapshot_publication_is_not_exposed(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    runtime = tmp_path / "runtime"
    invocation_work = tmp_path / "method_support_001_M01"
    original_replace = runtime_observability.os.replace

    def fail_snapshot_publish(source, destination):
        destination = Path(destination)
        if destination.parent.name == "provider_runtime" and Path(source).is_dir():
            raise OSError("simulated snapshot publication interruption")
        return original_replace(source, destination)

    monkeypatch.setattr(runtime_observability.os, "replace", fail_snapshot_publish)

    with pytest.raises(OSError, match="publication interruption"):
        run_observed_provider(
            command=[sys.executable, str(FIXTURE), "exec", "--json"],
            prompt="fixture prompt",
            runtime_dir=runtime,
            invocation_work_dir=invocation_work,
            backend="codex",
            task_id="dr-partial",
            candidate_id="C1",
            node="L4",
            job_timeout=3,
            observer_interval=0.01,
        )

    receipt_sha256 = hashlib.sha256(
        (runtime / "runtime_receipt.json").read_bytes()
    ).hexdigest()
    assert not (invocation_work / "provider_runtime" / receipt_sha256).exists()


def test_atomic_status_write_retries_transient_windows_lock(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    original_replace = runtime_observability.os.replace
    calls = []

    def flaky_replace(source, destination):
        calls.append((source, destination))
        if len(calls) == 1:
            raise PermissionError(5, "destination is temporarily locked")
        return original_replace(source, destination)

    monkeypatch.setattr(runtime_observability.os, "replace", flaky_replace)

    runtime_observability._write_json_atomic(path, {"state": "running"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "running"}
    assert len(calls) == 2


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


def test_inactivity_timeout_preserves_receipt_and_cleans_process_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "silent")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "1.0")
    runtime = tmp_path / "runtime"

    result = run_observed_provider(
        command=[sys.executable, str(FIXTURE), "exec", "--json"],
        prompt="fixture prompt",
        runtime_dir=runtime,
        backend="codex",
        task_id="dr-inactivity",
        candidate_id="C1",
        node="L1",
        job_timeout=3,
        inactivity_timeout=0.3,
        observer_interval=0.05,
        cwd=tmp_path,
    )

    assert result.final_status == "inactivity_timed_out"
    receipt = json.loads((runtime / "runtime_receipt.json").read_text(encoding="utf-8"))
    assert receipt["termination_reason"] == "inactivity_timeout"
    assert receipt["timed_out"] is True
    assert receipt["cwd"] == str(tmp_path.resolve())
    assert receipt["timeout_config"] == {
        "job_timeout_seconds": 3,
        "inactivity_timeout_seconds": 0.3,
        "observer_interval_seconds": 0.05,
    }
    assert receipt["command_metadata"]["backend"] == "codex"
    assert receipt["process_tree_cleanup"]["attempted"] is True
    assert receipt["process_tree_cleanup"]["provider_alive_after_cleanup"] is False


def test_stderr_noise_cannot_indefinitely_refresh_effective_inactivity(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stderr_noise")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.03")
    original_snapshot = runtime_observability._process_snapshot

    def frozen_process_activity(pid):
        value = original_snapshot(pid)
        if value.get("alive"):
            value["cpu_seconds"] = 0.0
            value["io_bytes"] = 0
        return value

    monkeypatch.setattr(runtime_observability, "_process_snapshot", frozen_process_activity)
    result = run_observed_provider(
        command=[sys.executable, str(FIXTURE), "exec", "--json"],
        prompt="fixture prompt",
        runtime_dir=tmp_path / "runtime",
        backend="codex",
        task_id="dr-stderr-noise",
        candidate_id="C1",
        node="L1",
        job_timeout=0.8,
        inactivity_timeout=0.15,
        observer_interval=0.03,
        cwd=tmp_path,
    )

    assert result.final_status == "inactivity_timed_out"


def test_process_activity_aggregates_active_child_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "child_busy")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    result = run_observed_provider(
        command=[sys.executable, str(FIXTURE), "exec", "--json"],
        prompt="fixture prompt",
        runtime_dir=tmp_path / "runtime",
        backend="codex",
        task_id="dr-child-activity",
        candidate_id="C1",
        node="L1",
        job_timeout=0.7,
        inactivity_timeout=0.20,
        observer_interval=0.03,
        cwd=tmp_path,
    )
    receipt = json.loads((tmp_path / "runtime" / "runtime_receipt.json").read_text(encoding="utf-8"))

    assert result.final_status == "job_timed_out"
    assert receipt["process_activity"]["cpu_seconds"] > 0
    assert receipt["process_activity"]["last_process_activity_at"]


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
        runtime_dir = Path(os.environ["RLR_DEEP_RESEARCH_TASK_DIR"])
        result = run_observed_provider(
            command=[sys.executable, str(FIXTURE), "exec", "--json"],
            prompt="fixture prompt",
            runtime_dir=runtime_dir,
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

    current = json.loads((task_dir / "status.json").read_text(encoding="utf-8"))
    attempt_dir = task_dir / current["attempt_path"]
    receipt = json.loads((attempt_dir / "runtime_receipt.json").read_text(encoding="utf-8"))
    provider_stderr = attempt_dir / "stderr.log"
    actual_hash = hashlib.sha256(provider_stderr.read_bytes()).hexdigest()
    assert receipt["artifacts"]["stderr"]["sha256"] == actual_hash
    worker_stderr = attempt_dir / "worker_stderr.log"
    assert worker_stderr.is_file()
    assert "post-provider worker diagnostic" in worker_stderr.read_text(encoding="utf-8")


def test_recoverable_error_event_does_not_claim_terminal_provider_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "recoverable_error")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.15")
    runtime = tmp_path / "runtime"

    result = _run(runtime)
    events = [
        json.loads(line)
        for line in (runtime / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert any(event.get("type") == "error" for event in events)
    assert result.final_status == "succeeded"
    assert _status(runtime)["state"] != "provider_failed"


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


def test_receipt_retains_last_known_process_activity_after_provider_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    runtime = tmp_path / "runtime"
    original_snapshot = runtime_observability._process_snapshot

    def snapshot(pid):
        value = original_snapshot(pid)
        if value.get("alive"):
            value["cpu_seconds"] = 1.25
            value["io_bytes"] = 4242
        return value

    monkeypatch.setattr(runtime_observability, "_process_snapshot", snapshot)
    result = run_observed_provider(
        command=[sys.executable, str(FIXTURE), "exec", "--json"],
        prompt="fixture prompt",
        runtime_dir=runtime,
        backend="codex",
        task_id="dr-telemetry",
        candidate_id="C1",
        node="L1",
        job_timeout=3,
        observer_interval=0.20,
    )

    assert result.final_status == "succeeded"
    receipt = json.loads((runtime / "runtime_receipt.json").read_text(encoding="utf-8"))
    assert receipt["process_activity"]["cpu_seconds"] == 1.25
    assert receipt["process_activity"]["io_bytes"] == 4242
