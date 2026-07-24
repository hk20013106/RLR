import json
from unittest.mock import patch

import pytest

from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError
from research_loop.hypothesis_migration import commit, dry_run


def _legacy_project(tmp_path):
    project = tmp_path / "P"
    candidate_dir = project / "01_Candidates"
    notes = project / "02_Agent_Notes" / "Einstein"
    candidate_dir.mkdir(parents=True)
    notes.mkdir(parents=True)
    (candidate_dir / "C1.md").write_text(
        "---\ncandidate_id: C1\nround_id: 1\n---\n", encoding="utf-8"
    )
    source = notes / "C1_L1_einstein_delta.json"
    source.write_text(json.dumps({
        "hypotheses": [{"id": "h1", "text": "A", "testable": True,
                         "rationale": "r"}],
        "key_uncertainty": "u", "primary_hypothesis": "h1",
    }), encoding="utf-8")
    return project, source


def test_migration_dry_run_writes_only_audit_report(tmp_path):
    project, source = _legacy_project(tmp_path)
    ledger = HypothesisLedger(tmp_path / "store.sqlite")
    report, path = dry_run(project, ledger)
    assert path.is_file()
    assert report["unresolved"][0]["source_path"].endswith(source.name)
    assert not (project / "00_Preflight" / "hypothesis_store_binding.json").exists()
    assert not list(project.rglob("*_delta.v2.json"))
    assert ledger.search() == []


def test_resolution_must_cover_each_unresolved_source_and_commit_activates_atomically(tmp_path):
    project, source = _legacy_project(tmp_path)
    store = tmp_path / "store.sqlite"
    ledger = HypothesisLedger(store)
    report, _ = dry_run(project, ledger)
    empty_resolution = tmp_path / "empty.json"
    empty_resolution.write_text(json.dumps({
        "schema_version": "1.0", "dry_run_report_hash": report["dry_run_report_hash"],
        "entries": [],
    }), encoding="utf-8")
    with pytest.raises(LedgerError, match="incomplete"):
        commit(project, ledger, empty_resolution, "tester")
    assert not (project / "00_Preflight" / "hypothesis_store_binding.json").exists()

    unresolved = report["unresolved"][0]
    resolution = tmp_path / "resolution.json"
    resolution.write_text(json.dumps({
        "schema_version": "1.0", "dry_run_report_hash": report["dry_run_report_hash"],
        "entries": [{
            "source_path": unresolved["source_path"],
            "source_sha256": unresolved["source_sha256"],
            "candidate_id": "C1", "node": "L1",
            "v2_delta": {
                "schema_version": "2.0", "hypotheses": [{
                    "proposal_key": "h1", "statement": "A",
                    "operationalization": "measure A",
                    "falsification_criteria": ["A is absent"], "rationale": "r",
                }], "primary_proposal_key": "h1", "key_uncertainty": "u",
            },
        }],
    }), encoding="utf-8")
    manifest = commit(project, ledger, resolution, "tester")
    migrated = HypothesisLedger(store)
    activation = migrated.require_activated_project(project)
    assert activation["activation_mode"] == "MIGRATED_V2"
    assert manifest["project_id"] == activation["project_id"]
    assert source.is_file()
    assert list(project.rglob("*_delta.v2.json"))
    assert migrated.search("A")


def test_resolution_rejects_changed_source_hash(tmp_path):
    project, source = _legacy_project(tmp_path)
    ledger = HypothesisLedger(tmp_path / "store.sqlite")
    report, _ = dry_run(project, ledger)
    item = report["unresolved"][0]
    source.write_text("{}", encoding="utf-8")
    resolution = tmp_path / "resolution.json"
    resolution.write_text(json.dumps({
        "schema_version": "1.0", "dry_run_report_hash": report["dry_run_report_hash"],
        "entries": [{**{key: item[key] for key in ("source_path", "source_sha256", "candidate_id", "node")},
                     "v2_delta": {}}],
    }), encoding="utf-8")
    with pytest.raises(LedgerError, match="source hash changed"):
        commit(project, ledger, resolution, "tester")


def test_publish_crash_leaves_database_inactive_and_retry_recovers(tmp_path):
    project, _ = _legacy_project(tmp_path)
    store = tmp_path / "store.sqlite"
    ledger = HypothesisLedger(store)
    report, _ = dry_run(project, ledger)
    item = report["unresolved"][0]
    resolution = tmp_path / "resolution.json"
    resolution.write_text(json.dumps({
        "schema_version": "1.0", "dry_run_report_hash": report["dry_run_report_hash"],
        "entries": [{
            **{key: item[key] for key in ("source_path", "source_sha256", "candidate_id", "node")},
            "v2_delta": {"schema_version": "2.0", "hypotheses": [{
                "proposal_key": "h", "statement": "A", "operationalization": "measure",
                "falsification_criteria": ["absent"], "rationale": "r",
            }], "primary_proposal_key": "h", "key_uncertainty": "u"},
        }],
    }), encoding="utf-8")
    from research_loop import hypothesis_migration
    real_publish = hypothesis_migration._publish_exclusive
    calls = 0

    def fail_after_first(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publish crash")
        return real_publish(source, target)

    with patch.object(hypothesis_migration, "_publish_exclusive",
                      side_effect=fail_after_first):
        with pytest.raises(OSError, match="simulated publish crash"):
            commit(project, ledger, resolution, "tester")
    original = HypothesisLedger(store)
    with pytest.raises(LedgerError, match="binding missing|not activated"):
        original.require_activated_project(project)
    assert original.search() == []

    manifest = commit(project, original, resolution, "tester")
    assert HypothesisLedger(store).require_activated_project(project)[
        "migration_id"
    ] == manifest["migration_id"]
