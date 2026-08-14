from pathlib import Path
from types import SimpleNamespace

from rlr_maintenance.loopx_cli import LoopXCli


def _capture(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr("rlr_maintenance.loopx_cli.subprocess.run", fake_run)
    return calls


def test_turn_settlement_reuses_one_loopx_identity_and_durable_refresh(monkeypatch, tmp_path):
    calls = _capture(monkeypatch)
    client = LoopXCli()
    turn_id = "meta-rlr:abc123"
    worktree = tmp_path / "repair"
    project = tmp_path / "control"

    client.todo_complete(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        evidence="profile=l0_state_integrity passed=true",
        note="bounded repair independently verified", no_follow_up=True,
        turn_instance_id=turn_id,
    )
    assert "--turn-instance-id" in calls[-1]
    assert turn_id in calls[-1]

    client.refresh_state(
        goal_id="g",
        agent_id="codex-maintainer",
        todo_id="todo_event",
        turn_instance_id=turn_id,
        delivery_outcome="outcome_progress",
        delivery_workspace_path=worktree,
        project=project,
    )
    refresh = calls[-1]
    assert "refresh-state" in refresh
    assert refresh[refresh.index("--turn-instance-id") + 1] == turn_id
    assert refresh[refresh.index("--todo-id") + 1] == "todo_event"
    assert refresh[refresh.index("--delivery-outcome") + 1] == "outcome_progress"
    assert refresh[refresh.index("--delivery-workspace-path") + 1] == str(worktree)
    assert refresh[refresh.index("--project") + 1] == str(project)

    client.quota_spend_slot(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        capabilities=("shell",), turn_instance_id=turn_id,
    )
    assert "--turn-instance-id" in calls[-1]
    assert turn_id in calls[-1]
    assert [call[call.index("--turn-instance-id") + 1] for call in calls] == [turn_id, turn_id, turn_id]
