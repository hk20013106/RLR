import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import deep_research as dr


def _source(extract: str) -> str:
    return (
        f"<article><p>{extract}</p>"
        + "substantive source context " * 40
        + "</article>"
    )


def _payload():
    method_text = "Fit a linear model with species, region, and interaction terms."
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["heart transcriptome comparative method review"],
        "method_components": [{
            "component_id": "de_model",
            "name": "Differential-expression model",
            "required": True,
            "rationale": "Tests the selected hypothesis.",
        }],
        "method_candidates": [{
            "method_id": "limma",
            "component_id": "de_model",
            "name": "limma",
            "status": "eligible",
            "purpose": "Estimate group effects.",
            "applicable_to": ["continuous expression"],
            "implementation_steps": ["fit design", "test contrasts"],
            "assumptions": ["valid design matrix"],
            "expected_outputs": ["effect estimates"],
            "strengths": ["complex designs"],
            "limitations": ["model dependent"],
            "alternatives": ["mixed model"],
            "rejection_reasons": [],
            "method_anchor_ids": ["A1"],
            "missing_source": "",
        }],
        "papers": [
            {
                "doi": "10.1000/method",
                "pmid": "",
                "url": "https://example.org/method",
                "title": "Method paper",
                "source_database": "Europe PMC",
                "metadata": {},
                "source_metadata_response": {"id": "method"},
                "open_access": True,
                "content_type": "text/html",
                "source_payload": _source(method_text),
                "paper_type": "method_paper",
                "user_source_id": "",
                "user_source_sha256": "",
                "extracts": [{
                    "anchor_id": "A1",
                    "section": "Model fitting",
                    "text": method_text,
                    "locator": "Model fitting paragraph 1",
                    "extraction_method": "source-located",
                    "verification_status": "located",
                    "method_component_ids": ["de_model"],
                    "method_ids": ["limma"],
                    "source_kind": "method_paper",
                }],
            },
            {
                "doi": "10.1000/primary",
                "pmid": "67890",
                "url": "https://example.org/primary",
                "title": "Relevant cardiovascular transcriptome study",
                "source_database": "PubMed",
                "metadata": {},
                "source_metadata_response": {"id": "67890"},
                "open_access": False,
                "content_type": "text/plain",
                "source_payload": "",
                "paper_type": "primary study",
                "user_source_id": "",
                "user_source_sha256": "",
                "extracts": [{
                    "section": "Results",
                    "text": "The study used a multi-region cardiovascular design.",
                    "locator": "Results paragraph 1",
                    "extraction_method": "source-located",
                    "verification_status": "located",
                }],
            },
            {
                "doi": "10.1000/review",
                "pmid": "12345",
                "url": "https://example.org/review",
                "title": "Review of transcriptome methods",
                "source_database": "PubMed",
                "metadata": {},
                "source_metadata_response": {"id": "12345"},
                "open_access": False,
                "content_type": "text/plain",
                "source_payload": "",
                "paper_type": "review",
                "user_source_id": "",
                "user_source_sha256": "",
                "extracts": [
                    {
                        "section": "Results",
                        "text": "The review compared model classes.",
                        "locator": "Results paragraph 2",
                        "extraction_method": "source-located",
                        "verification_status": "located",
                    },
                    {
                        "section": "Conclusion",
                        "text": "Complex designs require explicit contrasts.",
                        "locator": "Conclusion paragraph 1",
                        "extraction_method": "source-located",
                        "verification_status": "located",
                    },
                ],
            },
        ],
        "review_search": {
            "query": "transcriptome method review",
            "status": "relevant_review_located",
            "receipt": "PubMed PMID 12345",
        },
        "verification": [],
    }


def test_l4_schema_allows_navigation_extracts_without_anchor_fields():
    schema = dr._runtime_schema("L4")
    extract = schema["properties"]["papers"]["items"]["properties"][
        "extracts"
    ]["items"]
    assert "anchor_id" in extract["properties"]
    assert "anchor_id" not in extract["required"]


def test_structured_l4_keeps_navigation_but_does_not_count_it_as_anchor(tmp_path):
    project = tmp_path / "P"
    artifact = dr.persist_run(
        project,
        "C1",
        "L4",
        _payload(),
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test"),
    )

    assert artifact["review_search"]["status"] == "completed"
    assert (
        artifact["review_search"]["reported_status"]
        == "relevant_review_located"
    )
    assert len(artifact["papers"]) == 3
    assert [anchor["anchor_id"] for anchor in artifact["method_anchors"]] == [
        "A1"
    ]
    summary = (project / artifact["summary_path"]).read_text(encoding="utf-8")
    assert "Relevant cardiovascular transcriptome study" in summary
    assert "navigation only, not a method anchor" in summary
    assert dr.audit_evidence_pack(
        project, "C1", "L4", run_id=artifact["run_id"]
    ) == (True, "")
