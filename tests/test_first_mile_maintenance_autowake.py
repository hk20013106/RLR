from pathlib import Path
from types import SimpleNamespace

from rlr_maintenance import autowake_adapter as adapter
from rlr_maintenance.autowake import (
    AUTOWAKE_CONFIG_ENV,
    AUTOWAKE_RETRY_GUARD_ENV,
    RepairHandoff,
)


def _handoff(tmp_path: Path, entrypoint: str = "research_loop_v04.py") -> RepairHandoff:
    worktree = tmp_path / "repair-worktree"
    worktree.mkdir()
    (worktree / entrypoint).write_text("# repaired fixture\n", encoding="utf-8")
    return RepairHandoff(
        outcome="verified",
        event_id="rme-0123456789abcdefabcd",
        event_path=tmp_path / "event.json",
        commit_sha="a" * 40,
        worktree_path=worktree,
    )


def test_first_mile_wrapper_success_is_inert(monkeypatch, tmp_path):
    wake_calls = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: wake_calls.append(kwargs),
        raising=False,
    )

    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 0,
        entrypoint_name="research_loop_v04.py",
    )

    assert wrapped(["preflight", str(tmp_path), "--backend", "codex"]) == 0
    assert wake_calls == []


def test_first_mile_wrapper_is_inert_without_autowake_config(monkeypatch, tmp_path):
    monkeypatch.delenv(AUTOWAKE_CONFIG_ENV, raising=False)
    wake_calls = []
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: wake_calls.append(kwargs),
        raising=False,
    )

    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3,
        entrypoint_name="research_loop_v04.py",
    )

    assert wrapped(["preflight", str(tmp_path), "--backend", "codex"]) == 3
    assert wake_calls == []


def test_first_mile_wrapper_replays_verified_preflight_from_repair_worktree(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    project.mkdir()
    handoff = _handoff(tmp_path)
    wake_calls = []
    replay_calls = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")

    def wake(**kwargs):
        wake_calls.append(kwargs)
        return handoff

    def replay(**kwargs):
        replay_calls.append(kwargs)
        return 0

    monkeypatch.setattr(adapter, "maybe_wake_first_mile_failure", wake, raising=False)
    monkeypatch.setattr(adapter, "_resume_verified_cli", replay, raising=False)
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_BINDING_MISMATCH",
            "reason": "project binding differs from receipt",
        },
        raising=False,
    )

    argv = ["preflight", str(project), "--backend", "codex"]
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3,
        entrypoint_name="research_loop_v04.py",
    )

    assert wrapped(argv) == 0
    assert len(wake_calls) == 1
    assert wake_calls[0]["project_dir"] == project
    assert wake_calls[0]["failure"]["code"] == "PROJECT_READY_BINDING_MISMATCH"
    assert wake_calls[0]["operation"] == "preflight"
    assert len(replay_calls) == 1
    assert replay_calls[0]["handoff"] == handoff
    assert replay_calls[0]["entrypoint_name"] == "research_loop_v04.py"
    assert replay_calls[0]["argv"] == argv


def test_first_mile_wrapper_does_not_repair_expected_configuration_failure(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    project.mkdir()
    wake_calls = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_HOST_MISMATCH",
            "reason": "declared backend does not match this host",
        },
        raising=False,
    )
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: wake_calls.append(kwargs),
        raising=False,
    )

    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3,
        entrypoint_name="research_loop_v04.py",
    )

    assert wrapped(["preflight", str(project), "--backend", "codex"]) == 3
    assert wake_calls == []


def test_first_mile_wrapper_covers_canonical_runner_project_ready_failure(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "C001.md").write_text("---\ncurrent_status: NEW\n---\n", encoding="utf-8")
    handoff = _handoff(tmp_path, entrypoint="run_loop.py")
    wake_calls = []
    replay_calls = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_CANDIDATE_BINDING_MISMATCH",
            "reason": "candidate does not pin the current receipt",
        },
        raising=False,
    )
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: (wake_calls.append(kwargs) or handoff),
        raising=False,
    )
    monkeypatch.setattr(
        adapter,
        "_resume_verified_cli",
        lambda **kwargs: (replay_calls.append(kwargs) or 0),
        raising=False,
    )

    argv = ["run", str(project), "C001"]
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3,
        entrypoint_name="run_loop.py",
    )

    assert wrapped(argv) == 0
    assert wake_calls[0]["operation"] == "run"
    assert wake_calls[0]["project_dir"] == project
    assert replay_calls[0]["entrypoint_name"] == "run_loop.py"
    assert replay_calls[0]["argv"] == argv


def test_resume_verified_cli_uses_repaired_entrypoint_and_preserves_argv(
    monkeypatch, tmp_path
):
    handoff = _handoff(tmp_path)
    calls = []
    monkeypatch.setenv(AUTOWAKE_RETRY_GUARD_ENV, "1")

    def runner(command, **kwargs):
        calls.append((list(command), kwargs))
        return SimpleNamespace(returncode=0)

    argv = ["preflight", str(tmp_path / "project"), "--backend", "codex"]
    result = adapter._resume_verified_cli(
        handoff=handoff,
        entrypoint_name="research_loop_v04.py",
        argv=argv,
        runner=runner,
    )

    assert result == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert Path(command[1]) == handoff.worktree_path / "research_loop_v04.py"
    assert command[2:] == argv
    assert kwargs["shell"] is False
    assert AUTOWAKE_RETRY_GUARD_ENV not in kwargs["env"]
