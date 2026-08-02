import os

from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.hypothesis_pool import build_pool
from tests.native_v2_helpers import commit_v2


def _seed_rejected_hypothesis(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    ledger.bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)

    l1 = commit_v2(project, "C1", "L1", "Einstein", {
        "schema_version": "2.1",
        "hypotheses": [
            {
                "proposal_key": f"p{index}",
                "statement": (
                    "Extracellular-matrix expression declines with elevated heart rate"
                    if index == 0 else f"Alternative hypothesis {index}"
                ),
                "operationalization": f"Measure outcome {index}",
                "falsification_criteria": [f"Outcome {index} is absent"],
                "rationale": "pool projection fixture",
            }
            for index in range(5)
        ],
        "primary_proposal_key": "p0",
        "key_uncertainty": "effect magnitude",
    })
    hypotheses = l1.normalized_delta["hypotheses"]
    rejected_id = hypotheses[0]["hypothesis_id"]

    commit_v2(project, "C1", "L2", "Feynman", {
        "schema_version": "2.1",
        "attacks": [{
            "hypothesis_id": rejected_id,
            "severity": "HIGH",
            "text": "The observed pattern may be caused by tissue composition.",
        }],
        "confounders": [],
        "diagnostic_tests": [],
        "verdicts": [
            {
                "hypothesis_id": item["hypothesis_id"],
                "outcome": "REJECT" if index < 3 else "SURVIVES",
                "reason": "fixture verdict",
            }
            for index, item in enumerate(hypotheses)
        ],
    })

    commit_v2(project, "C1", "L3", "Oppenheimer", {
        "schema_version": "2.1",
        "triage": [
            {
                "hypothesis_id": item["hypothesis_id"],
                "disposition": "SELECTED" if index == 4 else "REJECTED",
                "reason_code": "TESTABLE" if index == 4 else "INSUFFICIENT_EVIDENCE",
                "reason": "fixture triage",
                "assessments": {
                    field: {
                        "verdict": "PASS" if index == 4 else "FAIL",
                        "evidence": "fixture assessment",
                    }
                    for field in ("testability", "novelty", "feasibility", "impact")
                },
            }
            for index, item in enumerate(hypotheses)
        ],
        "route_to": "Fisher",
    })
    return project, ledger, rejected_id


def test_pool_keeps_rejected_hypothesis_with_attack_history(tmp_path):
    _project, ledger, rejected_id = _seed_rejected_hypothesis(tmp_path)

    pool = build_pool(ledger)
    record = next(
        item for item in pool["records"]
        if item["hypothesis_id"] == rejected_id
    )

    assert record["occurrence_count"] == 1
    assert record["attack_count"] >= 1
    assert record["rejection_count"] == 1
    assert record["latest_workflow_status"] == "REJECTED"
    assert record["reactivation_eligibility"] == "ELIGIBLE_WITH_BASIS"
    assert record["last_rejection"]["round_id"] == "1"
