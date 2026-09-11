import json
from pathlib import Path
from types import SimpleNamespace

from rlr_maintenance import autowake
from rlr_maintenance import autowake_adapter as adapter
from rlr_maintenance.autowake import (
    AUTOWAKE_CONFIG_ENV,
    AUTOWAKE_RETRY_GUARD_ENV,
    RepairHandoff,
)
from rlr_maintenance.contracts import validate_maintenance_event


BASE_SHA = "a" * 40


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


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "autowake.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "RLRMetaAutoWakeConfig/v1",
                "loopx_project": str(tmp_path / "loopx-project"),
                "goal_id": "goal-first-mile",
                "agent_id": "meta-rlr",
                "workspace_parent": str(tmp_path / "repairs"),
                "registry": str(tmp_path / "loopx-registry.json"),
                "loopx_executable": "loopx",
                "quota_runtime_profile": "outer_controller",
                "quota_scan_root": str(tmp_path),
                "codex_executable": "codex",
                "capabilities": ["shell"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_first_mile_wrapper_success_is_inert(monkeypatch, tmp_path):
    wake_calls = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: wake_calls.append(kwargs),
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

    monkeypatch.setattr(adapter, "maybe_wake_first_mile_failure", wake)
    monkeypatch.setattr(adapter, "_resume_verified_cli", replay)
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_BINDING_MISMATCH",
            "reason": "project binding differs from receipt",
        },
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
    replay_calls = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_HOST_MISMATCH",
            "reason": "declared backend does not match this host",
        },
    )
    monkeypatch.setattr(
        adapter,
        "_resume_verified_cli",
        lambda **kwargs: replay_calls.append(kwargs),
    )

    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3,
        entrypoint_name="research_loop_v04.py",
    )

    assert wrapped(["preflight", str(project), "--backend", "codex"]) == 3
    assert replay_calls == []


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
            "code": "PROJECT_READY_BINDING_MISMATCH",
            "reason": "project binding differs from receipt",
        },
    )
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: (wake_calls.append(kwargs) or handoff),
    )
    monkeypatch.setattr(
        adapter,
        "_resume_verified_cli",
        lambda **kwargs: (replay_calls.append(kwargs) or 0),
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


def test_repairable_first_mile_failure_uses_existing_meta_cli_and_l0_profile(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    (project / "00_Preflight").mkdir(parents=True)
    (project / "00_Preflight" / "preflight_receipt.json").write_text(
        "{}\n", encoding="utf-8"
    )
    config = _config(tmp_path)
    repair_worktree = tmp_path / "repairs" / "verified"
    repair_worktree.mkdir(parents=True)
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, str(config))
    monkeypatch.setattr(autowake, "_current_revision", lambda _repo, _runner: BASE_SHA)
    monkeypatch.setattr(
        autowake,
        "_resolve_verified_worktree",
        lambda **_kwargs: repair_worktree,
    )
    calls = []

    def runner(command, **kwargs):
        calls.append((list(command), kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "outcome": "verified",
                    "event_id": "unused",
                    "todo_id": "todo-1",
                    "profile_id": "l0_state_integrity",
                    "commit_sha": "b" * 40,
                    "reason": None,
                }
            ),
            stderr="",
        )

    result = autowake.maybe_wake_first_mile_failure(
        project_dir=project,
        operation="preflight",
        failure={
            "code": "PROJECT_READY_BINDING_MISMATCH",
            "reason": "project binding differs from receipt",
        },
        command_runner=runner,
    )

    assert result is not None
    assert result.worktree_path == repair_worktree
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert Path(command[1]).name == "meta_rlr.py"
    assert command[2] == "run-once"
    assert kwargs["env"][AUTOWAKE_RETRY_GUARD_ENV] == "1"
    event = validate_maintenance_event(
        json.loads(result.event_path.read_text(encoding="utf-8"))
    )
    assert event["event_type"] == "contract_failure"
    assert event["component"] == "first_mile:preflight"
    assert event["expected_contract"] == "first_mile_project_ready_integrity"
    assert event["observed"]["error_code"] == "PROJECT_READY_BINDING_MISMATCH"
