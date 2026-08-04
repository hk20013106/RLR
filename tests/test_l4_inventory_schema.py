import json

from research_loop import deep_research as dr
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p


def test_inventory_wire_schema_omits_unsupported_unique_items():
    schema = l4_inventory.discovery_schema(l4p)

    def walk(value):
        if isinstance(value, dict):
            if "uniqueItems" in value:
                yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    assert list(walk(schema)) == []


def _payload():
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "DESeq2 method paper",
            "purpose": "Resolve the canonical source.",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": [{
            "asset_id": "A1",
            "doi": "10.1186/s13059-014-0550-8",
            "pmid": "25516281",
            "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
            "title": "Moderated estimation with DESeq2",
            "year": 2014,
            "role": "method",
            "journal": "Genome Biology",
            "abstract": "metadata",
            "source_database": "PubMed",
            "source_metadata_response": json.dumps(
                {"pmcid": "PMC4302049"}, sort_keys=True, separators=(",", ":")
            ),
            "open_access_status": "open",
            "full_text_status": "available_oa",
            "full_text_locations": [
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"
            ],
            "relevance_score": 10.0,
            "selection_status": "selected",
            "selection_reason": "Canonical source.",
            "hypothesis_ids": ["H1"],
            "method_component_hints": ["deseq2"],
            "diagnostic_requirements": [],
        }],
        "method_inventory": [{
            "method_id": "deseq2",
            "name": "DESeq2",
            "purpose": "Differential-expression modelling.",
            "inventory_reason": "Required by H1.",
            "source_asset_ids": ["A1"],
            "source_hints": [],
        }],
    }


def test_inventory_manifest_identical_retry_is_idempotent(tmp_path):
    receipt = dr.skill_receipt(
        "codex", ["codex", "exec"], "prompt", "fixture"
    )
    kwargs = {
        "question": "Which method tests H1?",
        "claim": "H1 predicts differential expression.",
        "project_id": "P1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
    }

    first = l4_inventory.persist_discovery(
        l4p, dr, tmp_path, "C1", _payload(), receipt, **kwargs
    )
    second = l4_inventory.persist_discovery(
        l4p, dr, tmp_path, "C1", _payload(), receipt, **kwargs
    )

    assert second == first
    assert first["manifest_sha256"]
    assert len(list(tmp_path.glob(
        "09_Literature_Database/l4/discovery/manifests/*.json"
    ))) == 1
