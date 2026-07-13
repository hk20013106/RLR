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

Grounded with a temporary project and synthetic evidence fixtures:
  L9a allowed_inputs == [L1, L7, L8, L8.5]  (excludes L9b)  -> verified via CLI probe
  L9b and L9a are mutually invisible; L10c is the only ALL-reader.
Manifests land in DemoProject_v03/08_Audit/context_manifest_<node>_<ts>.json.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from deep_research_fixtures import persist_synthetic_evidence

HERE = Path(__file__).resolve().parent.parent


def _assemble(node, project, candidate):
    """Run assemble-context for a node; return (rc, newest manifest dict|None)."""
    audit_dir = Path(project) / "08_Audit"
    before = set(audit_dir.glob(f"context_manifest_{node}_*.json")) if audit_dir.exists() else set()
    mode = ["--pre-research-mode", "none"] if node == "L8.5" else []
    proc = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"),
         "assemble-context", str(project), candidate, "--node", node, *mode],
        capture_output=True, text=True, cwd=str(HERE),
    )
    after = set(audit_dir.glob(f"context_manifest_{node}_*.json"))
    fresh = sorted(after - before, key=lambda p: p.stat().st_mtime)
    manifest = json.loads(fresh[-1].read_text(encoding="utf-8")) if fresh else None
    return proc.returncode, manifest


@pytest.fixture
def context_project(tmp_path):
    project = tmp_path / "context-isolation"
    source_input = tmp_path / "input.txt"
    source_input.write_text("synthetic input", encoding="utf-8")
    created = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"), "new-project", str(project), "Topic"],
        capture_output=True, text=True, cwd=str(HERE),
    )
    assert created.returncode == 0, created.stderr
    candidate = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"), "new-candidate", str(project),
         "--title", "T", "--question", "Q", "--claim", "C",
         "--input", "synthetic tabular input for context isolation",
         "--input-type", "files", "--input-files", str(source_input),
         "--input-format", "txt"],
        capture_output=True, text=True, cwd=str(HERE),
    )
    assert candidate.returncode == 0, candidate.stderr
    candidate_id = candidate.stdout.splitlines()[0]
    for node in ("L1", "L8.5"):
        persist_synthetic_evidence(
            project, candidate_id, node, [f"synthetic {node} evidence"],
            result_context='{"L7_key_results": {"synthetic": "observed"}}',
        )
    return project, candidate_id


@pytest.mark.parametrize("node,forbidden", [
    ("L9a", "L9b"),   # falsify (Feynman) must never see biology (Darwin)
    ("L9b", "L9a"),   # symmetric
])
def test_parallel_nodes_mutually_invisible(node, forbidden, context_project):
    rc, manifest = _assemble(node, *context_project)
    assert rc == 0, f"{node} assemble should succeed (rc=0), got {rc}"
    assert manifest is not None, f"{node} must write a context manifest"
    allowed = manifest.get("allowed_inputs", [])
    assert forbidden not in allowed, (
        f"ISOLATION VIOLATION: {node}.allowed_inputs={allowed} must not contain {forbidden}"
    )


def test_l9a_allowed_inputs_exact(context_project):
    """Lock the exact visibility set so extraction cannot silently widen it."""
    rc, manifest = _assemble("L9a", *context_project)
    assert rc == 0 and manifest is not None
    assert set(manifest["allowed_inputs"]) == {"L1", "L7", "L8", "L8.5"}


def test_injected_deltas_subset_of_allowed(context_project):
    """Whatever is actually injected must be within the declared allow-set."""
    for node in ("L5", "L9a", "L9b"):
        rc, manifest = _assemble(node, *context_project)
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

def test_l10c_is_the_all_reader(context_project):
    """L10c (Linnaeus aggregation) is the ONE node allowed to read everything."""
    rc, manifest = _assemble("L10c", *context_project)
    assert rc == 0 and manifest is not None
    assert manifest["allowed_inputs"] == ["ALL"]


# Every context-assembling node except L10c -- L1 is a literature gate (rc=3,
# writes no manifest) so it is not assemble-only and is excluded here.
_NON_ALL_NODES = ["L0", "L2", "L5", "L8.5", "L9a", "L9b", "L10b"]


def _l85_fixture_project(tmp_path):
    project = tmp_path / "l85-context"
    created = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"), "new-project", str(project), "Topic"],
        capture_output=True, text=True, cwd=str(HERE),
    )
    assert created.returncode == 0, created.stderr
    candidate = subprocess.run(
        [sys.executable, str(HERE / "research_loop_v04.py"), "new-candidate", str(project),
         "--title", "T", "--question", "Q", "--claim", "C", "--input", "data"],
        capture_output=True, text=True, cwd=str(HERE),
    )
    assert candidate.returncode == 0, candidate.stderr
    cand_id = candidate.stdout.splitlines()[0]
    persist_synthetic_evidence(
        project, cand_id, "L8.5", ["synthetic L8.5 verification"],
        result_context='{"L7_key_results": {"synthetic": "observed"}}',
    )
    return project, cand_id


@pytest.mark.parametrize("node", _NON_ALL_NODES)
def test_all_wildcard_is_l10c_only(node, tmp_path, context_project):
    """No node other than L10c may carry the `ALL` read wildcard."""
    project, candidate = _l85_fixture_project(tmp_path) if node == "L8.5" else context_project
    rc, manifest = _assemble(node, project, candidate)
    assert rc == 0 and manifest is not None
    assert "ALL" not in manifest["allowed_inputs"], (
        f"ISOLATION VIOLATION: {node} must not be an ALL-reader; "
        f"allowed_inputs={manifest['allowed_inputs']}"
    )


def test_l0_source_input_exception_preserved(context_project):
    """L0 (Linnaeus preflight) sees ONLY candidate frontmatter -- no upstream
    deltas exist yet, and it must never be widened to read any Lx delta."""
    rc, manifest = _assemble("L0", *context_project)
    assert rc == 0 and manifest is not None
    allowed = manifest["allowed_inputs"]
    assert allowed == ["candidate_frontmatter"], allowed
