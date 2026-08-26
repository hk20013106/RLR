import pytest

import research_loop.l05_curie as curie
from research_loop.l05_curie.selector import (
    SELECTOR_DECISION_SCHEMA_VERSION,
    build_selector_decision,
    select_candidates,
    validate_selector_decision,
)


def _record(paper_id, *, title="Paper", pmcid=None, oa=False, in_epmc=False, query_ids=None):
    ids = {"doi": f"10.1000/{paper_id.lower()}"}
    if pmcid:
        ids["pmcid"] = pmcid
    return {
        "paper_id": paper_id,
        "title": title,
        "identifiers": ids,
        "metadata": {
            "abstract": title,
            "is_open_access": oa,
            "in_europe_pmc": in_epmc,
        },
        "provenance": {"originating_query_ids": list(query_ids or ["Q001"])},
    }


def _score(**overrides):
    base = {
        "relevance": 0.8,
        "directness": 0.7,
        "methodological_value": 0.4,
        "contradiction_value": 0.2,
        "evidence_diversity": 0.5,
        "reason": "Direct mechanistic study.",
    }
    base.update(overrides)
    return base


def test_selector_decision_contract_preserves_cognitive_dimensions():
    decision = build_selector_decision(
        paper_id="P1", decision="INCLUDE", originating_query_ids=["Q001", "Q002"],
        **_score(contradiction_value=0.9),
    )
    validated = validate_selector_decision(decision)
    assert validated["schema_version"] == SELECTOR_DECISION_SCHEMA_VERSION
    assert validated["decision"] == "INCLUDE"
    assert validated["contradiction_value"] == 0.9
    assert validated["originating_query_ids"] == ["Q001", "Q002"]


def test_selector_rejects_invalid_scores_and_unknown_decisions():
    with pytest.raises(curie.CurieContractError, match="relevance"):
        build_selector_decision(
            paper_id="P1", decision="INCLUDE", originating_query_ids=["Q001"],
            **_score(relevance=1.5),
        )
    with pytest.raises(curie.CurieContractError, match="decision"):
        build_selector_decision(
            paper_id="P1", decision="MAYBE", originating_query_ids=["Q001"],
            **_score(),
        )


def test_hard_eligibility_exclusion_overrides_cognitive_score():
    records = [
        _record("P1", title="Highly relevant but no retrievable source"),
        _record("P2", title="Retrievable direct study", pmcid="PMC2", oa=True, in_epmc=True),
    ]

    def scorer(record, _seed):
        if record["paper_id"] == "P1":
            return _score(relevance=1.0, directness=1.0, contradiction_value=1.0)
        return _score(relevance=0.5, directness=0.5)

    result = select_candidates(
        records,
        seed={"scientific_question": "question", "hypothesis_seed": "hypothesis"},
        scorer=scorer,
        max_papers=1,
        eligibility=lambda record: (
            bool(record["identifiers"].get("pmcid") and record["metadata"].get("is_open_access")),
            "NO_RETRIEVABLE_SOURCE",
        ),
        query_ids={"Q001"},
    )
    decisions = {item["paper_id"]: item for item in result["decisions"]}
    assert decisions["P1"]["decision"] == "EXCLUDE"
    assert decisions["P1"]["reason_code"] == "NO_RETRIEVABLE_SOURCE"
    assert decisions["P2"]["decision"] == "INCLUDE"


def test_contradictory_value_can_promote_evidence_instead_of_penalizing_it():
    records = [
        _record("P1", title="Confirmatory study", pmcid="PMC1", oa=True, in_epmc=True),
        _record("P2", title="Strong contradictory study", pmcid="PMC2", oa=True, in_epmc=True),
    ]

    def scorer(record, _seed):
        if record["paper_id"] == "P2":
            return _score(relevance=0.8, directness=0.8, contradiction_value=1.0)
        return _score(relevance=0.8, directness=0.8, contradiction_value=0.0)

    result = select_candidates(
        records,
        seed={"scientific_question": "question", "hypothesis_seed": "hypothesis"},
        scorer=scorer,
        max_papers=1,
        eligibility=lambda _record: (True, ""),
        query_ids={"Q001"},
    )
    included = [item for item in result["decisions"] if item["decision"] == "INCLUDE"]
    assert included[0]["paper_id"] == "P2"
    assert included[0]["contradiction_value"] == 1.0


def test_selector_persists_all_include_exclude_reserve_decisions(tmp_path):
    records = [
        _record("P1", pmcid="PMC1", oa=True, in_epmc=True),
        _record("P2", pmcid="PMC2", oa=True, in_epmc=True),
        _record("P3"),
    ]
    result = select_candidates(
        records,
        seed={"scientific_question": "question", "hypothesis_seed": "hypothesis"},
        scorer=lambda _r, _s: _score(),
        max_papers=1,
        eligibility=lambda record: (
            (bool(record["identifiers"].get("pmcid")), "")
            if record["identifiers"].get("pmcid") else (False, "NO_SOURCE")
        ),
        project_dir=tmp_path,
        candidate_id="C001",
        run_id="RUN1",
        query_ids={"Q001"},
    )
    assert {item["decision"] for item in result["decisions"]} == {"INCLUDE", "RESERVE", "EXCLUDE"}
    receipt = tmp_path / result["artifact_path"]
    assert receipt.is_file()
    assert len(result["artifact_sha256"]) == 64
