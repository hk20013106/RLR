"""RC2 native-missing-authority tests for L10a/L10b.

These tests assume the current production patch in context.py and ledger.py:
native v2.1 + missing/invalid native_l85_evidence must fail closed and must
never reach deep_research.evidence_ids() / mtime latest.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import delta as delta_mod
from research_loop.commands import ledger as ledger_commands
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.context import cmd_assemble_context
from research_loop.hypothesis_ledger import HypothesisLedger

from test_rc2_l85_exact_run_identity import (
    _make_l85_run,
    _make_l85_delta,
    _sha256,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _native_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    binding = ledger.bind_project(project, profile_id=PROFILE_V21_CATALOG_1)
    cand = project / "01_Candidates" / "C1.md"
    cand.parent.mkdir(parents=True)
    cand.write_text(
        "---\n"
        "candidate_id: C1\n"
        "question: Q\n"
        "claim: C\n"
        "round_id: 1\n"
        "current_status: UNDER_REVIEW\n"
        "---\n",
        encoding="utf-8",
    )
    return project, store, binding


def _assemble_args(project, node, evidence_run_id=None):
    return SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        node=node,
        authorization_id=None,
        knowledge_store=str(project.parent / "hypotheses.sqlite"),
        template_mode="contract",
        pre_research_mode="none",
        pre_research_token_budget=None,
        context_token_budget=12000,
        evidence_run_id=evidence_run_id,
    )


def _latest_context_manifest(project, node):
    manifests = sorted((project / "08_Audit").glob(f"context_manifest_{node}_*.json"))
    assert manifests, f"no {node} context manifest found"
    path = manifests[-1]
    return path, json.loads(path.read_text(encoding="utf-8"))


def _build_provider_receipt(project, manifest_path, manifest, delta_path):
    rendered = Path(str(manifest["rendered_context_path"]))
    receipt_path = project / "08_Audit" / "test_provider_receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    from research_loop.providers.base import RunReceipt

    receipt = RunReceipt(
        node="L10b",
        persona="Oppenheimer",
        provider="synthetic-native-boundary",
        timestamp="2026-09-22T00:00:00Z",
        context_hash=str(manifest["rendered_context_sha256"]),
        project_id=str(manifest["project_id"]),
        candidate_id="C1",
        round_id=str(manifest["round_id"]),
        profile_id=str(manifest["profile_id"]),
        context_manifest_path=str(manifest_path),
        context_manifest_hash=hashlib.sha256(
            Path(manifest_path).read_bytes()
        ).hexdigest(),
        rendered_context_path=str(rendered),
        rendered_context_hash=str(manifest["rendered_context_sha256"]),
        prompt_file=str(rendered),
        prompt_hash=hashlib.sha256(rendered.read_bytes()).hexdigest(),
        provider_delta_path=str(delta_path),
        provider_delta_hash=_sha256(delta_path.read_bytes()),
    )
    receipt.write(receipt_path)
    return receipt_path


def _route_l85_delta_lookup(monkeypatch, project):
    """Route the assembler's committed-L8.5 lookup at the fixture delta.

    Fixture deltas are written straight to disk and carry no ledger emission
    receipt, so the production lookup (which admits only committed v2
    artifacts) cannot return them; the lookup is redirected for this test.
    """
    original = delta_mod._delta_for_candidate
    delta_path = project / "08_Audit" / "C1_L8.5_curie_delta.v2.json"

    def _resolver(project_dir, delta_key, cand_id):
        if delta_key == "L8.5_curie":
            return delta_path
        return original(project_dir, delta_key, cand_id)

    monkeypatch.setattr(delta_mod, "_delta_for_candidate", _resolver)


# ---------------------------------------------------------------------------
# N1 — producer boundary: delta missing deep_research_run_id
# ---------------------------------------------------------------------------

def test_n1_missing_run_id_in_delta_fails_closed(tmp_path, monkeypatch):
    """native v2.1 L10b context assembly must fail when L8.5 delta has no
    deep_research_run_id, even though valid L8.5 runs exist on disk."""
    project, store, binding = _native_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    _make_l85_run(project, "C1", "L85_runA", evidence_ids=["ev_A"])
    _make_l85_run(project, "C1", "L85_runB", evidence_ids=["ev_B"])

    # Write an L8.5 delta WITHOUT deep_research_run_id.
    audit = project / "08_Audit"
    audit.mkdir(parents=True, exist_ok=True)
    delta_path = audit / "C1_L8.5_curie_delta.v2.json"
    delta_path.write_text(
        json.dumps({
            "deep_research_receipt_hash": _sha256("receipt"),
            "assessments": [],
            "summary": "test summary",
            "searched_keywords": [],
            "papers": [],
        }, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    rc = cmd_assemble_context(_assemble_args(project, "L10b"))
    assert rc == 3, "missing deep_research_run_id must fail context assembly"


def test_n1b_no_context_manifest_produced(tmp_path, monkeypatch):
    """When assembly fails closed, no usable native L8.5 authority manifest is
    produced for L10b."""
    project, store, binding = _native_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    _make_l85_run(project, "C1", "L85_runA", evidence_ids=["ev_A"])
    _make_l85_delta(project, "C1", None)

    rc = cmd_assemble_context(_assemble_args(project, "L10b"))
    assert rc == 3

    manifests = sorted((project / "08_Audit").glob("context_manifest_L10b_*.json"))
    assert not manifests, "failed assembly must not produce a context manifest"


# ---------------------------------------------------------------------------
# N2 — consumer boundary: tampered native_l85_evidence in manifest
# ---------------------------------------------------------------------------

def test_n2_missing_native_l85_evidence_fails_closed_at_emit(
    tmp_path, monkeypatch, capsys
):
    """A native ContextManifest whose native_l85_evidence was removed must fail
    at the ledger emission boundary, before any legacy evidence_ids() lookup."""
    project, store, binding = _native_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    run_id = "L85_consumer_tampered"
    _make_l85_run(project, "C1", run_id, evidence_ids=["ev_tampered"])
    _make_l85_delta(project, "C1", run_id)
    _route_l85_delta_lookup(monkeypatch, project)

    rc = cmd_assemble_context(_assemble_args(project, "L10b"))
    assert rc == 0, "assembly must succeed for valid native run"
    manifest_path, manifest = _latest_context_manifest(project, "L10b")
    assert manifest.get("native_l85_evidence") is not None

    # Tamper: remove native_l85_evidence from the manifest.
    manifest["native_l85_evidence"] = None
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    delta_path = tmp_path / "L10b_delta.json"
    delta_path.write_text(
        json.dumps({
            "schema_version": "2.1",
            "candidate_id": "C1",
            "decision": "KEEP",
            "reason": "test",
            "next_steps": [],
            "hypothesis_decisions": [],
            "literature_evidence_ids": ["ev_tampered"],
        }, indent=2),
        encoding="utf-8",
    )
    receipt_path = _build_provider_receipt(project, manifest_path, manifest, delta_path)

    rc = ledger_commands.cmd_emit_delta(
        SimpleNamespace(
            project_dir=str(project),
            cand_id="C1",
            node="L10b",
            persona="Oppenheimer",
            file=str(delta_path),
            knowledge_store=str(store),
            context_manifest=str(manifest_path),
            provider_receipt=str(receipt_path),
        )
    )
    captured = capsys.readouterr()
    assert rc != 0, "tampered native authority must fail at emit"
    assert "lacks the frozen L8.5 evidence authority" in captured.err


def test_n2b_no_deep_research_evidence_ids_called_on_native_missing(
    tmp_path, monkeypatch, capsys
):
    """Native missing authority must not reach deep_research.evidence_ids()."""
    project, store, binding = _native_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    run_id = "L85_no_legacy_lookup"
    _make_l85_run(project, "C1", run_id, evidence_ids=["ev_lookup"])
    _make_l85_delta(project, "C1", run_id)
    _route_l85_delta_lookup(monkeypatch, project)

    rc = cmd_assemble_context(_assemble_args(project, "L10b"))
    assert rc == 0
    manifest_path, manifest = _latest_context_manifest(project, "L10b")
    manifest["native_l85_evidence"] = None
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    delta_path = tmp_path / "L10b_delta2.json"
    delta_path.write_text(
        json.dumps({
            "schema_version": "2.1",
            "candidate_id": "C1",
            "decision": "KEEP",
            "reason": "test",
            "next_steps": [],
            "hypothesis_decisions": [],
            "literature_evidence_ids": ["ev_lookup"],
        }, indent=2),
        encoding="utf-8",
    )
    receipt_path = _build_provider_receipt(project, manifest_path, manifest, delta_path)

    calls = []

    def recordedEvidenceIds(project_dir, candidate_id, nodes, *, run_ids=None):
        calls.append((project_dir, candidate_id, nodes, run_ids))
        return dr.evidence_ids(project_dir, candidate_id, nodes, run_ids=run_ids)

    monkeypatch.setattr(dr, "evidence_ids", recordedEvidenceIds)

    rc = ledger_commands.cmd_emit_delta(
        SimpleNamespace(
            project_dir=str(project),
            cand_id="C1",
            node="L10b",
            persona="Oppenheimer",
            file=str(delta_path),
            knowledge_store=str(store),
            context_manifest=str(manifest_path),
            provider_receipt=str(receipt_path),
        )
    )
    assert rc != 0
    assert not calls, (
        "native missing authority must not call deep_research.evidence_ids()"
    )
