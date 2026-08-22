import json
import sqlite3
from pathlib import Path

import pytest

from research_loop import l0_contract
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.engine import main
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.providers.base import RunReceipt
from research_loop.yamlio import _replace_field
from native_v2_helpers import write_catalog_emission_receipts


def _receipt(**overrides):
    values = {
        "node": "L1",
        "persona": "Einstein",
        "provider": "test",
        "timestamp": "2026-07-30T00:00:00Z",
        "context_hash": "a" * 64,
        "project_id": "P1",
        "candidate_id": "C1",
        "round_id": "1",
        "profile_id": PROFILE_V21_CATALOG_1,
        "context_manifest_path": "manifest.json",
        "context_manifest_hash": "b" * 64,
        "rendered_context_path": "context.txt",
        "rendered_context_hash": "a" * 64,
        "prompt_file": "prompt.txt",
        "prompt_hash": "c" * 64,
        "provider_delta_path": "delta.json",
        "provider_delta_hash": "d" * 64,
    }
    values.update(overrides)
    return RunReceipt(**values)


def test_run_receipt_utf8_round_trip_and_strict_schema(tmp_path):
    path = tmp_path / "receipt.json"
    _receipt(provider="测试-provider").write(path)
    loaded = RunReceipt.read(path)
    assert loaded.provider == "测试-provider"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "RunReceipt/v9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        RunReceipt.read(path)


def test_run_receipt_rejects_unknown_fields(tmp_path):
    path = tmp_path / "receipt.json"
    _receipt().write(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tools_policy"] = "all"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="fields"):
        RunReceipt.read(path)


@pytest.mark.parametrize(
    "field",
    ["prompt_hash", "provider_delta_path", "provider_delta_hash", "round_id"],
)
def test_run_receipt_rejects_missing_provenance(field):
    with pytest.raises(ValueError, match=field):
        _receipt(**{field: None}).validate()


def test_atomic_callback_failure_leaves_no_ledger_emission(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    store = tmp_path / "ledger.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(
        project, "P1", profile_id=PROFILE_V21_CATALOG_1
    )
    delta = {
        "schema_version": "2.1",
        "hypotheses": [
            {
                "proposal_key": f"p{i}",
                "statement": f"hypothesis {i}",
                "operationalization": "measure it",
                "falsification_criteria": ["not observed"],
                "rationale": "fixture",
            }
            for i in range(3)
        ],
        "primary_proposal_key": "p0",
        "key_uncertainty": "effect",
    }

    def fail_persistence(_result):
        raise OSError("simulated disk failure")

    with pytest.raises(OSError, match="simulated disk failure"):
        ledger.commit_delta(
            project_dir=project,
            candidate_id="C1",
            round_id="1",
            node="L1",
            persona="Einstein",
            delta=delta,
            delta_path=project / "02_Agent_Notes" / "Einstein" / "C1_L1.json",
            _finalize_callback=fail_persistence,
        )
    con = sqlite3.connect(store)
    try:
        assert con.execute("SELECT COUNT(*) FROM emissions").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        con.close()


def _native_l1_boundary(tmp_path):
    project = tmp_path / "P"
    store = tmp_path / "ledger.sqlite"
    assert main([
        "new-project", str(project), "topic", "--knowledge-store", str(store)
    ]) == 0
    assert main([
        "new-candidate", str(project), "--title", "t", "--question", "q",
        "--claim", "c", "--input", "inline", "--knowledge-store", str(store),
    ]) == 0
    candidate = next((project / "01_Candidates").glob("C*.md")).stem
    source = tmp_path / "l1.json"
    source.write_text(json.dumps({
        "schema_version": "2.1",
        "hypotheses": [
            {
                "proposal_key": f"p{i}",
                "statement": f"hypothesis {i}",
                "operationalization": "measure it",
                "falsification_criteria": ["not observed"],
                "rationale": "fixture",
            }
            for i in range(3)
        ],
        "primary_proposal_key": "p0",
        "key_uncertainty": "effect",
    }), encoding="utf-8")
    manifest, receipt = write_catalog_emission_receipts(
        project, candidate, "L1", "Einstein", source, store_path=store
    )
    return project, store, candidate, source, manifest, receipt


def _assert_zero_native_writes(project, store, candidate):
    assert not (
        project / "02_Agent_Notes" / "Einstein"
        / f"{candidate}_L1_einstein_delta.v2.json"
    ).exists()
    con = sqlite3.connect(store)
    try:
        assert con.execute("SELECT COUNT(*) FROM emissions").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM committed_emissions").fetchone()[0] == 0
    finally:
        con.close()


def _emit_l1(project, store, candidate, source, manifest, receipt):
    return main([
        "emit-delta", str(project), candidate, "--node", "L1",
        "--persona", "Einstein", "--file", str(source),
        "--knowledge-store", str(store),
        "--context-manifest", str(manifest),
        "--provider-receipt", str(receipt),
    ])


def test_receipt_identity_mismatch_rejects_before_any_write(tmp_path):
    project, store, candidate, source, manifest, receipt = _native_l1_boundary(
        tmp_path
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["round_id"] = "99"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    assert _emit_l1(project, store, candidate, source, manifest, receipt) == 1
    _assert_zero_native_writes(project, store, candidate)


def test_provider_delta_hash_tamper_rejects_before_any_write(tmp_path):
    project, store, candidate, source, manifest, receipt = _native_l1_boundary(
        tmp_path
    )
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert _emit_l1(project, store, candidate, source, manifest, receipt) == 1
    _assert_zero_native_writes(project, store, candidate)


def test_exact_evidence_artifact_tamper_rejects_before_any_write(tmp_path):
    project, store, candidate, source, manifest, receipt = _native_l1_boundary(
        tmp_path
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    paper = next(
        item for item in payload["pre_research"]["evidence_artifacts"]["files"]
        if item["kind"] == "paper"
    )
    paper_path = project / paper["path"]
    paper_path.write_text(
        paper_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    assert _emit_l1(project, store, candidate, source, manifest, receipt) == 1
    _assert_zero_native_writes(project, store, candidate)


def test_l1_canonical_seed_drift_rejects_stale_receipt_before_any_write(
    tmp_path, capsys
):
    project, store, candidate, source, manifest, receipt = _native_l1_boundary(
        tmp_path
    )
    contract, _path, _raw = l0_contract.load_contract(project, candidate)
    contract["scientific_question"] = "a different canonical scientific question"
    _new_path, new_digest = l0_contract.write_contract(project, candidate, contract)
    candidate_path = project / "01_Candidates" / f"{candidate}.md"
    _replace_field(candidate_path, "input_contract_hash", new_digest)

    assert _emit_l1(project, store, candidate, source, manifest, receipt) == 1
    captured = capsys.readouterr()
    assert "canonical research seed changed since context assembly" in captured.err
    _assert_zero_native_writes(project, store, candidate)