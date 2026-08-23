import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import rlr_maintenance.codex_cli as codex_cli
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


class RecordingObservedRunner:
    def __init__(self, *, final_status="succeeded", payload=None):
        self.final_status = final_status
        self.payload = payload or {
            "status": "changed",
            "summary": "bounded repair",
            "tests_requested": [],
            "blocker": None,
        }
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        runtime_dir = Path(kwargs["runtime_dir"])
        return SimpleNamespace(
            args=list(kwargs["command"]),
            returncode=0 if self.final_status == "succeeded" else 124,
            final_output=json.dumps(self.payload) if self.final_status == "succeeded" else "",
            stderr="",
            final_status=self.final_status,
            runtime_dir=runtime_dir,
            runtime_receipt_path=runtime_dir / "runtime_receipt.json",
            runtime_receipt_sha256="receipt-sha256",
        )


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


def test_codex_repair_isolates_test_cache_and_scratch_environment(tmp_path):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    runner = RecordingRunner(
        {"status": "changed", "summary": "bounded repair", "tests_requested": [], "blocker": None}
    )

    CodexCli(runner=runner).run_repair(worktree=worktree, prompt="repair")

    environment = runner.calls[0][1]["env"]
    assert "-p no:cacheprovider" in environment["PYTEST_ADDOPTS"]
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    scratch = Path(environment["TEMP"]).resolve()
    assert scratch.is_dir()
    assert scratch == Path(environment["TMP"]).resolve()
    assert scratch == Path(environment["TMPDIR"]).resolve()
    assert worktree.resolve() not in scratch.parents


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


def test_codex_repair_uses_bounded_observed_runner(tmp_path):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    runner = RecordingObservedRunner()

    result = CodexCli(
        executable="codex",
        observed_runner=runner,
        job_timeout=7,
        inactivity_timeout=3,
        observer_interval=0.1,
    ).run_repair(worktree=worktree, prompt="diagnose before repair")

    call = runner.calls[0]
    assert call["backend"] == "codex"
    assert call["prompt"] == "diagnose before repair"
    assert call["input_text"] == "diagnose before repair"
    assert call["job_timeout"] == 7
    assert call["inactivity_timeout"] == 3
    assert call["observer_interval"] == 0.1
    assert Path(call["cwd"]).resolve() == worktree.resolve()
    assert Path(call["runtime_dir"]).is_dir()
    assert result.status == "changed"


def test_codex_default_runner_is_bounded(tmp_path, monkeypatch):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    runner = RecordingObservedRunner()
    monkeypatch.setattr(codex_cli, "_default_observed_runner", runner)

    CodexCli(executable="codex", job_timeout=7, inactivity_timeout=3).run_repair(
        worktree=worktree,
        prompt="diagnose before repair",
    )

    assert runner.calls[0]["job_timeout"] == 7
    assert runner.calls[0]["inactivity_timeout"] == 3


def test_repair_default_timeout_is_an_emergency_ceiling_not_the_old_900_second_deadline():
    assert codex_cli.DEFAULT_REPAIR_EMERGENCY_TIMEOUT > 900
    assert codex_cli.DEFAULT_REPAIR_JOB_TIMEOUT == codex_cli.DEFAULT_REPAIR_EMERGENCY_TIMEOUT


def test_codex_default_observer_runs_real_subprocess_and_persists_receipt(tmp_path):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    fixture = tmp_path / "codex_repair_fixture.py"
    fixture.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "final = Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'repair-fixture'}), flush=True)\n"
        "print('repair fixture diagnostic', file=sys.stderr, flush=True)\n"
        "final.write_text(json.dumps({'status': 'changed', 'summary': 'bounded', 'tests_requested': [], 'blocker': None}), encoding='utf-8')\n",
        encoding="utf-8",
    )

    result = CodexCli(
        executable=[sys.executable, str(fixture)],
        job_timeout=3,
        inactivity_timeout=1,
        observer_interval=0.05,
    ).run_repair(worktree=worktree, prompt="real bounded repair")

    assert result.status == "changed"
    runtime_dirs = list(tmp_path.glob(".repair.meta-rlr-runtime-*"))
    assert len(runtime_dirs) == 1
    receipt = json.loads(
        (runtime_dirs[0] / "runtime_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["cwd"] == str(worktree.resolve())
    assert receipt["timeout_config"] == {
        "job_timeout_seconds": 3,
        "inactivity_timeout_seconds": 1,
        "observer_interval_seconds": 0.05,
    }
    assert receipt["command_metadata"]["backend"] == "codex"
    assert (runtime_dirs[0] / "stderr.log").read_text(encoding="utf-8").strip()


def test_codex_repair_surfaces_bounded_terminal_status(tmp_path):
    worktree = tmp_path / "repair"
    worktree.mkdir()
    runner = RecordingObservedRunner(final_status="inactivity_timed_out")

    with pytest.raises(CodexError, match="inactivity_timed_out"):
        CodexCli(executable="codex", observed_runner=runner).run_repair(
            worktree=worktree,
            prompt="diagnose before repair",
        )
