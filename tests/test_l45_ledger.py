from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import l45_ledger
from research_loop import l4_pipeline as l4p


def _receipt():
    return {
        "candidate_id": "C1",
        "node": "L4",
        "provenance": {
            "evidence_artifacts": {"run_id": "RUN2"},
        },
    }


def _module(tmp_path, evidence):
    calls = []

    def write_receipt(project_dir, receipt):
        calls.append(("receipt", receipt))
        return Path(project_dir) / "receipt.json"

    def artifact(project_dir, candidate_id, node, *, run_id=None):
        calls.append(("artifact", candidate_id, node, run_id))
        return evidence

    delta = tmp_path / "02_Agent_Notes" / "Fisher" / "C1_L4_fisher_delta.json"
    delta.parent.mkdir(parents=True)
    delta.write_text("{}", encoding="utf-8")

    module = SimpleNamespace(
        _write_hypothesis_commit_receipt=write_receipt,
        _v2_candidate_delta_file=lambda project_dir, key, candidate_id: delta,
        deep_research=SimpleNamespace(_artifact=artifact),
    )
    return module, calls, delta


def test_staged_l4_runs_l45_before_hypothesis_receipt(monkeypatch, tmp_path):
    evidence = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
    }
    module, calls, delta = _module(tmp_path, evidence)

    def commit(project_dir, candidate_id, artifact, delta_path):
        calls.append(("l45", candidate_id, artifact["run_id"], delta_path))
        return ({"schema_version": l4p.L45_COMMIT_SCHEMA_VERSION}, tmp_path / "l45.json", True)

    monkeypatch.setattr(l45_ledger, "commit_l45_method_projection", commit)
    l45_ledger.install(module)

    result = module._write_hypothesis_commit_receipt(tmp_path, _receipt())

    assert result == tmp_path / "receipt.json"
    assert [item[0] for item in calls] == ["artifact", "l45", "receipt"]
    assert calls[1][3] == delta


def test_legacy_l4_evidence_skips_l45(monkeypatch, tmp_path):
    module, calls, _ = _module(tmp_path, {"run_id": "RUN2"})
    monkeypatch.setattr(
        l45_ledger,
        "commit_l45_method_projection",
        lambda *a, **k: pytest.fail("legacy evidence triggered L4.5"),
    )
    l45_ledger.install(module)

    module._write_hypothesis_commit_receipt(tmp_path, _receipt())

    assert [item[0] for item in calls] == ["artifact", "receipt"]


def test_l45_failure_prevents_hypothesis_receipt(monkeypatch, tmp_path):
    evidence = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
    }
    module, calls, _ = _module(tmp_path, evidence)

    def fail(*args, **kwargs):
        calls.append(("l45",))
        raise ValueError("broken lineage")

    monkeypatch.setattr(l45_ledger, "commit_l45_method_projection", fail)
    l45_ledger.install(module)

    with pytest.raises(ValueError, match="broken lineage"):
        module._write_hypothesis_commit_receipt(tmp_path, _receipt())

    assert [item[0] for item in calls] == ["artifact", "l45"]
