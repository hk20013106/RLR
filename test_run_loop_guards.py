# -*- coding: utf-8 -*-
"""Regression tests for run_loop controller fail-closed guards."""
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import run_loop


class _Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_main_agent_run_emits_handoff_without_python_provider():
    old_ctl = run_loop._ctl
    old_run_round = run_loop.run_round
    try:
        run_loop._ctl = lambda *args: _Result(0, "", "")
        run_loop.run_round = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("main-agent mode must not enter python run_round"))
        with tempfile.TemporaryDirectory() as d:
            project = Path(d)
            candidates = project / "01_Candidates"
            candidates.mkdir()
            (candidates / "C1.md").write_text(
                "---\ncandidate_id: C1\ncurrent_status: NEW\n---\n",
                encoding="utf-8")
            args = SimpleNamespace(
                project_dir=str(project), cand_id="C1", config=None,
                max_rounds=None, dry_run=False, no_review=False,
                provider=None, resume=False, stop_after_node="L1")
            output = StringIO()
            with redirect_stdout(output):
                rc = run_loop.cmd_run(args)
        assert rc == 0
        text = output.getvalue()
        assert "main-agent handoff" in text
        assert "python research_loop_v04.py next-step" in text
    finally:
        run_loop._ctl = old_ctl
        run_loop.run_round = old_run_round


def test_assemble_context_raises_when_controller_fails():
    old_ctl = run_loop._ctl
    try:
        run_loop._ctl = lambda *args: _Result(2, "", "controller rejected")
        try:
            run_loop.assemble_context("Project", "C1", "L1")
        except RuntimeError as e:
            assert "assemble-context L1 failed" in str(e)
        else:
            raise AssertionError("assemble_context must raise on controller failure")
    finally:
        run_loop._ctl = old_ctl


def test_exec_turing_stops_when_workspace_prepare_fails():
    old_ctl = run_loop._ctl
    old_provider_for = run_loop.provider_for
    provider_called = {"value": False}

    class Provider:
        name = "test-provider"

        def run_agent(self, *args, **kwargs):
            provider_called["value"] = True
            return {}

    def fake_ctl(*args):
        if args[0] == "prepare-turing-workspace":
            return _Result(1, "", "workspace rejected")
        if args[0] == "execution-gate":
            return _Result(0, "", "")
        return _Result(0, "", "")

    try:
        run_loop._ctl = fake_ctl
        run_loop.provider_for = lambda node, cfg, args: Provider()
        with tempfile.TemporaryDirectory() as d:
            ok = run_loop.exec_turing(
                d, "C1", {"tools_policy": "workspace-fs"},
                SimpleNamespace(stop_policy={}), SimpleNamespace(provider=None),
                Path(d), 1, {"l7_failures": 0})
        assert not ok
        assert not provider_called["value"], "provider must not run without workspace"
    finally:
        run_loop._ctl = old_ctl
        run_loop.provider_for = old_provider_for


def test_advance_does_not_sync_obsidian():
    old_ctl = run_loop._ctl
    old_subprocess_run = run_loop.subprocess.run
    calls = []
    sync_calls = []

    def fake_subprocess_run(args, **kwargs):
        sync_calls.append(args)
        return _Result(0, "", "")

    try:
        run_loop._ctl = lambda *args: calls.append(args) or _Result(0, "", "")
        run_loop.subprocess.run = fake_subprocess_run
        run_loop.advance("Project", "C1", {
            "advance_command": "decision",
            "advance_status": "IDEA_PROPOSED",
            "advance_reason": "test",
        })
        assert all("sync_to_obsidian.py" not in str(c) for c in calls)
        assert not sync_calls, "advance must not run Obsidian sync"
    finally:
        run_loop._ctl = old_ctl
        run_loop.subprocess.run = old_subprocess_run


def test_run_round_aborts_after_repeated_cognitive_emit_failure():
    """R3: a cognitive node whose emit keeps failing must not loop forever --
    run_round must bound the retries and abort with a distinct outcome."""
    old_next_step = run_loop.next_step
    old_ensure_pre = run_loop.ensure_pre_research
    old_exec_cog = run_loop.exec_cognitive
    call_count = {"value": 0}

    step = {"node": "L1", "persona": "Einstein",
           "advance_command": "decision", "advance_status": "X",
           "advance_reason": "y"}

    def fake_exec_cognitive(*args, **kwargs):
        call_count["value"] += 1
        return False  # emit always rejected

    try:
        run_loop.next_step = lambda project, cand: step
        run_loop.ensure_pre_research = lambda *a, **k: None
        run_loop.exec_cognitive = fake_exec_cognitive
        cfg = SimpleNamespace(stop_policy={"max_l7_failures": 2,
                                           "max_node_failures": 2})
        args = SimpleNamespace(stop_after_node=None)
        exec_state = {"l7_failures": 0, "node_failures": {}}
        with tempfile.TemporaryDirectory() as d:
            outcome = run_loop.run_round(d, "C1", cfg, args, 1, 3, exec_state)
        assert outcome == "node_failed:L1", outcome
        assert call_count["value"] == 2, \
            f"expected exactly max_node_failures=2 attempts, got {call_count['value']}"
        assert exec_state["node_failures"]["L1"] == 2
    finally:
        run_loop.next_step = old_next_step
        run_loop.ensure_pre_research = old_ensure_pre
        run_loop.exec_cognitive = old_exec_cog


def _run_as_script():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
