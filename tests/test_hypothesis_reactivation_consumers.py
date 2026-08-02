from tests.test_hypothesis_pool import _seed_rejected_hypothesis
from tests.test_hypothesis_reactivation_lifecycle import (
    _basis,
    _commit_l1,
    _finalize,
    _source,
    _write_l1_and_skip,
)


def _selected_reactivation(tmp_path):
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
    _write_l1_and_skip(project, l1)
    l3 = ledger.commit_delta(
        project_dir=project,
        candidate_id="C2",
        round_id="2",
        node="L3",
        persona="Oppenheimer",
        delta={
            "schema_version": "2.1",
            "triage": [{
                "hypothesis_id": hypothesis_id,
                "disposition": "SELECTED",
                "reason_code": "TESTABLE",
                "reason": "The prior blocker is resolved.",
                "assessments": {
                    field: {"verdict": "PASS", "evidence": "fixture"}
                    for field in ("testability", "novelty", "feasibility", "impact")
                },
                "reactivation_assessment": {
                    "source_hypothesis_id": hypothesis_id,
                    "prior_blocking_event_ids": recalled[
                        "unresolved_blocker_event_ids"
                    ],
                    "basis_verdict": "RESOLVED",
                    "reason": "New evidence addresses the prior concern.",
                    "remaining_risks": [],
                },
            }],
            "route_to": "Fisher",
        },
        delta_path=(
            project / "02_Agent_Notes" / "Oppenheimer" / "C2_L3.json"
        ),
    )
    _finalize(ledger, l3)
    return project, ledger, hypothesis_id


def test_l4_recognizes_selected_reactivation(tmp_path):
    project, ledger, hypothesis_id = _selected_reactivation(tmp_path)

    l4 = ledger.commit_delta(
        project_dir=project,
        candidate_id="C2",
        round_id="2",
        node="L4",
        persona="Fisher",
        delta={
            "schema_version": "2.1",
            "strategies": [{
                "strategy_id": "S1",
                "hypothesis_ids": [hypothesis_id],
                "name": "Focused analysis",
                "steps": ["estimate the effect"],
            }],
        },
        delta_path=project / "02_Agent_Notes" / "Fisher" / "C2_L4.json",
    )

    assert l4.normalized_delta["strategies"][0]["hypothesis_ids"] == [
        hypothesis_id
    ]


def test_ranking_inputs_include_reactivated_candidate_and_review(tmp_path):
    project, ledger, hypothesis_id = _selected_reactivation(tmp_path)
    project_id = ledger.require_binding(project)["project_id"]

    payload = ledger.ranking_inputs(
        ["C2"], "L3", project_id=project_id
    )

    assert payload["candidates"][0]["hypothesis_id"] == hypothesis_id
    assert payload["formal_decisions"][0]["formal_decision"] == "SELECTED"


def test_projection_rebuild_understands_reactivation_events(tmp_path):
    _project, ledger, _hypothesis_id = _selected_reactivation(tmp_path)

    assert ledger.verify(rebuild=True) == []
