"""Phase 0 safety net: command-level gate snapshots (rc + stderr).

Rev-2 C-C2/C3 (Codex): gates enforce at two sites with DIFFERENT contracts --
assemble-context fails CLOSED with rc=3, emit-delta validation returns rc=1,
malformed input rc=2. Logical pass/fail is not enough; the GateRegistry
extraction (Phase 6) must preserve the exact command boundary (return code +
which stream carries the message). Full-report byte-hashing is brittle
(timestamps/receipt paths vary), so we snapshot per-command rc + a stable stderr
substring instead.

Grounded via CLI probe on v0.7-migration baseline (DemoProject_v03 /
C20260625112755162852):
  assemble-context --node L1 (pre-research artifact absent)
    -> rc=3, stderr contains "V0.7 deep-research gate", stdout empty
  assemble-context --node L5  -> rc=0, non-empty stdout
These are the fail-closed and pass baselines the registry must not change.
"""
import subprocess
import sys
import json
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent.parent


@pytest.fixture
def gate_project(tmp_path):
    project = tmp_path / "gate-snapshot"
    created = _cli("new-project", str(project), "Topic")
    assert created[0] == 0, created[2]
    source_input = tmp_path / "input.txt"
    source_input.write_text("synthetic input", encoding="utf-8")
    candidate = _cli(
        "new-candidate", str(project), "--title", "T", "--question", "Q",
        "--claim", "C", "--input", "synthetic gate input",
        "--input-type", "files", "--input-files", str(source_input),
        "--input-format", "txt",
    )
    assert candidate[0] == 0, candidate[2]
    cand_id = candidate[1].splitlines()[0]
    notes = project / "02_Agent_Notes"
    for persona, key, delta in (
        ("Fisher", "L4_fisher", {
            "strategies": [], "recommended": "", "scripts_needed": [],
            "key_decisions": [],
        }),
        ("Feynman", "L2_feynman", {
            "attacks": [], "confounders": [], "diagnostic_tests": [],
            "verdict": "",
        }),
    ):
        folder = notes / persona
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{cand_id}_{key}_delta.json").write_text(
            json.dumps({"candidate_id": cand_id, **delta}), encoding="utf-8")
    return project, cand_id


def _cli(*args):
    proc = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"), *args],
        capture_output=True, text=True, cwd=str(HERE),
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_l1_pre_research_gate_fails_closed_rc3(gate_project):
    """L1 literature pre-research missing -> hard fail-closed rc=3, no context on stdout."""
    project, cand = gate_project
    rc, out, err = _cli("assemble-context", str(project), cand, "--node", "L1")
    assert rc == 3, f"L1 pre-research gate must fail closed with rc=3, got {rc}"
    assert "V0.7 deep-research gate" in err, f"expected gate message in stderr, got: {err[:200]}"
    assert out.strip() == "", "fail-closed gate must not emit usable context on stdout"


def test_l4_pre_research_gate_fails_closed_rc3(gate_project):
    """L4 method literature gate shares the L1 fail-closed contract."""
    project, cand = gate_project
    rc, out, err = _cli("assemble-context", str(project), cand, "--node", "L4")
    assert rc == 3, f"L4 pre-research gate must fail closed with rc=3, got {rc}"
    assert out.strip() == "", "fail-closed gate must not emit usable context on stdout"


def test_l5_assemble_passes_rc0(gate_project):
    """A node with satisfied inputs assembles context -> rc=0, non-empty stdout."""
    project, cand = gate_project
    rc, out, err = _cli("assemble-context", str(project), cand, "--node", "L5")
    assert rc == 0, f"L5 assemble should pass (rc=0), got {rc}; stderr={err[:200]}"
    assert out.strip() != "", "passing assemble-context must emit context on stdout"


def test_unknown_node_is_input_error_not_gate(gate_project):
    """Malformed input must stay a distinct rc (2), never masquerade as a gate fail (3)."""
    project, cand = gate_project
    rc, out, err = _cli("assemble-context", str(project), cand, "--node", "L99")
    assert rc == 2, f"unknown node should be input error rc=2, got {rc}"
