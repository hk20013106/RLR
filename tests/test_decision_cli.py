"""Public CLI regression coverage for decision-log persistence."""

import json
import os
from pathlib import Path
import subprocess
import sys

from native_v2_helpers import write_native_emission_receipts


ROOT = Path(__file__).resolve().parents[1]


def _run_module_cli(*args, store=None):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((
        str(ROOT / "src"), str(ROOT / "tests"),
        os.environ.get("PYTHONPATH", ""),
    ))}
    if store is not None:
        env["RLR_HYPOTHESIS_STORE"] = str(store)
    return subprocess.run(
        [sys.executable, "-m", "research_loop.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )


def _run_public_cli(*args):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((
        str(ROOT / "src"), str(ROOT / "tests"),
        os.environ.get("PYTHONPATH", ""),
    ))}
    return subprocess.run(
        [sys.executable, str(ROOT / "research_loop_v04.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )


def test_cli_decision_new_to_idea_proposed_writes_existing_log_contract(tmp_path):
    """The independent CLI module must not rely on engine import side effects."""
    project = tmp_path / "project"
    store = tmp_path / "ledger.sqlite"
    created = _run_public_cli(
        "new-project", str(project), "decision regression",
        "--knowledge-store", str(store),
    )
    assert created.returncode == 0, created.stderr

    candidate_result = _run_public_cli(
        "new-candidate", str(project), "--title", "candidate",
        "--question", "question", "--claim", "claim", "--input", "inline",
        "--knowledge-store", str(store),
    )
    assert candidate_result.returncode == 0, candidate_result.stderr
    candidate_id = candidate_result.stdout.splitlines()[0]

    l0_source = tmp_path / "l0.json"
    l0_source.write_text(json.dumps({"schema_version": "2.1"}), encoding="utf-8")
    manifest, receipt = write_native_emission_receipts(
        project, candidate_id, "L0", "Linnaeus", l0_source, store_path=store,
    )
    emitted = _run_public_cli(
        "emit-delta", str(project), candidate_id, "--node", "L0",
        "--persona", "Linnaeus", "--file", str(l0_source),
        "--knowledge-store", str(store), "--context-manifest", str(manifest),
        "--provider-receipt", str(receipt),
    )
    assert emitted.returncode == 0, emitted.stderr

    decision = _run_module_cli(
        "decision", str(project), candidate_id, "--status", "IDEA_PROPOSED",
        "--reason", "L0 contract committed", "--route", "Einstein",
    )

    assert decision.returncode == 0, decision.stderr
    decision_log = next(
        path for path in (project / "05_Decision_Log").glob(f"D*_{candidate_id}.md")
        if "to_status: IDEA_PROPOSED" in path.read_text(encoding="utf-8")
    )
    log_text = decision_log.read_text(encoding="utf-8")
    assert "log_id: D0002" in log_text
    assert f"candidate_id: {candidate_id}" in log_text
    assert "from_status: NEW" in log_text
    assert "to_status: IDEA_PROPOSED" in log_text
    assert "route_to: Einstein" in log_text

    candidate_text = (project / "01_Candidates" / f"{candidate_id}.md").read_text(
        encoding="utf-8"
    )
    assert "current_status: IDEA_PROPOSED" in candidate_text
    next_step = _run_module_cli("next-step", str(project), candidate_id, store=store)
    assert next_step.returncode == 0, next_step.stderr
    assert json.loads(next_step.stdout)["node"] == "L0.5"