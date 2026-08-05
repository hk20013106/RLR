import hashlib
import json
from pathlib import Path

import pytest

from research_loop import deep_research as dr
from research_loop import l4_inventory
from research_loop import l4_method_registry as registry
from research_loop import l4_pipeline as l4p


def _deep_research_payload(source_payload: str, content_type: str) -> dict:
    extracts = [
        ("Results", "Observed result.", "Results paragraph 1"),
        ("Discussion", "Interpreted result.", "Discussion paragraph 1"),
        ("Conclusion", "Concluding result.", "Conclusion paragraph 1"),
        ("Materials and methods", "Method details for the retained source.", "Methods paragraph 1"),
    ]
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["fixture query"],
        "papers": [{
            "doi": "10.1000/source-bytes",
            "pmid": "12345678",
            "url": "https://example.org/source-bytes",
            "title": "Source byte fixture",
            "source_database": "fixture",
            "metadata": {"year": 2026, "journal": "Fixture"},
            "source_metadata_response": {
                "id": "12345678",
                "title": "Source byte fixture",
            },
            "open_access": True,
            "content_type": content_type,
            "source_payload": source_payload,
            "paper_type": "primary",
            "extracts": [{
                "section": section,
                "text": text,
                "locator": locator,
                "extraction_method": "fixture",
                "verification_status": "located",
            } for section, text, locator in extracts],
        }],
        "review_search": {
            "query": "fixture review",
            "status": "none_found",
            "receipt": "fixture 0",
        },
        "verification": [],
    }


def test_source_payload_is_persisted_as_exact_utf8_bytes(monkeypatch, tmp_path):
    source_payload = "<article>\n<section>alpha</section>\n</article>\n"
    expected = source_payload.encode("utf-8")
    original_write_text = Path.write_text

    def windows_style_write_text(path, data, *args, **kwargs):
        normalized = str(path).replace("\\", "/")
        if "/evidence_packs/sources/" in normalized:
            data = data.replace("\n", "\r\n")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", windows_style_write_text)
    artifact = dr.persist_run(
        tmp_path,
        "C1",
        "L1",
        _deep_research_payload(source_payload, "application/xml; type=jats"),
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "fixture"),
    )

    paper_path = tmp_path / artifact["papers"][0]["path"]
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    source_path = tmp_path / paper["source_payload_path"]
    actual = source_path.read_bytes()
    expected_hash = hashlib.sha256(expected).hexdigest()

    assert source_path.suffix == ".xml"
    assert actual == expected
    assert paper["content_hash"] == expected_hash
    assert {item["source_hash"] for item in paper["evidence_extracts"]} == {
        expected_hash
    }
    assert hashlib.sha256(actual).hexdigest() == expected_hash


def _asset(asset_id: str, *, doi: str, pmid: str, title: str) -> dict:
    return {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": pmid,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "title": title,
        "year": 2014 if asset_id == "A1" else 2007,
        "role": "method",
        "journal": "Fixture",
        "abstract": "metadata",
        "source_database": "PubMed",
        "source_metadata_response": json.dumps(
            {"id": pmid, "title": title},
            sort_keys=True,
            separators=(",", ":"),
        ),
        "open_access_status": "unknown",
        "full_text_status": "metadata_only",
        "full_text_locations": [],
        "relevance_score": 9.0,
        "selection_status": "selected",
        "selection_reason": "Exact linked source.",
        "hypothesis_ids": ["H1"],
        "method_component_hints": [],
        "diagnostic_requirements": [],
    }


def _method(method_id: str, name: str, asset_id: str) -> dict:
    return {
        "method_id": method_id,
        "name": name,
        "purpose": "Resolve an implementation source.",
        "inventory_reason": "Required by the selected hypothesis.",
        "source_asset_ids": [asset_id],
        "source_hints": [],
    }


def _inventory_payload() -> dict:
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "method source metadata",
            "purpose": "Resolve exact method sources.",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": [
            _asset(
                "A1",
                doi="10.1186/s13059-014-0550-8",
                pmid="25516281",
                title="Moderated estimation with DESeq2",
            ),
            _asset(
                "A2",
                doi="10.1371/journal.pgen.0030161",
                pmid="17907809",
                title="Surrogate variable analysis",
            ),
        ],
        "method_inventory": [
            _method(
                "differential_expression_model",
                "negative-binomial differential-expression model",
                "A1",
            ),
            _method(
                "latent_factor_adjustment",
                "latent-factor adjustment",
                "A2",
            ),
        ],
    }


def test_linked_exact_assets_close_registry_matches_and_manifest_metadata(tmp_path):
    artifact = l4_inventory.persist_discovery(
        l4p,
        dr,
        tmp_path,
        "C1",
        _inventory_payload(),
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "fixture"),
        question="Which methods test H1?",
        claim="H1 predicts differential expression.",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )

    matches = artifact["runtime_receipt"]["method_source_registry"]["matches"]
    assert matches == [
        {
            "method_id": "differential_expression_model",
            "canonical_method_ids": ["deseq2"],
        },
        {
            "method_id": "latent_factor_adjustment",
            "canonical_method_ids": ["sva"],
        },
    ]

    assets = {asset["asset_id"]: asset for asset in artifact["assets"]}
    a1 = assets["A1"]
    assert a1["doi"] == "10.1186/s13059-014-0550-8"
    assert a1["pmid"] == "25516281"
    assert a1["source_metadata_response"]["pmcid"] == "PMC4302049"
    assert "deseq2-love-2014" in a1["source_metadata_response"][
        "method_source_ref_ids"
    ]
    assert a1["open_access_status"] == "open"
    assert a1["full_text_status"] == "available_oa"
    assert (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"
        in a1["full_text_locations"]
    )

    a2 = assets["A2"]
    assert a2["source_metadata_response"]["pmcid"] == "PMC1994707"
    assert a2["full_text_status"] == "available_oa"


def _source_hint(*, doi: str, pmid: str, pmcid: str = "") -> dict:
    return {
        "source_ref_id": "linked-source",
        "title": "Linked exact source",
        "year": 2014,
        "doi": doi,
        "pmid": pmid,
        "pmcid": pmcid,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "source_kind": "method_paper",
        "rationale": "Linked exact identifier.",
        "full_text_locations": [],
    }


def test_registry_matches_generic_method_by_existing_exact_hint(tmp_path):
    method = _method("generic_model", "generic model", "A1")
    method["source_asset_ids"] = []
    method["source_hints"] = [_source_hint(
        doi="10.1186/s13059-014-0550-8",
        pmid="25516281",
    )]

    inventory, receipt = registry.apply_registry(tmp_path, [method])

    assert receipt["matches"] == [{
        "method_id": "generic_model",
        "canonical_method_ids": ["deseq2"],
    }]
    assert any(hint["pmcid"] == "PMC4302049" for hint in inventory[0]["source_hints"])


def test_registry_matches_generic_method_by_linked_asset_identifiers(tmp_path):
    method = _method("generic_model", "generic model", "A1")
    asset = _asset(
        "A1",
        doi="10.1186/s13059-014-0550-8",
        pmid="25516281",
        title="Moderated estimation with DESeq2",
    )

    _, receipt = registry.apply_registry(tmp_path, [method], assets=[asset])

    assert receipt["matches"] == [{
        "method_id": "generic_model",
        "canonical_method_ids": ["deseq2"],
    }]


def test_registry_does_not_match_unrelated_exact_source(tmp_path):
    method = _method("generic_model", "generic model", "")
    method["source_asset_ids"] = []
    method["source_hints"] = [_source_hint(
        doi="10.1000/unrelated",
        pmid="99999999",
    )]

    inventory, receipt = registry.apply_registry(tmp_path, [method])

    assert receipt["matches"] == []
    assert inventory[0]["source_hints"] == method["source_hints"]


def test_registry_fails_closed_on_partially_matching_identifier_conflict(tmp_path):
    method = _method("generic_model", "generic model", "")
    method["source_asset_ids"] = []
    method["source_hints"] = [_source_hint(
        doi="10.1186/s13059-014-0550-8",
        pmid="99999999",
    )]

    with pytest.raises(registry.MethodRegistryError, match="PMID.*conflict"):
        registry.apply_registry(tmp_path, [method])
