"""Phase 0 safety net: DAG context-isolation (information invisibility).

Rev-2 C-C4 (Codex): context isolation is a SECURITY boundary, not a convenience
filter. The ContextAssembler extraction (Phase 5) is the highest-risk phase --
a refactor from "iterate declared inputs" to "load all, filter later" could
weaken physical absence while the final prompt still looks filtered.

This test asserts on the AUTHORITATIVE audit field written by assemble-context:
`context_manifest_<node>_<ts>.json -> allowed_inputs`. That is the structural
truth of what a node may see. We deliberately do NOT string-grep the rendered
context for a persona name: probing showed L9a's context legitimately contains
"- Influenced by L9b" (benign branch metadata), which a naive grep would
false-positive on. The real invariant is node-level visibility, and the
manifest is where it is recorded.

Grounded (v0.7-migration baseline, DemoProject_v03 / C20260625112755162852):
  L9a allowed_inputs == [L1, L7, L8, L8.5]  (excludes L9b)  -> verified via CLI probe
  L9b and L9a are mutually invisible; L10c is the only ALL-reader.
Manifests land in DemoProject_v03/08_Audit/context_manifest_<node>_<ts>.json.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
PROJECT = "DemoProject_v03"
CAND = "C20260625112755162852"
AUDIT_DIR = HERE / PROJECT / "08_Audit"


def _assemble(node):
    """Run assemble-context for a node; return (rc, newest manifest dict|None)."""
    before = set(AUDIT_DIR.glob(f"context_manifest_{node}_*.json")) if AUDIT_DIR.exists() else set()
    proc = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"),
         "assemble-context", PROJECT, CAND, "--node", node],
        capture_output=True, text=True, cwd=str(HERE),
    )
    after = set(AUDIT_DIR.glob(f"context_manifest_{node}_*.json"))
    fresh = sorted(after - before, key=lambda p: p.stat().st_mtime)
    manifest = json.loads(fresh[-1].read_text(encoding="utf-8")) if fresh else None
    return proc.returncode, manifest


@pytest.mark.parametrize("node,forbidden", [
    ("L9a", "L9b"),   # falsify (Feynman) must never see biology (Darwin)
    ("L9b", "L9a"),   # symmetric
])
def test_parallel_nodes_mutually_invisible(node, forbidden):
    rc, manifest = _assemble(node)
    assert rc == 0, f"{node} assemble should succeed (rc=0), got {rc}"
    assert manifest is not None, f"{node} must write a context manifest"
    allowed = manifest.get("allowed_inputs", [])
    assert forbidden not in allowed, (
        f"ISOLATION VIOLATION: {node}.allowed_inputs={allowed} must not contain {forbidden}"
    )


def test_l9a_allowed_inputs_exact():
    """Lock the exact visibility set so extraction cannot silently widen it."""
    rc, manifest = _assemble("L9a")
    assert rc == 0 and manifest is not None
    assert set(manifest["allowed_inputs"]) == {"L1", "L7", "L8", "L8.5"}


def test_injected_deltas_subset_of_allowed():
    """Whatever is actually injected must be within the declared allow-set."""
    for node in ("L5", "L9a", "L9b"):
        rc, manifest = _assemble(node)
        assert rc == 0 and manifest is not None
        allowed = set(manifest.get("allowed_inputs", []))
        injected = manifest.get("injected_deltas", []) or []
        stray = [d for d in injected if not any(str(d).startswith(a) for a in allowed)]
        assert not stray, f"{node}: injected {stray} outside allowed_inputs {allowed}"


# --- Phase 7 (C4): the two structural exceptions to node-level isolation ------
# `ALL` (unrestricted read) and `candidate_frontmatter`-only are the only two
# ways a node escapes the normal DAG-parent visibility. Lock both so a future
# ContextAssembler change cannot silently hand another node the wildcard or
# widen L0 past its source_input-only view.

def test_l10c_is_the_all_reader():
    """L10c (Linnaeus aggregation) is the ONE node allowed to read everything."""
    rc, manifest = _assemble("L10c")
    assert rc == 0 and manifest is not None
    assert manifest["allowed_inputs"] == ["ALL"]


# Every context-assembling node except L10c -- L1 is a literature gate (rc=3,
# writes no manifest) so it is not assemble-only and is excluded here.
_NON_ALL_NODES = ["L0", "L2", "L5", "L8.5", "L9a", "L9b", "L10b"]


@pytest.mark.parametrize("node", _NON_ALL_NODES)
def test_all_wildcard_is_l10c_only(node):
    """No node other than L10c may carry the `ALL` read wildcard."""
    rc, manifest = _assemble(node)
    assert rc == 0 and manifest is not None
    assert "ALL" not in manifest["allowed_inputs"], (
        f"ISOLATION VIOLATION: {node} must not be an ALL-reader; "
        f"allowed_inputs={manifest['allowed_inputs']}"
    )


def test_l0_source_input_exception_preserved():
    """L0 (Linnaeus preflight) sees ONLY candidate frontmatter -- no upstream
    deltas exist yet, and it must never be widened to read any Lx delta."""
    rc, manifest = _assemble("L0")
    assert rc == 0 and manifest is not None
    allowed = manifest["allowed_inputs"]
    assert allowed == ["candidate_frontmatter"], allowed
