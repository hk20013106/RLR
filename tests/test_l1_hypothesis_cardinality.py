from research_loop.hypothesis_contracts import validate_submission


def _l1_delta(count: int) -> dict:
    hypotheses = [
        {
            "proposal_key": f"p{index}",
            "statement": f"Testable hypothesis {index}",
            "operationalization": f"Measure outcome {index}.",
            "falsification_criteria": [f"Outcome {index} is absent."],
            "rationale": "Cardinality regression fixture.",
        }
        for index in range(count)
    ]
    return {
        "schema_version": "2.1",
        "hypotheses": hypotheses,
        "primary_proposal_key": "p0" if hypotheses else "missing",
        "key_uncertainty": "effect size",
    }


def test_v21_l1_accepts_one_hypothesis():
    assert validate_submission(
        "L1", _l1_delta(1), schema_version="2.1"
    ) == []


def test_v21_l1_accepts_two_hypotheses():
    assert validate_submission(
        "L1", _l1_delta(2), schema_version="2.1"
    ) == []


def test_v21_l1_rejects_zero_hypotheses():
    errors = validate_submission("L1", _l1_delta(0), schema_version="2.1")

    assert any("hypotheses" in error and "too short" in error for error in errors)
