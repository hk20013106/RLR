import re
import json

import pytest
from research_loop import research_seed
from research_loop.l05_curie import CurieContractError, validate_evidence_extract
from research_loop.l05_curie import europepmc_runtime
from research_loop.l05_curie.query_planner import build_scientific_query_plan
from research_loop.l05_curie.multisource import build_multisource_query_plan
from tests.test_l05_curie_europepmc_runtime import XML, _project, _search_payload


def test_chinese_seed_becomes_bounded_english_concept_queries():
    seed = {
        "scientific_question": (
            "高心率物种如何在长期维持极高心率的同时避免出现与持续高频心脏活动相关的"
            "病理性重塑或功能损伤？这一生理特征是否伴随能量与营养供给、肾上腺素能调控—"
            "Ca2+调控—心肌收缩轴，以及心脏结构与力学性质的协同重塑？"
        ),
        "hypothesis_seed": (
            "energy / nutrient supply; adrenergic regulation; Ca2+ handling; "
            "excitation-contraction coupling; myofilament response; cardiac structure / mechanics; "
            "high-heart-rate shrews and related high-HR mammals"
        ),
    }

    plan = build_scientific_query_plan(seed)
    queries = [item["query"] for item in plan["queries"]]
    joined = " ".join(queries).casefold()

    assert 3 <= len(queries) <= 6
    assert all(query.strip() for query in queries)
    assert not any(re.search(r"[\u3400-\u9fff]", query) for query in queries)
    assert "high heart rate" in joined
    assert "cardiac" in joined
    assert "adrenergic" in joined
    assert "calcium" in joined
    assert "calcium handling" in joined
    assert "excitation-contraction" in joined
    assert "myofilament" in joined
    assert "myofilament response" in joined
    assert "energy" in joined or "nutrient" in joined
    assert "shrew" in joined or "mammal" in joined
    assert "ca2+" not in joined
    assert joined != seed["scientific_question"] + " " + seed["hypothesis_seed"]


def test_multisource_default_plan_uses_scientific_planner_output():
    seed = {
        "candidate_id": "C001",
        "round_id": "1",
        "scientific_question": "高心率物种如何避免病理性心脏重塑？",
        "hypothesis_seed": "肾上腺素能调控和钙离子处理支持心脏适应。",
    }

    plan = build_multisource_query_plan(
        seed,
        seed_sha256=research_seed.seed_sha256(seed),
        providers=["europe-pmc"],
    )

    assert plan["planner"] == "scientific-query-planner/v1"
    assert plan["planning"]["schema_version"] == "L05ScientificQueryPlan/v1"
    assert 3 <= len(plan["queries"]) <= 6
    assert all("[" not in item["query"] for item in plan["queries"])
    assert not any(re.search(r"[\u3400-\u9fff]", item["query"]) for item in plan["queries"])
    assert all(item["providers"] == ["europe-pmc"] for item in plan["queries"])


def test_english_seed_remains_a_normal_scientific_query_plan():
    seed = {
        "scientific_question": "How can bats sustain high heart rates without cardiac injury?",
        "hypothesis_seed": "Adaptive calcium handling and cardiac remodeling preserve function.",
    }

    plan = build_scientific_query_plan(seed)
    joined = " ".join(item["query"] for item in plan["queries"])

    assert 3 <= len(plan["queries"]) <= 6
    assert "bats" in joined
    assert "heart rate" in joined
    assert "calcium" in joined
    assert "cardiac" in joined


def test_explicit_queries_keep_the_existing_operator_priority():
    seed = {
        "candidate_id": "C001",
        "round_id": "1",
        "scientific_question": "高心率物种如何适应？",
        "hypothesis_seed": "心脏调控支持适应。",
    }

    plan = build_multisource_query_plan(
        seed,
        seed_sha256=research_seed.seed_sha256(seed),
        explicit_queries=["operator selected cardiac query"],
        providers=["europe-pmc"],
    )

    assert [item["query"] for item in plan["queries"]] == [
        "operator selected cardiac query"
    ]
    assert plan["planner"] == "curie-multisource-explicit-query/v1"
    assert "planning" not in plan


def test_initial_zero_hit_reformulates_once_before_freeze(tmp_path):
    project, _seed = _project(tmp_path)
    search_calls = []

    def http_get(url, _timeout):
        if "/search?" in url:
            search_calls.append(url)
            if len(search_calls) <= 4:
                return json.dumps(
                    {"hitCount": 0, "resultList": {"result": []}}
                ).encode("utf-8")
            return _search_payload()
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = europepmc_runtime.run_europepmc_acquisition(
        project,
        "C001",
        max_papers=1,
        page_size=5,
        run_id="AUTO_REFORM",
        http_get=http_get,
        timeout=7,
    )

    assert result["status"] == "FROZEN"
    audit = json.loads(
        (project / result["acquisition_manifest_path"]).read_text(encoding="utf-8")
    )
    initial = audit["initial_acquisition"]
    assert initial["reformulated"] is True
    assert initial["reformulation_reason"] == "zero_discovery_records"
    assert len(initial["attempts"]) == 2
    assert initial["attempts"][0]["discovery_outcome"]["record_count"] == 0
    assert initial["attempts"][1]["discovery_outcome"]["record_count"] > 0
    assert len(audit["query_plans"]) == 2
    assert audit["queries_executed"]
    assert audit["final_executed_queries"]
    first_query_count = len(audit["query_plans"][0]["queries"])
    assert 3 <= first_query_count <= 6
    assert len(search_calls) == sum(
        len(plan["queries"]) for plan in audit["query_plans"]
    )
    assert {
        item["query_id"] for item in audit["query_plans"][0]["queries"]
    }.isdisjoint({
        item["query_id"] for item in audit["query_plans"][1]["queries"]
    })


def test_initial_zero_hit_exhaustion_is_truthful_and_bounded(tmp_path):
    project, _seed = _project(tmp_path)
    search_calls = []

    def http_get(url, _timeout):
        if "/search?" in url:
            search_calls.append(url)
            return b'{"hitCount":0,"resultList":{"result":[]}}'
        raise AssertionError(url)

    result = europepmc_runtime.run_europepmc_acquisition(
        project,
        "C001",
        run_id="AUTO_STOP",
        http_get=http_get,
        timeout=7,
    )

    assert result["status"] == "INSUFFICIENT_STOP"
    assert result["evidence_pack"] is None
    assert result["coverage"]["verdict"] == "INSUFFICIENT_STOP"
    assert result["initial_acquisition"]["reformulated"] is True
    assert len(result["initial_acquisition"]["attempts"]) == 2
    assert len(search_calls) == sum(
        len(plan["queries"]) for plan in result["query_plans"]
    )


def test_initial_non_oa_records_are_clearly_insufficient_and_reformulate(tmp_path):
    project, seed = _project(tmp_path)
    search_calls = []
    first_plan = build_multisource_query_plan(
        seed,
        seed_sha256=research_seed.seed_sha256(seed),
        providers=["europe-pmc"],
    )
    first_query_count = len(first_plan["queries"])

    def http_get(url, _timeout):
        if "/search?" in url:
            search_calls.append(url)
            if len(search_calls) <= first_query_count:
                return _search_payload(open_access=False)
            return _search_payload()
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = europepmc_runtime.run_europepmc_acquisition(
        project,
        "C001",
        max_papers=1,
        page_size=5,
        run_id="AUTO_NO_OA",
        http_get=http_get,
        timeout=7,
    )

    assert result["status"] == "FROZEN"
    initial = result["initial_acquisition"]
    assert initial["reformulated"] is True
    assert initial["reformulation_reason"] == "no_source_qualified_records"
    assert initial["attempts"][0]["discovery_outcome"]["record_count"] > 0
    assert initial["attempts"][0]["discovery_outcome"]["source_qualified_record_count"] == 0
    assert initial["attempts"][1]["discovery_outcome"]["source_qualified_record_count"] > 0
    assert len(search_calls) == sum(
        len(plan["queries"]) for plan in result["query_plans"]
    )


def test_initial_network_failure_is_not_reformulated(tmp_path):
    project, _seed = _project(tmp_path)
    search_calls = []

    def http_get(url, _timeout):
        if "/search?" in url:
            search_calls.append(url)
            raise OSError("simulated Europe PMC outage")
        raise AssertionError(url)

    with pytest.raises(CurieContractError, match="Europe PMC search request failed"):
        europepmc_runtime.run_europepmc_acquisition(
            project,
            "C001",
            run_id="AUTO_NETWORK_FAILURE",
            http_get=http_get,
            timeout=7,
        )

    assert len(search_calls) == 1


def test_initial_reformulation_configuration_is_hard_capped(tmp_path):
    project, _seed = _project(tmp_path)

    with pytest.raises(CurieContractError, match="max_initial_reformulations"):
        europepmc_runtime.run_europepmc_acquisition(
            project,
            "C001",
            max_initial_reformulations=2,
            http_get=lambda *_args: pytest.fail("bounded configuration should fail before HTTP"),
        )


def test_query_planner_output_has_no_evidence_authority():
    plan = build_scientific_query_plan({
        "scientific_question": "How do bats sustain high heart rates?",
        "hypothesis_seed": "Cardiac adaptation preserves function.",
    })

    assert not {"papers", "evidence", "verification", "role", "status"}.intersection(plan)
    assert all(
        not {"paper_id", "verification_status", "role", "evidence_id"}.intersection(item)
        for item in plan["queries"]
    )
    with pytest.raises(CurieContractError):
        validate_evidence_extract(plan)
