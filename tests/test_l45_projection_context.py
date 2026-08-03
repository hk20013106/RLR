import pytest

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p


def _manifest(project):
    payload = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "method",
            "purpose": "find method evidence",
            "status": "completed",
            "receipt": "receipt",
        }],
        "assets": [{
            "asset_id": "A1",
            "doi": "10.1000/example",
            "pmid": "",
            "url": "https://example.org/paper",
            "title": "Method paper",
            "year": 2026,
            "journal": "Methods",
            "abstract": "metadata",
            "source_database": "Europe PMC",
            "source_metadata_response": '{"id":"A1"}',
            "open_access_status": "open",
            "full_text_status": "available_oa",
            "full_text_locations": ["https://example.org/paper"],
            "relevance_score": 9,
            "selection_status": "selected",
            "selection_reason": "relevant",
            "hypothesis_ids": ["H1"],
            "method_component_hints": ["model"],
            "diagnostic_requirements": ["interaction"],
        }],
    }
    receipt = dr.skill_receipt("codex", ["codex"], "prompt", "test")
    return l4p.persist_l4a_discovery(
        project, "C1", payload, receipt, question="Q", claim="H"
    )


def _staged_evidence(manifest):
    return {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
        "project_id": "P1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "method_components": [],
        "method_candidates": [],
        "method_anchors": [],
    }


def _evidence_manifest(sha):
    return {
        "run_id": "RUN2",
        "candidate_id": "C1",
        "target_node": "L4",
        "files": [{"kind": "run", "path": "run.json", "sha256": sha}],
    }


def test_staged_l45_requires_context_evidence_manifest(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path)
    evidence = _staged_evidence(manifest)
    delta = tmp_path / "delta.json"
    delta.write_text("{}", encoding="utf-8")
    current = _evidence_manifest("same")
    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(dr, "evidence_artifact_manifest", lambda *a, **k: current)

    with pytest.raises(
        dr.DeepResearchError, match="requires the evidence manifest recorded at context assembly"
    ):
        l4p.commit_l45_method_projection(tmp_path, "C1", evidence, delta)


def test_staged_l45_rejects_context_evidence_manifest_mismatch(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path)
    evidence = _staged_evidence(manifest)
    delta = tmp_path / "delta.json"
    delta.write_text("{}", encoding="utf-8")
    current = _evidence_manifest("new")
    expected = _evidence_manifest("old")
    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(dr, "evidence_artifact_manifest", lambda *a, **k: current)

    with pytest.raises(
        dr.DeepResearchError, match="changed since context assembly"
    ):
        l4p.commit_l45_method_projection(
            tmp_path,
            "C1",
            evidence,
            delta,
            expected_evidence_manifest=expected,
        )


def test_staged_l45_commits_exact_context_evidence_manifest(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path)
    evidence = _staged_evidence(manifest)
    delta = tmp_path / "delta.json"
    delta.write_text("{}", encoding="utf-8")
    expected = _evidence_manifest("same")
    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(dr, "evidence_artifact_manifest", lambda *a, **k: expected)

    artifact, path, created = l4p.commit_l45_method_projection(
        tmp_path,
        "C1",
        evidence,
        delta,
        expected_evidence_manifest=expected,
    )

    assert created is True
    assert path.is_file()
    assert artifact["l4b_evidence_manifest"] == expected


def test_staged_l45_removes_new_projection_if_evidence_changes_during_commit(
    monkeypatch, tmp_path
):
    manifest = _manifest(tmp_path)
    evidence = _staged_evidence(manifest)
    delta = tmp_path / "delta.json"
    delta.write_text("{}", encoding="utf-8")
    expected = _evidence_manifest("same")
    changed = _evidence_manifest("changed-during-commit")
    observed = iter((expected, changed))
    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(
        dr, "evidence_artifact_manifest", lambda *a, **k: next(observed)
    )

    with pytest.raises(
        dr.DeepResearchError, match="changed since context assembly"
    ):
        l4p.commit_l45_method_projection(
            tmp_path,
            "C1",
            evidence,
            delta,
            expected_evidence_manifest=expected,
        )

    commit_dir = tmp_path / "08_Audit" / "l4_method_commits"
    assert not commit_dir.exists() or list(commit_dir.glob("*.json")) == []
