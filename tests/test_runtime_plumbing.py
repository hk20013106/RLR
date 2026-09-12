"""Regression tests for the v0.9.7 runtime/plumbing boundaries."""

import os
import subprocess
import sys
import json
from pathlib import Path
from types import SimpleNamespace

import run_loop
from research_loop import cli, context, runtime_preflight


CONTROLLER = Path(__file__).resolve().parents[1] / "research_loop_v04.py"


def _candidate_project(tmp_path):
    project = tmp_path / "project"
    candidates = project / "01_Candidates"
    candidates.mkdir(parents=True)
    (candidates / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: NEW\n---\n",
        encoding="utf-8",
    )
    return project


def test_context_token_budget_has_one_40000_default_owner():
    assert context.DEFAULT_CONTEXT_TOKEN_BUDGET == 40000
    assert run_loop._context_token_budget(SimpleNamespace(data={})) == 40000

    parsed = cli.build_parser().parse_args(
        ["assemble-context", "PROJECT", "C1", "--node", "L1"]
    )
    assert parsed.context_token_budget == 40000


def test_explicit_context_token_budget_still_overrides_the_default():
    assert run_loop._context_token_budget(
        SimpleNamespace(data={"context_token_budget": 50000})
    ) == 50000


def test_formal_runner_fails_closed_before_dependency_gate_on_runtime_drift(
    tmp_path, monkeypatch,
):
    project = _candidate_project(tmp_path)
    calls = []

    def fail_preflight():
        calls.append("runtime_preflight")
        raise runtime_preflight.RuntimePreflightError("wrong interpreter")

    def unexpected_controller_call(*argv):
        calls.append(argv[0])
        raise AssertionError("formal runtime drift must stop before the controller")

    monkeypatch.setattr(runtime_preflight, "require_ready", fail_preflight)
    monkeypatch.setattr(run_loop, "_ctl", unexpected_controller_call)

    args = SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        knowledge_store=None,
        dry_run=False,
    )

    assert run_loop.cmd_run(args) == 3
    assert calls == ["runtime_preflight"]


def test_generated_main_agent_prompt_declares_formal_runtime_and_codex_host():
    prompt = run_loop.MAIN_AGENT_PROMPT_TEMPLATE

    assert "micromamba run -n rlr python" in prompt
    assert "$env:RLR_HOST_BACKEND='codex'" in prompt
    assert "Do not set it to codex on non-Codex hosts" in prompt


def test_runtime_preflight_module_is_not_preimported_during_package_startup():
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ)
    env["PYTHONPATH"] = src
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import research_loop, sys; "
            "print('research_loop.runtime_preflight' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def test_cold_start_formal_l0_run_stops_after_receipt(tmp_path):
    """Run the canonical L0 boundary in a fresh formal-environment process."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env["PYTHONPATH"] = str(CONTROLLER.parent / "src")
    env["RLR_HYPOTHESIS_STORE"] = str(tmp_path / "hypotheses.sqlite")
    env["RLR_HOST_BACKEND"] = "codex"
    project = tmp_path / "project"

    created = subprocess.run(
        [sys.executable, str(CONTROLLER), "new-project", str(project),
         "Formal L0 cold start", "--profile", "v2.1-catalog-1"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert created.returncode == 0, created.stderr
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    env["OBSIDIAN_VAULT"] = str(vault)
    runtime_config = project / "00_Preflight" / "deep_research_runtime.json"
    runtime_config.write_text(json.dumps({
        "schema_version": "1.0", "backend": "codex", "executable": sys.executable,
    }), encoding="utf-8")
    preflight = subprocess.run(
        [sys.executable, str(CONTROLLER), "preflight", str(project), "--backend", "codex"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert preflight.returncode == 0, preflight.stderr
    candidate_result = subprocess.run(
        [sys.executable, str(CONTROLLER), "new-candidate", str(project),
         "--title", "Cold start", "--question", "Which bytes reach L0?",
         "--claim", "The receipt binds the bytes", "--input", "cold-start"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert candidate_result.returncode == 0, candidate_result.stderr
    candidate = candidate_result.stdout.strip().splitlines()[0]

    delta = tmp_path / "provider_delta.json"
    delta.write_text(json.dumps({
        "schema_version": "2.1", "candidate_id": candidate,
    }, separators=(",", ":")), encoding="utf-8")
    writer = tmp_path / "provider_writer.py"
    writer.write_text(
        "import shutil, sys; shutil.copyfile(sys.argv[1], sys.argv[2])",
        encoding="utf-8",
    )
    runtime_config.write_text(json.dumps({
        "schema_version": "1.0",
        "backend": "codex",
        "executable": sys.executable,
    }), encoding="utf-8")
    config = tmp_path / "runner.json"
    config.write_text(json.dumps({
        "mode": "headless",
        "max_rounds": 1,
        "provider": {"default": {
            "type": "command",
            "command": (
                f'"{sys.executable}" "{writer}" "{delta}" '
                '"{output_file}"'
            ),
            "timeout": 30,
        }},
        "review": {"enabled": False},
    }), encoding="utf-8")

    child = r'''
import json, os
from pathlib import Path
import run_loop
from research_loop.providers.main_agent import ProviderConfig

assert os.environ["RLR_HOST_BACKEND"] == "codex"

def pass_formal_runtime_preflight():
    print("[run_loop] FORMAL RUNTIME PREFLIGHT PASS -- test fixture")
    return True

run_loop._formal_runtime_preflight = pass_formal_runtime_preflight

project = os.environ["RLR_SMOKE_PROJECT"]
candidate = os.environ["RLR_SMOKE_CANDIDATE"]
config = os.environ["RLR_SMOKE_CONFIG"]
args = type("Args", (), {
    "project_dir": project, "cand_id": candidate,
    "knowledge_store": os.environ["RLR_HYPOTHESIS_STORE"],
    "config": config, "max_rounds": 1, "dry_run": False,
    "no_review": True, "provider": None, "resume": False,
    "stop_after_node": "L0",
})()
rc = run_loop.cmd_run(args)
run_dir = Path(project) / "08_Run_Receipts" / candidate / "round_01"
receipts = list(run_dir.glob("L0_Linnaeus_receipt.json"))
assert len(receipts) == 1
receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
manifest_path = Path(receipt["context_manifest_path"])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
print(json.dumps({
    "rc": rc,
    "budget": run_loop._context_token_budget(ProviderConfig.load(config)),
    "receipt": str(receipts[0]),
    "manifest": str(manifest_path),
    "manifest_node": manifest["node"],
    "context_hash_matches": (
        receipt["rendered_context_hash"] == manifest["rendered_context_sha256"]
    ),
    "provider_delta_exists": Path(receipt["provider_delta_path"]).is_file(),
    "host": os.environ["RLR_HOST_BACKEND"],
}, sort_keys=True))
'''
    smoke_env = {
        **env,
        "RLR_SMOKE_PROJECT": str(project),
        "RLR_SMOKE_CANDIDATE": candidate,
        "RLR_SMOKE_CONFIG": str(config),
    }
    smoke = subprocess.run(
        [sys.executable, "-c", child], capture_output=True, text=True,
        encoding="utf-8", env=smoke_env, cwd=str(CONTROLLER.parent / "src"),
    )
    assert smoke.returncode == 0, smoke.stderr + smoke.stdout
    result = json.loads(smoke.stdout.strip().splitlines()[-1])
    assert result == {
        "budget": 40000,
        "context_hash_matches": True,
        "host": "codex",
        "manifest": result["manifest"],
        "manifest_node": "L0",
        "provider_delta_exists": True,
        "rc": 0,
        "receipt": result["receipt"],
    }
    assert "FORMAL RUNTIME PREFLIGHT PASS" in smoke.stdout
    assert "--stop-after-node L0" in smoke.stdout
