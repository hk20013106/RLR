import json

import pytest

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p


def _manifest(project):
    payload = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "method",
            "purpose": "find method evidence",
            "status": "completed",
            "receipt": "receipt",
        }],
        "assets": [{
            "asset_id": "A1",
            "doi": "10.1000/example",
            "pmid": "",
            "url": "https://example.org/paper",
            "title": "Method paper",
            "year": 2026,
            "journal": "Methods",
            "abstract": "metadata",
            "source_database": "Europe PMC",
            "source_metadata_response": {"id": "A1"},
            "open_access_status": "open",
            "full_text_status": "available_oa",
            "full_text_locations": ["https://example.org/paper"],
            "relevance_score": 9,
            "selection_status": "selected",
            "selection_reason": "relevant",
            "hypothesis_ids": ["H1"],
            "method_component_hints": ["model"],
            "diagnostic_requirements": ["interaction"],
        }],
    }
    receipt = dr.skill_receipt("codex", ["codex"], "prompt", "test")
    return l4p.persist_l4a_discovery(
        project, "C1", payload, receipt, question="Q", claim="H"
    )


def test_l45_rejects_evidence_manifest_changed_since_context(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path)
    evidence = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
        "node": "L4",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "method_components": [],
        "method_candidates": [],
        "method_anchors": [],
    }
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({"schema_version": "2.1"}), encoding="utf-8")
    expected = {
        "run_id": "RUN2",
        "files": [{"kind": "run", "path": "run.json", "sha256": "old"}],
    }
    current = {
        "run_id": "RUN2",
        "files": [{"kind": "run", "path": "run.json", "sha256": "new"}],
    }

    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(dr, "evidence_artifact_manifest", lambda *a, **k: current)

    with pytest.raises(
        dr.DeepResearchError, match="changed since context assembly"
    ):
        l4p.commit_l45_method_projection(
            tmp_path,
            "C1",
            evidence,
            delta,
            expected_evidence_manifest=expected,
        )
