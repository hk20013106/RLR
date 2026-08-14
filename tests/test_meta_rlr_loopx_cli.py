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
