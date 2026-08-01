# -*- coding: utf-8 -*-
"""Focused tests for candidate-scoped L7 workspace hydration."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from native_v2_helpers import activate_native_project, commit_v2, seed_selected_hypothesis

HERE = Path(__file__).resolve().parent
RL = str(HERE.parent / "research_loop_v04.py")


def _run(*args):
    return subprocess.run(
        [sys.executable, RL] + list(args), capture_output=True, text=True,
        timeout=15, encoding="utf-8", errors="replace")


def _fixture(missing_input=False, missing_script=False):
    base = Path(tempfile.mkdtemp(prefix="rlr_hydrate_"))
    project = base / "project"
    source = base / "source"
    source.mkdir()
    if not missing_input:
        (source / "real.csv").write_text("gene,value\nCOL6A1,1\n", encoding="utf-8")

    candidate = project / "01_Candidates"
    candidate.mkdir(parents=True)
    (candidate / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: NEEDS_EXECUTION\n"
        "current_owner: Turing\ninput_alias: registered_input\n---\n",
        encoding="utf-8")

    preflight = project / "00_Preflight"
    preflight.mkdir()
    for name in ("skill_use_plan.md", "output_manifest.md", "forbidden_shortcuts.md"):
        (preflight / name).write_text(name, encoding="utf-8")
    (preflight / "input_manifest.md").write_text(
        "| alias | path | key files | format | classification | verification |\n"
        "|---|---|---|---|---|---|\n"
        f"| `registered_input` | `{source.as_posix()}/` | `real.csv` | CSV | primary | verified |\n",
        encoding="utf-8")

    scripts = project / "04_Analysis_Outputs"
    scripts.mkdir()
    if not missing_script:
        (scripts / "analysis.py").write_text(
            "from pathlib import Path\n"
            "data = Path('inputs/registered_input/real.csv').read_text()\n"
            "Path('results/result.txt').write_text(data)\n",
            encoding="utf-8")
    (project / "unrelated.txt").write_text("must not be copied", encoding="utf-8")
    activate_native_project(project)
    commit_v2(project, "C1", "L0", "Linnaeus", {"schema_version": "2.0"})
    hid = seed_selected_hypothesis(project, "C1")
    commit_v2(project, "C1", "L4", "Fisher", {
        "schema_version": "2.0", "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hid],
            "name": "workspace hydration", "steps": ["run analysis.py"],
        }],
    })
    commit_v2(project, "C1", "L6", "Oppenheimer", {
        "schema_version": "2.0", "analysis_plan": [{
            "strategy_id": "S1", "hypothesis_ids": [hid],
            "scripts": ["analysis.py"], "parameters": {}, "outputs": ["result.txt"],
        }], "method_decision": "APPROVE", "reason": "ready",
    })
    return project


def _workspace(stdout):
    line = next(x for x in stdout.splitlines() if "Turing workspace ready:" in x)
    return Path(line.split("ready:", 1)[1].strip())


def test_hydrates_allowlisted_inputs_scripts_and_json_manifest():
    project = _fixture()
    result = _run("prepare-turing-workspace", str(project), "C1")
    assert result.returncode == 0, result.stderr
    workspace = _workspace(result.stdout)
    staged_input = workspace / "inputs" / "registered_input" / "real.csv"
    staged_script = workspace / "scripts" / "analysis.py"
    assert staged_input.exists()
    assert staged_script.exists()
    assert not (workspace / "unrelated.txt").exists()
    assert "inputs/registered_input/real.csv" in staged_script.read_text(encoding="utf-8")
    executed = subprocess.run(
        [sys.executable, str(staged_script)], cwd=workspace,
        capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr
    assert (workspace / "results" / "result.txt").read_text(
        encoding="utf-8") == staged_input.read_text(encoding="utf-8")

    manifest = json.loads(
        (workspace / "WORKSPACE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["candidate_id"] == "C1"
    assert manifest["node"] == "L7"
    records = manifest["staged_files"]
    for record in records:
        assert set(("original_path", "workspace_path", "sha256", "reason",
                    "candidate_id", "node")) <= set(record)
        assert record["candidate_id"] == "C1"
        assert record["node"] == "L7"
        staged = Path(record["workspace_path"])
        assert record["sha256"] == hashlib.sha256(staged.read_bytes()).hexdigest()
    # workspace_path is stored via .resolve() (execution.py); compare resolved
    # here too, since GitHub Actions' Windows runners expose TEMP through an
    # 8.3 short-name alias (RUNNER~1) that differs from the resolved long path.
    assert any(r["workspace_path"] == str(staged_input.resolve()) for r in records)
    assert any(r["workspace_path"] == str(staged_script.resolve()) for r in records)


def test_missing_required_input_fails_cleanly():
    project = _fixture(missing_input=True)
    result = _run("prepare-turing-workspace", str(project), "C1")
    assert result.returncode != 0
    assert "missing required input" in result.stderr.lower()
    assert "real.csv" in result.stderr


def test_missing_approved_script_fails_cleanly():
    project = _fixture(missing_script=True)
    result = _run("prepare-turing-workspace", str(project), "C1")
    assert result.returncode != 0
    assert "missing execution script" in result.stderr.lower()
    assert "analysis.py" in result.stderr


def _run_as_script():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
