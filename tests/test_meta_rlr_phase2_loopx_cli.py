import json
import sys
from pathlib import Path

from rlr_maintenance.loopx_cli import LoopXCli


def _fake_loopx(tmp_path: Path, payload: dict) -> tuple[tuple[str, ...], Path]:
    script = tmp_path / "fake_loopx_phase2.py"
    argv_file = tmp_path / "argv.json"
    script.write_text(
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(argv_file)!r}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    return (sys.executable, str(script)), argv_file


def _argv(path: Path) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_add_maintenance_todo_uses_loopx_native_dedup_lane(tmp_path):
    executable, argv_file = _fake_loopx(
        tmp_path, {"ok": True, "todo_id": "todo_event", "already_exists": False}
    )
    client = LoopXCli(executable=executable, registry="registry.json")
    payload = client.todo_add_agent(
        goal_id="meta-rlr",
        text="Repair RLR failure abc123: l0_restore violates l0_restore_fail_closed",
        task_class="advancement_task",
        action_kind="repair",
    )
    assert payload["todo_id"] == "todo_event"
    assert _argv(argv_file) == [
        "--format", "json", "--registry", "registry.json",
        "todo", "add", "--goal-id", "meta-rlr", "--role", "agent",
        "--text", "Repair RLR failure abc123: l0_restore violates l0_restore_fail_closed",
        "--task-class", "advancement_task", "--action-kind", "repair",
    ]


def test_claim_binds_actor_and_owner_to_same_registered_agent(tmp_path):
    executable, argv_file = _fake_loopx(tmp_path, {"ok": True, "todo_id": "todo_event"})
    client = LoopXCli(executable=executable)
    client.todo_claim(goal_id="g", todo_id="todo_event", agent_id="codex-maintainer")
    assert _argv(argv_file) == [
        "--format", "json", "todo", "claim", "--goal-id", "g",
        "--todo-id", "todo_event", "--claimed-by", "codex-maintainer",
        "--agent-id", "codex-maintainer",
    ]


def test_blocked_writeback_uses_todo_update_not_completion(tmp_path):
    executable, argv_file = _fake_loopx(tmp_path, {"ok": True, "todo_id": "todo_event"})
    client = LoopXCli(executable=executable)
    client.todo_update(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        status="blocked", reason="verification failed",
        evidence="profile=l0_state_integrity passed=false",
    )
    assert _argv(argv_file) == [
        "--format", "json", "todo", "update", "--goal-id", "g",
        "--todo-id", "todo_event", "--agent-id", "codex-maintainer",
        "--status", "blocked", "--evidence", "profile=l0_state_integrity passed=false",
        "--reason", "verification failed",
    ]


def test_complete_then_spend_use_native_turn_settlement(tmp_path):
    executable, argv_file = _fake_loopx(tmp_path, {"ok": True})
    client = LoopXCli(executable=executable)
    turn_id = "meta-rlr:abc123"
    client.todo_complete(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        evidence="profile=l0_state_integrity passed=true",
        note="bounded repair independently verified", no_follow_up=True,
        turn_instance_id=turn_id,
    )
    assert _argv(argv_file) == [
        "--format", "json", "todo", "complete", "--goal-id", "g",
        "--todo-id", "todo_event", "--agent-id", "codex-maintainer",
        "--claimed-by", "codex-maintainer",
        "--evidence", "profile=l0_state_integrity passed=true",
        "--turn-instance-id", turn_id,
        "--note", "bounded repair independently verified", "--no-follow-up",
    ]
    assert not hasattr(client, "refresh_state")
    client.quota_spend_slot(
        goal_id="g", todo_id="todo_event", agent_id="codex-maintainer",
        capabilities=("shell",), turn_instance_id=turn_id,
    )
    assert _argv(argv_file) == [
        "--format", "json", "quota", "spend-slot", "--goal-id", "g",
        "--todo-id", "todo_event", "--slots", "1", "--source", "heartbeat",
        "--execute", "--agent-id", "codex-maintainer",
        "--turn-instance-id", turn_id,
        "--available-capability", "shell",
    ]
