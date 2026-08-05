import pytest

from research_loop import deep_research as dr
from research_loop import l4_closed_corpus
from research_loop import l4_inventory_projection as projection


def _asset():
    return {
        "asset_id": "A1",
        "doi": "10.1186/s13059-014-0550-8",
        "pmid": "25516281",
        "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
        "title": "DESeq2 method paper",
        "year": 2014,
        "source_metadata_response": {"source": "PubMed"},
        "full_text_locations": [
            "https://pubmed.ncbi.nlm.nih.gov/25516281/"
        ],
        "open_access_status": "unknown",
        "full_text_status": "metadata_only",
        "inventory_method_ids": ["deseq2"],
        "inventory_source_ref_ids": ["deseq2-love-2014"],
    }


def _hint(*, pmid="25516281"):
    return {
        "asset_id": "A1",
        "source_ref_id": "deseq2-love-2014",
        "title": "Moderated estimation with DESeq2",
        "year": 2014,
        "doi": "10.1186/s13059-014-0550-8",
        "pmid": pmid,
        "pmcid": "PMC4302049",
        "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
        "source_kind": "method_paper",
        "rationale": "Canonical DESeq2 paper.",
        "full_text_locations": [
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"
        ],
    }


def _manifest(hint=None):
    return {
        "method_inventory": [{
            "method_id": "deseq2",
            "source_hints": [hint or _hint()],
        }]
    }


def test_projection_merges_registry_pmcid_into_existing_asset():
    assets, gaps = projection.enrich_inventory_sources(
        _manifest(), [_asset()], [], dr
    )

    assert gaps == []
    asset = assets[0]
    assert asset["doi"] == "10.1186/s13059-014-0550-8"
    assert asset["pmid"] == "25516281"
    assert asset["source_metadata_response"]["pmcid"] == "PMC4302049"
    assert asset["open_access_status"] == "open"
    assert asset["full_text_status"] == "available_oa"
    assert (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"
        in asset["full_text_locations"]
    )

    contract = l4_closed_corpus.build_retrieval_contract(asset)
    assert contract["pmcid"] == "PMC4302049"


def test_projection_fails_closed_on_identifier_conflict():
    with pytest.raises(dr.DeepResearchError, match="PMID conflicts"):
        projection.enrich_inventory_sources(
            _manifest(_hint(pmid="99999999")), [_asset()], [], dr
        )
