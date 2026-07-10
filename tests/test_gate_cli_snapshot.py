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
    -> rc=3, stderr contains "V0.5 deep-research gate", stdout empty
  assemble-context --node L5  -> rc=0, non-empty stdout
These are the fail-closed and pass baselines the registry must not change.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PROJECT = "DemoProject_v03"
CAND = "C20260625112755162852"


def _cli(*args):
    proc = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"), *args],
        capture_output=True, text=True, cwd=str(HERE),
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_l1_pre_research_gate_fails_closed_rc3():
    """L1 literature pre-research missing -> hard fail-closed rc=3, no context on stdout."""
    rc, out, err = _cli("assemble-context", PROJECT, CAND, "--node", "L1")
    assert rc == 3, f"L1 pre-research gate must fail closed with rc=3, got {rc}"
    assert "V0.5 deep-research gate" in err, f"expected gate message in stderr, got: {err[:200]}"
    assert out.strip() == "", "fail-closed gate must not emit usable context on stdout"


def test_l4_pre_research_gate_fails_closed_rc3():
    """L4 method literature gate shares the L1 fail-closed contract."""
    rc, out, err = _cli("assemble-context", PROJECT, CAND, "--node", "L4")
    assert rc == 3, f"L4 pre-research gate must fail closed with rc=3, got {rc}"
    assert out.strip() == "", "fail-closed gate must not emit usable context on stdout"


def test_l5_assemble_passes_rc0():
    """A node with satisfied inputs assembles context -> rc=0, non-empty stdout."""
    rc, out, err = _cli("assemble-context", PROJECT, CAND, "--node", "L5")
    assert rc == 0, f"L5 assemble should pass (rc=0), got {rc}; stderr={err[:200]}"
    assert out.strip() != "", "passing assemble-context must emit context on stdout"


def test_unknown_node_is_input_error_not_gate():
    """Malformed input must stay a distinct rc (2), never masquerade as a gate fail (3)."""
    rc, out, err = _cli("assemble-context", PROJECT, CAND, "--node", "L99")
    assert rc == 2, f"unknown node should be input error rc=2, got {rc}"
