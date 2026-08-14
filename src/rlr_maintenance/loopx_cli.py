"""External LoopX JSON CLI boundary for Meta-RLR."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping, Sequence


class LoopXError(RuntimeError):
    """Raised when the external LoopX boundary cannot provide a valid packet."""


def _command_prefix(executable: str | Sequence[str]) -> tuple[str, ...]:
    values = (executable,) if isinstance(executable, str) else tuple(str(x) for x in executable)
    if not values or any(not item for item in values):
        raise ValueError("LoopX executable must contain at least one non-empty argv token")
    return values


class LoopXCli:
    def __init__(
        self,
        executable: str | Sequence[str] = "loopx",
        registry: str | None = None,
        quota_runtime_profile: str | None = None,
        quota_scan_root: str | Path | None = None,
    ) -> None:
        self._executable = _command_prefix(executable)
        self._registry = str(registry) if registry else None
        self._quota_runtime_profile = str(quota_runtime_profile) if quota_runtime_profile else None
        self._quota_scan_root = str(quota_scan_root) if quota_scan_root else None

    def _base_command(self) -> list[str]:
        command = [*self._executable, "--format", "json"]
        if self._registry:
            command.extend(["--registry", self._registry])
        return command

    def run_json(self, args: Sequence[str], *, cwd: str | Path | None = None) -> dict:
        command = self._base_command()
        command.extend(str(item) for item in args)
        completed = subprocess.run(command, cwd=Path(cwd) if cwd is not None else None, text=True, encoding="utf-8", capture_output=True, shell=False)
        if completed.returncode != 0:
            raise LoopXError(f"LoopX command failed with exit code {completed.returncode}")
        raw = (completed.stdout or "").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LoopXError(f"LoopX did not return exactly one valid JSON document: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise LoopXError("LoopX JSON response must be an object")
        return dict(payload)

    @staticmethod
    def _capability_args(capabilities: Sequence[str]) -> list[str]:
        args: list[str] = []
        for capability in capabilities:
            value = str(capability)
            if not value:
                raise ValueError("LoopX capability must be non-empty")
            args.extend(["--available-capability", value])
        return args

    def agent_onboard(self, *, project: str | Path, goal_id: str, agent_id: str, task_text: str, capabilities: Sequence[str] = ("shell",), cwd: str | Path | None = None) -> dict:
        args = ["agent-onboard", "--agent-type", "other-agent", "--project", str(project), "--goal-id", str(goal_id), "--agent-id", str(agent_id), "--task-text", str(task_text)]
        args.extend(self._capability_args(capabilities))
        return self.run_json(args, cwd=cwd)

    def quota_should_run(self, *, goal_id: str, agent_id: str, capabilities: Sequence[str] = ("shell",), turn_instance_id: str | None = None, cwd: str | Path | None = None) -> dict:
        args = ["quota", "should-run", "--goal-id", str(goal_id), "--agent-id", str(agent_id)]
        if self._quota_runtime_profile is not None:
            args.extend(["--runtime-profile", self._quota_runtime_profile])
        if self._quota_scan_root is not None:
            args.extend(["--scan-root", self._quota_scan_root])
        if turn_instance_id is not None:
            args.extend(["--turn-instance-id", str(turn_instance_id)])
        args.extend(self._capability_args(capabilities))
        return self.run_json(args, cwd=cwd)

    def todo_add_agent(self, *, goal_id: str, text: str, task_class: str = "advancement_task", action_kind: str = "repair", cwd: str | Path | None = None) -> dict:
        return self.run_json(["todo", "add", "--goal-id", str(goal_id), "--role", "agent", "--text", str(text), "--task-class", str(task_class), "--action-kind", str(action_kind)], cwd=cwd)

    def todo_claim(self, *, goal_id: str, todo_id: str, agent_id: str, cwd: str | Path | None = None) -> dict:
        return self.run_json(["todo", "claim", "--goal-id", str(goal_id), "--todo-id", str(todo_id), "--claimed-by", str(agent_id), "--agent-id", str(agent_id)], cwd=cwd)

    def todo_update(self, *, goal_id: str, todo_id: str, agent_id: str, status: str | None = None, evidence: str | None = None, reason: str | None = None, note: str | None = None, cwd: str | Path | None = None) -> dict:
        args = ["todo", "update", "--goal-id", str(goal_id), "--todo-id", str(todo_id), "--agent-id", str(agent_id)]
        for flag, value in (("--status", status), ("--evidence", evidence), ("--reason", reason), ("--note", note)):
            if value is not None:
                args.extend([flag, str(value)])
        return self.run_json(args, cwd=cwd)

    def todo_complete(self, *, goal_id: str, todo_id: str, agent_id: str, evidence: str, note: str | None = None, no_follow_up: bool = False, turn_instance_id: str | None = None, cwd: str | Path | None = None) -> dict:
        args = ["todo", "complete", "--goal-id", str(goal_id), "--todo-id", str(todo_id), "--agent-id", str(agent_id), "--claimed-by", str(agent_id), "--evidence", str(evidence)]
        if turn_instance_id is not None:
            args.extend(["--turn-instance-id", str(turn_instance_id)])
        if note is not None:
            args.extend(["--note", str(note)])
        if no_follow_up:
            args.append("--no-follow-up")
        return self.run_json(args, cwd=cwd)

    def quota_spend_slot(self, *, goal_id: str, todo_id: str, agent_id: str, capabilities: Sequence[str] = ("shell",), turn_instance_id: str | None = None, cwd: str | Path | None = None) -> dict:
        args = ["quota", "spend-slot", "--goal-id", str(goal_id), "--todo-id", str(todo_id), "--slots", "1", "--source", "heartbeat", "--execute", "--agent-id", str(agent_id)]
        if turn_instance_id is not None:
            args.extend(["--turn-instance-id", str(turn_instance_id)])
        args.extend(self._capability_args(capabilities))
        return self.run_json(args, cwd=cwd)
