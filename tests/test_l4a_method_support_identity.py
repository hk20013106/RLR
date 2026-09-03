import copy
import json
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l4_contextual_literature as contextual
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p


def _method(method_id: str, name: str) -> dict:
    return {
        "method_id": method_id,
        "name": name,
        "purpose": f"Use {name} for the selected scientific question.",
        "inventory_reason": f"{name} is required by the selected hypothesis.",
        "source_asset_ids": [],
        "source_hints": [],
    }


def _record(paper_id: str, title: str | None = None, query_ids=None) -> dict:
    return {
        "paper_id": paper_id,
        "title": title or f"{paper_id} method study",
        "identifiers": {"doi": f"10.1000/{paper_id.casefold()}"},
        "metadata": {
            "abstract": f"The abstract for {paper_id} evaluates the target method.",
            "journal": "Methods Journal",
            "year": "2024",
            "authors": "Researcher",
            "publication_types": ["journal-article"],
        },
        "provenance": {
            "provider": "fixture",
            "originating_query_ids": list(query_ids or ["Q001"]),
            "source_records": [{"provider": "fixture"}],
        },
    }


def _selection(*pairs: tuple[str, str]) -> dict:
    return {
        "pairs": [
            {
                "paper_id": paper_id,
                "method_id": method_id,
                "semantic_score": 0.9,
                "semantic_rank": index,
                "selector_decision": "INCLUDE",
            }
            for index, (paper_id, method_id) in enumerate(pairs, 1)
        ]
    }


def _wire(*classifications: str) -> dict:
    return {
        "schema_version": contextual.METHOD_SUPPORT_SCHEMA_VERSION,
        "decisions": [
            {
                "classification": classification,
                "rationale": f"Metadata-only rationale {index}.",
            }
            for index, classification in enumerate(classifications, 1)
        ],
    }


def _prompt_payload(prompt: str) -> dict:
    marker = "Supplied one-method L4A metadata:\n"
    payload_text = prompt.split(marker, 1)[1].split(
        "\n\nReturn JSON", 1
    )[0]
    return json.loads(payload_text)


def _run(
    monkeypatch,
    tmp_path,
    methods,
    records,
    selection,
    wire_payloads,
):
    calls = []
    payloads = list(wire_payloads)
    spec = dr.RuntimeSpec(
        "codex", "codex", model="configured-model", timeout=3
    )

    def build_invocation(_spec, _node, _question, _claim, work_dir):
        return [
            "codex",
            "exec",
            "--output-schema",
            str(work_dir / "deep_research_output.schema.json"),
            "--model",
            "configured-model",
        ], "unused"

    monkeypatch.setattr(dr, "build_invocation", build_invocation)
    monkeypatch.setattr(dr, "resolve_subprocess_executable", lambda value: value)

    def subprocess_invocation(command, prompt):
        calls.append({"command": list(command), "prompt": prompt})
        return command, {}

    monkeypatch.setattr(dr, "subprocess_invocation", subprocess_invocation)
    monkeypatch.setattr(
        dr,
        "execute_provider_invocation",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payloads.pop(0)),
            stderr="",
        ),
    )
    monkeypatch.setattr(
        dr,
        "skill_receipt",
        lambda *args, **kwargs: {
            "provider": "codex",
            "model": "configured-model",
        },
    )

    result = contextual._run_method_support_adjudication(
        l4p,
        dr,
        tmp_path,
        "C1",
        "question",
        "claim",
        spec,
        tmp_path / "work",
        "fixture",
        methods,
        records,
        selection,
        inventory_module=l4_inventory,
    )
    return result, calls


def test_caller_owned_pair_identity_is_restored_by_ordered_zip(
    tmp_path, monkeypatch
):
    methods = [_method("M10", "Hierarchical mixed-effects modeling")]
    records = [
        _record("P_A", "Candidate A"),
        _record("P_B", "Candidate B"),
        _record("P_C", "Candidate C"),
    ]
    result, _ = _run(
        monkeypatch,
        tmp_path,
        methods,
        records,
        _selection(("P_A", "M10"), ("P_B", "M10"), ("P_C", "M10")),
        [_wire(
            "DIRECT_METHOD_SUPPORT",
            "RELATED_BUT_NOT_METHOD_SUPPORT",
            "INSUFFICIENT_METADATA",
        )],
    )

    assert [
        (item["paper_id"], item["method_id"])
        for item in result["decisions"]
    ] == [("P_A", "M10"), ("P_B", "M10"), ("P_C", "M10")]
    assert [item["classification"] for item in result["decisions"]] == [
        "DIRECT_METHOD_SUPPORT",
        "RELATED_BUT_NOT_METHOD_SUPPORT",
        "INSUFFICIENT_METADATA",
    ]


def test_method_support_wire_contract_has_no_identity_fields():
    decision_schema = contextual._method_support_schema()["properties"][
        "decisions"
    ]["items"]

    assert set(decision_schema["properties"]) == {
        "classification",
        "rationale",
    }
    assert "paper_id" not in decision_schema["properties"]
    assert "method_id" not in decision_schema["properties"]
    assert set(decision_schema["required"]) == {
        "classification",
        "rationale",
    }


@pytest.mark.parametrize("count", [4, 6])
def test_wrong_ordered_result_length_fails_closed(count):
    payload = _wire(*(["IRRELEVANT"] * count))

    with pytest.raises(dr.DeepResearchError, match="decision count"):
        contextual._validate_method_support_payload(dr, payload, 5)


def test_per_method_calls_are_isolated_and_cannot_cross_attach(tmp_path, monkeypatch):
    methods = [
        _method("M10", "M10 target method"),
        _method("M11", "M11 target method"),
    ]
    records = [
        _record("P10_A", "M10 paper A"),
        _record("P10_B", "M10 paper B"),
        _record("P11_A", "M11 paper A"),
        _record("P11_B", "M11 paper B"),
    ]
    result, calls = _run(
        monkeypatch,
        tmp_path,
        methods,
        records,
        _selection(
            ("P10_A", "M10"),
            ("P10_B", "M10"),
            ("P11_A", "M11"),
            ("P11_B", "M11"),
        ),
        [
            _wire("DIRECT_METHOD_SUPPORT", "IRRELEVANT"),
            _wire("RELATED_BUT_NOT_METHOD_SUPPORT", "INSUFFICIENT_METADATA"),
        ],
    )

    assert len(calls) == 2
    assert "M10 target method" in calls[0]["prompt"]
    assert "M11 target method" not in calls[0]["prompt"]
    assert "paper_id" not in _prompt_payload(calls[0]["prompt"])
    assert "method_id" not in _prompt_payload(calls[0]["prompt"])
    assert "M11 target method" in calls[1]["prompt"]
    assert "M10 target method" not in calls[1]["prompt"]
    assert "paper_id" not in _prompt_payload(calls[1]["prompt"])
    assert "method_id" not in _prompt_payload(calls[1]["prompt"])
    assert [batch["method_id"] for batch in result["method_batches"]] == [
        "M10",
        "M11",
    ]
    assert [
        (item["paper_id"], item["method_id"])
        for item in result["decisions"]
    ] == [
        ("P10_A", "M10"),
        ("P10_B", "M10"),
        ("P11_A", "M11"),
        ("P11_B", "M11"),
    ]


def test_direct_only_binding_is_preserved_after_ordered_adjudication(
    tmp_path, monkeypatch
):
    methods = [_method("M10", "Target method")]
    records = [_record("P_A"), _record("P_B"), _record("P_C")]
    result, _ = _run(
        monkeypatch,
        tmp_path,
        methods,
        records,
        _selection(("P_A", "M10"), ("P_B", "M10"), ("P_C", "M10")),
        [_wire(
            "DIRECT_METHOD_SUPPORT",
            "RELATED_BUT_NOT_METHOD_SUPPORT",
            "INSUFFICIENT_METADATA",
        )],
    )

    inventory, assets, selected_ids = contextual._bind_selected_records(
        methods,
        records,
        _selection(("P_A", "M10"), ("P_B", "M10"), ("P_C", "M10")),
        result,
        {"sources": []},
        l4_inventory,
    )

    assert inventory[0]["source_asset_ids"] == ["P_A"]
    assert assets[0]["method_component_hints"] == ["M10"]
    assert selected_ids == ["P_A", "P_B", "P_C"]


def test_zero_direct_remains_legal(tmp_path, monkeypatch):
    methods = [_method("M10", "Target method")]
    records = [_record("P_A"), _record("P_B")]
    result, _ = _run(
        monkeypatch,
        tmp_path,
        methods,
        records,
        _selection(("P_A", "M10"), ("P_B", "M10")),
        [_wire("RELATED_BUT_NOT_METHOD_SUPPORT", "INSUFFICIENT_METADATA")],
    )

    inventory, assets, selected_ids = contextual._bind_selected_records(
        methods,
        records,
        _selection(("P_A", "M10"), ("P_B", "M10")),
        result,
        {"sources": []},
        l4_inventory,
    )

    assert inventory[0]["source_asset_ids"] == []
    assert all(item["method_component_hints"] == [] for item in assets)
    assert selected_ids == ["P_A", "P_B"]


def test_mult_query_provenance_is_not_mutated_by_adjudication(tmp_path, monkeypatch):
    record = _record("P_CROSS", query_ids=["Q001", "Q003"])
    before = copy.deepcopy(record["provenance"])
    result, _ = _run(
        monkeypatch,
        tmp_path,
        [_method("M10", "Target method")],
        [record],
        _selection(("P_CROSS", "M10")),
        [_wire("DIRECT_METHOD_SUPPORT")],
    )

    assert record["provenance"] == before
    assert result["decisions"][0]["paper_id"] == "P_CROSS"
    assert result["decisions"][0]["method_id"] == "M10"
