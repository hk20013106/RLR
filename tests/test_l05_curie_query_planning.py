import json

import pytest

from research_loop import research_seed
from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie import europepmc_runtime
from research_loop.l05_curie.multisource import build_multisource_query_plan
from research_loop.l05_curie.query_planner import build_scientific_query_plan
from tests.test_l05_curie_europepmc_runtime import XML, _project, _search_payload


def test_default_curie_plan_is_bounded_and_keeps_planner_provenance():
    seed = {
        "candidate_id": "C001",
        "round_id": "1",
        "scientific_question": "How do high-heart-rate mammals avoid cardiac injury?",
        "hypothesis_seed": "Calcium handling and cardiac remodeling preserve function.",
    }

    plan = build_multisource_query_plan(
        seed,
        seed_sha256=research_seed.seed_sha256(seed),
        providers=["europe-pmc"],
    )

    assert plan["planner"] == "scientific-query-planner/v1"
    assert plan["planning"]["schema_version"] == "L05ScientificQueryPlan/v1"
    assert 3 <= len(plan["queries"]) <= 6
    assert all(item["providers"] == ["europe-pmc"] for item in plan["queries"])
    assert all(item["concepts"] for item in plan["queries"])


def test_initial_zero_discovery_reformulates_once_and_records_both_attempts(tmp_path):
    project, _seed = _project(tmp_path)
    searches = []

    def http_get(url, _timeout):
        if "/search?" in url:
            searches.append(url)
            # The first bounded plan owns exactly three requests; the second
            # attempt must receive the fixture's qualified record.
            if len(searches) <= 3:
                return b'{"hitCount":0,"resultList":{"result":[]}}'
            return _search_payload()
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = europepmc_runtime.run_europepmc_acquisition(
        project, "C001", max_papers=1, run_id="REPLAN", http_get=http_get
    )

    assert result["status"] == "FROZEN"
    audit = json.loads(
        (project / result["acquisition_manifest_path"]).read_text(encoding="utf-8")
    )
    assert audit["initial_acquisition"]["reformulated"] is True
    assert len(audit["initial_acquisition"]["attempts"]) == 2
    assert len(audit["query_plans"]) == 2


def test_query_planner_rejects_unbounded_reformulation_index():
    with pytest.raises(CurieContractError, match="reformulation_index"):
        build_scientific_query_plan(
            {
                "scientific_question": "Which mechanism is supported?",
                "hypothesis_seed": "Independent evidence is required.",
            },
            reformulation_index=2,
        )
