from pathlib import Path
from types import SimpleNamespace

from research_loop import maintenance_autowake_adapter as adapter
from rlr_maintenance.autowake import (
    AUTOWAKE_RETRY_GUARD_ENV,
    RepairHandoff,
)


def _handoff(tmp_path: Path) -> RepairHandoff:
    worktree = tmp_path / "repair-worktree"
    worktree.mkdir()
    return RepairHandoff(
        outcome="verified",
        event_id="rme-0123456789abcdefabcd",
        event_path=tmp_path / "event.json",
        commit_sha="a" * 40,
        worktree_path=worktree,
    )


def test_resume_verified_worker_uses_repaired_cli_same_task_and_retry_guard(tmp_path):
    handoff = _handoff(tmp_path)
    repaired_cli = handoff.worktree_path / "research_loop_v04.py"
    repaired_cli.write_text("# fixture\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    calls = []

    def runner(command, **kwargs):
        calls.append((list(command), kwargs))
        return SimpleNamespace(returncode=0)

    result = adapter._resume_verified_worker(
        project_dir=project,
        task_id="dr-original",
        request={"working_directory": str(working_directory)},
        handoff=handoff,
        runner=runner,
    )

    assert result == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert Path(command[1]) == repaired_cli
    assert command[2] == "_deep-research-worker"
    assert Path(command[3]) == project.resolve()
    assert command[4] == "dr-original"
    assert kwargs["cwd"] == working_directory
    assert kwargs["env"][AUTOWAKE_RETRY_GUARD_ENV] == "1"
    assert kwargs["shell"] is False


def test_resume_verified_worker_fails_closed_without_repaired_entrypoint(tmp_path):
    handoff = _handoff(tmp_path)
    calls = []

    result = adapter._resume_verified_worker(
        project_dir=tmp_path,
        task_id="dr-original",
        request={},
        handoff=handoff,
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert result is None
    assert calls == []


def _fake_detached_module(tmp_path: Path, original_returncode: int):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    request = {
        "working_directory": str(tmp_path),
        "handler_args": {
            "project_dir": str(tmp_path),
            "cand_id": "C-test",
            "node": "L4B",
        },
    }
    status = {
        "state": "provider_failed",
        "termination_reason": "provider_exit_nonzero",
        "updated_at": "2026-08-16T00:00:00+00:00",
    }
    calls = []

    def original_run_worker(project_dir, task_id, synchronous_handler):
        calls.append((project_dir, task_id, synchronous_handler))
        return original_returncode

    def read_json(path, _label):
        return request if path.name == "request.json" else status

    return SimpleNamespace(
        run_worker=original_run_worker,
        _task_dir=lambda _project, _task_id: task_dir,
        _read_json=read_json,
        _validate_request=lambda _request, _project, _task_id: request["handler_args"],
    ), calls


def test_adapter_success_path_never_wakes_meta_rlr(tmp_path, monkeypatch):
    module, original_calls = _fake_detached_module(tmp_path, 0)
    wake_calls = []
    monkeypatch.setattr(
        adapter,
        "maybe_wake_meta_rlr",
        lambda **kwargs: wake_calls.append(kwargs),
    )
    adapter.install(module)

    result = module.run_worker(tmp_path, "dr-test", object())

    assert result == 0
    assert len(original_calls) == 1
    assert wake_calls == []


def test_adapter_verified_repair_resumes_and_returns_fresh_worker_result(tmp_path, monkeypatch):
    module, _ = _fake_detached_module(tmp_path, 3)
    handoff = _handoff(tmp_path)
    wake_calls = []
    resume_calls = []

    def wake(**kwargs):
        wake_calls.append(kwargs)
        return handoff

    def resume(**kwargs):
        resume_calls.append(kwargs)
        return 0

    monkeypatch.setattr(adapter, "maybe_wake_meta_rlr", wake)
    monkeypatch.setattr(adapter, "_resume_verified_worker", resume)
    adapter.install(module)

    result = module.run_worker(tmp_path, "dr-test", object())

    assert result == 0
    assert len(wake_calls) == 1
    assert wake_calls[0]["task_id"] == "dr-test"
    assert wake_calls[0]["status"]["termination_reason"] == "provider_exit_nonzero"
    assert len(resume_calls) == 1
    assert resume_calls[0]["handoff"] == handoff
    assert resume_calls[0]["task_id"] == "dr-test"


def test_adapter_failed_post_repair_worker_does_not_claim_success(tmp_path, monkeypatch):
    module, _ = _fake_detached_module(tmp_path, 3)
    handoff = _handoff(tmp_path)
    monkeypatch.setattr(adapter, "maybe_wake_meta_rlr", lambda **_kwargs: handoff)
    monkeypatch.setattr(adapter, "_resume_verified_worker", lambda **_kwargs: 3)
    adapter.install(module)

    assert module.run_worker(tmp_path, "dr-test", object()) == 3
