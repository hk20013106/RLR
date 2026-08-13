import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l4_lineage
from research_loop import l4_pipeline as l4p
from research_loop.user_sources import register_pdf


def _asset(
    *,
    asset_id="A1",
    doi="10.1000/example",
    pmid="",
    url="https://example.org/paper",
    title="Example method paper",
    year=2026,
    selection_status="selected",
):
    return {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "title": title,
        "year": year,
        "role": "method",
        "journal": "Methods Journal",
        "abstract": "Metadata only.",
        "source_database": "Europe PMC",
        "source_metadata_response": '{"id":"A1"}',
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": [url],
        "relevance_score": 9.0,
        "selection_status": selection_status,
        "selection_reason": "Relevant to the selected hypothesis.",
        "hypothesis_ids": ["H1"],
        "method_component_hints": ["model"],
        "diagnostic_requirements": ["interaction test"],
    }


def _payload(*assets, queries=None):
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": queries
        if queries is not None
        else [
            {
                "query_id": "Q1",
                "query": "interaction model method",
                "purpose": "Find implementation evidence.",
                "status": "completed",
                "receipt": "Europe PMC receipt",
            }
        ],
        "assets": list(assets),
    }


def _receipt():
    return dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test")


def _manifest(
    project: Path,
    *,
    candidate_id="C1",
    project_id="P1",
    round_id="1",
    profile_id="v2.1-catalog-1",
    asset=None,
):
    return l4p.persist_l4a_discovery(
        project,
        candidate_id,
        _payload(asset or _asset()),
        _receipt(),
        question="Q",
        claim="H",
        project_id=project_id,
        round_id=round_id,
        profile_id=profile_id,
    )


def _paper_record(project: Path, *, name="paper.json", **fields):
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


def _linked_artifact(project: Path, manifest: dict, *, papers, **overrides):
    relative = Path("09_Literature_Database/evidence_packs/runs/RUN2.json")
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    base = {
        "schema_version": dr.SCHEMA_VERSION,
        "run_id": "RUN2",
        "candidate_id": "C1",
        "project_id": "P1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
        "node": "L4",
        "status": "completed",
        "path": relative.as_posix(),
        "papers": papers,
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
    }
    base.update(overrides)
    unstaged = {
        key: value
        for key, value in base.items()
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
    return base, path


def test_l4a_rejects_empty_query_list_before_persistence(tmp_path):
    with pytest.raises(dr.DeepResearchError, match="queries"):
        l4p.persist_l4a_discovery(
            tmp_path,
            "C1",
            _payload(_asset(), queries=[]),
            _receipt(),
            question="Q",
            claim="H",
        )


def test_l4a_rejects_duplicate_query_and_asset_ids(tmp_path):
    duplicate_queries = [
        {
            "query_id": "Q1",
            "query": "one",
            "purpose": "purpose",
            "status": "completed",
            "receipt": "receipt",
        },
        {
            "query_id": "Q1",
            "query": "two",
            "purpose": "purpose",
            "status": "completed",
            "receipt": "receipt",
        },
    ]
    with pytest.raises(dr.DeepResearchError, match="query_id"):
        l4p.persist_l4a_discovery(
            tmp_path,
            "C1",
            _payload(_asset(), queries=duplicate_queries),
            _receipt(),
            question="Q",
            claim="H",
        )

    with pytest.raises(dr.DeepResearchError, match="asset_id"):
        l4p.persist_l4a_discovery(
            tmp_path,
            "C1",
            _payload(_asset(), _asset()),
            _receipt(),
            question="Q",
            claim="H",
        )


def test_l4a_rejects_missing_required_asset_field(tmp_path):
    malformed = _asset()
    malformed.pop("source_database")
    with pytest.raises(dr.DeepResearchError, match="source_database"):
        l4p.persist_l4a_discovery(
            tmp_path,
            "C1",
            _payload(malformed),
            _receipt(),
            question="Q",
            claim="H",
        )


def test_l4a_manifest_rejects_inconsistent_selected_ids(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["selected_asset_ids"] = []
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256")
    manifest["manifest_sha256"] = l4p._sha256_json(unsigned)
    (tmp_path / manifest["path"]).write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    ok, reason = l4p.validate_l4a_manifest(tmp_path, manifest)

    assert ok is False
    assert "selected_asset_ids" in reason


def test_l4b_accepts_normalized_doi_from_frozen_corpus(tmp_path):
    manifest = _manifest(tmp_path)
    paper_path = _paper_record(
        tmp_path,
        doi="https://doi.org/10.1000/EXAMPLE",
        pmid="",
        url="",
    )
    artifact, path = _linked_artifact(
        tmp_path,
        manifest,
        papers=[
            {
                "paper_id": "P1",
                "path": paper_path,
                "doi": "https://doi.org/10.1000/EXAMPLE",
                "pmid": "",
                "url": "",
                "user_source_id": "",
                "evidence_ids": [],
            }
        ],
    )

    l4p._persist_l4b_linkage(tmp_path, artifact)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["pipeline_stage"] == "L4B"


def test_l4b_rejects_out_of_corpus_paper_before_staged_linkage(tmp_path):
    manifest = _manifest(tmp_path)
    paper_path = _paper_record(
        tmp_path,
        name="outside.json",
        title="Unselected paper",
        metadata={"year": 2025},
        doi="10.9999/outside",
        pmid="",
        url="https://outside.example/paper",
    )
    artifact, path = _linked_artifact(
        tmp_path,
        manifest,
        papers=[
            {
                "paper_id": "P2",
                "path": paper_path,
                "doi": "10.9999/outside",
                "pmid": "",
                "url": "https://outside.example/paper",
                "user_source_id": "",
                "evidence_ids": [],
            }
        ],
    )

    with pytest.raises(dr.DeepResearchError, match="frozen L4A corpus"):
        l4p._persist_l4b_linkage(tmp_path, artifact)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "pipeline_schema" not in persisted


def test_l4b_accepts_candidate_owned_registered_user_source(tmp_path):
    candidate = tmp_path / "01_Candidates/C1.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("# Candidate", encoding="utf-8")
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\nregistered source")
    registered = register_pdf(tmp_path, "C1", pdf)

    manifest = _manifest(tmp_path)
    paper_path = _paper_record(
        tmp_path,
        name="user-source.json",
        doi="",
        pmid="",
        url="",
        user_source_id=registered["user_source_id"],
        user_source_sha256=registered["sha256"],
    )
    artifact, path = _linked_artifact(
        tmp_path,
        manifest,
        papers=[
            {
                "paper_id": "P3",
                "path": paper_path,
                "doi": "",
                "pmid": "",
                "url": "",
                "user_source_id": registered["user_source_id"],
                "evidence_ids": [],
            }
        ],
    )

    l4p._persist_l4b_linkage(tmp_path, artifact)

    assert json.loads(path.read_text(encoding="utf-8"))["pipeline_stage"] == "L4B"


def test_l4_lineage_rejects_manifest_from_another_candidate(tmp_path):
    manifest = _manifest(tmp_path, candidate_id="C2")
    artifact = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
    }
    module = SimpleNamespace(
        _artifact=lambda *args, **kwargs: artifact,
        audit_evidence_pack=lambda *args, **kwargs: (True, ""),
        evidence_artifact_manifest=lambda *args, **kwargs: {
            "run_id": "RUN2",
            "files": [],
        },
    )
    l4_lineage.install(module)

    ok, reason = module.audit_evidence_pack(
        tmp_path, "C1", "L4", run_id="RUN2"
    )

    assert ok is False
    assert "candidate" in reason


def test_l4_lineage_rejects_wrong_l4a_run_id(tmp_path):
    manifest = _manifest(tmp_path)
    artifact = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": "OTHER-RUN",
    }
    module = SimpleNamespace(
        _artifact=lambda *args, **kwargs: artifact,
        audit_evidence_pack=lambda *args, **kwargs: (True, ""),
        evidence_artifact_manifest=lambda *args, **kwargs: {
            "run_id": "RUN2",
            "files": [],
        },
    )
    l4_lineage.install(module)

    ok, reason = module.audit_evidence_pack(
        tmp_path, "C1", "L4", run_id="RUN2"
    )

    assert ok is False
    assert "run" in reason


def test_l45_rejects_project_round_profile_identity_mismatch(monkeypatch, tmp_path):
    manifest = _manifest(
        tmp_path,
        project_id="P2",
        round_id="2",
        profile_id="other-profile",
    )
    evidence = {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
        "project_id": "P1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
        "method_components": [],
        "method_candidates": [],
        "method_anchors": [],
    }
    delta = tmp_path / "delta.json"
    delta.write_text("{}", encoding="utf-8")
    expected_manifest = {"run_id": "RUN2", "files": []}
    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(
        dr,
        "evidence_artifact_manifest",
        lambda *a, **k: expected_manifest,
    )

    with pytest.raises(dr.DeepResearchError, match="project_id|round_id|profile_id"):
        l4p.commit_l45_method_projection(
            tmp_path,
            "C1",
            evidence,
            delta,
            expected_evidence_manifest=expected_manifest,
        )
