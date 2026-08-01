import json
from pathlib import Path

import pytest

from research_loop.compatibility import (
    PROFILE_V20,
    PROFILE_V21,
    PROFILE_V21_CATALOG_1,
    CompatibilityError,
    profile_for_schema,
)
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.hypothesis_ledger import LedgerError, canonical_json
from research_loop.hypothesis_migration import dry_run_profile_upgrade, upgrade_profile
from research_loop.topology import topology_for_profile
from research_loop.hypothesis_contracts import validate_submission


def test_profile_registry_keeps_legacy_and_current_contracts_distinct():
    assert profile_for_schema("2.0").profile_id == PROFILE_V20
    with pytest.raises(CompatibilityError, match="ambiguous"):
        profile_for_schema("2.1")
    assert profile_for_schema("2.1", profile_id=PROFILE_V21).profile_id == PROFILE_V21
    assert profile_for_schema("2.1", profile_id=PROFILE_V21_CATALOG_1).profile_id == PROFILE_V21_CATALOG_1
    assert profile_for_schema("2.0").l9_parallel is True
    assert profile_for_schema("2.1", profile_id=PROFILE_V21).l9_parallel is False


def test_unknown_schema_profile_fails_closed():
    with pytest.raises(CompatibilityError, match="unsupported delta schema"):
        profile_for_schema("9.9")


def test_project_binding_pins_profile_and_refuses_an_implicit_change(tmp_path: Path):
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"

    binding = ledger.bind_project(project, profile_id=PROFILE_V20)

    assert binding["profile_id"] == PROFILE_V20
    assert ledger.project_profile(project) == PROFILE_V20
    with pytest.raises(Exception, match="profile mismatch"):
        ledger.bind_project(project, project_id=binding["project_id"],
                            profile_id=PROFILE_V21)


def test_failed_rebind_does_not_create_an_orphan_project(tmp_path: Path):
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"
    ledger.bind_project(project, profile_id=PROFILE_V20)
    with pytest.raises(Exception, match="profile mismatch"):
        ledger.bind_project(project, profile_id=PROFILE_V21)
    con = ledger._connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    finally:
        con.close()


def test_v21_l1_contract_requires_three_to_twelve_hypotheses():
    def payload(count):
        return {"schema_version": "2.1", "hypotheses": [
            {"proposal_key": str(i), "statement": f"S{i}", "operationalization": "O",
             "falsification_criteria": ["F"], "rationale": "R"}
            for i in range(count)
        ], "primary_proposal_key": "0", "key_uncertainty": "U"}
    assert validate_submission("L1", payload(2), schema_version="2.1")
    assert not validate_submission("L1", payload(3), schema_version="2.1")
    assert not validate_submission("L1", payload(12), schema_version="2.1")
    assert validate_submission("L1", payload(13), schema_version="2.1")


def test_v21_commit_rejects_a_missing_schema_version(tmp_path: Path):
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"
    ledger.bind_project(project, profile_id=PROFILE_V21)
    with pytest.raises(Exception, match="schema_version is required"):
        ledger.commit_delta(project_dir=project, candidate_id="C1", round_id="1",
                            node="L1", persona="Einstein", delta={},
                            delta_path=project / "delta.json")


def _finalized_v21_l1(ledger, project):
    result = ledger.commit_delta(
        project_dir=project, candidate_id="C1", round_id="1", node="L1",
        persona="Einstein", delta={
            "schema_version": "2.1", "hypotheses": [
                {"proposal_key": key, "statement": f"S{key}", "operationalization": "O",
                 "falsification_criteria": ["F"], "rationale": "R"}
                for key in ("one", "two", "three")
            ], "primary_proposal_key": "one", "key_uncertainty": "U",
        }, delta_path=project / "02_Agent_Notes" / "L1.json",
    )
    ledger.finalize_emission(result.delta_hash, artifact_sha256=result.delta_hash,
                             receipt_sha256=result.delta_hash)
    return result


def test_v21_rejected_cross_delta_constraint_leaves_ledger_unchanged(tmp_path: Path):
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"
    ledger.bind_project(project, profile_id=PROFILE_V21)
    l1 = _finalized_v21_l1(ledger, project)
    before = ledger._connect(readonly=True)
    try:
        state = {
            table: before.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("emissions", "events", "workflow_projection", "epistemic_projection")
        }
        cursor = before.execute("SELECT COALESCE(MAX(commit_seq), 0) FROM emissions").fetchone()[0]
    finally:
        before.close()
    ids = [item["hypothesis_id"] for item in l1.normalized_delta["hypotheses"]]
    with pytest.raises(LedgerError, match="ceil\\(L1_count/2\\) REJECT"):
        ledger.commit_delta(
            project_dir=project, candidate_id="C1", round_id="1", node="L2",
            persona="Feynman", delta={
                "schema_version": "2.1", "attacks": [], "confounders": [],
                "diagnostic_tests": [], "verdicts": [
                    {"hypothesis_id": hid, "outcome": "SURVIVES", "reason": "R"}
                    for hid in ids
                ],
            }, delta_path=project / "02_Agent_Notes" / "L2.json",
        )
    after = ledger._connect(readonly=True)
    try:
        assert {
            table: after.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in state
        } == state
        assert after.execute("SELECT COALESCE(MAX(commit_seq), 0) FROM emissions").fetchone()[0] == cursor
    finally:
        after.close()


def test_v21_topology_is_serial_and_context_carries_pinned_versions(tmp_path: Path):
    _, legacy, legacy_sequence = topology_for_profile(PROFILE_V20)
    _, current, current_sequence = topology_for_profile(PROFILE_V21)
    assert "L9_parallel" in legacy_sequence
    assert current_sequence.index("L9a") < current_sequence.index("L9b") < current_sequence.index("L10a")
    assert "L9a" not in legacy["L9b"]["context_inputs"]
    assert "L9a" in current["L9b"]["context_inputs"]
    assert current["L8"]["persona"] == "Tukey"

    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"
    ledger.bind_project(project, profile_id=PROFILE_V21)
    _finalized_v21_l1(ledger, project)
    snapshot = ledger.materialize_authorized_context(project, "C1", "1", "L2")
    assert snapshot["profile_id"] == PROFILE_V21
    assert snapshot["schema_version"] == "2.1"
    assert snapshot["topology_version"] == "2.1"


def test_profile_upgrade_is_append_only_and_blocks_nonterminal_candidates(tmp_path: Path):
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    project = tmp_path / "project"
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: UNDER_REVIEW\n---\n", encoding="utf-8"
    )
    ledger.bind_project(project, profile_id=PROFILE_V20)
    report = dry_run_profile_upgrade(project, ledger)
    assert report["nonterminal"]
    resolution = tmp_path / "resolution.json"
    resolution.write_text("{}", encoding="utf-8")
    with pytest.raises(LedgerError, match="no nonterminal"):
        upgrade_profile(project, ledger, resolution_path=resolution, resolved_by="tester")

    (candidate_dir / "C1.md").write_text(
        "---\ncandidate_id: C1\ncurrent_status: KEEP\n---\n", encoding="utf-8"
    )
    report = dry_run_profile_upgrade(project, ledger)
    resolution.write_text(json.dumps({
        "schema_version": "1.0",
        "dry_run_report_hash": report["dry_run_report_hash"],
        "entries": [],
    }), encoding="utf-8")
    receipt = upgrade_profile(project, ledger, resolution_path=resolution, resolved_by="tester")
    assert receipt["transition_id"]
    assert ledger.project_profile(project) == PROFILE_V21
    con = ledger._connect()
    try:
        with pytest.raises(Exception, match="append-only"):
            con.execute("DELETE FROM profile_transitions")
    finally:
        con.close()
