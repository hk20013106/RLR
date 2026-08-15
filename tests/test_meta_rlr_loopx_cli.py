import json
import sys
from pathlib import Path

import pytest

from rlr_maintenance.loopx_cli import LoopXCli, LoopXError


def _write_fake_loopx(tmp_path: Path, body: str) -> tuple[str, str]:
    script = tmp_path / "fake_loopx.py"
    argv_file = tmp_path / "argv.json"
    script.write_text(
        "import json, pathlib, sys\n"
        f"argv_file = pathlib.Path({str(argv_file)!r})\n"
        "argv_file.write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        + body,
        encoding="utf-8",
    )
    return str(script), str(argv_file)


def test_unconfigured_quota_should_run_preserves_documented_json_cli_contract(tmp_path):
    script, argv_file = _write_fake_loopx(
        tmp_path,
        "print(json.dumps({'ok': True, 'route': 'ready_for_host'}))\n",
    )
    client = LoopXCli(executable=(sys.executable, script))

    packet = client.quota_should_run(
        goal_id="meta-rlr",
        agent_id="codex-maintainer",
        capabilities=("shell",),
    )

    recorded = json.loads(Path(argv_file).read_text(encoding="utf-8"))
    assert packet["ok"] is True
    assert recorded[:4] == ["--format", "json", "quota", "should-run"]
    assert recorded[4:] == [
        "--goal-id", "meta-rlr",
        "--agent-id", "codex-maintainer",
        "--available-capability", "shell",
    ]


def test_quota_should_run_adds_configured_runtime_profile_and_scan_root(tmp_path):
    script, argv_file = _write_fake_loopx(
        tmp_path,
        "print(json.dumps({'ok': True, 'route': 'ready_for_host'}))\n",
    )
    scan_root = tmp_path / "public-acceptance-root"
    client = LoopXCli(
        executable=(sys.executable, script),
        quota_runtime_profile="outer_controller",
        quota_scan_root=scan_root,
    )

    client.quota_should_run(
        goal_id="meta-rlr",
        agent_id="meta-rlr-native-windows",
        capabilities=("shell",),
    )

    recorded = json.loads(Path(argv_file).read_text(encoding="utf-8"))
    assert recorded == [
        "--format", "json", "quota", "should-run",
        "--goal-id", "meta-rlr",
        "--agent-id", "meta-rlr-native-windows",
        "--runtime-profile", "outer_controller",
        "--scan-root", str(scan_root),
        "--available-capability", "shell",
    ]


def test_scoped_quota_should_run_keeps_turn_id_with_configured_context(tmp_path):
    script, argv_file = _write_fake_loopx(
        tmp_path,
        "print(json.dumps({'ok': True, 'route': 'ready_for_host'}))\n",
    )
    scan_root = tmp_path / "public-acceptance-root"
    turn_id = "meta-rlr:event-123:todo-456"
    client = LoopXCli(
        executable=(sys.executable, script),
        quota_runtime_profile="outer_controller",
        quota_scan_root=scan_root,
    )

    client.quota_should_run(
        goal_id="meta-rlr",
        agent_id="meta-rlr-native-windows",
        capabilities=("shell",),
        turn_instance_id=turn_id,
    )

    recorded = json.loads(Path(argv_file).read_text(encoding="utf-8"))
    assert recorded == [
        "--format", "json", "quota", "should-run",
        "--goal-id", "meta-rlr",
        "--agent-id", "meta-rlr-native-windows",
        "--runtime-profile", "outer_controller",
        "--scan-root", str(scan_root),
        "--turn-instance-id", turn_id,
        "--available-capability", "shell",
    ]


def test_refresh_state_uses_explicit_durable_settlement_writeback_contract(tmp_path):
    script, argv_file = _write_fake_loopx(
        tmp_path,
        "print(json.dumps({'ok': True, 'settlement_result': {'ok': True}}))\n",
    )
    worktree = tmp_path / "verified-repair-worktree"
    client = LoopXCli(
        executable=(sys.executable, script),
        quota_runtime_profile="outer_controller",
        quota_scan_root=tmp_path / "quota-scan-root",
    )

    packet = client.refresh_state(
        goal_id="meta-rlr",
        agent_id="meta-rlr-native-windows",
        todo_id="todo-123",
        turn_instance_id="meta-rlr:event-123:todo-123",
        delivery_workspace_path=worktree,
        capabilities=("shell", "git"),
    )

    recorded = json.loads(Path(argv_file).read_text(encoding="utf-8"))
    assert packet["ok"] is True
    assert recorded == [
        "--format", "json", "refresh-state",
        "--goal-id", "meta-rlr",
        "--agent-id", "meta-rlr-native-windows",
        "--todo-id", "todo-123",
        "--turn-instance-id", "meta-rlr:event-123:todo-123",
        "--classification", "validated_progress",
        "--delivery-batch-scale", "single_surface",
        "--delivery-outcome", "outcome_progress",
        "--delivery-workspace-path", str(worktree),
        "--available-capability", "shell",
        "--available-capability", "git",
    ]
    assert "--runtime-profile" not in recorded
    assert "--scan-root" not in recorded


def test_quota_spend_slot_uses_configured_scan_root_without_runtime_profile(tmp_path):
    script, argv_file = _write_fake_loopx(
        tmp_path,
        "print(json.dumps({'ok': True, 'settlement_result': {'ok': True}}))\n",
    )
    scan_root = tmp_path / "public-acceptance-root"
    client = LoopXCli(
        executable=(sys.executable, script),
        quota_runtime_profile="outer_controller",
        quota_scan_root=scan_root,
    )

    client.quota_spend_slot(
        goal_id="meta-rlr",
        todo_id="todo-123",
        agent_id="meta-rlr-native-windows",
        turn_instance_id="meta-rlr:event-123:todo-123",
        capabilities=("shell",),
    )

    recorded = json.loads(Path(argv_file).read_text(encoding="utf-8"))
    assert recorded == [
        "--format", "json", "quota", "spend-slot",
        "--goal-id", "meta-rlr",
        "--todo-id", "todo-123",
        "--slots", "1",
        "--source", "heartbeat",
        "--execute",
        "--agent-id", "meta-rlr-native-windows",
        "--scan-root", str(scan_root),
        "--turn-instance-id", "meta-rlr:event-123:todo-123",
        "--available-capability", "shell",
    ]
    assert "--runtime-profile" not in recorded


def test_agent_onboard_uses_other_agent_without_hidden_permissions(tmp_path):
    script, argv_file = _write_fake_loopx(
        tmp_path,
        "print(json.dumps({'ok': True}))\n",
    )
    client = LoopXCli(executable=(sys.executable, script))

    client.agent_onboard(
        project=tmp_path,
        goal_id="meta-rlr",
        agent_id="codex-maintainer",
        task_text="repair one bounded RLR defect",
        capabilities=("shell",),
    )

    recorded = json.loads(Path(argv_file).read_text(encoding="utf-8"))
    assert recorded[:4] == ["--format", "json", "agent-onboard", "--agent-type"]
    assert recorded[4] == "other-agent"
    assert "--available-capability" in recorded
    assert "shell" in recorded


def test_registry_is_explicit_cli_argument_not_loopx_python_import(tmp_path):
    script, argv_file = _write_fake_loopx(
        tmp_path,
        "print(json.dumps({'ok': True}))\n",
    )
    client = LoopXCli(
        executable=(sys.executable, script),
        registry="registry.global.json",
    )

    client.quota_should_run(goal_id="g", agent_id="a")
    recorded = json.loads(Path(argv_file).read_text(encoding="utf-8"))

    assert recorded[:4] == [
        "--format", "json", "--registry", "registry.global.json"
    ]


@pytest.mark.parametrize(
    "body,match",
    [
        ("print('not-json')\n", "JSON"),
        ("print('{\\\"a\\\": 1}')\nprint('{\\\"b\\\": 2}')\n", "JSON"),
        ("print(json.dumps(['not', 'an', 'object']))\n", "object"),
    ],
)
def test_invalid_or_ambiguous_json_fails_closed(tmp_path, body, match):
    script, _argv_file = _write_fake_loopx(tmp_path, body)
    client = LoopXCli(executable=(sys.executable, script))

    with pytest.raises(LoopXError, match=match):
        client.quota_should_run(goal_id="g", agent_id="a")


def test_nonzero_loopx_exit_never_synthesizes_success(tmp_path):
    script, _argv_file = _write_fake_loopx(
        tmp_path,
        "print('failed', file=sys.stderr)\nsys.exit(7)\n",
    )
    client = LoopXCli(executable=(sys.executable, script))

    with pytest.raises(LoopXError, match="exit code 7"):
        client.quota_should_run(goal_id="g", agent_id="a")


def test_loopx_json_boundary_forces_utf8_for_windows_child_process(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return type("Completed", (), {"returncode": 0, "stdout": '{"ok": true}', "stderr": ""})()

    monkeypatch.setattr("rlr_maintenance.loopx_cli.subprocess.run", fake_run)

    LoopXCli().quota_should_run(goal_id="g", agent_id="a")

    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["env"]["PYTHONUTF8"] == "1"
