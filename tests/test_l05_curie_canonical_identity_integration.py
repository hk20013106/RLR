from __future__ import annotations

import itertools

from research_loop.l05_curie import multisource
from research_loop.l05_curie.europepmc import canonicalize_europepmc_record


def _record(paper_id: str, identifiers: dict[str, str], provider: str, query_id: str) -> dict:
    return {
        "paper_id": paper_id,
        "title": "Shared paper",
        "identifiers": dict(identifiers),
        "metadata": {
            "authors": "A Author",
            "year": "2024",
            "journal": "Journal",
            "abstract": "",
            "publication_types": [],
            "is_open_access": False,
        },
        "provenance": {
            "provider": provider,
            "raw_record_sha256": provider * 8,
            "originating_query_ids": [query_id],
        },
    }


def test_identifier_normalizers_are_owned_by_multisource():
    assert multisource.normalize_doi.__module__ == multisource.__name__
    assert multisource.normalize_pmid.__module__ == multisource.__name__
    assert multisource.normalize_pmcid.__module__ == multisource.__name__

    assert multisource.normalize_doi("https://doi.org/10.1000/ABC.") == "10.1000/abc"
    assert multisource.normalize_pmid("34114716") == "34114716"
    assert multisource.normalize_pmcid("pmc_9545966") == "PMC9545966"


def test_europepmc_source_identity_is_provenance_not_canonical_identifier():
    record = canonicalize_europepmc_record(
        {
            "source": "MED",
            "id": "99999999",
            "title": "Provider-only identity paper",
            "authorString": "A Author",
            "pubYear": "2024",
        }
    )

    assert "europepmc_source" not in record["identifiers"]
    assert "europepmc_id" not in record["identifiers"]
    assert record["provenance"]["source"] == "MED"
    assert record["provenance"]["ext_id"] == "99999999"


def test_identity_graph_dedup_is_transitive_order_invariant_and_preserves_query_lineage():
    records = [
        _record("P_DOI", {"doi": "10.1000/shared"}, "crossref", "Q1"),
        _record(
            "P_BRIDGE",
            {"doi": "10.1000/shared", "pmid": "12345678"},
            "pubmed",
            "Q2",
        ),
        _record("P_PMID", {"pmid": "12345678"}, "europe-pmc", "Q3"),
    ]

    snapshots = []
    for ordering in itertools.permutations(records):
        unique, duplicates = multisource.deduplicate_provider_records(list(ordering))
        assert len(unique) == 1
        canonical = unique[0]
        assert canonical["identifiers"]["doi"] == "10.1000/shared"
        assert canonical["identifiers"]["pmid"] == "12345678"
        assert set(canonical["provenance"]["originating_query_ids"]) == {"Q1", "Q2", "Q3"}
        assert len(canonical["provenance"]["source_records"]) == 3
        snapshots.append((canonical["paper_id"], tuple(sorted(duplicates))))

    assert len(set(snapshots)) == 1
