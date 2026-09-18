# -*- coding: utf-8 -*-
"""Regression tests for run_loop controller fail-closed guards."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import run_loop
from research_loop import pre_e2e_closure


class _Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _runner_args(project, config, *, provider=None):
    return SimpleNamespace(
        project_dir=str(project), cand_id="C1", config=str(config),
        knowledge_store=None, max_rounds=1, dry_run=False,
        no_review=True, provider=provider, resume=False,
        stop_after_node="L0",
    )


def _prepare_runner_boundary(project, monkeypatch):
    candidates = project / "01_Candidates"
    candidates.mkdir(parents=True)
    (candidates / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: NEW\n---\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        run_loop.l0_preflight, "validate_project_ready", lambda *_a, **_k: {"status": "PASS"}
    )
    monkeypatch.setattr(run_loop, "_formal_runtime_preflight", lambda: True)
    monkeypatch.setattr(run_loop, "_ctl", lambda *_a: _Result(0, "", ""))


@pytest.mark.parametrize("backend", ["headless", "host", "auto", "command"])
def test_backend_choice_does_not_change_canonical_run_round_path(
    tmp_path, monkeypatch, backend
):
    project = tmp_path / "project"
    _prepare_runner_boundary(project, monkeypatch)
    config = tmp_path / "runner.yaml"
    config.write_text(
        "provider:\n  default:\n    type: command\n    command: unused\n"
        "review:\n  enabled: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_loop, "restore_previous_round", lambda *_a: {})
    monkeypatch.setattr(
        pre_e2e_closure, "audit_static_closure", lambda *_a: {"e2e_start_allowed": True}
    )
    calls = []
    monkeypatch.setattr(
        run_loop,
        "run_round",
        lambda *args, **kwargs: calls.append(args[1]) or "stopped_after_node",
    )

    assert run_loop.cmd_run(_runner_args(project, config, provider=backend)) == 0
    assert calls == ["C1"]


def test_review_uses_the_same_canonical_per_node_provider_resolver(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "FINAL_REPORT.md").write_text("report", encoding="utf-8")
    calls = []

    class Provider:
        def run_agent(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"review_verdict": "accept"}

    monkeypatch.setattr(run_loop, "next_step", lambda *_a: {"profile_id": "profile"})
    monkeypatch.setattr(run_loop, "get_profile", lambda *_a: object())
    monkeypatch.setattr(
        run_loop, "artifact_for_node", lambda *_a: SimpleNamespace(storage_key="L8")
    )
    monkeypatch.setattr(run_loop, "load_delta", lambda *_a: None)
    resolved = []
    monkeypatch.setattr(
        run_loop,
        "provider_for",
        lambda node, cfg, args: resolved.append(node) or Provider(),
    )
    cfg = SimpleNamespace(
        default={"type": "command", "command": "unused"},
        nodes={"REVIEW": {"type": "command", "command": "review"}},
        review={"enabled": True, "provider": {"type": "main_agent"}},
    )

    result = run_loop.run_review_gate(
        project,
        "C1",
        cfg,
        SimpleNamespace(provider=None),
        tmp_path / "run",
    )

    assert result == {"review_verdict": "accept"}
    assert resolved == ["REVIEW"]
    assert len(calls) == 1


@pytest.mark.parametrize("override", [None, "host", "command"])
def test_retired_main_agent_config_fails_before_restore_even_with_override(
    tmp_path, monkeypatch, capsys, override
):
    project = tmp_path / "project"
    _prepare_runner_boundary(project, monkeypatch)
    config = tmp_path / "legacy.yaml"
    config.write_text(
        "mode: main_agent\nprovider:\n  default:\n    type: headless\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_loop,
        "restore_previous_round",
        lambda *_a: pytest.fail("retired mode must fail before state restore"),
    )

    assert run_loop.cmd_run(_runner_args(project, config, provider=override)) == 2
    output = capsys.readouterr().out
    assert "retired mode: main_agent" in output
    assert "Remove `mode: main_agent`" in output


def test_retired_main_agent_cli_override_fails_with_new_config(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "project"
    _prepare_runner_boundary(project, monkeypatch)
    config = tmp_path / "runner.yaml"
    config.write_text(
        "provider:\n  default:\n    type: command\n    command: unused\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_loop,
        "restore_previous_round",
        lambda *_a: pytest.fail("retired provider must fail before state restore"),
    )

    assert run_loop.cmd_run(
        _runner_args(project, config, provider="main_agent")
    ) == 2
    assert "retired mode: main_agent" in capsys.readouterr().out


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


def test_stop_after_node_executes_the_requested_cognitive_node_before_halting():
    old_next_step = run_loop.next_step
    old_exec_cognitive = run_loop.exec_cognitive
    calls = []
    try:
        run_loop.next_step = lambda *_args: {
            "node": "L0", "persona": "Linnaeus", "advance_command": "decision"
        }
        run_loop.exec_cognitive = lambda *args, **kwargs: calls.append(args[2]["node"]) or True
        cfg = SimpleNamespace(stop_policy={"max_l7_failures": 2, "max_node_failures": 2})
        args = SimpleNamespace(stop_after_node="L0")

        outcome = run_loop.run_round(
            "Project", "C1", cfg, args, 1, 1,
            {"l7_failures": 0, "node_failures": {}},
        )

        assert outcome == "stopped_after_node"
        assert calls == ["L0"]
    finally:
        run_loop.next_step = old_next_step
        run_loop.exec_cognitive = old_exec_cognitive


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
        run_loop.ensure_pre_research = lambda *a, **k: True
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
