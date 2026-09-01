import pytest

import research_loop.l05_curie as curie
from research_loop.l05_curie.multisource import (
    canonicalize_openalex_record,
    deduplicate_provider_records,
)


def _openalex(work_id: str, doi: str, title: str) -> dict:
    return canonicalize_openalex_record({
        "id": f"https://openalex.org/{work_id}",
        "title": title,
        "doi": f"https://doi.org/{doi}",
        "ids": {
            "openalex": f"https://openalex.org/{work_id}",
            "doi": f"https://doi.org/{doi}",
        },
    })


def test_same_doi_same_title_different_openalex_ids_merge_as_provider_aliases():
    records = [
        _openalex("W3132672593", "10.53846/goediss-8394", "Shared work title"),
        _openalex("W4226217688", "10.53846/goediss-8394", "Shared work title"),
    ]

    unique, duplicates = deduplicate_provider_records(records)

    assert len(unique) == 1
    merged = unique[0]
    assert merged["identifiers"]["doi"] == "10.53846/goediss-8394"
    assert "openalex_id" not in merged["identifiers"]
    assert merged["provenance"]["identifier_aliases"]["openalex_id"] == [
        "W3132672593",
        "W4226217688",
    ]
    assert len(duplicates) == 1


def test_provider_alias_merge_is_order_independent():
    left = _openalex("W3132672593", "10.53846/goediss-8394", "Shared work title")
    right = _openalex("W4226217688", "10.53846/goediss-8394", "Shared work title")

    forward, _ = deduplicate_provider_records([left, right])
    reverse, _ = deduplicate_provider_records([right, left])

    assert forward[0]["paper_id"] == reverse[0]["paper_id"]
    assert forward[0]["identifiers"] == reverse[0]["identifiers"]
    assert forward[0]["provenance"]["identifier_aliases"] == reverse[0]["provenance"]["identifier_aliases"]


def test_same_openalex_id_with_different_dois_still_fails_closed():
    records = [
        _openalex("W123", "10.1000/a", "Paper A"),
        _openalex("W123", "10.1000/b", "Paper B"),
    ]

    with pytest.raises(curie.CurieContractError, match="cross-provider identity conflict"):
        deduplicate_provider_records(records)


def test_same_doi_with_materially_different_titles_still_fails_closed():
    records = [
        _openalex("W111", "10.1000/shared", "Completely different paper A"),
        _openalex("W222", "10.1000/shared", "Unrelated paper B"),
    ]

    with pytest.raises(curie.CurieContractError, match="identity conflict"):
        deduplicate_provider_records(records)
