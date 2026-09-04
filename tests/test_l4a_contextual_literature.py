import pytest
from types import SimpleNamespace

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p
from research_loop.l4_contextual_literature import (
    _contextual_command,
    _contextual_prompt,
    _contextual_query_plan_schema,
    _validate_contextual_payload,
)


def _method(method_id="M07"):
    return {
        "method_id": method_id,
        "name": "Cross-species expression normalization",
        "purpose": "Compare orthologous expression across species.",
        "inventory_reason": "Required by the selected hypothesis.",
    }


def _planner_payload():
    return {
        "schema_version": "L4AContextualQueryPlan/v1",
        "queries": [{
            "query_id": "Q001",
            "query": "cross-species expression normalization RNA-seq comparative study",
            "purpose": "Find comparable studies for the unresolved analysis action.",
            "status": "planned",
            "receipt": "planner-only",
            "method_ids": ["M07"],
            "method_terms": ["cross-species expression normalization"],
            "context_terms": ["RNA-seq", "comparative study"],
        }],
    }


def _method_first_payload(method_id, method_terms, context_terms):
    return {
        "schema_version": "L4AContextualQueryPlan/v1",
        "queries": [{
            "query_id": "Q001",
            "query": " ".join([*method_terms, *context_terms]),
            "purpose": "Find the canonical method literature for one unresolved action.",
            "status": "planned",
            "receipt": "method-first planner",
            "method_ids": [method_id],
            "method_terms": list(method_terms),
            "context_terms": list(context_terms),
        }],
    }


def test_contextual_provider_wire_contract_contains_queries_not_papers():
    payload = _planner_payload()
    validated = _validate_contextual_payload(l4p, dr, payload, ["M07"])
    assert validated == payload
    assert "assets" not in validated

    payload["assets"] = []
    with pytest.raises(dr.DeepResearchError, match="assets"):
        _validate_contextual_payload(l4p, dr, payload, ["M07"])


def test_contextual_query_plan_schema_types_const_constrained_status():
    status_schema = (
        _contextual_query_plan_schema()["properties"]["queries"]["items"]["properties"]["status"]
    )
    assert status_schema == {"type": "string", "const": "planned"}


def test_contextual_query_plan_schema_requires_all_declared_query_fields():
    query_schema = _contextual_query_plan_schema()["properties"]["queries"]["items"]
    assert set(query_schema["required"]) == set(query_schema["properties"])


def test_contextual_prompt_is_planning_only_and_command_is_offline(tmp_path):
    prompt = _contextual_prompt("Q", "H", [_method()], "codex").casefold()
    assert "query planning" in prompt
    assert "return only contextual queries" in prompt
    assert "method-first" in prompt
    assert "one unresolved method per query" in prompt
    assert "method_terms" in prompt
    assert "context_terms" in prompt
    assert "do not copy the scientific question" in prompt
    assert "$academic-research-suite" not in prompt
    assert "doi" in prompt
    assert "paper title" in prompt

    command = _contextual_command(
        ["codex", "exec"], SimpleNamespace(backend="codex"), tmp_path
    )
    assert ["--sandbox", "read-only"] == command[2:4]
    assert 'web_search="disabled"' in command


@pytest.mark.parametrize(
    ("method_id", "method_terms", "context_terms", "expected_query"),
    [
        (
            "M15",
            ["gene set enrichment analysis", "GSEA", "pathway enrichment benchmark"],
            ["RNA-seq", "comparative study"],
            "gene set enrichment analysis GSEA pathway enrichment benchmark RNA-seq comparative study",
        ),
        (
            "M17",
            [
                "weighted gene co-expression network analysis",
                "WGCNA",
                "module preservation",
            ],
            ["RNA-seq", "cross-species"],
            "weighted gene co-expression network analysis WGCNA module preservation RNA-seq cross-species",
        ),
        (
            "M12",
            [
                "phylogenetic generalized least squares",
                "PGLS",
                "phylogenetic comparative method",
            ],
            ["comparative study"],
            "phylogenetic generalized least squares PGLS phylogenetic comparative method comparative study",
        ),
        (
            "M18",
            [
                "differential transcript usage",
                "DTU",
                "isoform switching",
            ],
            ["RNA-seq"],
            "differential transcript usage DTU isoform switching RNA-seq",
        ),
        (
            "M18",
            [
                "differential exon usage",
                "DEXSeq",
                "exon-level RNA-seq analysis",
            ],
            ["RNA-seq"],
            "differential exon usage DEXSeq exon-level RNA-seq analysis RNA-seq",
        ),
    ],
)
def test_method_first_query_contract_keeps_method_terms_ahead_of_limited_context(
    method_id, method_terms, context_terms, expected_query
):
    payload = _method_first_payload(method_id, method_terms, context_terms)
    validated = _validate_contextual_payload(l4p, dr, payload, [method_id])
    query = validated["queries"][0]

    assert query["query"] == expected_query
    assert query["query"].split()[: len(" ".join(method_terms).split())] == (
        " ".join(method_terms).split()
    )
    assert len(context_terms) <= 2
    assert not any(
        term in query["query"].casefold()
        for term in ("cardiac", "calcium", "high heart rate", "ecm")
    )


def test_method_first_query_contract_rejects_extra_biological_context():
    payload = _method_first_payload(
        "M15",
        ["gene set enrichment analysis", "GSEA", "pathway enrichment benchmark"],
        ["RNA-seq", "comparative study"],
    )
    payload["queries"][0]["query"] += " cardiac calcium high heart rate ECM"

    with pytest.raises(dr.DeepResearchError, match="method_terms.*context_terms"):
        _validate_contextual_payload(l4p, dr, payload, ["M15"])
