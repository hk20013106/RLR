"""External LoopX CLI boundary for Meta-RLR.

LoopX remains an independent control plane. This module speaks only its
provider-neutral JSON CLI contract and intentionally does not import LoopX
Python implementation modules.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping, Sequence


class LoopXError(RuntimeError):
    """Raised when the external LoopX boundary cannot provide a valid packet."""


def _command_prefix(executable: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(executable, str):
        values = (executable,)
    else:
        values = tuple(str(item) for item in executable)
    if not values or any(not item for item in values):
        raise ValueError("LoopX executable must contain at least one non-empty argv token")
    return values


class LoopXCli:
    """Small fail-closed adapter around the documented LoopX JSON CLI."""

    def __init__(
        self,
        executable: str | Sequence[str] = "loopx",
        registry: str | None = None,
    ) -> None:
        self._executable = _command_prefix(executable)
        self._registry = str(registry) if registry else None

    def _base_command(self) -> list[str]:
        command = [*self._executable, "--format", "json"]
        if self._registry:
            command.extend(["--registry", self._registry])
        return command

    def run_json(
        self,
        args: Sequence[str],
        *,
        cwd: str | Path | None = None,
    ) -> dict:
        command = self._base_command()
        command.extend(str(item) for item in args)
        completed = subprocess.run(
            command,
            cwd=Path(cwd) if cwd is not None else None,
            text=True,
            encoding="utf-8",
            capture_output=True,
            shell=False,
        )
        if completed.returncode != 0:
            diagnostic = (completed.stderr or "").strip().replace("\n", " ")
            if len(diagnostic) > 500:
                diagnostic = diagnostic[:497] + "..."
            suffix = f": {diagnostic}" if diagnostic else ""
            raise LoopXError(
                f"LoopX command failed with exit code {completed.returncode}{suffix}"
            )

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

    def agent_onboard(
        self,
        *,
        project: str | Path,
        goal_id: str,
        agent_id: str,
        task_text: str,
        capabilities: Sequence[str] = ("shell",),
        cwd: str | Path | None = None,
    ) -> dict:
        args = [
            "agent-onboard",
            "--agent-type",
            "other-agent",
            "--project",
            str(project),
            "--goal-id",
            str(goal_id),
            "--agent-id",
            str(agent_id),
            "--task-text",
            str(task_text),
        ]
        args.extend(self._capability_args(capabilities))
        return self.run_json(args, cwd=cwd)

    def quota_should_run(
        self,
        *,
        goal_id: str,
        agent_id: str,
        capabilities: Sequence[str] = ("shell",),
        cwd: str | Path | None = None,
    ) -> dict:
        args = [
            "quota",
            "should-run",
            "--goal-id",
            str(goal_id),
            "--agent-id",
            str(agent_id),
        ]
        args.extend(self._capability_args(capabilities))
        return self.run_json(args, cwd=cwd)
