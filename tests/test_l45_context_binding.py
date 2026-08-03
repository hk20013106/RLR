from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import l45_ledger
from research_loop import l4_pipeline as l4p


def test_l45_rejects_evidence_manifest_changed_since_context(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    delta = project / "02_Agent_Notes" / "Fisher" / "C1_L4_fisher_delta.v2.json"
    delta.parent.mkdir(parents=True)
    delta.write_text("{}", encoding="utf-8")
    expected = {
        "run_id": "RUN2",
        "files": [{"kind": "run", "path": "run.json", "sha256": "old"}],
    }
    current = {
        "run_id": "RUN2",
        "files": [{"kind": "run", "path": "run.json", "sha256": "new"}],
    }
    staged = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
    }
    receipt_called = []

    module = SimpleNamespace(
        _write_hypothesis_commit_receipt=lambda *a, **k: receipt_called.append(True),
        _v2_candidate_delta_file=lambda *a, **k: delta,
        deep_research=SimpleNamespace(
            _artifact=lambda *a, **k: staged,
            evidence_artifact_manifest=lambda *a, **k: current,
            DeepResearchError=ValueError,
        ),
    )
    monkeypatch.setattr(
        l45_ledger,
        "commit_l45_method_projection",
        lambda *a, **k: pytest.fail("changed evidence reached L4.5 commit"),
    )
    l45_ledger.install(module)

    with pytest.raises(ValueError, match="changed since context assembly"):
        module._write_hypothesis_commit_receipt(
            project,
            {
                "candidate_id": "C1",
                "node": "L4",
                "provenance": {"evidence_artifacts": expected},
            },
        )

    assert receipt_called == []
