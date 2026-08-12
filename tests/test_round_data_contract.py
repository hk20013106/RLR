"""Round-level data declaration semantics for L0InputContract 1.1.

These tests deliberately stay below evidence restore/binding.  The L0 contract
owns declaration intent only: current-round source_input plus continuation-only
inherited selectors.  Exact previous-manifest authorization is tested in the
binding layer.
"""
from pathlib import Path

from research_loop import l0_contract


def _current_source(tmp_path: Path):
    path = tmp_path / "new.csv"
    path.write_text("sample,value\na,1\n", encoding="utf-8")
    return l0_contract.build_source_input(
        input_type="files",
        files=[str(path)],
        location=str(tmp_path),
        description="new round-N+1 measurements",
        fmt="csv",
    )


def _inherited_selector():
    return {
        "path": "04_Analysis_Outputs/result.json",
        "sha256": "a" * 64,
        "role": "prior_result",
        "reuse_reason": "reanalyze the verified round-N result",
    }


def _continuation(tmp_path: Path, *, source_input, inherited_inputs):
    return {
        "schema_version": "1.1",
        "round_type": "continuation",
        "round_id": "2",
        "parent_round_id": "1",
        "previous_candidate_id": "C1",
        "candidate_id": "C2",
        "scientific_question": "Does the revised analysis still support H?",
        "source_input": source_input,
        "inherited_inputs": inherited_inputs,
        "previous_round": {
            "candidate_id": "C1",
            "hypothesis": "H",
            "final_decision": "REVISE",
            "conclusion": "more data or reanalysis is required",
            "memory_hash": "memory-sha",
        },
        "current_round": {"hypothesis": "H revised"},
    }


def _validate(contract, tmp_path: Path):
    return l0_contract.validate_l0_input_contract(
        contract,
        {"from_memory": True, "memory_hash": "memory-sha"},
        tmp_path,
        "C2",
    )


def test_schema_11_continuation_allows_inherited_only(tmp_path):
    contract = _continuation(
        tmp_path, source_input=None, inherited_inputs=[_inherited_selector()]
    )
    assert _validate(contract, tmp_path) == []


def test_schema_11_continuation_allows_new_only(tmp_path):
    contract = _continuation(
        tmp_path, source_input=_current_source(tmp_path), inherited_inputs=[]
    )
    assert _validate(contract, tmp_path) == []


def test_schema_11_continuation_allows_inherited_plus_new(tmp_path):
    contract = _continuation(
        tmp_path,
        source_input=_current_source(tmp_path),
        inherited_inputs=[_inherited_selector()],
    )
    assert _validate(contract, tmp_path) == []


def test_schema_11_continuation_rejects_empty_authorized_union(tmp_path):
    contract = _continuation(tmp_path, source_input=None, inherited_inputs=[])
    errors = _validate(contract, tmp_path)
    assert any("at least one" in error and "input" in error for error in errors), errors


def test_schema_11_initial_rejects_inherited_inputs(tmp_path):
    contract = l0_contract.build_initial_contract(
        "C1",
        "1",
        "Does X track Y?",
        _current_source(tmp_path),
        "X tracks Y",
    )
    contract["schema_version"] = "1.1"
    contract["inherited_inputs"] = [_inherited_selector()]
    errors = l0_contract.validate_l0_input_contract(
        contract, {}, tmp_path, "C1"
    )
    assert any("inherited_inputs" in error and "initial" in error for error in errors), errors


def test_schema_11_inherited_selector_requires_complete_shape(tmp_path):
    selector = _inherited_selector()
    selector.pop("role")
    contract = _continuation(
        tmp_path, source_input=None, inherited_inputs=[selector]
    )
    errors = _validate(contract, tmp_path)
    assert any("inherited_inputs[0].role" in error for error in errors), errors
