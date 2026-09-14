import json
from pathlib import Path
from types import SimpleNamespace

from rlr_maintenance import autowake, autowake_adapter as adapter
from rlr_maintenance.autowake import (
    AUTOWAKE_CONFIG_ENV,
    AUTOWAKE_RETRY_GUARD_ENV,
    RepairHandoff,
)
from rlr_maintenance.contracts import validate_maintenance_event


def _handoff(tmp_path: Path) -> RepairHandoff:
    worktree = tmp_path / "repair-worktree"
    worktree.mkdir()
    (worktree / "research_loop_v04.py").write_text("# repaired fixture\n", encoding="utf-8")
    return RepairHandoff(
        outcome="verified",
        event_id="rme-0123456789abcdefabcd",
        event_path=tmp_path / "event.json",
        commit_sha="a" * 40,
        worktree_path=worktree,
    )


def test_pre_l0_failure_wakes_once_and_replays_only_verified_repair(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    handoff = _handoff(tmp_path)
    wakes = []
    replays = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_RUNTIME_TAMPERED",
            "reason": "runtime config bytes differ from receipt",
        },
    )
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: (wakes.append(kwargs) or handoff),
    )
    monkeypatch.setattr(
        adapter,
        "_resume_verified_cli",
        lambda **kwargs: (replays.append(kwargs) or 0),
    )

    argv = ["preflight", str(project), "--backend", "codex"]
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3, entrypoint_name="research_loop_v04.py"
    )

    assert wrapped(argv) == 0
    assert len(wakes) == 1
    assert wakes[0]["operation"] == "preflight"
    assert wakes[0]["failure"]["code"] == "PROJECT_READY_RUNTIME_TAMPERED"
    assert len(replays) == 1
    assert replays[0]["argv"] == argv


def test_pre_l0_failure_is_inert_without_explicit_autowake_config(monkeypatch, tmp_path):
    wakes = []
    monkeypatch.delenv(AUTOWAKE_CONFIG_ENV, raising=False)
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: wakes.append(kwargs),
    )
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3, entrypoint_name="research_loop_v04.py"
    )

    assert wrapped(["preflight", str(tmp_path), "--backend", "codex"]) == 3
    assert wakes == []


def test_unverified_pre_l0_repair_preserves_original_exit(monkeypatch, tmp_path):
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_BINDING_MISMATCH",
            "reason": "fixture",
        },
    )
    monkeypatch.setattr(adapter, "maybe_wake_first_mile_failure", lambda **_kwargs: None)
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3, entrypoint_name="research_loop_v04.py"
    )

    assert wrapped(["preflight", str(tmp_path), "--backend", "codex"]) == 3


def test_pre_l0_retry_guard_preserves_original_failure_without_second_wake(monkeypatch, tmp_path):
    wakes = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setenv(AUTOWAKE_RETRY_GUARD_ENV, "1")
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: wakes.append(kwargs),
    )
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3, entrypoint_name="research_loop_v04.py"
    )

    assert wrapped(["preflight", str(tmp_path), "--backend", "codex"]) == 3
    assert wakes == []


def test_maintenance_exception_preserves_original_pre_l0_exit(monkeypatch, tmp_path):
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "_first_mile_failure",
        lambda **_kwargs: {
            "code": "PROJECT_READY_BINDING_MISMATCH",
            "reason": "fixture",
        },
    )
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("maintenance failed")),
    )
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: 3, entrypoint_name="research_loop_v04.py"
    )

    assert wrapped(["preflight", str(tmp_path), "--backend", "codex"]) == 3


def test_repairable_pre_l0_failure_reuses_canonical_event_and_l0_profile(monkeypatch, tmp_path):
    config = tmp_path / "autowake.json"
    config.write_text(
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
    project = tmp_path / "project"
    (project / "00_Preflight").mkdir(parents=True)
    (project / "00_Preflight" / "preflight_receipt.json").write_text("{}\n", encoding="utf-8")
    verified = tmp_path / "repairs" / "verified"
    verified.mkdir(parents=True)
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, str(config))
    monkeypatch.setattr(autowake, "_current_revision", lambda *_args: "a" * 40)
    monkeypatch.setattr(autowake, "_resolve_verified_worktree", lambda **_kwargs: verified)
    calls = []

    def runner(command, **kwargs):
        calls.append((list(command), kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "outcome": "verified",
                    "profile_id": "l0_state_integrity",
                    "commit_sha": "b" * 40,
                }
            ),
            stderr="",
        )

    result = autowake.maybe_wake_first_mile_failure(
        project_dir=project,
        operation="preflight",
        failure={
            "code": "PROJECT_READY_RUNTIME_TAMPERED",
            "reason": "runtime config bytes differ from receipt",
        },
        command_runner=runner,
    )

    assert result is not None
    assert result.worktree_path == verified
    assert len(calls) == 1
    event = validate_maintenance_event(json.loads(result.event_path.read_text(encoding="utf-8")))
    assert event["component"] == "first_mile:preflight"
    assert event["expected_contract"] == "first_mile_project_ready_integrity"
    assert event["observed"]["error_code"] == "PROJECT_READY_RUNTIME_TAMPERED"
