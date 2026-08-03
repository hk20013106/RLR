from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import l45_ledger
from research_loop import l4_pipeline as l4p


def test_l45_projection_is_removed_when_ledger_finalization_fails(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    delta = project / "02_Agent_Notes" / "Fisher" / "C1_L4_fisher_delta.v2.json"
    delta.parent.mkdir(parents=True)
    delta.write_text("{}", encoding="utf-8")
    projection = project / "08_Audit" / "l4_method_commits" / "commit.json"
    projection.parent.mkdir(parents=True)
    events = []

    evidence_manifest = {
        "run_id": "RUN2",
        "files": [{"kind": "run", "path": "run.json", "sha256": "abc"}],
    }
    staged = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
    }

    def write_receipt(project_dir, receipt):
        events.append("receipt")
        path = Path(project_dir) / "receipt.json"
        path.write_text("{}", encoding="utf-8")
        return path

    class FakeLedger:
        def commit_delta(self, *args, **kwargs):
            result = SimpleNamespace(receipt={"candidate_id": "C1", "node": "L4"})
            _, _, cleanup = kwargs["_finalize_callback"](result)
            cleanup()
            raise RuntimeError("database finalization failed")

    module = SimpleNamespace(
        _write_hypothesis_commit_receipt=write_receipt,
        _v2_candidate_delta_file=lambda *a, **k: delta,
        deep_research=SimpleNamespace(
            _artifact=lambda *a, **k: staged,
            evidence_artifact_manifest=lambda *a, **k: evidence_manifest,
            DeepResearchError=ValueError,
        ),
        HypothesisLedger=FakeLedger,
    )

    def commit_projection(*args, **kwargs):
        assert kwargs["expected_evidence_manifest"] == evidence_manifest
        projection.write_text("{}", encoding="utf-8")
        events.append("l45")
        return {"schema_version": l4p.L45_COMMIT_SCHEMA_VERSION}, projection, True

    monkeypatch.setattr(l45_ledger, "commit_l45_method_projection", commit_projection)
    l45_ledger.install(module)

    def finalize(result):
        module._write_hypothesis_commit_receipt(
            project,
            {
                "candidate_id": "C1",
                "node": "L4",
                "provenance": {"evidence_artifacts": evidence_manifest},
            },
        )
        return "delta-hash", "receipt-hash", lambda: events.append("base-cleanup")

    with pytest.raises(RuntimeError, match="database finalization failed"):
        module.HypothesisLedger().commit_delta(
            project_dir=project,
            candidate_id="C1",
            node="L4",
            _finalize_callback=finalize,
        )

    assert events == ["l45", "receipt", "base-cleanup"]
    assert not projection.exists()
