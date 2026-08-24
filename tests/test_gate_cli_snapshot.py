"""Phase 0 safety net: command-level gate snapshots (rc + stderr).

Rev-2 C-C2/C3 (Codex): gates enforce at two sites with DIFFERENT contracts --
assemble-context fails CLOSED with rc=3, emit-delta validation returns rc=1,
malformed input rc=2. Logical pass/fail is not enough; the GateRegistry
extraction (Phase 6) must preserve the exact command boundary (return code +
which stream carries the message). Full-report byte-hashing is brittle
(timestamps/receipt paths vary), so we snapshot per-command rc + a stable stderr
substring instead.

Native v2.1 L1 now fails closed at the Curie frozen-evidence binding gate rather
than the historical V0.7 Deep Research gate. Historical L4 keeps the legacy
pre-research gate. These are the current command-boundary baselines.
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


def test_l1_native_evidence_gate_fails_closed_rc3(gate_project):
    """Native L1 missing Curie binding -> hard fail-closed rc=3, empty stdout."""
    project, cand = gate_project
    rc, out, err = _cli("assemble-context", str(project), cand, "--node", "L1")
    assert rc == 3, f"native L1 evidence gate must fail closed with rc=3, got {rc}"
    assert "native L1 evidence binding gate" in err, (
        f"expected native evidence gate message in stderr, got: {err[:200]}"
    )
    assert out.strip() == "", "fail-closed gate must not emit usable context on stdout"


def test_l4_pre_research_gate_fails_closed_rc3(gate_project):
    """L4 method literature gate shares the fail-closed rc=3 contract."""
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
