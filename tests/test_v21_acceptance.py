import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from research_loop.compatibility import PROFILE_V20, PROFILE_V21
from research_loop.hypothesis_ledger import (
    HypothesisLedger,
    LedgerError,
    canonical_json,
)
from research_loop.hypothesis_migration import (
    dry_run_profile_upgrade,
    upgrade_profile,
)


def _ledger_snapshot(ledger: HypothesisLedger) -> dict:
    con = ledger._connect(readonly=True, immutable=True)
    try:
        tables = [
            str(row[0]) for row in con.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        state = {}
        for table in tables:
            rows = [
                list(row) for row in con.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                ).fetchall()
            ]
            state[table] = {
                "count": len(rows),
                "sha256": hashlib.sha256(
                    canonical_json(rows).encode("utf-8")
                ).hexdigest(),
            }
        cursor = con.execute(
            "SELECT COALESCE(MAX(commit_seq), 0) FROM emissions"
        ).fetchone()[0]
        return {"tables": state, "max_commit_seq": int(cursor)}
    finally:
        con.close()


def _commit_finalized(ledger, project, node, persona, delta):
    result = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node=node,
        persona=persona,
        delta=delta,
        delta_path=project / "02_Agent_Notes" / f"{node}.json",
    )
    ledger.finalize_emission(
        result.delta_hash,
        artifact_sha256=result.delta_hash,
        receipt_sha256=result.delta_hash,
    )
    return result


def _new_v21(tmp_path: Path, *, hypothesis_count: int = 5):
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"
    ledger.bind_project(project, profile_id=PROFILE_V21)
    l1 = _commit_finalized(
        ledger,
        project,
        "L1",
        "Einstein",
        {
            "schema_version": "2.1",
            "hypotheses": [
                {
                    "proposal_key": f"p{i}",
                    "statement": f"Hypothesis {i}",
                    "operationalization": f"Measure {i}",
                    "falsification_criteria": [f"Criterion {i} fails"],
                    "rationale": "fixture",
                }
                for i in range(hypothesis_count)
            ],
            "primary_proposal_key": "p0",
            "key_uncertainty": "fixture uncertainty",
        },
    )
    ids = [item["hypothesis_id"] for item in l1.normalized_delta["hypotheses"]]
    return ledger, project, ids


def _assessment(verdict="PASS"):
    return {
        key: {"verdict": verdict, "evidence": "fixture evidence"}
        for key in ("testability", "novelty", "feasibility", "impact")
    }


def _valid_l2(ids):
    return {
        "schema_version": "2.1",
        "attacks": [],
        "confounders": [],
        "diagnostic_tests": [],
        "verdicts": [
            {
                "hypothesis_id": hid,
                "outcome": "REJECT" if index < (len(ids) + 1) // 2 else "SURVIVES",
                "reason": "fixture verdict",
            }
            for index, hid in enumerate(ids)
        ],
    }


def _valid_l3(ids):
    return {
        "schema_version": "2.1",
        "triage": [
            {
                "hypothesis_id": hid,
                "disposition": "SELECTED" if index == 0 else "REJECTED",
                "reason_code": "TESTABLE" if index == 0 else "LOW_IMPACT",
                "reason": "fixture triage",
                "assessments": _assessment("PASS" if index == 0 else "FAIL"),
            }
            for index, hid in enumerate(ids)
        ],
        "route_to": "Fisher",
    }


def _valid_l4(ids):
    return {
        "schema_version": "2.1",
        "strategies": [
            {
                "strategy_id": "S1",
                "hypothesis_ids": [ids[0]],
                "name": "Strategy one",
                "steps": ["measure"],
            }
        ],
    }


def _valid_l5(ids):
    return {
        "schema_version": "2.1",
        "attacks": [
            {
                "attack_id": "A1",
                "strategy_id": "S1",
                "hypothesis_ids": [ids[0]],
                "severity": "HIGH",
                "text": "High-risk attack",
            }
        ],
        "qc_checkpoints": [
            {
                "strategy_id": "S1",
                "hypothesis_ids": [ids[0]],
                "name": "QC",
                "criterion": "passes",
            }
        ],
        "failure_stop_rules": [
            {
                "strategy_id": "S1",
                "hypothesis_ids": [ids[0]],
                "name": "Stop",
                "condition": "failure",
                "reason": "unsafe",
            }
        ],
    }


def _valid_l6(ids):
    return {
        "schema_version": "2.1",
        "analysis_plan": [
            {
                "strategy_id": "S1",
                "hypothesis_ids": [ids[0]],
                "scripts": [],
                "parameters": {},
                "outputs": ["result.json"],
                "feasibility_assessment": {
                    "verdict": "PASS",
                    "evidence": "fixture evidence",
                },
                "attack_resolutions": [{
                    "attack_id": "A1",
                    "verdict": "RESOLVED",
                    "evidence": "mitigation verified by fixture",
                }],
            }
        ],
        "method_decision": "APPROVE",
        "reason": "ready",
    }


def _assert_rejected_without_mutation(ledger, project, node, persona, delta):
    before = _ledger_snapshot(ledger)
    with pytest.raises(LedgerError):
        ledger.commit_delta(
            project_dir=project,
            candidate_id="C1",
            round_id="1",
            node=node,
            persona=persona,
            delta=delta,
            delta_path=project / "02_Agent_Notes" / f"invalid-{node}.json",
        )
    assert _ledger_snapshot(ledger) == before


def _assert_valid_retry_is_idempotent(ledger, project, node, persona, delta):
    first = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node=node,
        persona=persona,
        delta=delta,
        delta_path=project / "02_Agent_Notes" / f"valid-{node}.json",
    )
    after_first = _ledger_snapshot(ledger)
    second = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node=node,
        persona=persona,
        delta=delta,
        delta_path=project / "02_Agent_Notes" / f"valid-{node}.json",
    )
    assert (second.delta_hash, second.commit_seq, second.event_ids) == (
        first.delta_hash,
        first.commit_seq,
        first.event_ids,
    )
    assert _ledger_snapshot(ledger) == after_first
    ledger.finalize_emission(
        first.delta_hash,
        artifact_sha256=first.delta_hash,
        receipt_sha256=first.delta_hash,
    )
    return first


def test_l2_rejections_are_atomic_and_valid_retry_is_idempotent(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    invalid = []
    incomplete = _valid_l2(ids)
    incomplete["verdicts"] = incomplete["verdicts"][:-1]
    invalid.append(incomplete)
    insufficient = _valid_l2(ids)
    for verdict in insufficient["verdicts"]:
        verdict["outcome"] = "SURVIVES"
    invalid.append(insufficient)
    no_evidence = _valid_l2(ids)
    for verdict in no_evidence["verdicts"][:3]:
        verdict["outcome"] = "NOT_APPLICABLE"
    invalid.append(no_evidence)
    unevidenced_na = _valid_l2(ids)
    unevidenced_na["verdicts"][0]["outcome"] = "NOT_APPLICABLE"
    invalid.append(unevidenced_na)
    for delta in invalid:
        _assert_rejected_without_mutation(ledger, project, "L2", "Feynman", delta)
    _assert_valid_retry_is_idempotent(
        ledger, project, "L2", "Feynman", _valid_l2(ids)
    )


def test_l3_rejections_are_atomic_and_valid_retry_is_idempotent(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    incomplete = _valid_l3(ids)
    incomplete["triage"] = incomplete["triage"][:-1]
    duplicate = _valid_l3(ids)
    duplicate["triage"][-1]["hypothesis_id"] = ids[0]
    five_selected = _valid_l3(ids)
    for item in five_selected["triage"]:
        item["disposition"] = "SELECTED"
        item["reason_code"] = "TESTABLE"
    missing_assessment = _valid_l3(ids)
    del missing_assessment["triage"][0]["assessments"]
    unknown_reason = _valid_l3(ids)
    unknown_reason["triage"][0]["reason_code"] = "UNKNOWN"
    for delta in (
        incomplete,
        duplicate,
        five_selected,
        missing_assessment,
        unknown_reason,
    ):
        _assert_rejected_without_mutation(
            ledger, project, "L3", "Oppenheimer", delta
        )
    _assert_valid_retry_is_idempotent(
        ledger, project, "L3", "Oppenheimer", _valid_l3(ids)
    )


def test_l4_rejections_are_atomic_and_valid_retry_is_idempotent(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    _commit_finalized(ledger, project, "L3", "Oppenheimer", _valid_l3(ids))
    rejected = _valid_l4(ids)
    rejected["strategies"][0]["hypothesis_ids"] = [ids[1]]
    orphan = _valid_l4(ids)
    orphan["strategies"][0]["hypothesis_ids"] = ["H:missing"]
    duplicate = _valid_l4(ids)
    duplicate["strategies"].append(copy.deepcopy(duplicate["strategies"][0]))
    for delta in (rejected, orphan, duplicate):
        _assert_rejected_without_mutation(ledger, project, "L4", "Fisher", delta)
    _assert_valid_retry_is_idempotent(
        ledger, project, "L4", "Fisher", _valid_l4(ids)
    )


def test_unfinalized_l3_cannot_authorize_l4(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node="L3",
        persona="Oppenheimer",
        delta=_valid_l3(ids),
        delta_path=project / "02_Agent_Notes" / "unfinalized-L3.json",
    )
    _assert_rejected_without_mutation(
        ledger, project, "L4", "Fisher", _valid_l4(ids)
    )


def test_l3_requires_a_finalized_l2_submission(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _assert_rejected_without_mutation(
        ledger, project, "L3", "Oppenheimer", _valid_l3(ids)
    )


def test_l5_rejections_are_atomic_and_valid_retry_is_idempotent(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    _commit_finalized(ledger, project, "L3", "Oppenheimer", _valid_l3(ids))
    _commit_finalized(ledger, project, "L4", "Fisher", _valid_l4(ids))
    invalid = []
    for group in ("attacks", "qc_checkpoints", "failure_stop_rules"):
        missing = _valid_l5(ids)
        missing[group] = []
        invalid.append(missing)
    unknown = _valid_l5(ids)
    unknown["attacks"][0]["strategy_id"] = "S404"
    invalid.append(unknown)
    mismatch = _valid_l5(ids)
    mismatch["attacks"][0]["hypothesis_ids"] = [ids[1]]
    invalid.append(mismatch)
    for delta in invalid:
        _assert_rejected_without_mutation(ledger, project, "L5", "Tukey", delta)
    _assert_valid_retry_is_idempotent(
        ledger, project, "L5", "Tukey", _valid_l5(ids)
    )


def test_l5_requires_finalized_l4_and_rejects_duplicate_attack_ids(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _assert_rejected_without_mutation(
        ledger, project, "L5", "Tukey", _valid_l5(ids)
    )
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    _commit_finalized(ledger, project, "L3", "Oppenheimer", _valid_l3(ids))
    _commit_finalized(ledger, project, "L4", "Fisher", _valid_l4(ids))
    duplicate = _valid_l5(ids)
    duplicate["attacks"].append({
        **copy.deepcopy(duplicate["attacks"][0]), "severity": "LOW",
    })
    _assert_rejected_without_mutation(ledger, project, "L5", "Tukey", duplicate)


def test_l5_rejects_attack_id_reused_by_an_earlier_finalized_submission(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    _commit_finalized(ledger, project, "L3", "Oppenheimer", _valid_l3(ids))
    _commit_finalized(ledger, project, "L4", "Fisher", _valid_l4(ids))
    _commit_finalized(ledger, project, "L5", "Tukey", _valid_l5(ids))
    reused = _valid_l5(ids)
    reused["attacks"][0]["severity"] = "LOW"
    _assert_rejected_without_mutation(ledger, project, "L5", "Tukey", reused)


def test_l6_rejections_are_atomic_and_valid_retry_is_idempotent(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    _commit_finalized(ledger, project, "L3", "Oppenheimer", _valid_l3(ids))
    _commit_finalized(ledger, project, "L4", "Fisher", _valid_l4(ids))
    _commit_finalized(ledger, project, "L5", "Tukey", _valid_l5(ids))
    unknown = _valid_l6(ids)
    unknown["analysis_plan"][0]["strategy_id"] = "S404"
    mismatch = _valid_l6(ids)
    mismatch["analysis_plan"][0]["hypothesis_ids"] = [ids[1]]
    five_plans = _valid_l6(ids)
    five_plans["analysis_plan"] = [
        {**copy.deepcopy(five_plans["analysis_plan"][0]), "strategy_id": f"S{i}"}
        for i in range(5)
    ]
    unresolved = _valid_l6(ids)
    unresolved["analysis_plan"][0]["attack_resolutions"] = []
    for delta in (unknown, mismatch, five_plans, unresolved):
        _assert_rejected_without_mutation(
            ledger, project, "L6", "Oppenheimer", delta
        )
    _assert_valid_retry_is_idempotent(
        ledger, project, "L6", "Oppenheimer", _valid_l6(ids)
    )


def test_l6_requires_a_finalized_l5_submission(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    _commit_finalized(ledger, project, "L3", "Oppenheimer", _valid_l3(ids))
    _commit_finalized(ledger, project, "L4", "Fisher", _valid_l4(ids))
    _assert_rejected_without_mutation(
        ledger, project, "L6", "Oppenheimer", _valid_l6(ids)
    )


def test_v21_l8_requires_profile_persona_and_preserves_retry_receipt(tmp_path):
    ledger, project, ids = _new_v21(tmp_path)
    _commit_finalized(ledger, project, "L2", "Feynman", _valid_l2(ids))
    _commit_finalized(ledger, project, "L3", "Oppenheimer", _valid_l3(ids))
    _commit_finalized(ledger, project, "L4", "Fisher", _valid_l4(ids))
    _commit_finalized(ledger, project, "L5", "Tukey", _valid_l5(ids))
    _commit_finalized(ledger, project, "L6", "Oppenheimer", _valid_l6(ids))
    l7 = _commit_finalized(ledger, project, "L7", "Turing", {
        "schema_version": "2.1", "results": [{
            "result_key": "R1", "hypothesis_ids": [ids[0]], "summary": "result",
            "artifact_refs": [{"path": "result.json", "sha256": "a" * 64}],
        }], "scripts_run": [], "warnings": [], "failures": [],
    })
    evidence_id = l7.normalized_delta["results"][0]["evidence_id"]
    l8 = {"schema_version": "2.1", "evidence_assessments": [{
        "evidence_id": evidence_id, "verification": "VERIFIED",
        "relations": [{"hypothesis_id": ids[0], "outcome": "INCONCLUSIVE", "reason": "fixture"}],
    }]}
    _assert_rejected_without_mutation(ledger, project, "L8", "Curie", l8)
    first = ledger.commit_delta(
        project_dir=project, candidate_id="C1", round_id="1", node="L8",
        persona="Tukey", delta=l8, delta_path=project / "02_Agent_Notes" / "L8.json",
    )
    second = ledger.commit_delta(
        project_dir=project, candidate_id="C1", round_id="1", node="L8",
        persona="Tukey", delta=l8, delta_path=project / "02_Agent_Notes" / "L8.json",
    )
    assert second.receipt == first.receipt


def _file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _legacy_profile_project(tmp_path: Path, *, status="KEEP"):
    ledger = HypothesisLedger(tmp_path / "store.sqlite")
    project = tmp_path / "project"
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "C1.md").write_text(
        f"---\ncandidate_id: C1\ncurrent_status: {status}\n---\n",
        encoding="utf-8",
    )
    ledger.bind_project(project, profile_id=PROFILE_V20)
    result = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node="L1",
        persona="Einstein",
        delta={
            "schema_version": "2.0",
            "hypotheses": [
                {
                    "proposal_key": "p1",
                    "statement": "Legacy hypothesis",
                    "operationalization": "measure",
                    "falsification_criteria": ["absent"],
                    "rationale": "legacy",
                }
            ],
            "primary_proposal_key": "p1",
            "key_uncertainty": "legacy",
        },
        delta_path=project / "02_Agent_Notes" / "Einstein" / "C1_L1.json",
    )
    delta_path = project / "02_Agent_Notes" / "Einstein" / "C1_L1.json"
    delta_path.parent.mkdir(parents=True)
    delta_path.write_text(
        canonical_json(result.normalized_delta), encoding="utf-8"
    )
    ledger.finalize_emission(
        result.delta_hash,
        artifact_sha256=result.delta_hash,
        receipt_sha256=result.delta_hash,
    )
    return ledger, project


def _resolution(path: Path, report: dict, *, include_findings=True):
    entries = []
    if include_findings:
        entries = [
            {
                "finding_id": item["finding_id"],
                "resolution": "retain-under-source-profile",
                "reason": "terminal historical artifact remains governed by v2.0",
            }
            for item in report["resolution_required"]
        ]
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "dry_run_report_hash": report["dry_run_report_hash"],
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )


def test_profile_upgrade_dry_run_is_read_only_and_reports_structuring_gaps(tmp_path):
    ledger, project = _legacy_profile_project(tmp_path)
    before_files = _file_snapshot(tmp_path)
    before_ledger = _ledger_snapshot(ledger)
    report = dry_run_profile_upgrade(project, ledger)
    assert _file_snapshot(tmp_path) == before_files
    assert _ledger_snapshot(ledger) == before_ledger
    assert report["nonterminal"] == []
    assert report["resolution_required"]
    assert report["resolution_required"][0]["kind"] == "STRUCTURING_REQUIRED"
    assert report["resolution_required"][0]["node"] == "L1"


def test_profile_upgrade_blocks_unfinalized_or_stale_ledger_state(tmp_path):
    ledger, project = _legacy_profile_project(tmp_path)
    report = dry_run_profile_upgrade(project, ledger)
    resolution = tmp_path / "resolution.json"
    _resolution(resolution, report)
    con = ledger._connect(readonly=True)
    try:
        hypothesis_id = str(con.execute("SELECT hypothesis_id FROM occurrences").fetchone()[0])
    finally:
        con.close()
    ledger.commit_delta(
        project_dir=project, candidate_id="C1", round_id="1", node="L2",
        persona="Feynman", delta={
            "schema_version": "2.0", "attacks": [], "confounders": [],
            "diagnostic_tests": [], "verdicts": [{
                "hypothesis_id": hypothesis_id, "outcome": "REJECT", "reason": "fixture",
            }],
        }, delta_path=project / "02_Agent_Notes" / "Feynman" / "C1_L2.json",
    )
    next_report = dry_run_profile_upgrade(project, ledger)
    assert next_report["blocking_findings"]
    before = _ledger_snapshot(ledger)
    with pytest.raises(LedgerError, match="every source emission to be finalized"):
        upgrade_profile(project, ledger, resolution_path=resolution, resolved_by="tester")
    assert _ledger_snapshot(ledger) == before


def test_profile_transition_rejects_a_candidate_change_after_dry_run(tmp_path):
    ledger, project = _legacy_profile_project(tmp_path)
    report = dry_run_profile_upgrade(project, ledger)
    (project / "01_Candidates" / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: KEEP\ntitle: changed\n---\n",
        encoding="utf-8",
    )
    before = _ledger_snapshot(ledger)
    with pytest.raises(LedgerError, match="candidate state changed"):
        ledger.record_profile_transition(
            project_dir=project, source_profile_id=PROFILE_V20,
            target_profile_id=PROFILE_V21, dry_run_report_hash="d" * 64,
            resolution_hash="r" * 64, manifest_hash="m" * 64,
            resolved_by="tester", candidate_state_hash=report["candidate_state_hash"],
            expected_source_ledger_state_hash=report["source_ledger_state_hash"],
            expected_through_commit_seq=report["source_through_commit_seq"],
        )
    assert _ledger_snapshot(ledger) == before


def test_commit_rejects_when_profile_changes_while_acquiring_write_lock(tmp_path, monkeypatch):
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"
    ledger.bind_project(project, profile_id=PROFILE_V20)
    profiles = iter([PROFILE_V20, PROFILE_V20, PROFILE_V21])

    def profile_at_boundary(_con, _binding):
        return next(profiles)

    monkeypatch.setattr(ledger, "_project_profile_in_connection", profile_at_boundary)
    before = _ledger_snapshot(ledger)
    with pytest.raises(LedgerError, match="profile changed while acquiring"):
        ledger.commit_delta(
            project_dir=project, candidate_id="C1", round_id="1", node="L1",
            persona="Einstein", delta={
                "schema_version": "2.0", "hypotheses": [{
                    "proposal_key": "p", "statement": "legacy", "operationalization": "measure",
                    "falsification_criteria": ["absent"], "rationale": "fixture",
                }], "primary_proposal_key": "p", "key_uncertainty": "fixture",
            }, delta_path=project / "delta.json",
        )
    assert _ledger_snapshot(ledger) == before


def test_profile_upgrade_rejects_nonterminal_and_incomplete_resolution_without_transition(
    tmp_path,
):
    ledger, project = _legacy_profile_project(tmp_path, status="UNDER_REVIEW")
    report = dry_run_profile_upgrade(project, ledger)
    resolution = tmp_path / "resolution.json"
    _resolution(resolution, report)
    before = _ledger_snapshot(ledger)
    with pytest.raises(LedgerError, match="nonterminal"):
        upgrade_profile(
            project, ledger, resolution_path=resolution, resolved_by="tester"
        )
    assert _ledger_snapshot(ledger) == before
    assert ledger.project_profile(project) == PROFILE_V20

    (project / "01_Candidates" / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: KEEP\n---\n", encoding="utf-8"
    )
    report = dry_run_profile_upgrade(project, ledger)
    _resolution(resolution, report, include_findings=False)
    before = _ledger_snapshot(ledger)
    with pytest.raises(LedgerError, match="incomplete"):
        upgrade_profile(
            project, ledger, resolution_path=resolution, resolved_by="tester"
        )
    assert _ledger_snapshot(ledger) == before
    assert ledger.project_profile(project) == PROFILE_V20


def test_profile_upgrade_receipt_is_verifiable_append_only_and_complete(tmp_path):
    ledger, project = _legacy_profile_project(tmp_path)
    report = dry_run_profile_upgrade(project, ledger)
    resolution = tmp_path / "resolution.json"
    _resolution(resolution, report)
    receipt = upgrade_profile(
        project, ledger, resolution_path=resolution, resolved_by="tester"
    )
    assert ledger.project_profile(project) == PROFILE_V21
    assert receipt["source_ledger_state_hash"]
    assert receipt["destination_ledger_state_hash"]
    assert receipt["receipt_hash"]
    assert ledger.verify_profile_transition(receipt["transition_id"]) == []
    con = ledger._connect()
    try:
        row = con.execute(
            "SELECT receipt_json FROM profile_transitions WHERE transition_id=?",
            (receipt["transition_id"],),
        ).fetchone()
        assert json.loads(row[0]) == receipt
        with pytest.raises(Exception, match="append-only"):
            con.execute(
                "UPDATE profile_transitions SET resolved_by='other' "
                "WHERE transition_id=?",
                (receipt["transition_id"],),
            )
        with pytest.raises(Exception, match="append-only"):
            con.execute(
                "DELETE FROM profile_transitions WHERE transition_id=?",
                (receipt["transition_id"],),
            )
    finally:
        con.close()


def test_profile_upgrade_cli_uses_explicit_target_profile_without_writes(tmp_path):
    ledger, project = _legacy_profile_project(tmp_path)
    before_files = _file_snapshot(tmp_path)
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "research_loop_v04.py"),
        "hypothesis-migrate",
        str(project),
        "--knowledge-store",
        str(ledger.path),
        "--target-profile",
        PROFILE_V21,
        "--dry-run",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["target_profile_id"] == PROFILE_V21
    assert _file_snapshot(tmp_path) == before_files


def test_profile_upgrade_cli_dry_run_does_not_initialize_older_store(tmp_path):
    ledger, project = _legacy_profile_project(tmp_path)
    con = ledger._connect()
    try:
        con.execute("DROP TABLE profile_transitions")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()
    before_files = _file_snapshot(tmp_path)
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "research_loop_v04.py"),
        "hypothesis-migrate",
        str(project),
        "--knowledge-store",
        str(ledger.path),
        "--target-profile",
        PROFILE_V21,
        "--dry-run",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert _file_snapshot(tmp_path) == before_files
