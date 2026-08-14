from types import SimpleNamespace

from rlr_maintenance.loopx_cli import LoopXCli


def _capture(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr("rlr_maintenance.loopx_cli.subprocess.run", fake_run)
    return calls


def test_turn_settlement_reuses_one_loopx_identity(monkeypatch):
    calls = _capture(monkeypatch)
    client = LoopXCli()
    turn_id = "meta-rlr:abc123"
    client.todo_complete(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        evidence="profile=l0_state_integrity passed=true",
        note="bounded repair independently verified", no_follow_up=True,
        turn_instance_id=turn_id,
    )
    assert "--turn-instance-id" in calls[-1]
    assert turn_id in calls[-1]
    client.refresh_state(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        turn_instance_id=turn_id, delivery_workspace_path="D:/verified-repair-worktree",
        capabilities=("shell",),
    )
    assert calls[-1][3] == "refresh-state"
    assert "--turn-instance-id" in calls[-1]
    assert turn_id in calls[-1]
    client.quota_spend_slot(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        capabilities=("shell",), turn_instance_id=turn_id,
    )
    assert "--turn-instance-id" in calls[-1]
    assert turn_id in calls[-1]
