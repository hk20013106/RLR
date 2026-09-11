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


def test_unhandled_first_mile_exception_wakes_existing_meta_path_and_replays(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    project.mkdir()
    handoff = _handoff(tmp_path)
    wake_calls = []
    replay_calls = []
    monkeypatch.setenv(AUTOWAKE_CONFIG_ENV, "enabled-for-test")

    def broken(_argv=None):
        raise RuntimeError("fixture detail must not become maintenance identity")

    def wake(**kwargs):
        wake_calls.append(kwargs)
        return handoff

    monkeypatch.setattr(adapter, "maybe_wake_first_mile_failure", wake)
    monkeypatch.setattr(
        adapter,
        "_resume_verified_cli",
        lambda **kwargs: (replay_calls.append(kwargs) or 0),
    )
    wrapped = adapter.wrap_first_mile_main(
        broken,
        entrypoint_name="research_loop_v04.py",
    )
    argv = ["preflight", str(project), "--backend", "codex"]

    assert wrapped(argv) == 0
    assert len(wake_calls) == 1
    assert wake_calls[0]["operation"] == "preflight"
    assert wake_calls[0]["failure"] == {
        "code": "FIRST_MILE_UNHANDLED_EXCEPTION:RuntimeError",
        "reason": "unexpected RLR exception during First-Mile operation",
    }
    assert replay_calls[0]["argv"] == argv


def test_unhandled_first_mile_exception_re_raises_when_maintenance_is_disabled(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(AUTOWAKE_CONFIG_ENV, raising=False)

    def broken(_argv=None):
        raise ValueError("original failure")

    wrapped = adapter.wrap_first_mile_main(
        broken,
        entrypoint_name="research_loop_v04.py",
    )

    with pytest.raises(ValueError, match="original failure"):
        wrapped(["preflight", str(tmp_path), "--backend", "codex"])
