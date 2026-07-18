import json

import pytest

from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError
from research_loop.engine import main


def _commit(ledger, project, node, delta, *, candidate="C1", round_id="1"):
    return ledger.commit_delta(
        project_dir=project,
        candidate_id=candidate,
        round_id=round_id,
        node=node,
        persona="Test",
        delta=delta,
        delta_path=project / "02_Agent_Notes" / "Test" / f"{candidate}_{node}_delta.v2.json",
    )


def test_lifecycle_is_append_only_and_replayable(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    l1 = _commit(ledger, project, "L1", {
        "schema_version": "2.0", "hypotheses": [{
            "proposal_key": "a", "statement": "  A  test hypothesis ",
            "operationalization": "measure A", "falsification_criteria": ["A is absent"],
            "rationale": "test rationale",
        }], "primary_proposal_key": "a", "key_uncertainty": "uncertain",
    })
    retry = _commit(ledger, project, "L1", {
        "schema_version": "2.0", "hypotheses": [{
            "proposal_key": "a", "statement": "  A  test hypothesis ",
            "operationalization": "measure A", "falsification_criteria": ["A is absent"],
            "rationale": "test rationale",
        }], "primary_proposal_key": "a", "key_uncertainty": "uncertain",
    })
    assert retry.commit_seq == l1.commit_seq
    hid = l1.normalized_delta["hypotheses"][0]["hypothesis_id"]
    _commit(ledger, project, "L3", {
        "schema_version": "2.0", "triage": [{"hypothesis_id": hid, "disposition": "SELECTED", "reason_code": "R", "reason": "worth testing"}], "route_to": "Fisher",
    })
    _commit(ledger, project, "L4", {"schema_version": "2.0", "strategies": [{"hypothesis_ids": [hid], "name": "method"}]})
    _commit(ledger, project, "L6", {"schema_version": "2.0", "analysis_plan": [{"hypothesis_ids": [hid], "name": "plan"}], "method_decision": "APPROVE", "reason": "ready"})
    l7 = _commit(ledger, project, "L7", {
        "schema_version": "2.0", "results": [{"result_key": "r1", "hypothesis_ids": [hid], "summary": "observed inverse result", "artifact_refs": [{"path": "artifacts/r1.json", "sha256": "a" * 64}]}],
        "scripts_run": [], "warnings": [], "failures": [],
    })
    evidence_id = l7.normalized_delta["results"][0]["evidence_id"]
    _commit(ledger, project, "L8", {"schema_version": "2.0", "evidence_assessments": [{"evidence_id": evidence_id, "verification": "VERIFIED", "relations": [{"hypothesis_id": hid, "outcome": "CONTRADICTS", "reason": "opposite result"}]}]})
    _commit(ledger, project, "L9a", {"schema_version": "2.0", "assessments": [{"hypothesis_id": hid, "epistemic_status": "FALSIFIED", "reason": "criterion met", "evidence_ids": [evidence_id], "falsification_criterion": "A is absent"}]})
    graph = ledger.graph(hid)
    assert graph["nodes"][0]["statement"] == "A test hypothesis"
    assert graph["nodes"][0]["current_state"]["epistemic_status"] == "FALSIFIED"
    assert [event["event_type"] for event in graph["events"]][-1] == "FALSIFIED"
    assert ledger.verify() == []


def test_l3_must_dispose_every_occurrence_and_falsification_needs_verified_evidence(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    result = _commit(ledger, project, "L1", {
        "schema_version": "2.0", "hypotheses": [{"proposal_key": "a", "statement": "A", "operationalization": "m", "falsification_criteria": ["no A"], "rationale": "r"}, {"proposal_key": "b", "statement": "B", "operationalization": "m", "falsification_criteria": ["no B"], "rationale": "r"}],
        "primary_proposal_key": "a", "key_uncertainty": "u",
    })
    hid = result.normalized_delta["hypotheses"][0]["hypothesis_id"]
    with pytest.raises(LedgerError, match="every and only"):
        _commit(ledger, project, "L3", {"schema_version": "2.0", "triage": [{"hypothesis_id": hid, "disposition": "SELECTED", "reason_code": "R", "reason": "r"}], "route_to": "Fisher"})


def test_cli_v2_emission_requires_binding_and_writes_receipt(tmp_path):
    project = tmp_path / "P"
    store = tmp_path / "ledger.sqlite"
    assert main(["new-project", str(project), "topic", "--knowledge-store", str(store)]) == 0
    assert main(["new-candidate", str(project), "--title", "t", "--question", "q", "--claim", "c", "--input", "inline"]) == 0
    candidate = next((project / "01_Candidates").glob("C*.md")).stem
    source = tmp_path / "l1.json"
    source.write_text(json.dumps({"schema_version": "2.0", "hypotheses": [{"proposal_key": "one", "statement": "S", "operationalization": "O", "falsification_criteria": ["F"], "rationale": "R"}], "primary_proposal_key": "one", "key_uncertainty": "U"}), encoding="utf-8")
    assert main(["emit-delta", str(project), candidate, "--node", "L1", "--persona", "Einstein", "--file", str(source), "--knowledge-store", str(store)]) == 0
    delta = project / "02_Agent_Notes" / "Einstein" / f"{candidate}_L1_einstein_delta.v2.json"
    assert delta.exists()
    receipts = list((project / "08_Audit" / "hypothesis_commits").glob("*.json"))
    assert len(receipts) == 1
