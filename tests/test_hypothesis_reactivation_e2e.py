import json

from research_loop.hypothesis_pool import build_pool
from tests.test_hypothesis_reactivation_consumers import _selected_reactivation


def test_rejected_hypothesis_can_return_without_erasing_history(tmp_path):
    _project, ledger, hypothesis_id = _selected_reactivation(tmp_path)

    record = next(
        item for item in build_pool(ledger)["records"]
        if item["hypothesis_id"] == hypothesis_id
    )

    assert record["occurrence_count"] == 2
    assert record["attack_count"] >= 1
    assert record["rejection_count"] == 1
    assert record["occurrences"][0]["workflow_status"] == "REJECTED"
    assert record["occurrences"][1]["workflow_status"] == "SELECTED"
    assert record["latest_workflow_status"] == "SELECTED"
    assert record["unresolved_blocker_event_ids"] == []

    con = ledger._connect(readonly=True)
    try:
        rows = con.execute(
            "SELECT event_type,payload_json FROM events "
            "WHERE hypothesis_id=? ORDER BY commit_seq,event_id",
            (hypothesis_id,),
        ).fetchall()
    finally:
        con.close()

    event_types = [row["event_type"] for row in rows]
    assert "ATTACKED" in event_types
    assert "REJECTED" in event_types
    assert "REPROPOSED" in event_types
    assert "REACTIVATION_REVIEWED" in event_types
    review = next(
        json.loads(row["payload_json"])
        for row in rows
        if row["event_type"] == "REACTIVATION_REVIEWED"
    )
    assert review["disposition"] == "SELECTED"
    assert review["reactivation_assessment"]["basis_verdict"] == "RESOLVED"
