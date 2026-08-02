import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import deep_research as dr


def test_navigation_only_l4_run_persists_precise_user_source_blocker(tmp_path):
    payload = {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["paywalled comparative transcriptome method"],
        "method_components": [{
            "component_id": "cross_species_model",
            "name": "Cross-species model",
            "required": True,
            "rationale": "Tests the selected comparative hypothesis.",
        }],
        "method_candidates": [{
            "method_id": "published_model",
            "component_id": "cross_species_model",
            "name": "Published comparative model",
            "status": "needs_user_source",
            "purpose": "Fit the cross-species comparison.",
            "applicable_to": ["ortholog expression matrix"],
            "implementation_steps": ["obtain full Methods", "reconstruct model"],
            "assumptions": ["full method can be verified"],
            "expected_outputs": ["species effects"],
            "strengths": ["directly relevant study design"],
            "limitations": ["Methods are paywalled"],
            "alternatives": ["official software workflow"],
            "rejection_reasons": [],
            "method_anchor_ids": [],
            "missing_source": "Provide the legally obtained primary-study PDF.",
        }],
        "papers": [{
            "doi": "10.1000/paywalled",
            "pmid": "12345678",
            "url": "https://example.org/paywalled",
            "title": "Relevant paywalled primary study",
            "source_database": "PubMed",
            "metadata": {},
            "source_metadata_response": {"id": "12345678"},
            "open_access": False,
            "content_type": "text/plain",
            "source_payload": "",
            "paper_type": "primary study",
            "user_source_id": "",
            "user_source_sha256": "",
            "extracts": [{
                "section": "Abstract",
                "text": "The study compared transcriptomes across species.",
                "locator": "PubMed abstract",
                "extraction_method": "source-located",
                "verification_status": "located",
            }],
        }],
        "review_search": {
            "query": "comparative transcriptome review",
            "status": "none_found",
            "receipt": "Europe PMC 0",
        },
        "verification": [],
    }
    project = tmp_path / "P"
    artifact = dr.persist_run(
        project,
        "C1",
        "L4",
        payload,
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test"),
    )

    assert artifact["method_anchors"] == []
    ok, reason = dr.audit_evidence_pack(
        project, "C1", "L4", run_id=artifact["run_id"]
    )
    assert ok is False
    assert "cross_species_model" in reason
    assert "user-supplied source" in reason
    summary = (project / artifact["summary_path"]).read_text(encoding="utf-8")
    assert "python scripts/import_literature_pdf.py" in summary
    assert "registration alone does not satisfy l4" in summary.casefold()
