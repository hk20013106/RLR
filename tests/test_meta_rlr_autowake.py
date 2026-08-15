import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rlr_maintenance import autowake
from rlr_maintenance.contracts import validate_maintenance_event


BASE_SHA = "3b3de53f4d51f6a2bf7b915532d15a91f5892c50"


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "autowake.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "RLRMetaAutoWakeConfig/v1",
                "loopx_project": str(tmp_path / "loopx-project"),
                "goal_id": "goal-phase3",
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


def _status(state: str = "provider_failed", reason: str = "provider_exit_nonzero") -> dict:
    return {
        "task_id": "dr-test",
        "state": state,
        "termination_reason": reason,
        "updated_at": "2026-08-16T00:00:00+00:00",
    }


def _handler_args(tmp_path: Path) -> dict:
    return {
        "project_dir": str(tmp_path / "project"),
        "cand_id": "C20260802150025462724",
        "node": "L4B",
    }


def test_autowake_is_disabled_without_explicit_config(tmp_path, monkeypatch):
    monkeypatch.delenv(autowake.AUTOWAKE_CONFIG_ENV, raising=False)
    calls = []

    result = autowake.maybe_wake_meta_rlr(
        project_dir=tmp_path / "project",
        task_id="dr-test",
        handler_args=_handler_args(tmp_path),
        returncode=3,
        status=_status(),
        command_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert result is None
    assert calls == []


@pytest.mark.parametrize(
    "state,reason",
    [
        ("running", ""),
        ("succeeded", "completed"),
        ("completed", "completed"),
        ("job_stopped", "operator_stop"),
        ("validation_failed", "completed"),
        ("provider_failed", "completed"),
        ("provider_failed", ""),
    ],
)
def test_autowake_fails_closed_for_non_runtime_repair_states(
    tmp_path, monkeypatch, state, reason
):
    config = _config(tmp_path)
    monkeypatch.setenv(autowake.AUTOWAKE_CONFIG_ENV, str(config))
    calls = []

    result = autowake.maybe_wake_meta_rlr(
        project_dir=tmp_path / "project",
        task_id="dr-test",
        handler_args=_handler_args(tmp_path),
        returncode=3,
        status=_status(state, reason),
        command_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert result is None
    assert calls == []


def _patch_verified_worktree(monkeypatch, repair_worktree: Path):
    monkeypatch.setattr(
        autowake,
        "_resolve_verified_worktree",
        lambda **_kwargs: repair_worktree,
    )


def test_autowake_emits_canonical_event_and_calls_existing_meta_cli(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    config = _config(tmp_path)
    monkeypatch.setenv(autowake.AUTOWAKE_CONFIG_ENV, str(config))
    monkeypatch.setattr(autowake, "_current_revision", lambda _repo, _runner: BASE_SHA)
    repair_worktree = tmp_path / "repairs" / "verified-worktree"
    repair_worktree.mkdir(parents=True)
    _patch_verified_worktree(monkeypatch, repair_worktree)
    calls = []

    def runner(command, **kwargs):
        calls.append((list(command), kwargs))
        payload = {
            "outcome": "verified",
            "event_id": "rme-placeholder",
            "todo_id": "todo-1",
            "profile_id": "provider_runtime_integrity",
            "commit_sha": "b" * 40,
            "reason": None,
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    result = autowake.maybe_wake_meta_rlr(
        project_dir=project,
        task_id="dr-test",
        handler_args=_handler_args(tmp_path),
        returncode=3,
        status=_status(),
        command_runner=runner,
    )

    assert result is not None
    assert result.outcome == "verified"
    assert result.worktree_path == repair_worktree
    assert result.commit_sha == "b" * 40
    assert len(calls) == 1
    command, command_kwargs = calls[0]
    assert "meta_rlr.py" in Path(command[1]).name
    assert command[2] == "run-once"
    assert "--quota-scan-root" in command
    assert command_kwargs["env"][autowake.AUTOWAKE_CONFIG_ENV] == str(config)
    assert command_kwargs["env"][autowake.AUTOWAKE_RETRY_GUARD_ENV] == "1"

    event = validate_maintenance_event(json.loads(result.event_path.read_text(encoding="utf-8")))
    assert event["event_type"] == "runtime_failure"
    assert event["component"] == "deep_research_provider:L4B"
    assert event["expected_contract"] == "provider_runtime_execution_integrity"
    assert event["observed"]["provider_state"] == "provider_failed"
    assert event["observed"]["termination_reason"] == "provider_exit_nonzero"
    assert event["candidate_ref"] == "C20260802150025462724"


def test_autowake_reuses_existing_event_for_same_failure(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    config = _config(tmp_path)
    monkeypatch.setenv(autowake.AUTOWAKE_CONFIG_ENV, str(config))
    monkeypatch.setattr(autowake, "_current_revision", lambda _repo, _runner: BASE_SHA)
    repair_worktree = tmp_path / "repairs" / "verified-worktree"
    repair_worktree.mkdir(parents=True)
    _patch_verified_worktree(monkeypatch, repair_worktree)
    event_args = []

    def runner(command, **kwargs):
        event_args.append(Path(command[command.index("--event") + 1]))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "outcome": "recovered",
                    "event_id": "unused",
                    "todo_id": "todo-1",
                    "profile_id": "provider_runtime_integrity",
                    "commit_sha": "c" * 40,
                    "reason": None,
                }
            ),
            stderr="",
        )

    kwargs = dict(
        project_dir=project,
        task_id="dr-test",
        handler_args=_handler_args(tmp_path),
        returncode=3,
        status=_status(),
        command_runner=runner,
    )
    first = autowake.maybe_wake_meta_rlr(**kwargs)
    second = autowake.maybe_wake_meta_rlr(**kwargs)

    assert first is not None and second is not None
    assert first.event_path == second.event_path
    assert first.event_id == second.event_id
    assert event_args == [first.event_path, first.event_path]


def test_autowake_retry_guard_prevents_recursive_repair(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setenv(autowake.AUTOWAKE_CONFIG_ENV, str(config))
    monkeypatch.setenv(autowake.AUTOWAKE_RETRY_GUARD_ENV, "1")
    calls = []

    result = autowake.maybe_wake_meta_rlr(
        project_dir=tmp_path / "project",
        task_id="dr-test",
        handler_args=_handler_args(tmp_path),
        returncode=3,
        status=_status(),
        command_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert result is None
    assert calls == []


def test_current_revision_rejects_dirty_checkout(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(list(command))
        if command[1:3] == ["status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout=" M src/research_loop/foo.py\n")
        raise AssertionError("rev-parse must not run for a dirty checkout")

    with pytest.raises(RuntimeError, match="requires a clean RLR code checkout"):
        autowake._current_revision(tmp_path, runner)

    assert calls == [["git", "status", "--porcelain"]]
