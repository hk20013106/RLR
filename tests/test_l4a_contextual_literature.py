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
            "query": "comparative transcriptomics cross species normalization",
            "purpose": "Find comparable studies for the unresolved analysis action.",
            "status": "planned",
            "receipt": "planner-only",
            "method_ids": ["M07"],
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
    assert "$academic-research-suite" not in prompt
    assert "doi" in prompt
    assert "paper title" in prompt

    command = _contextual_command(
        ["codex", "exec"], SimpleNamespace(backend="codex"), tmp_path
    )
    assert ["--sandbox", "read-only"] == command[2:4]
    assert 'web_search="disabled"' in command
