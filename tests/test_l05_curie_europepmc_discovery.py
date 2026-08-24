import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest

from research_loop import research_seed
from research_loop.l05_curie import validate_discovery_batch, validate_query_plan
from research_loop.l05_curie.europepmc import (
    EuropePmcTransport,
    build_europepmc_query_plan,
    canonicalize_europepmc_record,
    deduplicate_discovery_records,
)


def _seed():
    return {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C001",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "How is carbon dioxide sensed by yeast?",
        "hypothesis_seed": "A transcription factor regulates the carbon dioxide response.",
        "l0_contract_schema_version": "L0InputContract/v1.1",
        "l0_contract_path": "00_Preflight/l0_input.yaml",
        "l0_contract_sha256": "a" * 64,
    }


def _core_result(**overrides):
    result = {
        "id": "22253597",
        "source": "MED",
        "pmid": "22253597",
        "pmcid": "PMC3257301",
        "doi": "10.1371/journal.ppat.1002485",
        "title": "The bZIP Transcription Factor Rca1p Is a Central Regulator of a Novel CO2 Sensing Pathway in Yeast",
        "authorString": "Cottier F, et al.",
        "pubYear": "2012",
        "journalTitle": "PLoS Pathog",
        "isOpenAccess": "Y",
        "inEPMC": "Y",
        "abstractText": "Rca1p is required for transcriptional responses to carbon dioxide.",
        "pubTypeList": {"pubType": ["research-article"]},
    }
    result.update(overrides)
    return result


def test_query_planner_builds_auditable_europepmc_query_plan():
    seed = _seed()
    digest = research_seed.seed_sha256(seed)
    plan = build_europepmc_query_plan(
        seed,
        seed_sha256=digest,
        explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
    )

    validate_query_plan(plan, seed_sha256=digest)
    assert plan["queries"] == [
        {
            "query_id": "Q001",
            "intent": "operator_reproducible_query",
            "query": "EXT_ID:22253597 AND SRC:MED",
            "providers": ["europe-pmc"],
        }
    ]
    assert plan["coverage_targets"] == [
        "verified_full_text_source",
        "located_results_or_interpretation",
    ]


def test_canonical_identity_normalizes_doi_and_deduplicates():
    first = canonicalize_europepmc_record(_core_result())
    duplicate = canonicalize_europepmc_record(
        _core_result(
            doi="https://doi.org/10.1371/JOURNAL.PPAT.1002485",
            id="PMC3257301",
            source="PMC",
        )
    )
    other = canonicalize_europepmc_record(
        _core_result(
            id="99999999",
            pmid="99999999",
            pmcid="",
            doi="",
            title="Different paper",
        )
    )

    unique, duplicate_ids = deduplicate_discovery_records(
        [first, duplicate, other]
    )
    assert first["identifiers"]["doi"] == "10.1371/journal.ppat.1002485"
    assert first["paper_id"] == duplicate["paper_id"]
    assert [item["title"] for item in unique] == [first["title"], "Different paper"]
    assert duplicate_ids == [duplicate["paper_id"]]


def test_dedup_merges_cross_identifier_records_and_preserves_fulltext_identity():
    primary = canonicalize_europepmc_record(
        _core_result(pmcid="", isOpenAccess="N", inEPMC="N")
    )
    by_pmid_with_fulltext = canonicalize_europepmc_record(
        _core_result(
            doi="",
            id="22253597",
            source="MED",
            pmid="22253597",
            pmcid="PMC3257301",
            isOpenAccess="Y",
            inEPMC="Y",
        )
    )
    assert primary["paper_id"] != by_pmid_with_fulltext["paper_id"]

    unique, duplicate_ids = deduplicate_discovery_records(
        [primary, by_pmid_with_fulltext]
    )

    assert len(unique) == 1
    merged = unique[0]
    assert merged["paper_id"] == primary["paper_id"]
    assert merged["identifiers"]["pmid"] == "22253597"
    assert merged["identifiers"]["pmcid"] == "PMC3257301"
    assert merged["metadata"]["is_open_access"] is True
    assert merged["metadata"]["in_europe_pmc"] is True
    assert duplicate_ids == [by_pmid_with_fulltext["paper_id"]]


def test_europepmc_transport_persists_raw_response_and_binds_receipt(tmp_path):
    payload = {
        "hitCount": 1,
        "nextCursorMark": "AoIIP4q0sig1NTIyMDMxNQ==",
        "resultList": {"result": [_core_result()]},
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    seen = []

    def http_get(url, timeout):
        seen.append((url, timeout))
        parsed = urlparse(url)
        assert parsed.path.endswith("/search")
        query = parse_qs(parsed.query)
        assert query["resultType"] == ["core"]
        assert query["format"] == ["json"]
        assert query["pageSize"] == ["5"]
        return raw

    transport = EuropePmcTransport(
        tmp_path,
        candidate_id="C001",
        run_id="RUN001",
        http_get=http_get,
        timeout=7,
    )
    assert transport.handshake() == {
        "schema_version": "DiscoveryTransport/v1",
        "provider": "europe-pmc",
        "capabilities": ["search:core", "fulltext:xml", "cursor-pagination"],
    }

    batch = transport.search(
        {
            "query_id": "Q001",
            "query": "EXT_ID:22253597 AND SRC:MED",
            "page_size": 5,
        }
    )
    validate_discovery_batch(batch, query_ids={"Q001"})
    assert len(seen) == 1
    assert batch["records"][0]["identifiers"]["pmcid"] == "PMC3257301"
    assert batch["receipt"]["response_sha256"] == hashlib.sha256(raw).hexdigest()
    response_path = tmp_path / batch["receipt"]["response_path"]
    assert response_path.read_bytes() == raw
    assert hashlib.sha256(response_path.read_bytes()).hexdigest() == batch["receipt"]["response_sha256"]
