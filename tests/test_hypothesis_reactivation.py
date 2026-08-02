import json
import sqlite3
from pathlib import Path

from native_v2_helpers import write_catalog_emission_receipts
from research_loop.cli import main
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.hypothesis_recall import create_recall


def _native_l1_boundary(tmp_path, *, include_recall=True):
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
        "hypotheses": [{
            "proposal_key": "p0",
            "statement": "A testable hypothesis",
            "operationalization": "measure the effect",
            "falsification_criteria": ["the effect is absent"],
            "rationale": "fixture",
        }],
        "primary_proposal_key": "p0",
        "key_uncertainty": "effect size",
    }), encoding="utf-8")
    manifest, receipt = write_catalog_emission_receipts(
        project,
        candidate,
        "L1",
        "Einstein",
        source,
        store_path=store,
        include_recall=include_recall,
    )
    return project, store, candidate, source, manifest, receipt


def _emit_l1(project, store, candidate, source, manifest, receipt):
    return main([
        "emit-delta", str(project), candidate, "--node", "L1",
        "--persona", "Einstein", "--file", str(source),
        "--knowledge-store", str(store),
        "--context-manifest", str(manifest),
        "--provider-receipt", str(receipt),
    ])


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


def test_native_l1_context_requires_recall(tmp_path, capsys):
    project, store, candidate, *_ = _native_l1_boundary(
        tmp_path, include_recall=False
    )
    capsys.readouterr()

    rc = main([
        "assemble-context", str(project), candidate, "--node", "L1",
        "--knowledge-store", str(store),
    ])
    captured = capsys.readouterr()

    assert rc == 2
    assert "hypothesis recall" in captured.err.lower()
    assert captured.out == ""


def test_native_l1_context_binds_zero_result_recall(tmp_path, capsys):
    project, store, candidate, *_ = _native_l1_boundary(tmp_path)
    ledger = HypothesisLedger(store)
    create_recall(
        ledger,
        project,
        candidate,
        "1",
        query_text="unrelated query with no historical hypotheses",
    )
    capsys.readouterr()

    rc = main([
        "assemble-context", str(project), candidate, "--node", "L1",
        "--knowledge-store", str(store),
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert "HISTORICAL HYPOTHESIS RECALL" in captured.out
    manifest_line = next(
        line for line in captured.err.splitlines()
        if line.startswith("[audit] context manifest:")
    )
    manifest_path = Path(manifest_line.split(":", 1)[1].strip())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["hypothesis_recall"]["returned_hypothesis_ids"] == []
    assert manifest["hypothesis_recall"]["artifact_hash"]
    assert manifest["hypothesis_recall"]["artifact_sha256"]


def test_native_l1_receipt_without_recall_rejects_before_any_write(tmp_path):
    project, store, candidate, source, manifest, receipt = _native_l1_boundary(
        tmp_path, include_recall=False
    )

    assert _emit_l1(project, store, candidate, source, manifest, receipt) == 1
    _assert_zero_native_writes(project, store, candidate)
