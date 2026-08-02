from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger


def test_new_l1_submission_persists_explicit_origin(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    ledger.bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)

    result = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node="L1",
        persona="Einstein",
        delta={
            "schema_version": "2.1",
            "hypotheses": [{
                "proposal_key": "p1",
                "statement": "A newly proposed hypothesis",
                "operationalization": "Measure the predicted outcome",
                "falsification_criteria": ["The predicted outcome is absent"],
                "rationale": "fixture",
            }],
            "primary_proposal_key": "p1",
            "key_uncertainty": "effect size",
        },
        delta_path=(
            project / "02_Agent_Notes" / "Einstein" / "C1_L1.json"
        ),
    )

    assert result.normalized_delta["hypotheses"][0]["origin"] == "NEW"
    con = ledger._connect(readonly=True)
    try:
        event = con.execute(
            "SELECT event_type,payload_json FROM events WHERE commit_seq=?",
            (result.commit_seq,),
        ).fetchone()
        assert event["event_type"] == "PROPOSED"
        assert '"origin":"NEW"' in event["payload_json"]
    finally:
        con.close()
