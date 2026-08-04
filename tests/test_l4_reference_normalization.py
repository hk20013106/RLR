import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import deep_research as dr


def _source_text(extract: str) -> str:
    return (
        "<article><section><h2>Methods</h2><p>"
        + extract
        + "</p>"
        + "<p>Detailed reproducible procedure and parameter rationale. " * 20
        + "</p></section></article>"
    )


def _candidate(method_id: str, component_id: str, anchor_id: str) -> dict:
    return {
        "method_id": method_id,
        "component_id": component_id,
        "name": method_id,
        "status": "eligible",
        "purpose": f"Implement {component_id}.",
        "applicable_to": ["validated input data"],
        "implementation_steps": ["run the documented procedure"],
        "assumptions": [],
        "expected_outputs": ["validated result"],
        "strengths": [],
        "limitations": [],
        "alternatives": [],
        "rejection_reasons": [],
        "method_anchor_ids": [anchor_id],
        "missing_source": "",
    }


def _payload() -> dict:
    extract = "Apply the documented two-stage workflow and retain diagnostic outputs."
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["two-stage method workflow"],
        "method_components": [
            {
                "component_id": "component_a",
                "name": "Stage A",
                "required": True,
                "rationale": "Prepares the input.",
            },
            {
                "component_id": "component_b",
                "name": "Stage B",
                "required": True,
                "rationale": "Produces the final estimate.",
            },
        ],
        "method_candidates": [
            _candidate("method_a", "component_a", "anchor_1"),
            _candidate("method_b", "component_b", "anchor_1"),
        ],
        "papers": [
            {
                "doi": "10.1000/two-stage",
                "pmid": "",
                "url": "https://example.org/two-stage",
                "title": "Two-stage workflow",
                "source_database": "official",
                "metadata": {"year": 2026},
                "source_metadata_response": {"id": "two-stage"},
                "open_access": True,
                "content_type": "text/html",
                "source_payload": _source_text(extract),
                "paper_type": "method",
                "user_source_id": "",
                "user_source_sha256": "",
                "extracts": [
                    {
                        "anchor_id": "anchor_1",
                        "section": "Workflow",
                        "text": extract,
                        "locator": "Workflow paragraph 1",
                        "extraction_method": "source-located",
                        "verification_status": "located",
                        # Synthetic regression fixture derived from the exact
                        # real-pilot validator path: both method IDs are explicit,
                        # but the redundant component list omits method_b's component.
                        "method_component_ids": ["component_a"],
                        "method_ids": ["method_a", "method_b"],
                        "source_kind": "official_documentation",
                    }
                ],
            }
        ],
        "review_search": {
            "query": "two-stage workflow review",
            "status": "none_found",
            "receipt": "Europe PMC 0",
        },
        "verification": [],
    }


def _receipt() -> dict:
    return dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test")


def test_l4_canonicalizes_redundant_component_refs_from_explicit_method_refs(tmp_path):
    project = tmp_path / "project"

    artifact = dr.persist_run(project, "C1", "L4", _payload(), _receipt())

    assert artifact["method_anchors"][0]["method_ids"] == ["method_a", "method_b"]
    assert artifact["method_anchors"][0]["method_component_ids"] == [
        "component_a",
        "component_b",
    ]
