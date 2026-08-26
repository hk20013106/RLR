import pytest

import research_loop.l05_curie as curie
from research_loop import research_seed
from research_loop.l05_curie.multisource import (
    build_multisource_query_plan,
    run_multisource_discovery,
)
from research_loop.l05_curie.selector import select_candidates


class _Transport:
    def __init__(self, provider="pubmed"):
        self.provider = provider

    def handshake(self):
        return {
            "schema_version": curie.DISCOVERY_TRANSPORT_SCHEMA_VERSION,
            "provider": self.provider,
            "capabilities": ["search:test"],
        }

    def search(self, request):
        return {
            "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": self.provider,
            "query_id": request["query_id"],
            "receipt": {
                "request_sha256": "1" * 64,
                "response_sha256": "2" * 64,
            },
            "records": [{
                "paper_id": "P1",
                "title": "Shared paper",
                "identifiers": {"pmid": "123"},
                "metadata": {"abstract": "mechanism"},
                "provenance": {
                    "provider": self.provider,
                    "raw_record_sha256": "3" * 64,
                },
            }],
        }


def _plan():
    seed = {
        "candidate_id": "C001",
        "round_id": "1",
        "scientific_question": "question",
        "hypothesis_seed": "hypothesis",
    }
    return build_multisource_query_plan(
        seed,
        seed_sha256=research_seed.seed_sha256(seed),
        explicit_queries=["first query", "second query"],
        providers=["pubmed"],
    )


def test_multisource_records_preserve_all_originating_query_ids_after_dedup():
    result = run_multisource_discovery(
        _plan(), {"pubmed": _Transport()}, page_size=5
    )
    assert len(result["records"]) == 1
    assert result["records"][0]["provenance"]["originating_query_ids"] == [
        "Q001", "Q002"
    ]


def test_multisource_rejects_records_without_source_identity():
    class MissingSourceIdentity(_Transport):
        def search(self, request):
            batch = super().search(request)
            del batch["records"][0]["provenance"]["raw_record_sha256"]
            return batch

    with pytest.raises(curie.CurieContractError, match="raw_record_sha256"):
        run_multisource_discovery(_plan(), {"pubmed": MissingSourceIdentity()})


def test_selector_fails_closed_instead_of_inventing_unknown_query_provenance():
    record = {
        "paper_id": "P1",
        "title": "Paper",
        "identifiers": {"pmid": "123"},
        "metadata": {},
        "provenance": {"provider": "pubmed"},
    }
    with pytest.raises(curie.CurieContractError, match="query|provenance"):
        select_candidates(
            [record],
            seed={"scientific_question": "q", "hypothesis_seed": "h"},
            scorer=lambda _record, _seed: {
                "relevance": 0.5,
                "directness": 0.5,
                "methodological_value": 0.5,
                "contradiction_value": 0.5,
                "evidence_diversity": 0.5,
                "reason": "fixture",
            },
            eligibility=lambda _record: (False, "NO_SOURCE"),
        )


def test_selector_rejects_non_string_query_provenance():
    record = {
        "paper_id": "P1",
        "title": "Paper",
        "identifiers": {"pmid": "123"},
        "metadata": {},
        "provenance": {
            "provider": "pubmed",
            "originating_query_ids": [7],
        },
    }
    with pytest.raises(curie.CurieContractError, match="query|provenance"):
        select_candidates(
            [record],
            seed={"scientific_question": "q", "hypothesis_seed": "h"},
            scorer=lambda _record, _seed: {
                "relevance": 0.5,
                "directness": 0.5,
                "methodological_value": 0.5,
                "contradiction_value": 0.5,
                "evidence_diversity": 0.5,
                "reason": "fixture",
            },
            eligibility=lambda _record: (False, "NO_SOURCE"),
        )


def test_selector_rejects_query_provenance_outside_authorized_plan():
    record = {
        "paper_id": "P1",
        "title": "Paper",
        "identifiers": {"pmid": "123"},
        "metadata": {},
        "provenance": {
            "provider": "pubmed",
            "originating_query_ids": ["FORGED"],
        },
    }
    with pytest.raises(curie.CurieContractError, match="query|provenance"):
        select_candidates(
            [record],
            seed={"scientific_question": "q", "hypothesis_seed": "h"},
            scorer=lambda _record, _seed: {
                "relevance": 0.5,
                "directness": 0.5,
                "methodological_value": 0.5,
                "contradiction_value": 0.5,
                "evidence_diversity": 0.5,
                "reason": "fixture",
            },
            eligibility=lambda _record: (False, "NO_SOURCE"),
            query_ids={"Q001"},
        )
