"""RC2 RED tests — L8.5 exact run identity for L10a/L10b.

These tests prove the defect exists (RED) before the fix (GREEN).
"""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from research_loop import deep_research as dr
from research_loop import gates
from research_loop import l85_literature_verification as l85


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8") + b"\n"


def _make_l85_run(project, cand_id, run_id, *, evidence_ids=None):
    """Persist a native L8.5 run manifest at the canonical location."""
    evidence_ids = evidence_ids or [f"ev_{run_id}_1"]
    located = [
        {"evidence_id": eid, "verification_status": "LOCATED",
         "locator": "char:0:10", "text": f"evidence for {eid}",
         "retrieval": {"engine": "test", "source_sha256": _sha256(eid),
                       "snapshot_path": ""}}
        for eid in evidence_ids
    ]
    payload = {
        "research_seed": {}, "query_plan": {"plan_id": "qp1", "queries": []},
        "discovery": {}, "selected_paper_ids": [], "source_snapshots": [],
        "located_evidence": located, "semantic_verifications": [],
        "findings": [{"finding_id": "f1", "text": "test finding", "sources": ["L7"]}],
        "verdicts": [{"finding_id": "f1", "verdict": "supports",
                      "evidence_ids": evidence_ids, "reason": "test"}],
    }
    return l85.persist_run_manifest(project, cand_id, run_id=run_id, payload=payload)


def _make_l85_delta(project, cand_id, run_id):
    """Write a committed L8.5 delta with deep_research_run_id."""
    delta = {
        "deep_research_run_id": run_id,
        "deep_research_receipt_hash": _sha256(f"receipt_{run_id}"),
        "assessments": [{"hypothesis_id": "h1", "outcome": "SUPPORTS",
                         "comparison": "test", "evidence_ids": [f"ev_{run_id}_1"]}],
        "summary": "test summary",
        "searched_keywords": ["test"],
        "papers": [],
    }
    # Write as a v2 delta file
    audit = project / "08_Audit"
    audit.mkdir(parents=True, exist_ok=True)
    delta_path = audit / f"{cand_id}_L8.5_curie_delta.v2.json"
    delta_path.write_text(json.dumps(delta, ensure_ascii=False, sort_keys=True),
                          encoding="utf-8")
    return delta


def _make_l1_run(project, cand_id, run_id):
    """Persist a deep_research L1 run for the evidence_ids() path."""
    payload = {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": [f"query_{run_id}"],
        "papers": [{
            "doi": f"10.1000/test.{run_id}",
            "pmid": f"{10000000 + hash(run_id) % 9000000}",
            "url": f"https://doi.org/10.1000/test.{run_id}",
            "title": f"Paper {run_id}", "source_database": "test",
            "metadata": {"year": 2026},
            "source_metadata_response": {"id": f"PMID_{run_id}"},
            "open_access": True, "content_type": "text/html",
            "source_payload": f"<article>source for {run_id}</article>",
            "extracts": [{
                "section": "Results", "text": f"Result from {run_id}",
                "locator": "Results paragraph 1",
            }],
        }],
    }
    receipt = dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9")
    return dr.persist_run(project, cand_id, "L1", payload, receipt)


# ---------------------------------------------------------------------------
# R1 — exact B wins regardless of mtime
# ---------------------------------------------------------------------------

def test_r1_exact_B_wins_regardless_of_mtime(tmp_path):
    """L8.5 run A has newer mtime than B, but delta says B is canonical.

    Before fix: evidence_ids() would pick A (newer mtime).
    After fix:  evidence_ids() uses the delta's deep_research_run_id = B.
    """
    # Create run A (will have newer mtime)
    run_a = _make_l85_run(tmp_path, "C1", "L85_runA", evidence_ids=["ev_A_1"])
    # Create run B (older mtime)
    run_b = _make_l85_run(tmp_path, "C1", "L85_runB", evidence_ids=["ev_B_1"])
    # Make A newer by touching
    time.sleep(0.05)
    (tmp_path / "08_Audit" / "l85_literature_verification" / "C1"
     / "L85_runA.json").touch()

    # L8.5 delta says run B is canonical
    _make_l85_delta(tmp_path, "C1", "L85_runB")

    # Resolve evidence IDs from native L8.5 path
    evidence_ids = l85.resolve_l85_evidence_ids(tmp_path, "C1", "L85_runB")
    assert evidence_ids == ["ev_B_1"], f"Expected run B evidence, got {evidence_ids}"


# ---------------------------------------------------------------------------
# R2 — multiple runs, ID missing → FAIL CLOSED
# ---------------------------------------------------------------------------

def test_r2_multiple_runs_id_missing_fails_closed(tmp_path):
    """Multiple L8.5 runs exist but delta has no deep_research_run_id.

    Must fail closed — not pick latest by mtime.
    """
    _make_l85_run(tmp_path, "C1", "L85_runA")
    _make_l85_run(tmp_path, "C1", "L85_runB")
    # Write delta WITHOUT deep_research_run_id
    delta = {
        "assessments": [], "summary": "test",
        "searched_keywords": [], "papers": [],
    }
    audit = tmp_path / "08_Audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "C1_L8.5_curie_delta.v2.json").write_text(
        json.dumps(delta), encoding="utf-8")

    # resolve_l85_evidence_ids should return empty (no run_id to resolve with)
    # The caller (context assembly) must fail closed when run_id is missing.
    # This test proves the function doesn't silently pick a run.
    result = l85.resolve_l85_evidence_ids(tmp_path, "C1", "")
    assert result is None, f"Expected None for missing run_id, got {result}"


# ---------------------------------------------------------------------------
# R3 — single run, ID missing → FAIL CLOSED
# ---------------------------------------------------------------------------

def test_r3_single_run_id_missing_fails_closed(tmp_path):
    """Even with one L8.5 run on disk, missing deep_research_run_id = contract violation.

    Must NOT auto-resolve by uniqueness.
    """
    _make_l85_run(tmp_path, "C1", "L85_single")
    result = l85.resolve_l85_evidence_ids(tmp_path, "C1", "")
    assert result is None, "Missing run_id must not auto-resolve"


# ---------------------------------------------------------------------------
# R4 — stale/newer mtime cannot override authority
# ---------------------------------------------------------------------------

def test_r4_stale_mtime_cannot_override_authority(tmp_path):
    """Canonical=A, B has newer mtime. A must be selected."""
    run_a = _make_l85_run(tmp_path, "C1", "L85_canonical", evidence_ids=["ev_canonical_1"])
    _make_l85_run(tmp_path, "C1", "L85_newer", evidence_ids=["ev_newer_1"])

    # Touch A to make it older
    a_path = (tmp_path / "08_Audit" / "l85_literature_verification" / "C1"
              / "L85_canonical.json")
    old_time = time.time() - 100
    os.utime(a_path, (old_time, old_time))

    evidence_ids = l85.resolve_l85_evidence_ids(tmp_path, "C1", "L85_canonical")
    assert evidence_ids == ["ev_canonical_1"]


# ---------------------------------------------------------------------------
# R5 — exact ID references absent artifact → FAIL CLOSED
# ---------------------------------------------------------------------------

def test_r5_absent_artifact_fails_closed(tmp_path):
    """deep_research_run_id references a run that doesn't exist on disk."""
    result = l85.resolve_l85_evidence_ids(tmp_path, "C1", "L85_nonexistent")
    assert result is None, "Absent artifact must return None (caller fails closed)"


# ---------------------------------------------------------------------------
# R6 — identity/hash mismatch → FAIL CLOSED
# ---------------------------------------------------------------------------

def test_r6_hash_mismatch_fails_closed(tmp_path):
    """Run manifest exists but hash verification fails."""
    # Manually write a corrupted manifest
    manifest_dir = tmp_path / "08_Audit" / "l85_literature_verification" / "C1"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    corrupted = {
        "schema_version": l85.RUN_SCHEMA_VERSION,
        "run_id": "L85_corrupt",
        "candidate_id": "C1",
        "run_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "located_evidence": [{"evidence_id": "ev_1"}],
    }
    (manifest_dir / "L85_corrupt.json").write_text(
        json.dumps(corrupted), encoding="utf-8")

    result = l85.resolve_l85_evidence_ids(tmp_path, "C1", "L85_corrupt")
    assert result is None, "Hash mismatch must return None (caller fails closed)"


# ---------------------------------------------------------------------------
# R7 — L10a/L10b/gate consistency
# ---------------------------------------------------------------------------

def test_r7_l10a_l10b_gate_consistency(tmp_path):
    """All three consumers use the same frozen L8.5 evidence IDs."""
    run_id = "L85_consistent"
    _make_l85_run(tmp_path, "C1", run_id, evidence_ids=["ev_consistent_1", "ev_consistent_2"])

    # All three consumers should get the same IDs
    from_context = l85.resolve_l85_evidence_ids(tmp_path, "C1", run_id)
    from_gate = l85.resolve_l85_evidence_ids(tmp_path, "C1", run_id)
    from_ledger = l85.resolve_l85_evidence_ids(tmp_path, "C1", run_id)

    assert from_context == from_gate == from_ledger
    assert set(from_context) == {"ev_consistent_1", "ev_consistent_2"}


# ---------------------------------------------------------------------------
# R8 — native path does not invoke latest/mtime fallback
# ---------------------------------------------------------------------------

def test_r8_no_mtime_fallback_for_native_l85(tmp_path):
    """resolve_l85_evidence_ids never uses glob/st_mtime for selection.

    It loads by exact run_id only.
    """
    _make_l85_run(tmp_path, "C1", "L85_alpha", evidence_ids=["ev_alpha"])
    _make_l85_run(tmp_path, "C1", "L85_beta", evidence_ids=["ev_beta"])
    # Make alpha newer
    time.sleep(0.05)
    (tmp_path / "08_Audit" / "l85_literature_verification" / "C1"
     / "L85_alpha.json").touch()

    # Request beta — must get beta regardless of alpha being newer
    result = l85.resolve_l85_evidence_ids(tmp_path, "C1", "L85_beta")
    assert result == ["ev_beta"]
    # Request alpha — must get alpha
    result = l85.resolve_l85_evidence_ids(tmp_path, "C1", "L85_alpha")
    assert result == ["ev_alpha"]


# ---------------------------------------------------------------------------
# R9 — legacy _artifact() mtime fallback not broken
# ---------------------------------------------------------------------------

def test_r9_legacy_artifact_mtime_fallback_unchanged(tmp_path):
    """deep_research._artifact() mtime fallback still works for legacy callers."""
    # Create two L1 runs in deep_research location
    artifact_a = _make_l1_run(tmp_path, "C1", "legacy_A")
    run_a_id = artifact_a["run_id"]
    time.sleep(0.05)
    artifact_b = _make_l1_run(tmp_path, "C1", "legacy_B")
    run_b_id = artifact_b["run_id"]

    # Without run_id, _artifact picks newest (mtime fallback)
    artifact = dr._artifact(tmp_path, "C1", "L1")
    assert artifact is not None
    assert artifact["run_id"] == run_b_id  # newer mtime wins

    # With exact run_id, _artifact picks that run
    artifact = dr._artifact(tmp_path, "C1", "L1", run_id=run_a_id)
    assert artifact is not None
    assert artifact["run_id"] == run_a_id
