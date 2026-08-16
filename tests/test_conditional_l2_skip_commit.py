import hashlib
import json

from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.node_skips import ensure_l2_skip_receipt
from tests.native_v2_helpers import commit_v2, seed_revise_continuation


def test_verified_l2_skip_authorizes_l3_commit(tmp_path, monkeypatch):
    store = tmp_path / "ledger.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    project = tmp_path / "project"
    project.mkdir()
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)

    l1 = commit_v2(project, "C1", "L1", "Einstein", {
        "schema_version": "2.1",
        "hypotheses": [{
            "proposal_key": "p1",
            "statement": "One focused hypothesis",
            "operationalization": "Measure one outcome",
            "falsification_criteria": ["The outcome is absent"],
            "rationale": "fixture",
        }],
        "primary_proposal_key": "p1",
        "key_uncertainty": "effect size",
    })
    hypothesis_id = l1.normalized_delta["primary_hypothesis_id"]
    l1_path = (
        project / "02_Agent_Notes" / "Einstein"
        / "C1_L1_einstein_delta.v2.json"
    )
    ensure_l2_skip_receipt(project, "C1", l1_path)

    l3 = commit_v2(project, "C1", "L3", "Oppenheimer", {
        "schema_version": "2.1",
        "triage": [{
            "hypothesis_id": hypothesis_id,
            "disposition": "SELECTED",
            "reason_code": "TESTABLE",
            "reason": "The focused hypothesis is directly testable.",
            "assessments": {
                field: {"verdict": "PASS", "evidence": "fixture"}
                for field in ("testability", "novelty", "feasibility", "impact")
            },
        }],
        "route_to": "Fisher",
    })

    assert l3.normalized_delta["triage"][0]["disposition"] == "SELECTED"


def test_l3_continuation_successor_does_not_expand_finalized_l1_set(
    tmp_path, monkeypatch
):
    """A valid L0 continuation occurrence is not a Round 2 L1 triage item."""
    store = tmp_path / "ledger.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    project = tmp_path / "project"
    project.mkdir()
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)

    memory_path = seed_revise_continuation(project, "PARENT")
    memory_hash = hashlib.sha256(memory_path.read_bytes()).hexdigest()
    successor_id = json.loads(memory_path.read_text(encoding="utf-8"))[
        "next_round_hypothesis_id"
    ]
    successor_occurrence = ledger.create_continuation_occurrence(
        project_dir=project,
        candidate_id="C1",
        round_id="2",
        hypothesis_id=successor_id,
        memory_path=memory_path,
        memory_hash=memory_hash,
    )

    l1 = commit_v2(project, "C1", "L1", "Einstein", {
        "schema_version": "2.1",
        "hypotheses": [
            {
                "proposal_key": "p1",
                "statement": "Round 2 primary hypothesis",
                "operationalization": "Measure the primary outcome",
                "falsification_criteria": ["The primary outcome is absent"],
                "rationale": "fixture",
            },
            {
                "proposal_key": "p2",
                "statement": "Round 2 secondary hypothesis",
                "operationalization": "Measure the secondary outcome",
                "falsification_criteria": ["The secondary outcome is absent"],
                "rationale": "fixture",
            },
        ],
        "primary_proposal_key": "p1",
        "key_uncertainty": "effect size",
    }, round_id="2")
    l1_path = (
        project / "02_Agent_Notes" / "Einstein"
        / "C1_L1_einstein_delta.v2.json"
    )
    ensure_l2_skip_receipt(project, "C1", l1_path)

    triage = []
    for item in l1.normalized_delta["hypotheses"]:
        triage.append({
            "hypothesis_id": item["hypothesis_id"],
            "disposition": "SELECTED",
            "reason_code": "TESTABLE",
            "reason": "The finalized Round 2 L1 hypothesis is testable.",
            "assessments": {
                field: {"verdict": "PASS", "evidence": "fixture"}
                for field in ("testability", "novelty", "feasibility", "impact")
            },
        })

    l3 = commit_v2(project, "C1", "L3", "Oppenheimer", {
        "schema_version": "2.1",
        "triage": triage,
        "route_to": "Fisher",
    }, round_id="2")

    assert [item["hypothesis_id"] for item in l3.normalized_delta["triage"]] == [
        item["hypothesis_id"] for item in l1.normalized_delta["hypotheses"]
    ]
    con = ledger._connect(readonly=True)
    try:
        workflow = con.execute(
            "SELECT workflow_status FROM workflow_projection "
            "WHERE occurrence_id=?",
            (successor_occurrence,),
        ).fetchone()
    finally:
        con.close()
    assert workflow[0] == "PROPOSED"
