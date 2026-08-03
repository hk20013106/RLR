from types import SimpleNamespace

from research_loop import deep_research as dr
from research_loop import l4_lineage
from research_loop import l4_pipeline as l4p


def _asset():
    return {
        "asset_id": "A1", "doi": "10.1000/example", "pmid": "",
        "url": "https://example.org/paper", "title": "Method paper",
        "year": 2026, "journal": "Methods", "abstract": "metadata",
        "source_database": "Europe PMC",
        "source_metadata_response": '{"id":"A1"}',
        "open_access_status": "open", "full_text_status": "available_oa",
        "full_text_locations": ["https://example.org/paper"],
        "relevance_score": 9, "selection_status": "selected",
        "selection_reason": "relevant", "hypothesis_ids": ["H1"],
        "method_component_hints": ["model"],
        "diagnostic_requirements": ["interaction"],
    }


def _manifest(project):
    receipt = dr.skill_receipt("codex", ["codex"], "prompt", "test")
    return l4p.persist_l4a_discovery(
        project, "C1",
        {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "queries": [{
                "query_id": "Q1", "query": "model", "purpose": "method",
                "status": "completed", "receipt": "receipt",
            }],
            "assets": [_asset()],
        },
        receipt,
        question="Q", claim="H",
    )


def _module(artifact):
    return SimpleNamespace(
        _artifact=lambda *a, **k: artifact,
        audit_evidence_pack=lambda *a, **k: (True, ""),
        evidence_artifact_manifest=lambda *a, **k: {
            "run_id": "RUN2", "files": [{"kind": "run", "path": "run.json", "sha256": "runhash"}]
        },
    )


def test_staged_l4_audit_revalidates_l4a_manifest(tmp_path):
    manifest = _manifest(tmp_path)
    artifact = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B", "run_id": "RUN2",
        "candidate_id": "C1",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
    }
    module = _module(artifact)
    l4_lineage.install(module)

    assert module.audit_evidence_pack(tmp_path, "C1", "L4", run_id="RUN2") == (True, "")

    (tmp_path / manifest["path"]).write_text("{}", encoding="utf-8")
    ok, reason = module.audit_evidence_pack(tmp_path, "C1", "L4", run_id="RUN2")
    assert ok is False
    assert "L4A manifest" in reason


def test_staged_evidence_manifest_includes_exact_l4a_file(tmp_path):
    manifest = _manifest(tmp_path)
    artifact = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B", "run_id": "RUN2",
        "candidate_id": "C1",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
    }
    module = _module(artifact)
    l4_lineage.install(module)

    result = module.evidence_artifact_manifest(tmp_path, "C1", "L4", "RUN2")
    discovery = [item for item in result["files"] if item["kind"] == "l4a_discovery"]

    assert len(discovery) == 1
    assert discovery[0]["path"] == manifest["path"]
    expected = l4p._sha256_bytes((tmp_path / manifest["path"]).read_bytes())
    assert discovery[0]["sha256"] == expected
