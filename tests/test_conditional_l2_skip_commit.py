from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.node_skips import ensure_l2_skip_receipt
from tests.native_v2_helpers import commit_v2


def test_verified_l2_skip_authorizes_l3_commit(tmp_path, monkeypatch):
    store = tmp_path / "ledger.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    project = tmp_path / "project"
    project.mkdir()
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id="v2.1-native-1")

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
