import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p


def _schema_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _schema_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schema_keys(child)


def _asset(
    *,
    asset_id="A1",
    doi="10.1000/example",
    pmid="",
    url="https://example.org/paper",
    title="Example method paper",
    year=2026,
    relevance_score=8.0,
    selection_status="selected",
):
    return {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "title": title,
        "year": year,
        "journal": "Methods Journal",
        "abstract": "A metadata-only abstract.",
        "source_database": "Europe PMC",
        "source_metadata_response": {"id": asset_id, "title": title},
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": [url],
        "relevance_score": relevance_score,
        "selection_status": selection_status,
        "selection_reason": "Matches the required analysis component.",
        "hypothesis_ids": ["H1"],
        "method_component_hints": ["differential_expression"],
        "diagnostic_requirements": ["interaction test"],
    }


def _discovery_payload(*assets):
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "interaction model transcriptome method",
            "purpose": "Find implementation evidence.",
            "status": "completed",
            "receipt": "Europe PMC query receipt",
        }],
        "assets": list(assets),
    }


def _receipt():
    return dr.skill_receipt(
        "codex", ["codex", "exec"], "discovery prompt", "test"
    )


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


def test_l4a_deduplication_prefers_higher_relevance_for_normalized_doi():
    lower = _asset(
        asset_id="LOW",
        doi="https://doi.org/10.1000/EXAMPLE",
        relevance_score=4.0,
        selection_status="reserve",
    )
    higher = _asset(asset_id="HIGH", relevance_score=9.0)

    kept, duplicates = l4p.deduplicate_l4a_assets([lower, higher])

    assert [item["asset_id"] for item in kept] == ["HIGH"]
    assert duplicates == [{
        "identity": "doi:10.1000/example",
        "kept_asset_id": "HIGH",
        "duplicate_asset_id": "LOW",
        "reason": "lower_relevance_score",
    }]


def test_l4a_persistence_is_hash_bound_and_project_relative(tmp_path):
    project = tmp_path / "project"
    payload = _discovery_payload(_asset())

    artifact = l4p.persist_l4a_discovery(
        project,
        "C1",
        payload,
        _receipt(),
        question="Which interaction model should be used?",
        claim="H1 predicts a species by region interaction.",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )

    manifest_path = project / artifact["path"]
    assert artifact["schema_version"] == l4p.L4A_DISCOVERY_SCHEMA_VERSION
    assert artifact["pipeline_schema"] == l4p.PIPELINE_SCHEMA_VERSION
    assert artifact["pipeline_stage"] == "L4A"
    assert artifact["selected_asset_ids"] == ["A1"]
    assert not Path(artifact["path"]).is_absolute()
    assert manifest_path.is_file()
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == artifact
    assert l4p.validate_l4a_manifest(project, artifact) == (True, "")


def test_l4a_zero_selection_persists_then_fails_closed(tmp_path):
    project = tmp_path / "project"
    payload = _discovery_payload(
        _asset(asset_id="R1", selection_status="rejected")
    )

    artifact = l4p.persist_l4a_discovery(
        project, "C1", payload, _receipt(), question="Q", claim="H"
    )

    assert (project / artifact["path"]).is_file()
    assert artifact["selected_asset_ids"] == []
    with pytest.raises(dr.DeepResearchError, match="no selected literature assets"):
        l4p.selected_l4a_assets(artifact, require=True)
