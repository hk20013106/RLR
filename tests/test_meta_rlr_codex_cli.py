import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rlr_maintenance.codex_cli import CodexCli, CodexError


class RecordingRunner:
    def __init__(self, payload=None, returncode=0):
        self.payload = payload
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if self.payload is not None and "--output-last-message" in command:
            path = Path(command[command.index("--output-last-message") + 1])
            path.write_text(json.dumps(self.payload), encoding="utf-8")
        return SimpleNamespace(returncode=self.returncode, stdout="provider text", stderr="provider err")


def test_codex_exec_is_ephemeral_bounded_and_workspace_write(tmp_path):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    runner = RecordingRunner(
        {"status": "changed", "summary": "bounded repair", "tests_requested": ["tests/test_x.py"], "blocker": None}
    )
    result = CodexCli(executable="codex", runner=runner).run_repair(
        worktree=worktree, prompt="repair exactly one defect"
    )
    command, kwargs = runner.calls[0]
    assert command[0:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert Path(command[command.index("-C") + 1]) == worktree
    assert "--output-schema" in command
    assert "--output-last-message" in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert command[-1] == "-"
    assert kwargs["cwd"] == worktree
    assert kwargs["input"] == "repair exactly one defect"
    assert kwargs["shell"] is False
    assert result.status == "changed"
    assert result.summary == "bounded repair"
    assert not hasattr(result, "stdout")
    assert not hasattr(result, "stderr")


def test_codex_nonzero_exit_fails_closed_without_model_text(tmp_path):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    runner = RecordingRunner(returncode=9)
    with pytest.raises(CodexError, match="exit code 9"):
        CodexCli(runner=runner).run_repair(worktree=worktree, prompt="repair")


def test_codex_missing_final_json_fails_closed(tmp_path):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    runner = RecordingRunner(payload=None)
    with pytest.raises(CodexError, match="final result"):
        CodexCli(runner=runner).run_repair(worktree=worktree, prompt="repair")
