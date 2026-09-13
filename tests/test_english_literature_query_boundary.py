import re

import pytest

from research_loop import research_seed
from research_loop import l4_contextual_literature as l4ctx
from research_loop import l85_literature_verification as l85
from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie import europepmc_runtime
from research_loop.l05_curie.multisource import build_multisource_query_plan
from research_loop.l05_curie.query_language import classify_supported_input_language
from research_loop.l05_curie.query_planner import (
    build_scientific_query_plan,
    requires_provider_planning,
)
from tests.test_l05_curie_europepmc_runtime import _project


CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _seed(question, hypothesis):
    return {
        "candidate_id": "C001",
        "round_id": "1",
        "scientific_question": question,
        "hypothesis_seed": hypothesis,
    }


def test_supported_input_language_scope_is_chinese_and_english_only():
    assert classify_supported_input_language("耳蜗黑色素与噪声损伤") == "zh"
    assert classify_supported_input_language("Cochlear melanin and noise injury") == "en"
    with pytest.raises(CurieContractError, match="only Chinese and English"):
        classify_supported_input_language("蝸牛の色素と騒音障害")


def test_l05_chinese_requires_provider_planning_but_english_does_not():
    assert requires_provider_planning(
        _seed(
            "耳蜗黑色素是否降低噪声损伤？",
            "黑色素相关程序可能保护毛细胞。",
        )
    ) is True
    assert requires_provider_planning(
        _seed(
            "Does cochlear melanin reduce noise injury?",
            "Melanin-associated programs may protect hair cells.",
        )
    ) is False


def test_l05_english_planner_is_generic_not_project_lexicon_driven():
    plan = build_scientific_query_plan(
        _seed(
            "How does drought alter stomatal closure in Arabidopsis leaves?",
            "ABA signaling may increase guard-cell ion efflux during water stress.",
        )
    )

    rendered = " ".join(item["query"] for item in plan["queries"]).casefold()
    assert 3 <= len(plan["queries"]) <= 6
    assert "drought" in rendered
    assert "stomatal" in rendered
    assert "cardiac" not in rendered
    assert "shrew" not in rendered
    assert "adrenergic" not in rendered


def test_multisource_rejects_explicit_cjk_retrieval_query_before_transport():
    seed = _seed(
        "How does cochlear pigment affect acoustic injury?",
        "Melanin-associated programs may protect cochlear homeostasis.",
    )

    with pytest.raises(CurieContractError, match="English-only scientific text"):
        build_multisource_query_plan(
            seed,
            seed_sha256=research_seed.seed_sha256(seed),
            explicit_queries=["耳蜗 黑色素 噪声损伤"],
            providers=["europe-pmc"],
        )


def test_europepmc_runtime_cannot_bypass_explicit_query_language_gate(tmp_path):
    project, _seed_value = _project(tmp_path)
    called = {"transport": False}

    def http_get(_url, _timeout):
        called["transport"] = True
        raise AssertionError("transport must not run for a Chinese retrieval query")

    with pytest.raises(CurieContractError, match="English-only scientific text"):
        europepmc_runtime.run_europepmc_acquisition(
            project,
            "C001",
            explicit_queries=["耳蜗 黑色素 噪声损伤"],
            http_get=http_get,
        )
    assert called["transport"] is False


def test_default_l05_planner_fails_closed_for_chinese_seed_instead_of_using_project_lexicon():
    with pytest.raises(CurieContractError, match="provider-planned English"):
        build_scientific_query_plan(
            _seed(
                "鼩鼱为什么能在极高心率下维持心脏功能？",
                "钙离子处理和抗重塑机制可能共同保护心肌。",
            )
        )


def test_l05_candidate_ranking_uses_authorized_query_plan_not_raw_research_seed():
    record = {
        "paper_id": "P1",
        "title": "Cochlear melanin protects against noise-induced injury",
        "metadata": {
            "abstract": "Melanin-associated cochlear programs reduce acoustic injury.",
        },
        "provenance": {
            "originating_query_ids": ["Q001"],
            "source_records": [],
        },
    }
    query_plan = {
        "queries": [{
            "query_id": "Q001",
            "query": "cochlear melanin noise-induced injury",
        }],
    }

    score = europepmc_runtime._europepmc_selector_score(record, query_plan)

    assert score["relevance"] > 0.5


def test_l05_paperqa2_retrieval_reuses_english_query_plan_without_chinese_seed_text():
    selected = {
        "title": "Cochlear melanin protects against noise-induced injury",
        "provenance": {"originating_query_ids": ["Q001"]},
    }
    seed = _seed(
        "耳蜗黑色素是否可以降低噪声造成的听力损伤？",
        "黑色素相关保护程序可能降低氧化应激和毛细胞损伤。",
    )
    query_plan = {
        "queries": [{
            "query_id": "Q001",
            "query": "cochlear melanin oxidative stress noise injury",
            "intent": "operator_reproducible_query",
        }],
    }

    query = europepmc_runtime._paperqa2_retrieval_query(selected, seed, query_plan)

    assert selected["title"] in query
    assert "cochlear melanin" in query.casefold()
    assert CJK.search(query) is None


def test_l05_paperqa2_english_seed_keeps_semantic_focus_with_locator_query():
    selected = {
        "title": "The bZIP Transcription Factor Rca1p",
        "provenance": {"originating_query_ids": ["Q001"]},
    }
    seed = _seed(
        "How is carbon dioxide sensed by yeast?",
        "Rca1p regulates the carbon dioxide transcriptional response.",
    )
    query_plan = {
        "queries": [{
            "query_id": "Q001",
            "query": "EXT_ID:22253597 AND SRC:MED",
            "intent": "operator_reproducible_query",
        }],
    }

    query = europepmc_runtime._paperqa2_retrieval_query(selected, seed, query_plan)

    assert "carbon" in query.casefold()
    assert "rca1p" in query.casefold()
    assert CJK.search(query) is None


def test_l4_specter_query_reuses_contextual_english_query_only():
    method = {
        "method_id": "M1",
        "name": "加权基因共表达网络分析",
        "purpose": "比较不同物种之间的共表达模块",
        "inventory_reason": "用于寻找保守的分子模块",
    }
    planner_queries = [{
        "query_id": "PQ1",
        "method_ids": ["M1"],
        "query": "weighted gene co-expression network analysis cross-species",
    }]

    query = l4ctx._method_query(method, planner_queries)

    assert query == "weighted gene co-expression network analysis cross-species"
    assert CJK.search(query) is None


def test_l85_chinese_finding_requires_provider_planned_english_query():
    findings = [{
        "finding_id": "H1",
        "text": "回声定位蝙蝠外毛细胞中膜蛋白运输和细胞极性相关程序显著增强",
        "sources": ["L7"],
    }]

    with pytest.raises(l85.L85VerificationError, match="Chinese-to-English"):
        l85.finding_queries(findings)


def test_l85_unsupported_language_fails_closed_instead_of_being_translated():
    findings = [{
        "finding_id": "H1",
        "text": "蝸牛の色素と騒音障害",
        "sources": ["L7"],
    }]

    with pytest.raises(CurieContractError, match="only Chinese and English"):
        l85.finding_queries(findings)
