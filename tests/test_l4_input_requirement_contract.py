import pytest

from research_loop import deep_research as dr
from research_loop import l4_evidence_bundle as bundle
from research_loop.hypothesis_contracts import validate_provider_submission
from research_loop.method_contracts import validate_input_requirements


def _candidate(*, status="eligible", missing_inputs=None, missing_source=""):
    return {
        "method_id": "M1",
        "component_id": "MC1",
        "hypothesis_ids": ["H1"],
        "name": "diagnostic",
        "status": status,
        "purpose": "test",
        "applicable_to": ["sample metadata"],
        "implementation_steps": ["inspect design matrix"],
        "assumptions": [],
        "expected_outputs": ["diagnostic report"],
        "strengths": [],
        "limitations": [],
        "alternatives": [],
        "method_anchor_handles": [],
        "evidence_card_handles": [],
        "evidence_gap_handles": [],
        "required_inputs": ["sample metadata"],
        "optional_diagnostics": ["RNA quality"],
        "missing_inputs": list(missing_inputs or []),
        "rejection_reasons": [],
        "missing_source": missing_source,
        "execution_required": True,
    }


def _delta(candidate):
    return {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": "RUN1",
        "strategies": [{
            "strategy_id": "S1",
            "hypothesis_ids": ["H1"],
            "name": "strategy",
            "steps": ["run"],
        }],
        "method_components": [{
            "component_id": "MC1",
            "name": "diagnostic",
            "required": True,
            "rationale": "required",
        }],
        "method_candidates": [candidate],
    }


def _evidence_artifact():
    return {
        "run_id": "RUN1",
        "evidence_cards": [{
            "evidence_card_id": "CARD1",
            "method_id": "M1",
            "anchor_id": "ANCHOR1",
            "status": "accepted",
        }],
        "evidence_gaps": [],
    }


def test_catalog_provider_requires_explicit_input_classification():
    errors = validate_provider_submission(
        "L4",
        _delta(_candidate(status="needs_user_source", missing_source="exact method evidence")),
        schema_version="2.1",
        profile_id="v2.1-catalog-1",
    )
    assert errors == []


def test_data_gap_status_is_distinct_from_source_gap():
    candidate = _candidate(status="needs_user_data", missing_inputs=["sample metadata"])
    errors = validate_provider_submission(
        "L4",
        _delta(candidate),
        schema_version="2.1",
        profile_id="v2.1-catalog-1",
    )
    assert errors == []


def test_source_gap_cannot_carry_missing_data():
    candidate = _candidate(status="needs_user_source", missing_inputs=["sample metadata"])
    with pytest.raises(ValueError, match="needs_user_source.*missing_inputs"):
        validate_input_requirements(candidate)


def test_required_and_optional_inputs_cannot_overlap():
    candidate = _candidate()
    candidate["optional_diagnostics"] = ["Sample metadata"]
    with pytest.raises(ValueError, match="overlap"):
        validate_input_requirements(candidate)


def test_data_gap_cannot_be_disguised_as_source_gap():
    candidate = _candidate(status="needs_user_data", missing_inputs=["sample metadata"])
    candidate["missing_source"] = "Provide a method PDF"
    with pytest.raises(ValueError, match="needs_user_data.*missing_source"):
        validate_input_requirements(candidate)


def test_reference_binding_rejects_overlapping_input_classification():
    candidate = _candidate()
    candidate["evidence_card_handles"] = ["E1"]
    candidate["optional_diagnostics"] = ["sample metadata"]

    with pytest.raises(dr.DeepResearchError, match="overlap"):
        bundle.resolve_l4c_reference_handles(
            _evidence_artifact(),
            _delta(candidate),
        )


def test_required_path_does_not_accept_needs_user_data_candidate():
    candidate = _candidate(
        status="needs_user_data",
        missing_inputs=["sample metadata"],
    )
    evidence = {
        "run_id": "RUN1",
        "evidence_cards": [],
        "evidence_gaps": [],
    }

    with pytest.raises(
        dr.DeepResearchError,
        match="MC1 lacks an eligible execution-required candidate",
    ):
        bundle._validate_required_paths(dr, evidence, _delta(candidate))
