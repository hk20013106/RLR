import json

import pytest

from research_loop.hypothesis_ledger import LedgerError
from research_loop.hypothesis_pool import build_pool
from research_loop.hypothesis_recall import create_recall
from research_loop.node_skips import ensure_l2_skip_receipt
from tests.native_v2_helpers import commit_v2
from tests.test_hypothesis_pool import _seed_rejected_hypothesis


def _finalize(ledger, result):
    con = ledger._connect(readonly=True)
    try:
        if con.execute(
            "SELECT 1 FROM committed_emissions WHERE delta_hash=?",
            (result.delta_hash,),
        ).fetchone():
            return
    finally:
        con.close()
    ledger.finalize_emission(
        result.delta_hash,
        artifact_sha256=result.delta_hash,
        receipt_sha256=result.delta_hash,
    )


def _write_l1_and_skip(project, _result):
    path = (
        project / "02_Agent_Notes" / "Einstein"
        / "C2_L1_einstein_delta.v2.json"
    )
    assert path.is_file()
    ensure_l2_skip_receipt(project, "C2", path)


def _source(project, ledger, hypothesis_id):
    record = next(
        item for item in build_pool(ledger)["records"]
        if item["hypothesis_id"] == hypothesis_id
    )
    artifact = create_recall(
        ledger,
        project,
        "C2",
        "2",
        query_text=record["statement"],
    )
    result = next(
        item for item in artifact["results"]
        if item["hypothesis_id"] == hypothesis_id
    )
    return record, artifact, result


def _commit_l1(ledger, project, hypothesis):
    return commit_v2(
        project,
        "C2",
        "L1",
        "Einstein",
        {
            "schema_version": "2.1",
            "hypotheses": [hypothesis],
            "primary_proposal_key": hypothesis["proposal_key"],
            "key_uncertainty": "whether the new basis resolves the old blocker",
        },
        round_id="2",
    )


def _basis():
    return {
        "basis_type": "NEW_EVIDENCE",
        "summary": "A larger independent data set is now available.",
        "evidence_ids": [],
        "artifact_refs": [],
        "changed_conditions": ["sample size increased"],
    }


def test_reactivate_reuses_version_and_creates_new_occurrence(tmp_path):
    project, ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record, artifact, recalled = _source(project, ledger, hypothesis_id)
    old_occurrence = recalled["source_occurrence_id"]

    result = _commit_l1(ledger, project, {
        "proposal_key": "p-reactivate",
        "origin": "REACTIVATE",
        "source_hypothesis_id": hypothesis_id,
        "source_occurrence_id": old_occurrence,
        "statement": record["statement"],
        "operationalization": record["operationalization"],
        "falsification_criteria": record["falsification_criteria"],
        "rationale": "Retest after new evidence became available.",
        "reactivation_basis": _basis(),
    })
    _finalize(ledger, result)

    item = result.normalized_delta["hypotheses"][0]
    assert item["origin"] == "REACTIVATE"
    assert item["hypothesis_id"] == hypothesis_id

    con = ledger._connect(readonly=True)
    try:
        occurrences = con.execute(
            "SELECT occurrence_id,candidate_id,round_id FROM occurrences "
            "WHERE hypothesis_id=? ORDER BY rowid",
            (hypothesis_id,),
        ).fetchall()
        assert len(occurrences) == 2
        assert occurrences[0]["occurrence_id"] == old_occurrence
        assert occurrences[1]["candidate_id"] == "C2"
        assert occurrences[1]["round_id"] == "2"
        assert occurrences[1]["occurrence_id"] != old_occurrence
        assert con.execute(
            "SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?",
            (old_occurrence,),
        ).fetchone()[0] == "REJECTED"
        assert con.execute(
            "SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?",
            (occurrences[1]["occurrence_id"],),
        ).fetchone()[0] == "PROPOSED"
        event = con.execute(
            "SELECT event_type,payload_json FROM events WHERE commit_seq=?",
            (result.commit_seq,),
        ).fetchone()
        assert event["event_type"] == "REPROPOSED"
        payload = json.loads(event["payload_json"])
        assert payload["source_hypothesis_id"] == hypothesis_id
        assert payload["source_occurrence_id"] == old_occurrence
        assert payload["recall_artifact_hash"] == artifact["artifact_hash"]
    finally:
        con.close()


def test_revise_creates_new_version_in_same_family(tmp_path):
    project, ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record, _artifact, recalled = _source(project, ledger, hypothesis_id)

    result = _commit_l1(ledger, project, {
        "proposal_key": "p-revise",
        "origin": "REVISE",
        "source_hypothesis_id": hypothesis_id,
        "source_occurrence_id": recalled["source_occurrence_id"],
        "statement": record["statement"],
        "operationalization": record["operationalization"] + " with covariate adjustment",
        "falsification_criteria": record["falsification_criteria"],
        "rationale": "Retest with a more specific operationalization.",
        "change_summary": "Add explicit covariate adjustment.",
    })
    _finalize(ledger, result)

    item = result.normalized_delta["hypotheses"][0]
    assert item["origin"] == "REVISE"
    assert item["hypothesis_id"] != hypothesis_id
    assert item["hypothesis_family_id"] == record["hypothesis_family_id"]
    con = ledger._connect(readonly=True)
    try:
        event = con.execute(
            "SELECT event_type,payload_json FROM events WHERE commit_seq=?",
            (result.commit_seq,),
        ).fetchone()
        assert event["event_type"] == "REVISED"
        assert json.loads(event["payload_json"])["source_hypothesis_id"] == hypothesis_id
    finally:
        con.close()


def test_derive_creates_linked_new_family(tmp_path):
    project, ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record, _artifact, _recalled = _source(project, ledger, hypothesis_id)

    result = _commit_l1(ledger, project, {
        "proposal_key": "p-derive",
        "origin": "DERIVE",
        "parent_hypothesis_ids": [hypothesis_id],
        "statement": record["statement"] + " specifically in atrial tissue",
        "operationalization": record["operationalization"],
        "falsification_criteria": record["falsification_criteria"],
        "rationale": "Test a tissue-specific derivative.",
        "change_summary": "Restrict the claim to atrial tissue.",
    })
    _finalize(ledger, result)

    item = result.normalized_delta["hypotheses"][0]
    assert item["origin"] == "DERIVE"
    assert item["hypothesis_id"] != hypothesis_id
    assert item["hypothesis_family_id"] != record["hypothesis_family_id"]
    con = ledger._connect(readonly=True)
    try:
        event = con.execute(
            "SELECT event_type,payload_json FROM events WHERE commit_seq=?",
            (result.commit_seq,),
        ).fetchone()
        assert event["event_type"] == "DERIVED"
        assert json.loads(event["payload_json"])["parent_hypothesis_ids"] == [
            hypothesis_id
        ]
    finally:
        con.close()


def test_non_new_source_must_be_in_bound_recall(tmp_path):
    project, ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record = next(
        item for item in build_pool(ledger)["records"]
        if item["hypothesis_id"] == hypothesis_id
    )
    create_recall(
        ledger,
        project,
        "C2",
        "2",
        query_text="a query deliberately unrelated to the historical statement",
    )

    with pytest.raises(LedgerError, match="bound recall"):
        _commit_l1(ledger, project, {
            "proposal_key": "p-reactivate",
            "origin": "REACTIVATE",
            "source_hypothesis_id": hypothesis_id,
            "source_occurrence_id": record["latest_occurrence"]["occurrence_id"],
            "statement": record["statement"],
            "operationalization": record["operationalization"],
            "falsification_criteria": record["falsification_criteria"],
            "rationale": "fixture",
            "reactivation_basis": _basis(),
        })


def test_reactivate_requires_exact_definition(tmp_path):
    project, ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record, _artifact, recalled = _source(project, ledger, hypothesis_id)

    with pytest.raises(LedgerError, match="exact historical definition"):
        _commit_l1(ledger, project, {
            "proposal_key": "p-reactivate",
            "origin": "REACTIVATE",
            "source_hypothesis_id": hypothesis_id,
            "source_occurrence_id": recalled["source_occurrence_id"],
            "statement": record["statement"],
            "operationalization": record["operationalization"] + " changed",
            "falsification_criteria": record["falsification_criteria"],
            "rationale": "fixture",
            "reactivation_basis": _basis(),
        })


def test_revise_must_change_the_definition(tmp_path):
    project, ledger, hypothesis_id = _seed_rejected_hypothesis(tmp_path)
    record, _artifact, recalled = _source(project, ledger, hypothesis_id)

    with pytest.raises(LedgerError, match="must change"):
        _commit_l1(ledger, project, {
            "proposal_key": "p-revise",
            "origin": "REVISE",
            "source_hypothesis_id": hypothesis_id,
            "source_occurrence_id": recalled["source_occurrence_id"],
            "statement": record["statement"],
            "operationalization": record["operationalization"],
            "falsification_criteria": record["falsification_criteria"],
            "rationale": "fixture",
            "change_summary": "No actual change.",
        })


def test_l3_records_reactivation_review_without_erasing_disposition(tmp_path):
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
    blocker_ids = recalled["unresolved_blocker_event_ids"]

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
                "reason": "New evidence resolves the main objection.",
                "assessments": {
                    field: {"verdict": "PASS", "evidence": "fixture"}
                    for field in ("testability", "novelty", "feasibility", "impact")
                },
                "reactivation_assessment": {
                    "source_hypothesis_id": hypothesis_id,
                    "prior_blocking_event_ids": blocker_ids,
                    "basis_verdict": "RESOLVED",
                    "reason": "The larger data set addresses the prior concern.",
                    "remaining_risks": [],
                },
            }],
            "route_to": "Fisher",
        },
        delta_path=project / "02_Agent_Notes" / "Oppenheimer" / "C2_L3.json",
    )
    _finalize(ledger, l3)

    con = ledger._connect(readonly=True)
    try:
        events = con.execute(
            "SELECT event_type,payload_json FROM events WHERE commit_seq=? "
            "ORDER BY rowid",
            (l3.commit_seq,),
        ).fetchall()
        assert [row["event_type"] for row in events] == [
            "REACTIVATION_REVIEWED"
        ]
        payload = json.loads(events[0]["payload_json"])
        assert payload["disposition"] == "SELECTED"
        occurrence = con.execute(
            "SELECT occurrence_id FROM occurrences WHERE hypothesis_id=? "
            "AND candidate_id='C2' AND round_id='2'",
            (hypothesis_id,),
        ).fetchone()[0]
        assert con.execute(
            "SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?",
            (occurrence,),
        ).fetchone()[0] == "SELECTED"
    finally:
        con.close()
