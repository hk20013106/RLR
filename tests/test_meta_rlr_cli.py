from __future__ import annotations

import json
from pathlib import Path

import pytest

import meta_rlr
from rlr_maintenance.host import MetaRLRTurnResult


def test_run_once_wires_outer_controller_and_explicit_quota_scan_root(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"event_id": "rme-test"}), encoding="utf-8")
    scan_root = tmp_path / "public-safe-scan-root"
    captured = {}

    class FakeLoopX:
        def __init__(self, **kwargs):
            captured["loopx"] = kwargs

    class FakeCodex:
        def __init__(self, **kwargs):
            captured["codex"] = kwargs

    class FakeWorkspace:
        def __init__(self, **kwargs):
            captured["workspace"] = kwargs

    class FakeHost:
        def __init__(self, **kwargs):
            captured["host"] = kwargs

        def run_once(self, **kwargs):
            captured["run_once"] = kwargs
            return MetaRLRTurnResult(
                outcome="noop",
                event_id="rme-test",
                todo_id=None,
                profile_id="l0_state_integrity",
                commit_sha=None,
                reason="quota_no_run",
            )

    monkeypatch.setattr(meta_rlr, "LoopXCli", FakeLoopX)
    monkeypatch.setattr(meta_rlr, "CodexCli", FakeCodex)
    monkeypatch.setattr(meta_rlr, "GitWorkspace", FakeWorkspace)
    monkeypatch.setattr(meta_rlr, "MetaRLRHost", FakeHost)

    result = meta_rlr.main(
        [
            "run-once",
            "--event",
            str(event_path),
            "--repo",
            str(tmp_path / "repo"),
            "--loopx-project",
            str(tmp_path / "loopx-project"),
            "--goal-id",
            "goal",
            "--agent-id",
            "agent",
            "--workspace-parent",
            str(tmp_path / "workspaces"),
            "--registry",
            str(tmp_path / "registry.json"),
            "--loopx-executable",
            "loopx.exe",
            "--codex-executable",
            "codex.exe",
            "--quota-scan-root",
            str(scan_root),
        ]
    )

    assert result == 0
    assert captured["loopx"] == {
        "executable": "loopx.exe",
        "registry": str(tmp_path / "registry.json"),
        "quota_runtime_profile": "outer_controller",
        "quota_scan_root": scan_root,
    }
    assert json.loads(capsys.readouterr().out)["outcome"] == "noop"


def test_run_once_requires_explicit_quota_scan_root():
    with pytest.raises(SystemExit) as exc_info:
        meta_rlr.build_parser().parse_args(
            [
                "run-once",
                "--event",
                "event.json",
                "--repo",
                "repo",
                "--loopx-project",
                "loopx-project",
                "--goal-id",
                "goal",
                "--agent-id",
                "agent",
                "--workspace-parent",
                "workspaces",
            ]
        )

    assert exc_info.value.code == 2
