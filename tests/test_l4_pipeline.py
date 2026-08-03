import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import l4_pipeline as l4p


def _schema_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _schema_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schema_keys(child)


def test_l4a_discovery_schema_is_strict_metadata_only():
    schema = l4p.l4a_discovery_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert {"schema_version", "queries", "assets"}.issubset(schema["required"])

    asset = schema["properties"]["assets"]["items"]
    assert asset["additionalProperties"] is False
    assert {
        "doi",
        "pmid",
        "url",
        "title",
        "source_database",
        "source_metadata_response",
        "open_access_status",
        "full_text_status",
        "relevance_score",
        "selection_status",
        "selection_reason",
    }.issubset(asset["required"])

    forbidden = {
        "source_payload",
        "extracts",
        "method_components",
        "method_candidates",
        "method_anchors",
    }
    assert forbidden.isdisjoint(set(_schema_keys(schema)))


def test_l4_pipeline_declares_ordered_stage_identities():
    stages = l4p.L4_PIPELINE_STAGES

    assert tuple(stage["stage_id"] for stage in stages) == (
        "L4A",
        "L4B",
        "L4C",
        "L4.5",
    )
    assert stages[0]["responsibility"] == "literature_discovery"
    assert stages[1]["responsibility"] == "evidence_construction"
    assert stages[2]["storage_key"] == "L4_fisher"
    assert stages[2]["cognitive"] is True
    assert stages[3]["responsibility"] == "deterministic_commit"
    assert stages[3]["cognitive"] is False
