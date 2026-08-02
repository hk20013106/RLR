import pytest

from research_loop.hypothesis_ledger import LedgerError
from tests.test_hypothesis_pool import _seed_rejected_hypothesis
from tests.test_hypothesis_reactivation_lifecycle import (
    _basis,
    _commit_l1,
    _finalize,
    _source,
)


def test_l3_reactivation_source_must_match_l1_lineage(tmp_path):
    project, ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record, _artifact, recalled = _source(project, ledger, hypothesis_id)
    l1 = _commit_l1(ledger, project, {
        "proposal_key": "p-reactivate",
        "origin": "REACTIVATE",
        "source_hypothesis_id": hypothesis_id,
        "source_occurrence_id": recalled["source_occurrence_id"],
        "statement": record["statement"],
        "operationalization": record["operationalization"],
        "falsification_criteria": record["falsification_criteria"],
        "rationale": "fixture",
        "reactivation_basis": _basis(),
    })
    _finalize(ledger, l1)

    with pytest.raises(LedgerError, match="does not match L1 lineage"):
        ledger.commit_delta(
            project_dir=project,
            candidate_id="C2",
            round_id="2",
            node="L3",
            persona="Oppenheimer",
            delta={
                "schema_version": "2.1",
                "triage": [{
                    "hypothesis_id": hypothesis_id,
                    "disposition": "REJECTED",
                    "reason_code": "INSUFFICIENT_EVIDENCE",
                    "reason": "fixture",
                    "assessments": {
                        field: {"verdict": "PASS", "evidence": "fixture"}
                        for field in (
                            "testability", "novelty", "feasibility", "impact"
                        )
                    },
                    "reactivation_assessment": {
                        "source_hypothesis_id": "H:not-the-source",
                        "prior_blocking_event_ids": recalled[
                            "unresolved_blocker_event_ids"
                        ],
                        "basis_verdict": "UNRESOLVED",
                        "reason": "fixture",
                        "remaining_risks": ["confounding"],
                    },
                }],
                "route_to": "Fisher",
            },
            delta_path=(
                project / "02_Agent_Notes" / "Oppenheimer" / "C2_L3.json"
            ),
        )
