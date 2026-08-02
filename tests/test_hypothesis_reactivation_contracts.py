from copy import deepcopy

from research_loop.hypothesis_contracts import (
    validate_persisted,
    validate_submission,
)


def _hypothesis(**updates):
    item = {
        "proposal_key": "p0",
        "statement": "A historical hypothesis",
        "operationalization": "measure the effect",
        "falsification_criteria": ["the effect is absent"],
        "rationale": "fixture",
    }
    item.update(updates)
    return item


def _l1(item):
    return {
        "schema_version": "2.1",
        "hypotheses": [item],
        "primary_proposal_key": "p0",
        "key_uncertainty": "effect size",
    }


def test_l1_reactivate_requires_source_hypothesis_and_occurrence():
    errors = validate_submission(
        "L1",
        _l1(_hypothesis(origin="REACTIVATE")),
        schema_version="2.1",
    )

    assert any("source_hypothesis_id" in error for error in errors)
    assert any("source_occurrence_id" in error for error in errors)


def test_l1_new_forbids_historical_source_fields():
    errors = validate_submission(
        "L1",
        _l1(_hypothesis(
            origin="NEW",
            source_hypothesis_id="H:old",
            source_occurrence_id="HO:old",
        )),
        schema_version="2.1",
    )

    assert errors


def test_l1_revise_requires_source_and_change_summary():
    errors = validate_submission(
        "L1",
        _l1(_hypothesis(origin="REVISE")),
        schema_version="2.1",
    )

    assert any("source_hypothesis_id" in error for error in errors)
    assert any("change_summary" in error for error in errors)


def test_l1_derive_requires_parents_and_change_summary():
    errors = validate_submission(
        "L1",
        _l1(_hypothesis(origin="DERIVE")),
        schema_version="2.1",
    )

    assert any("parent_hypothesis_ids" in error for error in errors)
    assert any("change_summary" in error for error in errors)


def test_l1_omitted_origin_remains_submission_compatible():
    assert validate_submission(
        "L1", _l1(_hypothesis()), schema_version="2.1"
    ) == []


def test_persisted_l1_without_origin_remains_compatible():
    item = _hypothesis(
        hypothesis_id="H:new",
        hypothesis_family_id="HF:new",
    )
    delta = {
        **_l1(item),
        "candidate_id": "C1",
        "project_id": "PROJECT:1",
        "primary_hypothesis_id": "H:new",
    }

    assert validate_persisted("L1", delta, schema_version="2.1") == []


def _l3_item(**updates):
    item = {
        "hypothesis_id": "H:old",
        "disposition": "SELECTED",
        "reason_code": "TESTABLE",
        "reason": "fixture",
        "assessments": {
            field: {"verdict": "PASS", "evidence": "fixture"}
            for field in ("testability", "novelty", "feasibility", "impact")
        },
    }
    item.update(updates)
    return item


def _l3(item):
    return {
        "schema_version": "2.1",
        "triage": [item],
        "route_to": "Fisher",
    }


def test_l3_selected_unresolved_reactivation_is_schema_invalid():
    errors = validate_submission(
        "L3",
        _l3(_l3_item(reactivation_assessment={
            "source_hypothesis_id": "H:old",
            "prior_blocking_event_ids": ["HE:blocker"],
            "basis_verdict": "UNRESOLVED",
            "reason": "blocker remains",
            "remaining_risks": ["confounding"],
        })),
        schema_version="2.1",
    )

    assert errors


def test_l3_partial_resolution_requires_downstream_obligation():
    item = _l3_item(reactivation_assessment={
        "source_hypothesis_id": "H:old",
        "prior_blocking_event_ids": ["HE:blocker"],
        "basis_verdict": "PARTIALLY_RESOLVED",
        "reason": "residual risk remains",
        "remaining_risks": ["confounding"],
    })
    errors = validate_submission("L3", _l3(item), schema_version="2.1")
    assert errors

    valid = deepcopy(item)
    valid["downstream_obligations"] = [{
        "obligation_id": "RO1",
        "type": "QC",
        "description": "adjust for tissue composition",
        "source_blocker_event_ids": ["HE:blocker"],
    }]
    assert validate_submission(
        "L3", _l3(valid), schema_version="2.1"
    ) == []
