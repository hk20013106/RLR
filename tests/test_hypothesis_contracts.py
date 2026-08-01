import pytest

from research_loop.hypothesis_contracts import NODE_SCHEMAS, validate_submission_legacy


def _errors(node, payload):
    return "\n".join(validate_submission_legacy(node, {"schema_version": "2.0", **payload}))


def test_node_schemas_cover_the_complete_dag():
    assert set(NODE_SCHEMAS) == {
        "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8",
        "L8.5", "L9a", "L9b", "L10a", "L10b",
    }


@pytest.mark.parametrize(
    ("node", "payload", "missing"),
    [
        ("L2", {"attacks": [], "confounders": [], "diagnostic_tests": []}, "verdicts"),
        ("L5", {"attacks": [], "qc_checkpoints": []}, "failure_stop_rules"),
        ("L8.5", {"deep_research_run_id": "R", "assessments": [], "summary": "s"},
         "deep_research_receipt_hash"),
        ("L9b", {"assessments": [{"hypothesis_id": "H", "interpretation": "i",
                                     "evidence_ids": [], "limitations": []}]},
         "convergent_evolution"),
        ("L10a", {"assessments": [{"hypothesis_id": "H", "value_assessment": "v",
                                      "headline": "h", "publishable_now": [],
                                      "needs_more_work": []}]},
         "manuscript_framing"),
    ],
)
def test_completed_node_contracts_fail_closed_on_missing_required_fields(node, payload, missing):
    assert missing in _errors(node, payload)


def test_l2_contract_uses_per_hypothesis_verdicts_not_candidate_verdict():
    errors = _errors("L2", {
        "attacks": [], "confounders": [], "diagnostic_tests": [],
        "verdict": "SURVIVES",
    })
    assert "verdicts" in errors


def test_target_lists_reject_duplicate_hypothesis_ids():
    errors = _errors("L5", {
        "attacks": [{"hypothesis_ids": ["H:1", "H:1"], "strategy_id": "S1",
                     "severity": "HIGH", "text": "attack"}],
        "qc_checkpoints": [], "failure_stop_rules": [],
    })
    assert "non-unique" in errors
