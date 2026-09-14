from pathlib import Path

import pytest

from rlr_maintenance import autowake_adapter as adapter
from rlr_maintenance.autowake import AUTOWAKE_CONFIG_ENV, RepairHandoff


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


def test_unhandled_pre_l0_exception_uses_the_same_maintenance_bridge(monkeypatch, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    wakes = []
    replays = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **kwargs: (wakes.append(kwargs) or _handoff(tmp_path)),
    )
    monkeypatch.setattr(
        adapter,
        "_resume_verified_cli",
        lambda **kwargs: (replays.append(kwargs) or 0),
    )
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: (_ for _ in ()).throw(RuntimeError("original failure")),
        entrypoint_name="research_loop_v04.py",
    )

    assert wrapped(["preflight", str(project), "--backend", "codex"]) == 0
    assert len(wakes) == 1
    assert wakes[0]["failure"]["code"] == "FIRST_MILE_UNHANDLED_EXCEPTION:RuntimeError"
    assert len(replays) == 1


def test_unhandled_pre_l0_exception_preserves_original_error_if_maintenance_fails(monkeypatch, tmp_path):
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")
    monkeypatch.setattr(
        adapter,
        "maybe_wake_first_mile_failure",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("maintenance failed")),
    )
    wrapped = adapter.wrap_first_mile_main(
        lambda _argv=None: (_ for _ in ()).throw(ValueError("original failure")),
        entrypoint_name="research_loop_v04.py",
    )

    with pytest.raises(ValueError, match="original failure"):
        wrapped(["preflight", str(tmp_path), "--backend", "codex"])
