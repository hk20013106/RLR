import importlib

import pytest


def _curie():
    return importlib.import_module("research_loop.l05_curie")


def _query_plan(mod, *, seed_sha256="a" * 64, round_index=1):
    return {
        "schema_version": mod.QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": "C001",
        "round_id": "R1",
        "seed_sha256": seed_sha256,
        "plan_id": "QP001",
        "round_index": round_index,
        "queries": [
            {
                "query_id": "Q001",
                "intent": "phenotype_background",
                "query": "bat shrew high heart rate cardiac physiology",
                "providers": ["pubmed", "europe_pmc"],
            },
            {
                "query_id": "Q002",
                "intent": "contradictory_evidence",
                "query": "bat cardiac pathology tachycardia negative evidence",
                "providers": ["openalex"],
            },
        ],
    }


def test_query_plan_is_bound_to_canonical_research_seed():
    mod = _curie()
    plan = _query_plan(mod)

    validated = mod.validate_query_plan(plan, seed_sha256="a" * 64)

    assert validated == plan
    assert {q["query_id"] for q in validated["queries"]} == {"Q001", "Q002"}


def test_query_plan_rejects_seed_mismatch_and_empty_provider_list():
    mod = _curie()
    plan = _query_plan(mod)
    with pytest.raises(mod.CurieContractError, match="seed_sha256"):
        mod.validate_query_plan(plan, seed_sha256="b" * 64)

    plan = _query_plan(mod)
    plan["queries"][0]["providers"] = []
    with pytest.raises(mod.CurieContractError, match="providers"):
        mod.validate_query_plan(plan, seed_sha256="a" * 64)


def test_discovery_transport_requires_v1_handshake_and_query_provenance():
    mod = _curie()
    handshake = {
        "schema_version": mod.DISCOVERY_TRANSPORT_SCHEMA_VERSION,
        "provider": "pubmed",
        "capabilities": ["search", "metadata"],
    }
    assert mod.validate_transport_handshake(handshake) == handshake

    batch = {
        "schema_version": mod.DISCOVERY_BATCH_SCHEMA_VERSION,
        "provider": "pubmed",
        "query_id": "Q001",
        "receipt": {
            "request_sha256": "1" * 64,
            "response_sha256": "2" * 64,
        },
        "records": [
            {
                "paper_id": "PMID:123",
                "title": "Example paper",
                "identifiers": {"pmid": "123"},
            }
        ],
    }
    assert mod.validate_discovery_batch(batch, query_ids={"Q001", "Q002"}) == batch

    batch["query_id"] = "Q999"
    with pytest.raises(mod.CurieContractError, match="query_id"):
        mod.validate_discovery_batch(batch, query_ids={"Q001", "Q002"})


def test_evidence_extract_preserves_role_and_requires_located_source():
    mod = _curie()
    extract = {
        "schema_version": mod.EVIDENCE_EXTRACT_SCHEMA_VERSION,
        "evidence_id": "E001",
        "paper_id": "PMID:123",
        "section": "Results",
        "text": "No pathological remodeling was detected.",
        "locator": "Results, paragraph 4",
        "role": "CONTRADICTORY",
        "verification_status": "LOCATED",
        "retrieval": {
            "engine": "paperqa2",
            "source_sha256": "3" * 64,
        },
    }

    validated = mod.validate_evidence_extract(extract)
    assert validated["role"] == "CONTRADICTORY"

    bad = dict(extract, verification_status="UNVERIFIED")
    with pytest.raises(mod.CurieContractError, match="LOCATED"):
        mod.validate_evidence_extract(bad)

    bad = dict(extract, locator="")
    with pytest.raises(mod.CurieContractError, match="locator"):
        mod.validate_evidence_extract(bad)


def test_coverage_judge_is_bounded_and_fail_closed():
    mod = _curie()
    coverage = {
        "covered": ["phenotype", "metabolism"],
        "gaps": [
            {
                "gap_id": "G001",
                "topic": "autonomic_regulation",
                "reason": "only indirect evidence retrieved",
                "search_directions": ["bat vagal cardiac control"],
            }
        ],
    }

    retry = mod.judge_coverage(coverage, round_index=1, max_rounds=3)
    assert retry["schema_version"] == mod.COVERAGE_DECISION_SCHEMA_VERSION
    assert retry["verdict"] == "INSUFFICIENT_RETRY"

    stop = mod.judge_coverage(coverage, round_index=3, max_rounds=3)
    assert stop["verdict"] == "INSUFFICIENT_STOP"

    passed = mod.judge_coverage({"covered": ["all"], "gaps": []}, round_index=1)
    assert passed["verdict"] == "PASS"

    with pytest.raises(mod.CurieContractError, match="maximum"):
        mod.judge_coverage(coverage, round_index=1, max_rounds=4)


def test_gap_request_binds_exact_frozen_pack_hash():
    mod = _curie()
    gaps = [
        {
            "gap_id": "G001",
            "topic": "calcium_handling",
            "reason": "mechanistic evidence insufficient",
            "search_directions": ["bat cardiomyocyte calcium handling"],
        }
    ]

    request = mod.build_gap_request(
        candidate_id="C001",
        round_id="R1",
        seed_sha256="a" * 64,
        pack_sha256="f" * 64,
        gaps=gaps,
    )

    assert request["schema_version"] == mod.GAP_REQUEST_SCHEMA_VERSION
    assert request["pack_sha256"] == "f" * 64
    assert request["gaps"] == gaps
    assert request["status"] == "OPEN"
