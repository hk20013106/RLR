import json

import pytest

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p


def _payload():
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [
            {
                "query_id": "Q1",
                "query": "method",
                "purpose": "Find evidence.",
                "status": "completed",
                "receipt": "receipt",
            }
        ],
        "assets": [
            {
                "asset_id": "A1",
                "doi": "10.1000/example",
                "pmid": "",
                "url": "https://example.org/paper",
                "title": "Example paper",
                "year": 2026,
                "role": "method",
                "journal": "Methods",
                "abstract": "Metadata only.",
                "source_database": "Europe PMC",
                "source_metadata_response": json.dumps({"id": "A1"}),
                "open_access_status": "open",
                "full_text_status": "available_oa",
                "full_text_locations": ["https://example.org/paper"],
                "relevance_score": 9.0,
                "selection_status": "selected",
                "selection_reason": "Relevant.",
                "hypothesis_ids": ["H1"],
                "method_component_hints": ["model"],
                "diagnostic_requirements": ["test"],
            }
        ],
    }


def test_l4a_rejects_path_like_candidate_before_writing(tmp_path):
    project = tmp_path / "project"
    escaped = tmp_path / "escape_marker"

    with pytest.raises(dr.DeepResearchError, match="candidate_id"):
        l4p.persist_l4a_discovery(
            project,
            "../../../escape_marker",
            _payload(),
            dr.skill_receipt("codex", ["codex"], "prompt", "test"),
            question="Q",
            claim="H",
        )

    assert not escaped.exists()
