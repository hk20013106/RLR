import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p


def _schema_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _schema_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schema_keys(child)


def _asset(
    *,
    asset_id="A1",
    doi="10.1000/example",
    pmid="",
    url="https://example.org/paper",
    title="Example method paper",
    year=2026,
    relevance_score=8.0,
    selection_status="selected",
):
    return {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "title": title,
        "year": year,
        "journal": "Methods Journal",
        "abstract": "A metadata-only abstract.",
        "source_database": "Europe PMC",
        "source_metadata_response": {"id": asset_id, "title": title},
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": [url],
        "relevance_score": relevance_score,
        "selection_status": selection_status,
        "selection_reason": "Matches the required analysis component.",
        "hypothesis_ids": ["H1"],
        "method_component_hints": ["differential_expression"],
        "diagnostic_requirements": ["interaction test"],
    }


def _discovery_payload(*assets):
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "interaction model transcriptome method",
            "purpose": "Find implementation evidence.",
            "status": "completed",
            "receipt": "Europe PMC query receipt",
        }],
        "assets": list(assets),
    }


def _receipt():
    return dr.skill_receipt(
        "codex", ["codex", "exec"], "discovery prompt", "test"
    )


def _persist_manifest(project):
    return l4p.persist_l4a_discovery(
        project,
        "C1",
        _discovery_payload(_asset()),
        _receipt(),
        question="Q",
        claim="H",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )


def _linked_evidence(manifest):
    return {
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "run_id": "RUN2",
        "candidate_id": "C1",
        "node": "L4",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "method_components": [
            {"component_id": "C01", "name": "model", "required": True, "rationale": "test"}
        ],
        "method_candidates": [
            {
                "method_id": "M01",
                "component_id": "C01",
                "name": "interaction model",
                "status": "eligible",
                "method_anchor_ids": ["A01"],
            }
        ],
        "method_anchors": [
            {
                "anchor_id": "A01",
                "evidence_id": "E01",
                "method_component_ids": ["C01"],
                "method_ids": ["M01"],
            }
        ],
    }


def test_l4a_discovery_schema_is_strict_metadata_only():
    schema = l4p.l4a_discovery_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert {"schema_version", "queries", "assets"}.issubset(schema["required"])

    asset = schema["properties"]["assets"]["items"]
    assert asset["additionalProperties"] is False
    assert {
        "doi",
        "pmid",
        "url",
        "title",
        "source_database",
        "source_metadata_response",
        "open_access_status",
        "full_text_status",
        "relevance_score",
        "selection_status",
        "selection_reason",
    }.issubset(asset["required"])

    forbidden = {
        "source_payload",
        "extracts",
        "method_components",
        "method_candidates",
        "method_anchors",
    }
    assert forbidden.isdisjoint(set(_schema_keys(schema)))


def test_l4_pipeline_declares_ordered_stage_identities():
    stages = l4p.L4_PIPELINE_STAGES

    assert tuple(stage["stage_id"] for stage in stages) == (
        "L4A",
        "L4B",
        "L4C",
        "L4.5",
    )
    assert stages[0]["responsibility"] == "literature_discovery"
    assert stages[1]["responsibility"] == "evidence_construction"
    assert stages[2]["storage_key"] == "L4_fisher"
    assert stages[2]["cognitive"] is True
    assert stages[3]["responsibility"] == "deterministic_commit"
    assert stages[3]["cognitive"] is False


def test_l4a_deduplication_prefers_higher_relevance_for_normalized_doi():
    lower = _asset(
        asset_id="LOW",
        doi="https://doi.org/10.1000/EXAMPLE",
        relevance_score=4.0,
        selection_status="reserve",
    )
    higher = _asset(asset_id="HIGH", relevance_score=9.0)

    kept, duplicates = l4p.deduplicate_l4a_assets([lower, higher])

    assert [item["asset_id"] for item in kept] == ["HIGH"]
    assert duplicates == [{
        "identity": "doi:10.1000/example",
        "kept_asset_id": "HIGH",
        "duplicate_asset_id": "LOW",
        "reason": "lower_relevance_score",
    }]


def test_l4a_persistence_is_hash_bound_and_project_relative(tmp_path):
    project = tmp_path / "project"
    payload = _discovery_payload(_asset())

    artifact = l4p.persist_l4a_discovery(
        project,
        "C1",
        payload,
        _receipt(),
        question="Which interaction model should be used?",
        claim="H1 predicts a species by region interaction.",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )

    manifest_path = project / artifact["path"]
    assert artifact["schema_version"] == l4p.L4A_DISCOVERY_SCHEMA_VERSION
    assert artifact["pipeline_schema"] == l4p.PIPELINE_SCHEMA_VERSION
    assert artifact["pipeline_stage"] == "L4A"
    assert artifact["selected_asset_ids"] == ["A1"]
    assert not Path(artifact["path"]).is_absolute()
    assert manifest_path.is_file()
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == artifact
    assert l4p.validate_l4a_manifest(project, artifact) == (True, "")


def test_l4a_zero_selection_persists_then_fails_closed(tmp_path):
    project = tmp_path / "project"
    payload = _discovery_payload(
        _asset(asset_id="R1", selection_status="rejected")
    )

    artifact = l4p.persist_l4a_discovery(
        project, "C1", payload, _receipt(), question="Q", claim="H"
    )

    assert (project / artifact["path"]).is_file()
    assert artifact["selected_asset_ids"] == []
    with pytest.raises(dr.DeepResearchError, match="no selected literature assets"):
        l4p.selected_l4a_assets(artifact, require=True)


def test_frozen_l4a_catalog_is_canonical_and_metadata_only():
    manifest = {
        "selected_asset_ids": ["A1"],
        "assets": [_asset()],
    }

    text = l4p.frozen_l4a_catalog(manifest)
    decoded = json.loads(text)

    assert decoded["schema_version"] == l4p.L4A_DISCOVERY_SCHEMA_VERSION
    assert decoded["selected_asset_ids"] == ["A1"]
    assert decoded["assets"][0]["doi"] == "10.1000/example"
    assert "source_payload" not in text
    assert "method_anchors" not in text


def test_install_delegates_non_l4_without_discovery(monkeypatch, tmp_path):
    calls = []

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return {"node": args[2], "status": "completed"}

    module = SimpleNamespace(run_and_persist=original)
    monkeypatch.setattr(l4p, "run_l4a_discovery", lambda *a, **k: pytest.fail("L4A called"))
    l4p.install(module)

    result = module.run_and_persist(
        tmp_path, "C1", "L1", "Q", "H",
        dr.RuntimeSpec("codex", "codex"), tmp_path / "work",
    )

    assert result == {"node": "L1", "status": "completed"}
    assert len(calls) == 1
    assert calls[0][0][2] == "L1"


def test_install_runs_l4a_then_delegates_l4b_with_frozen_catalog(monkeypatch, tmp_path):
    manifest = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4A",
        "run_id": "RUN1",
        "path": "09_Literature_Database/l4/discovery/manifests/C1_RUN1.json",
        "manifest_sha256": "abc123",
        "selected_asset_ids": ["A1"],
        "assets": [_asset()],
    }
    observed = {}

    def original(*args, **kwargs):
        observed["claim"] = args[4]
        return {
            "node": "L4",
            "status": "completed",
            "path": "09_Literature_Database/evidence_packs/runs/RUN2.json",
        }

    module = SimpleNamespace(run_and_persist=original)
    monkeypatch.setattr(l4p, "run_l4a_discovery", lambda *a, **k: manifest)
    l4p.install(module)

    result = module.run_and_persist(
        tmp_path, "C1", "L4", "Q", "H",
        dr.RuntimeSpec("codex", "codex"), tmp_path / "work",
    )

    assert "FROZEN L4A DISCOVERY CORPUS" in observed["claim"]
    assert '"asset_id":"A1"' in observed["claim"]
    assert result["pipeline_schema"] == l4p.PIPELINE_SCHEMA_VERSION
    assert result["pipeline_stage"] == "L4B"
    assert result["l4a_manifest_path"] == manifest["path"]
    assert result["l4a_manifest_sha256"] == "abc123"


def test_l45_commit_is_hash_bound_and_idempotent(monkeypatch, tmp_path):
    project = tmp_path / "project"
    manifest = _persist_manifest(project)
    evidence = _linked_evidence(manifest)
    delta = project / "02_Agent_Notes" / "Fisher" / "C1_L4_fisher_delta.json"
    delta.parent.mkdir(parents=True)
    delta.write_text('{"schema_version":"2.1","candidate_id":"C1"}', encoding="utf-8")

    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(
        dr,
        "evidence_artifact_manifest",
        lambda *a, **k: {"run_id": "RUN2", "files": [{"path": "evidence", "sha256": "hash"}]},
    )

    first, first_path, first_created = l4p.commit_l45_method_projection(
        project, "C1", evidence, delta
    )
    second, second_path, second_created = l4p.commit_l45_method_projection(
        project, "C1", evidence, delta
    )

    assert first["schema_version"] == l4p.L45_COMMIT_SCHEMA_VERSION
    assert first["component_ids"] == ["C01"]
    assert first["method_ids"] == ["M01"]
    assert first["anchor_ids"] == ["A01"]
    assert first_path == second_path
    assert first_created is True
    assert second_created is False
    assert json.loads(first_path.read_text(encoding="utf-8")) == first


def test_l45_rejects_tampered_l4a_manifest(monkeypatch, tmp_path):
    project = tmp_path / "project"
    manifest = _persist_manifest(project)
    evidence = _linked_evidence(manifest)
    manifest_path = project / manifest["path"]
    manifest_path.write_text("{}", encoding="utf-8")
    delta = project / "delta.json"
    delta.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))

    with pytest.raises(dr.DeepResearchError, match="L4A manifest"):
        l4p.commit_l45_method_projection(project, "C1", evidence, delta)


def test_l45_rejects_changed_l4c_delta(monkeypatch, tmp_path):
    project = tmp_path / "project"
    manifest = _persist_manifest(project)
    evidence = _linked_evidence(manifest)
    delta = project / "delta.json"
    delta.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(dr, "audit_evidence_pack", lambda *a, **k: (True, ""))
    monkeypatch.setattr(
        dr,
        "evidence_artifact_manifest",
        lambda *a, **k: {"run_id": "RUN2", "files": []},
    )
    commit, _, _ = l4p.commit_l45_method_projection(project, "C1", evidence, delta)
    delta.write_text('{"changed":true}', encoding="utf-8")

    with pytest.raises(dr.DeepResearchError, match="L4C delta SHA256"):
        l4p.validate_l45_method_commit(project, commit)
