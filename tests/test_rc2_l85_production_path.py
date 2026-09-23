"""RC2 production-path integration — exact L8.5 authority crosses context/ledger/gate.

These tests close the gap identified in R7: they prove that the canonical
L8.5 run_id from the L8.5 delta is resolved exactly once during L10b context
assembly, frozen into ContextManifest/v2.native_l85_evidence, and then
consumed unchanged by the ledger emission path and the L10b gate.

The L8.5 delta file is prepared directly and injected through the production
_delta_for_candidate seam.  This avoids dragging an entire L4-L8 upstream chain
into a test whose sole purpose is the L10b authority boundary, while still
exercising the real context assembler, manifest writer, ledger emission, and
gate validator.
"""
import hashlib
import json
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from research_loop import context as context_mod
from research_loop import deep_research as dr
from research_loop import delta as delta_mod
from research_loop import l85_literature_verification as l85
from research_loop.commands import ledger as ledger_commands
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.context import cmd_assemble_context
from research_loop.engine import main as engine_main
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.providers.base import RunReceipt

from native_v2_helpers import (
    bootstrap_project_ready,
    commit_v2,
    seed_selected_hypothesis,
)
from test_l4b_to_l4c_context import _bind_round_data


RL = Path(__file__).resolve().parents[1] / "research_loop_v04.py"


def _sha256(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _native_project(tmp_path, monkeypatch):
    """Real native v2.1 project with one candidate."""
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    ledger = HypothesisLedger(store)
    binding = ledger.bind_project(project, profile_id=PROFILE_V21_CATALOG_1)

    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\n"
        "candidate_id: C1\n"
        "question: Q\n"
        "claim: C\n"
        "round_id: 1\n"
        "current_status: UNDER_REVIEW\n"
        "---\n",
        encoding="utf-8",
    )
    bootstrap_project_ready(
        project, RL, extra_env={"RLR_HYPOTHESIS_STORE": str(store)}
    )
    _bind_round_data(project)
    return project, store, binding


def _advance_to_reviewed(project, hypothesis_id):
    """Commit L4-L9a so the active occurrence reaches REVIEWED status for L10b."""
    result_path = project / "04_Analysis_Outputs" / "result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"result":"fixture"}\n', encoding="utf-8")
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()

    commit_v2(project, "C1", "L4", "Fisher", {
        "schema_version": "2.1",
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hypothesis_id],
            "name": "method", "steps": ["measure"],
        }],
    })
    commit_v2(project, "C1", "L5", "Tukey", {
        "schema_version": "2.1",
        "attacks": [{
            "attack_id": "A1", "strategy_id": "S1",
            "hypothesis_ids": [hypothesis_id], "severity": "HIGH", "text": "fixture",
        }],
        "qc_checkpoints": [{
            "strategy_id": "S1", "hypothesis_ids": [hypothesis_id],
            "name": "QC", "criterion": "pass",
        }],
        "failure_stop_rules": [{
            "strategy_id": "S1", "hypothesis_ids": [hypothesis_id],
            "name": "Stop", "condition": "failure", "reason": "fixture",
        }],
    })
    commit_v2(project, "C1", "L6", "Oppenheimer", {
        "schema_version": "2.1",
        "analysis_plan": [{
            "strategy_id": "S1", "hypothesis_ids": [hypothesis_id],
            "scripts": [], "parameters": {}, "outputs": ["result.json"],
            "feasibility_assessment": {"verdict": "PASS", "evidence": "fixture"},
            "attack_resolutions": [{
                "attack_id": "A1", "verdict": "RESOLVED", "evidence": "fixture",
            }],
        }],
        "method_decision": "APPROVE", "reason": "ready",
    })
    l7 = commit_v2(project, "C1", "L7", "Turing", {
        "schema_version": "2.1",
        "results": [{
            "result_key": "r1", "hypothesis_ids": [hypothesis_id],
            "summary": "result",
            "artifact_refs": [{
                "path": "04_Analysis_Outputs/result.json", "sha256": result_sha,
            }],
        }],
        "scripts_run": [], "warnings": [], "failures": [],
    })
    evidence_id = l7.normalized_delta["results"][0]["evidence_id"]
    commit_v2(project, "C1", "L8", "Tukey", {
        "schema_version": "2.1",
        "evidence_assessments": [{
            "evidence_id": evidence_id, "verification": "VERIFIED",
            "relations": [{
                "hypothesis_id": hypothesis_id, "outcome": "INCONCLUSIVE",
                "reason": "weak",
            }],
        }],
    })
    commit_v2(project, "C1", "L9a", "Feynman", {
        "schema_version": "2.1",
        "assessments": [{
            "hypothesis_id": hypothesis_id,
            "epistemic_status": "INSUFFICIENT_EVIDENCE",
            "reason": "weak", "evidence_ids": [evidence_id],
        }],
    })


def _make_deep_research_l85(project, cand_id, run_label):
    """Persist a deep_research L8.5 artifact; return run_id + evidence IDs."""
    url = f"https://example.invalid/{cand_id}/L8.5/{run_label}"
    payload = {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": [f"synthetic L8.5 {run_label}"],
        "papers": [{
            "url": url,
            "title": f"Synthetic L8.5 {run_label}",
            "source_database": "synthetic-test",
            "source_metadata_response": {
                "candidate_id": cand_id, "node": "L8.5", "run_label": run_label,
            },
            "open_access": False,
            "extracts": [
                {"section": "Results", "text": f"Result {run_label}",
                 "locator": "Results 1"},
            ],
        }],
        "verification": [{
            "finding": f"finding {run_label}",
            "verdict": "supports",
            "evidence_ids": [url],
        }],
    }
    artifact = dr.persist_run(
        project, cand_id, "L8.5", payload,
        dr.skill_receipt("codex", ["codex", "exec"], "synthetic", "test"),
        result_context=f'{{"synthetic":"{run_label}"}}',
        project_id="P1", round_id="1", profile_id=PROFILE_V21_CATALOG_1,
        research_persona="Curie",
    )
    evidence_ids = [
        eid
        for paper in artifact.get("papers", [])
        for eid in paper.get("evidence_ids", [])
    ]
    return artifact["run_id"], evidence_ids


def _make_native_l85(project, cand_id, run_id, evidence_ids):
    """Persist a native L8.5 run manifest matching the deep_research run_id."""
    located = []
    for index, eid in enumerate(evidence_ids):
        snapshot = (
            project / "08_Audit" / "l85_snapshots" / f"{run_id}_{index}.txt"
        )
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(eid.encode("utf-8"))
        located.append({
            "evidence_id": eid,
            "verification_status": "LOCATED",
            "locator": "char:0:10",
            "text": f"evidence for {eid}",
            "retrieval": {
                "engine": "test",
                "source_sha256": _sha256(eid),
                "snapshot_path": snapshot.relative_to(project).as_posix(),
            },
        })
    payload = {
        "research_seed": {},
        "query_plan": {"plan_id": "qp1", "queries": []},
        "discovery": {},
        "selected_paper_ids": [],
        "source_snapshots": [],
        "located_evidence": located,
        "semantic_verifications": [],
        "findings": [{
            "finding_id": "f1", "text": "test finding", "sources": ["L7"],
        }],
        "verdicts": [{
            "finding_id": "f1", "verdict": "supports",
            "evidence_ids": evidence_ids, "reason": "test",
        }],
    }
    return l85.persist_run_manifest(project, cand_id, run_id=run_id, payload=payload)


def _l85_delta(run_id, evidence_ids, hypothesis_id):
    """A committed-shaped L8.5 delta naming the canonical native run_id."""
    return {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": run_id,
        "deep_research_receipt_hash": "0" * 64,
        "evidence_assessments": [{
            "evidence_id": evidence_ids[0],
            "verification": "VERIFIED",
            "relations": [{
                "hypothesis_id": hypothesis_id,
                "outcome": "SUPPORTS",
                "reason": "test",
            }],
        }],
        "assessments": [{
            "hypothesis_id": hypothesis_id,
            "outcome": "SUPPORTS",
            "comparison": "test",
            "evidence_ids": evidence_ids,
        }],
        "summary": "test summary",
    }


def _assemble_args(project, store, node):
    return SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        node=node,
        authorization_id=None,
        knowledge_store=str(store),
        template_mode="contract",
        pre_research_mode="none",
        pre_research_token_budget=None,
        context_token_budget=12000,
        evidence_run_id=None,
    )


def _latest_manifest(project, node):
    manifest_path = sorted(
        (project / "08_Audit").glob(f"context_manifest_{node}_*.json")
    )[-1]
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))


def _provider_boundary(project, manifest_path, delta_path, node, persona):
    """Build a RunReceipt bound to the real ContextManifest."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    rendered = Path(manifest["rendered_context_path"])
    rendered_hash = str(manifest["rendered_context_sha256"])
    audit = project / "08_Audit" / "test_provider_receipts"
    audit.mkdir(parents=True, exist_ok=True)
    prompt = audit / f"C1_{node}_prompt.txt"
    prompt.write_bytes(rendered.read_bytes())
    receipt_path = audit / f"C1_{node}_provider_receipt.json"
    RunReceipt(
        node=node,
        persona=persona,
        provider="synthetic-native-boundary",
        timestamp="2026-09-20T00:00:00Z",
        context_hash=rendered_hash,
        project_id=str(manifest["project_id"]),
        candidate_id="C1",
        round_id=str(manifest["round_id"]),
        profile_id=str(manifest["profile_id"]),
        context_manifest_path=str(manifest_path),
        context_manifest_hash=hashlib.sha256(
            Path(manifest_path).read_bytes()
        ).hexdigest(),
        rendered_context_path=str(rendered),
        rendered_context_hash=rendered_hash,
        prompt_file=str(prompt),
        prompt_hash=hashlib.sha256(prompt.read_bytes()).hexdigest(),
        provider_delta_path=str(delta_path),
        provider_delta_hash=hashlib.sha256(delta_path.read_bytes()).hexdigest(),
    ).write(receipt_path)
    return receipt_path


def _l10b_delta(evidence_ids, hypothesis_id):
    return {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "decision": "KEEP",
        "reason": "test reason",
        "next_steps": ["step1"],
        "hypothesis_decisions": [{
            "hypothesis_id": hypothesis_id,
            "disposition": "RETAIN",
            "reason": "test",
        }],
        "literature_evidence_ids": evidence_ids,
    }


def _emit_l10b(project, store, manifest_path, receipt_path, delta_path):
    return engine_main([
        "emit-delta", str(project), "C1", "--node", "L10b", "--persona", "Oppenheimer",
        "--file", str(delta_path),
        "--knowledge-store", str(store),
        "--context-manifest", str(manifest_path),
        "--provider-receipt", str(receipt_path),
    ])


def _inject_l85_delta(project, run_id, evidence_ids, hypothesis_id):
    """Write the L8.5 delta file and patch every _delta_for_candidate lookup
    site the assembler holds: the module attribute in research_loop.delta (used
    by the in-function import in context.py) and the module-level binding
    imported into research_loop.context."""
    audit = project / "08_Audit"
    audit.mkdir(parents=True, exist_ok=True)
    delta_path = audit / "C1_L8.5_curie_delta.v2.json"
    delta_path.write_text(
        json.dumps(_l85_delta(run_id, evidence_ids, hypothesis_id)), encoding="utf-8"
    )

    original = delta_mod._delta_for_candidate

    def _resolver(project_dir, delta_key, cand_id):
        if delta_key == "L8.5_curie":
            return delta_path
        return original(project_dir, delta_key, cand_id)

    patches = ExitStack()
    patches.enter_context(patch.object(delta_mod, "_delta_for_candidate", _resolver))
    patches.enter_context(patch.object(context_mod, "_delta_for_candidate", _resolver))
    return patches


# -----------------------------------------------------------------------------
# Positive: canonical A is frozen and consumed, newer B is never selected
# -----------------------------------------------------------------------------


def test_l85_exact_authority_crosses_context_ledger_gate(tmp_path, monkeypatch, capsys):
    """Full production path: delta A → context manifest → ledger → gate.

    Two deep_research L8.5 artifacts exist (A older, B newer by mtime).
    Two native L8.5 manifests exist with matching run_ids.
    The L8.5 delta names A as canonical.

    L10b context assembly must freeze A, the ledger must pass A's evidence
    IDs to the gate, and the gate must accept only A's evidence.
    """
    project, store, binding = _native_project(tmp_path, monkeypatch)
    hypothesis_id = seed_selected_hypothesis(project, "C1")
    _advance_to_reviewed(project, hypothesis_id)

    # Two L8.5 runs; A is canonical, B will have newer mtime.
    run_a, ev_a = _make_deep_research_l85(project, "C1", "runA")
    _make_native_l85(project, "C1", run_a, ev_a)

    run_b, ev_b = _make_deep_research_l85(project, "C1", "runB")
    _make_native_l85(project, "C1", run_b, ev_b)

    time.sleep(0.05)
    run_b_file = (
        project / "09_Literature_Database" / "evidence_packs" / "runs"
        / f"C1_L8_5_{run_b}.json"
    )
    run_b_file.touch()
    native_b_file = (
        project / "08_Audit" / "l85_literature_verification" / "C1"
        / f"{run_b}.json"
    )
    native_b_file.touch()

    # Inject the canonical L8.5 delta naming A.
    patcher = _inject_l85_delta(project, run_a, ev_a, hypothesis_id)
    with patcher:
        # Assemble L10b context: must resolve native A by exact run_id.
        assert cmd_assemble_context(_assemble_args(project, store, "L10b")) == 0

    l10b_manifest_path, l10b_manifest = _latest_manifest(project, "L10b")
    frozen = l10b_manifest.get("native_l85_evidence")
    assert frozen is not None, "ContextManifest must freeze native L8.5 authority"
    assert frozen["run_id"] == run_a, (
        f"expected canonical run {run_a}, got {frozen['run_id']}"
    )
    assert frozen["evidence_ids"] == ev_a

    # Ledger path: emit L10b delta citing A's evidence.
    l10b_delta_path = tmp_path / "L10b_Oppenheimer_delta.json"
    l10b_delta_path.write_text(
        json.dumps(_l10b_delta(ev_a, hypothesis_id)), encoding="utf-8"
    )
    l10b_receipt_path = _provider_boundary(
        project, l10b_manifest_path, l10b_delta_path, "L10b", "Oppenheimer"
    )
    rc = _emit_l10b(project, store, l10b_manifest_path, l10b_receipt_path, l10b_delta_path)
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "DELTA V2 VALIDATION: PASS" in captured.out

    # Proof that mtime-fallback B was never selected: citing B's evidence now
    # must fail, because the gate consumed the frozen A authority.
    bad_delta_path = tmp_path / "L10b_Oppenheimer_delta_bad.json"
    bad_delta_path.write_text(
        json.dumps(_l10b_delta(ev_b, hypothesis_id)), encoding="utf-8"
    )
    bad_receipt_path = _provider_boundary(
        project, l10b_manifest_path, bad_delta_path, "L10b", "Oppenheimer"
    )
    rc = _emit_l10b(project, store, l10b_manifest_path, bad_receipt_path, bad_delta_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert "L10b references unknown evidence IDs" in captured.err


# -----------------------------------------------------------------------------
# Negative: frozen authority rejects evidence outside the frozen set
# -----------------------------------------------------------------------------


def test_l85_frozen_authority_rejects_unknown_evidence(tmp_path, monkeypatch, capsys):
    """Gate validates only the exact frozen evidence IDs from ContextManifest.

    Even if a different evidence ID exists in some other run (or is fabricated),
    the L10b gate must reject it because it is not in the frozen authority.
    """
    project, store, binding = _native_project(tmp_path, monkeypatch)
    hypothesis_id = seed_selected_hypothesis(project, "C1")
    _advance_to_reviewed(project, hypothesis_id)

    run_a, ev_a = _make_deep_research_l85(project, "C1", "runA")
    _make_native_l85(project, "C1", run_a, ev_a)

    # Inject the canonical L8.5 delta naming A.
    patcher = _inject_l85_delta(project, run_a, ev_a, hypothesis_id)
    with patcher:
        assert cmd_assemble_context(_assemble_args(project, store, "L10b")) == 0

    l10b_manifest_path, l10b_manifest = _latest_manifest(project, "L10b")
    frozen = l10b_manifest["native_l85_evidence"]
    assert frozen["run_id"] == run_a

    # L10b delta cites an ID that is not in the frozen authority.
    bad_evidence_ids = ["ev_not_in_frozen_authority"]
    l10b_delta_path = tmp_path / "L10b_Oppenheimer_delta_unknown.json"
    l10b_delta_path.write_text(
        json.dumps(_l10b_delta(bad_evidence_ids, hypothesis_id)), encoding="utf-8"
    )
    l10b_receipt_path = _provider_boundary(
        project, l10b_manifest_path, l10b_delta_path, "L10b", "Oppenheimer"
    )
    rc = _emit_l10b(project, store, l10b_manifest_path, l10b_receipt_path, l10b_delta_path)
    captured = capsys.readouterr()
    assert rc != 0
    assert "L10b references unknown evidence IDs" in captured.err
