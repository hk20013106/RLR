import inspect

import pytest

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p
from research_loop.commands import ledger as ledger_commands


def test_native_l45_helper_skips_legacy_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        dr,
        "_artifact",
        lambda *a, **k: {"run_id": "LEGACY", "candidate_id": "C1"},
    )
    monkeypatch.setattr(
        l4p,
        "commit_l45_method_projection",
        lambda *a, **k: pytest.fail("legacy evidence must not create L4.5"),
    )

    result = ledger_commands._commit_l45_for_native_l4(
        tmp_path,
        "C1",
        "L4",
        {"evidence_artifacts": {"run_id": "LEGACY", "files": []}},
        tmp_path / "delta.json",
    )

    assert result == (None, None, False)


def test_native_l45_helper_passes_exact_context_evidence_manifest(
    monkeypatch, tmp_path
):
    expected_manifest = {
        "run_id": "RUN2",
        "files": [{"kind": "run", "path": "run.json", "sha256": "abc"}],
    }
    staged = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
    }
    observed = {}
    commit_path = tmp_path / "08_Audit" / "l4_method_commits" / "commit.json"

    monkeypatch.setattr(dr, "_artifact", lambda *a, **k: staged)

    def fake_commit(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return {"schema_version": l4p.L45_COMMIT_SCHEMA_VERSION}, commit_path, True

    monkeypatch.setattr(l4p, "commit_l45_method_projection", fake_commit)

    result = ledger_commands._commit_l45_for_native_l4(
        tmp_path,
        "C1",
        "L4",
        {"evidence_artifacts": expected_manifest},
        tmp_path / "delta.json",
    )

    assert result[1:] == (commit_path, True)
    assert observed["args"][:3] == (tmp_path, "C1", staged)
    assert observed["kwargs"]["expected_evidence_manifest"] == expected_manifest


def test_native_finalize_calls_l45_and_tracks_new_projection_for_cleanup():
    source = inspect.getsource(ledger_commands._emit_delta_v2)

    assert "_commit_l45_for_native_l4(" in source
    assert "created.append(l45_path)" in source
