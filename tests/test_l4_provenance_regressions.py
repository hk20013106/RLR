import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l4_lineage
from research_loop import l4_pipeline as l4p


def _asset(
    *,
    asset_id="A1",
    doi="10.1000/example",
    pmid="111",
    url="https://example.org/paper",
    title="Example method paper",
    year=2026,
):
    return {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "title": title,
        "year": year,
        "journal": "Methods Journal",
        "abstract": "Metadata only.",
        "source_database": "Europe PMC",
        "source_metadata_response": json.dumps(
            {"id": asset_id}, sort_keys=True, separators=(",", ":")
        ),
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": [url],
        "relevance_score": 9.0,
        "selection_status": "selected",
        "selection_reason": "Relevant to the selected hypothesis.",
        "hypothesis_ids": ["H1"],
        "method_component_hints": ["model"],
        "diagnostic_requirements": ["interaction test"],
    }


def _manifest(project: Path, *assets: dict) -> dict:
    payload = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [
            {
                "query_id": "Q1",
                "query": "interaction model method",
                "purpose": "Find implementation evidence.",
                "status": "completed",
                "receipt": "Europe PMC receipt",
            }
        ],
        "assets": list(assets or (_asset(),)),
    }
    return l4p.persist_l4a_discovery(
        project,
        "C1",
        payload,
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test"),
        question="Q",
        claim="H",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )


def _paper_record(project: Path, *, name="paper.json", **fields) -> str:
    relative = Path("09_Literature_Database/evidence_packs/papers") / name
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "title": fields.pop("title", "Example method paper"),
        "metadata": fields.pop("metadata", {"year": 2026}),
        **fields,
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return relative.as_posix()


def _artifact(manifest: dict, *, papers: list[dict], path: str) -> dict:
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "run_id": "RUN2",
        "candidate_id": "C1",
        "project_id": "P1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
        "node": "L4",
        "status": "completed",
        "path": path,
        "papers": papers,
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
        "method_components": [],
        "method_candidates": [],
        "method_anchors": [],
    }


def _paper_reference(path: str, *, doi="", pmid="", url="") -> dict:
    return {
        "paper_id": "P1",
        "path": path,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "user_source_id": "",
        "evidence_ids": [],
    }


def _write_unstaged_run(project: Path, artifact: dict) -> None:
    path = project / artifact["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    unstaged = {
        key: value
        for key, value in artifact.items()
        if key
        not in {
            "pipeline_schema",
            "pipeline_stage",
            "l4a_manifest_path",
            "l4a_manifest_sha256",
            "l4a_run_id",
        }
    }
    path.write_text(json.dumps(unstaged), encoding="utf-8")


def test_l4b_rejects_conflicting_reference_and_paper_record_doi(tmp_path):
    manifest = _manifest(tmp_path, _asset())
    paper_path = _paper_record(
        tmp_path,
        doi="10.9999/outside",
        pmid="",
        url="",
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, doi="10.1000/example")],
        path="09_Literature_Database/evidence_packs/runs/RUN2.json",
    )
    _write_unstaged_run(tmp_path, artifact)

    with pytest.raises(dr.DeepResearchError, match="conflicting DOI"):
        l4p._persist_l4b_linkage(tmp_path, artifact)


def test_l4b_rejects_identifiers_spliced_from_different_selected_assets(tmp_path):
    manifest = _manifest(
        tmp_path,
        _asset(asset_id="A1", doi="10.1000/one", pmid="111"),
        _asset(
            asset_id="A2",
            doi="10.1000/two",
            pmid="222",
            url="https://example.org/two",
            title="Second method paper",
        ),
    )
    paper_path = _paper_record(
        tmp_path,
        doi="10.1000/one",
        pmid="222",
        url="",
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, doi="10.1000/one", pmid="222")],
        path="09_Literature_Database/evidence_packs/runs/RUN2.json",
    )
    _write_unstaged_run(tmp_path, artifact)

    with pytest.raises(dr.DeepResearchError, match="conflicting identifiers"):
        l4p._persist_l4b_linkage(tmp_path, artifact)


def test_l4b_nonempty_missing_artifact_path_does_not_bypass_validation(tmp_path):
    manifest = _manifest(tmp_path, _asset())
    paper_path = _paper_record(
        tmp_path,
        doi="10.9999/outside",
        pmid="",
        url="",
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, doi="10.9999/outside")],
        path="09_Literature_Database/evidence_packs/runs/MISSING.json",
    )

    with pytest.raises(dr.DeepResearchError, match="frozen L4A corpus"):
        l4p._persist_l4b_linkage(tmp_path, artifact)


def test_l4_lineage_rechecks_frozen_corpus_after_persistence(tmp_path):
    manifest = _manifest(tmp_path, _asset())
    paper_path = _paper_record(
        tmp_path,
        doi="10.9999/outside",
        pmid="",
        url="",
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, doi="10.9999/outside")],
        path="09_Literature_Database/evidence_packs/runs/RUN2.json",
    )

    ok, reason, path = l4_lineage._validate_link(
        SimpleNamespace(), tmp_path, artifact
    )

    assert ok is False
    assert path is None
    assert "frozen L4A corpus" in reason


def test_l45_rechecks_frozen_corpus_after_persistence(monkeypatch, tmp_path):
    manifest = _manifest(tmp_path, _asset())
    paper_path = _paper_record(
        tmp_path,
        doi="10.9999/outside",
        pmid="",
        url="",
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, doi="10.9999/outside")],
        path="09_Literature_Database/evidence_packs/runs/RUN2.json",
    )
    delta = tmp_path / "L4_fisher.json"
    delta.write_text("{}", encoding="utf-8")
    evidence_manifest = {"run_id": "RUN2", "files": []}
    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(
        dr,
        "evidence_artifact_manifest",
        lambda *a, **k: evidence_manifest,
    )

    with pytest.raises(dr.DeepResearchError, match="frozen L4A corpus"):
        l4p.commit_l45_method_projection(
            tmp_path,
            "C1",
            artifact,
            delta,
            expected_evidence_manifest=evidence_manifest,
        )
