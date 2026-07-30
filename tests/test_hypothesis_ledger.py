import hashlib
import json

import pytest

from research_loop.delta import _v2_commit_valid
from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError, canonical_json
from research_loop.engine import main
from native_v2_helpers import write_catalog_emission_receipts


def _commit(ledger, project, node, delta, *, candidate="C1", round_id="1",
            finalize=True):
    delta_path = (
        project / "02_Agent_Notes" / "Test" /
        f"{candidate}_{node}_delta.v2.json"
    )
    result = ledger.commit_delta(
        project_dir=project,
        candidate_id=candidate,
        round_id=round_id,
        node=node,
        persona="Test",
        delta=delta,
        delta_path=delta_path,
    )
    if finalize:
        delta_path.parent.mkdir(parents=True, exist_ok=True)
        delta_raw = canonical_json(result.normalized_delta)
        if not delta_path.exists():
            delta_path.write_text(delta_raw, encoding="utf-8")
        assert delta_path.read_text(encoding="utf-8") == delta_raw
        receipt_path = (
            project / "08_Audit" / "hypothesis_commits" /
            f"H{result.commit_seq:08d}_{candidate}_{node}.json"
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_raw = canonical_json(result.receipt)
        if not receipt_path.exists():
            receipt_path.write_text(receipt_raw, encoding="utf-8")
        ledger.finalize_emission(
            result.delta_hash,
            artifact_sha256=hashlib.sha256(delta_path.read_bytes()).hexdigest(),
            receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        )
    return result


def _l1_delta(statement="A"):
    return {
        "schema_version": "2.0",
        "hypotheses": [{
            "proposal_key": "a",
            "statement": statement,
            "operationalization": "measure",
            "falsification_criteria": ["absent"],
            "rationale": "fixture",
        }],
        "primary_proposal_key": "a",
        "key_uncertainty": "uncertain",
    }


def _finalize(ledger, result):
    ledger.finalize_emission(
        result.delta_hash,
        artifact_sha256=result.delta_hash,
        receipt_sha256=hashlib.sha256(
            canonical_json(result.receipt).encode("utf-8")
        ).hexdigest(),
    )


def test_orphan_l1_hidden_from_ranking_until_finalized(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    orphan = _commit(ledger, project, "L1", _l1_delta(), finalize=False)

    with pytest.raises(
        LedgerError, match="ranking candidate has no ledger L1 occurrence"
    ):
        ledger.ranking_inputs(["C1"], "L3", project_id="P1")

    _finalize(ledger, orphan)
    assert ledger.ranking_inputs(
        ["C1"], "L3", project_id="P1"
    )["candidates"][0]["candidate_id"] == "C1"


def test_orphan_decision_keeps_unavailable_until_finalized(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    l1 = _commit(ledger, project, "L1", _l1_delta())
    hid = l1.normalized_delta["primary_hypothesis_id"]
    orphan = _commit(ledger, project, "L3", {
        "schema_version": "2.0",
        "triage": [{
            "hypothesis_id": hid,
            "disposition": "SELECTED",
            "reason_code": "fixture",
            "reason": "fixture",
        }],
        "route_to": "Fisher",
    }, finalize=False)

    before = ledger.ranking_inputs(["C1"], "L3", project_id="P1")
    assert before["formal_decisions"][0]["formal_decision"] == "UNAVAILABLE"

    _finalize(ledger, orphan)
    after = ledger.ranking_inputs(["C1"], "L3", project_id="P1")
    assert after["formal_decisions"][0]["formal_decision"] == "SELECTED"


def test_orphan_absent_from_authorized_context(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    orphan = _commit(ledger, project, "L1", _l1_delta(), finalize=False)

    before = ledger.materialize_authorized_context(project, "C1", "1", "L2")
    assert before["events"] == []

    _finalize(ledger, orphan)
    after = ledger.materialize_authorized_context(project, "C1", "1", "L2")
    assert any(event["node"] == "L1" for event in after["events"])


def test_verify_emits_orphan_diagnostic(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    orphan = _commit(ledger, project, "L1", _l1_delta(), finalize=False)

    assert any(
        item.startswith("orphan emission missing finalization marker:")
        for item in ledger.verify()
    )

    _finalize(ledger, orphan)
    assert ledger.verify() == []


def test_snapshot_candidate_excludes_orphan(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    orphan = _commit(ledger, project, "L1", _l1_delta(), finalize=False)

    before = ledger.snapshot_candidate(project, "C1", "1")
    assert before["authorized_events"] == []

    _finalize(ledger, orphan)
    after = ledger.snapshot_candidate(project, "C1", "1")
    assert any(
        event["commit_seq"] == orphan.commit_seq
        for event in after["authorized_events"]
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
    ranking_dto = ledger.ranking_inputs(["C1"], "L3", project_id="P1")
    assert ranking_dto["candidates"][0]["hypothesis_id"] == hid
    assert ranking_dto["formal_decisions"][0]["formal_decision"] == "SELECTED"
    _commit(ledger, project, "L4", {"schema_version": "2.0", "strategies": [{"strategy_id": "S1", "hypothesis_ids": [hid], "name": "method", "steps": ["measure"]}]})
    _commit(ledger, project, "L6", {"schema_version": "2.0", "analysis_plan": [{"strategy_id": "S1", "hypothesis_ids": [hid], "scripts": [], "parameters": {}, "outputs": []}], "method_decision": "APPROVE", "reason": "ready"})
    l7 = _commit(ledger, project, "L7", {
        "schema_version": "2.0", "results": [{"result_key": "r1", "hypothesis_ids": [hid], "summary": "observed inverse result", "artifact_refs": [{"path": "artifacts/r1.json", "sha256": "a" * 64}]}],
        "scripts_run": [], "warnings": [], "failures": [],
    })
    evidence_id = l7.normalized_delta["results"][0]["evidence_id"]
    _commit(ledger, project, "L8", {"schema_version": "2.0", "evidence_assessments": [{"evidence_id": evidence_id, "verification": "VERIFIED", "relations": [{"hypothesis_id": hid, "outcome": "CONTRADICTS", "reason": "opposite result"}]}]})
    cursor = ledger.snapshot_candidate(project, "C1", "1")["as_of_commit_seq"]
    l9a_snapshot = ledger.materialize_authorized_context(
        project, "C1", "1", "L9a", as_of=cursor
    )
    l9b_snapshot = ledger.materialize_authorized_context(
        project, "C1", "1", "L9b", as_of=cursor
    )
    assert l9a_snapshot["event_ids"] == l9b_snapshot["event_ids"]
    assert l9a_snapshot["projection_hash"] == l9b_snapshot["projection_hash"]
    _commit(ledger, project, "L9a", {"schema_version": "2.0", "assessments": [{"hypothesis_id": hid, "epistemic_status": "FALSIFIED", "reason": "criterion met", "evidence_ids": [evidence_id], "falsification_criterion": "A is absent"}]})
    assert ledger.graph(hid, as_of=cursor)["nodes"][0]["current_state"][
        "epistemic_status"
    ] == "UNASSESSED"
    later_l9b = ledger.materialize_authorized_context(project, "C1", "1", "L9b")
    assert all(event["node"] != "L9a" for event in later_l9b["events"])
    assert later_l9b["current_state"][0]["epistemic_status"] == "UNASSESSED"
    assert ledger.load_authorized_context(project, later_l9b["authorization_id"])[
        "projection_hash"
    ] == later_l9b["projection_hash"]
    _commit(ledger, project, "L9b", {"schema_version": "2.0", "assessments": [{
        "hypothesis_id": hid, "interpretation": "bounded interpretation",
        "evidence_ids": [evidence_id], "limitations": ["synthetic"],
        "convergent_evolution": "not assessed",
    }]})
    _commit(ledger, project, "L10a", {"schema_version": "2.0", "assessments": [{
        "hypothesis_id": hid, "value_assessment": "limited", "headline": "test",
        "publishable_now": [], "needs_more_work": ["replicate"],
        "manuscript_framing": "software validation only",
    }]})
    assert ledger.graph(hid)["nodes"][0]["current_state"][
        "epistemic_status"
    ] == "FALSIFIED"
    graph = ledger.graph(hid)
    assert graph["nodes"][0]["statement"] == "A test hypothesis"
    assert graph["nodes"][0]["current_state"]["epistemic_status"] == "FALSIFIED"
    event_types = [event["event_type"] for event in graph["events"]]
    assert "FALSIFIED" in event_types
    assert event_types[-2:] == ["INTERPRETED", "VALUE_ASSESSED"]
    assert ledger.verify() == []
    assert ledger.verify(rebuild=True) == []


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


def test_bound_but_unactivated_project_cannot_commit(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1", activate=False)
    with pytest.raises(LedgerError, match="not activated"):
        _commit(ledger, project, "L1", {
            "schema_version": "2.0", "hypotheses": [{
                "proposal_key": "a", "statement": "A", "operationalization": "m",
                "falsification_criteria": ["no A"], "rationale": "r",
            }], "primary_proposal_key": "a", "key_uncertainty": "u",
        })


def test_cli_v2_emission_requires_binding_and_writes_receipt(tmp_path):
    project = tmp_path / "P"
    store = tmp_path / "ledger.sqlite"
    assert main(["new-project", str(project), "topic", "--knowledge-store", str(store)]) == 0
    assert main(["new-candidate", str(project), "--title", "t", "--question", "q", "--claim", "c", "--input", "inline", "--knowledge-store", str(store)]) == 0
    candidate = next((project / "01_Candidates").glob("C*.md")).stem
    source = tmp_path / "l1.json"
    source.write_text(json.dumps({"schema_version": "2.1", "hypotheses": [
        {"proposal_key": "one", "statement": "S1", "operationalization": "O", "falsification_criteria": ["F"], "rationale": "R"},
        {"proposal_key": "two", "statement": "S2", "operationalization": "O", "falsification_criteria": ["F"], "rationale": "R"},
        {"proposal_key": "three", "statement": "S3", "operationalization": "O", "falsification_criteria": ["F"], "rationale": "R"},
    ], "primary_proposal_key": "one", "key_uncertainty": "U"}), encoding="utf-8")
    manifest, provider_receipt = write_catalog_emission_receipts(
        project, candidate, "L1", "Einstein", source, store_path=store
    )
    assert main(["emit-delta", str(project), candidate, "--node", "L1", "--persona", "Einstein", "--file", str(source), "--knowledge-store", str(store),
                 "--context-manifest", str(manifest), "--provider-receipt", str(provider_receipt)]) == 0
    delta = project / "02_Agent_Notes" / "Einstein" / f"{candidate}_L1_einstein_delta.v2.json"
    assert delta.exists()
    receipts = list((project / "08_Audit" / "hypothesis_commits").glob("*.json"))
    assert len(receipts) == 1


def test_v2_resolver_requires_finalized_emission_marker(tmp_path, monkeypatch):
    project = tmp_path / "P"
    project.mkdir()
    store = tmp_path / "ledger.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, "P1")
    delta_path = project / "02_Agent_Notes" / "Einstein" / "C1_L1_einstein_delta.v2.json"
    delta_path.parent.mkdir(parents=True)
    result = ledger.commit_delta(project_dir=project, candidate_id="C1", round_id="1",
                                 node="L1", persona="Einstein", delta={
        "schema_version": "2.0", "hypotheses": [{
            "proposal_key": "one", "statement": "S", "operationalization": "O",
            "falsification_criteria": ["F"], "rationale": "R",
        }], "primary_proposal_key": "one", "key_uncertainty": "U",
    }, delta_path=delta_path)
    delta_path.write_text(canonical_json(result.normalized_delta), encoding="utf-8")
    receipt_path = project / "08_Audit" / "hypothesis_commits" / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(canonical_json(result.receipt), encoding="utf-8")
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    assert not _v2_commit_valid(project, "L1_einstein", "C1", delta_path)
    ledger.finalize_emission(
        result.delta_hash,
        artifact_sha256=hashlib.sha256(delta_path.read_bytes()).hexdigest(),
        receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    )
    assert _v2_commit_valid(project, "L1_einstein", "C1", delta_path)


def test_l2_and_l5_require_exhaustive_authorized_hypothesis_coverage(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    ledger.bind_project(project, "P1")
    result = _commit(ledger, project, "L1", {
        "schema_version": "2.0", "hypotheses": [
            {"proposal_key": "a", "statement": "A", "operationalization": "m",
             "falsification_criteria": ["no A"], "rationale": "r"},
            {"proposal_key": "b", "statement": "B", "operationalization": "m",
             "falsification_criteria": ["no B"], "rationale": "r"},
        ], "primary_proposal_key": "a", "key_uncertainty": "u",
    })
    hids = [item["hypothesis_id"] for item in result.normalized_delta["hypotheses"]]
    with pytest.raises(LedgerError, match="L2 verdicts must assess every and only"):
        _commit(ledger, project, "L2", {
            "schema_version": "2.0", "attacks": [], "confounders": [],
            "diagnostic_tests": [],
            "verdicts": [{"hypothesis_id": hids[0], "outcome": "SURVIVES", "reason": "r"}],
        })
    _commit(ledger, project, "L2", {
        "schema_version": "2.0",
        "attacks": [{"hypothesis_id": hids[0], "severity": "HIGH", "text": "attack"}],
        "confounders": [{"hypothesis_id": hids[1], "name": "batch", "severity": "HIGH", "text": "confound"}],
        "diagnostic_tests": [],
        "verdicts": [
            {"hypothesis_id": hids[0], "outcome": "SURVIVES", "reason": "r"},
            {"hypothesis_id": hids[1], "outcome": "REVISE", "reason": "r"},
        ],
    })
    _commit(ledger, project, "L3", {
        "schema_version": "2.0", "triage": [
            {"hypothesis_id": hid, "disposition": "SELECTED", "reason_code": "R", "reason": "r"}
            for hid in hids
        ], "route_to": "Fisher",
    })
    _commit(ledger, project, "L4", {
        "schema_version": "2.0", "strategies": [
            {"strategy_id": "S1", "hypothesis_ids": hids, "name": "method", "steps": ["measure"]}
        ],
    })
    with pytest.raises(LedgerError, match="L5 must review every selected hypothesis"):
        _commit(ledger, project, "L5", {
            "schema_version": "2.0",
            "attacks": [{"hypothesis_ids": [hids[0]], "strategy_id": "S1", "severity": "HIGH", "text": "attack"}],
            "qc_checkpoints": [], "failure_stop_rules": [],
        })


def test_cross_project_identity_reuse_does_not_leak_occurrence_context(tmp_path):
    ledger = HypothesisLedger(tmp_path / "shared.sqlite")
    projects = [tmp_path / "P1", tmp_path / "P2"]
    for index, project in enumerate(projects, 1):
        project.mkdir()
        ledger.bind_project(project, f"P{index}")
    base = {"schema_version": "2.0", "hypotheses": [{
        "proposal_key": "a", "statement": "Same  statement",
        "operationalization": "measure", "falsification_criteria": ["absent"],
        "rationale": "r",
    }], "primary_proposal_key": "a", "key_uncertainty": "u"}
    first = _commit(ledger, projects[0], "L1", base)
    second = _commit(ledger, projects[1], "L1", base)
    hid = first.normalized_delta["primary_hypothesis_id"]
    assert second.normalized_delta["primary_hypothesis_id"] == hid
    different = _commit(ledger, projects[1], "L1", {
        **base, "hypotheses": [{**base["hypotheses"][0],
                                 "operationalization": "different measure"}],
    }, candidate="C2")
    other_hid = different.normalized_delta["primary_hypothesis_id"]
    assert other_hid != hid
    assert ledger.graph(other_hid)["nodes"][0]["family_id"] == ledger.graph(hid)[
        "nodes"
    ][0]["family_id"]
    snapshot = ledger.materialize_authorized_context(projects[0], "C1", "1", "L2")
    assert {event["project_id"] for event in snapshot["events"]} == {"P1"}
