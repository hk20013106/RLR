import json
from pathlib import Path

import pytest

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p


REAL_UNSELECTED_REVIEW = {
    "doi": "10.1038/nrg.2017.19",
    "pmid": "28479595",
    "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6413734/",
    "title": "Comparative transcriptomics in human and mouse",
    "year": 2017,
}


def _asset(
    *,
    asset_id="A1",
    doi="10.1000/example",
    pmid="111",
    url="https://example.org/paper",
    title="Example method paper",
    year=2026,
    role="method",
):
    asset = {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "title": title,
        "year": year,
        "journal": "Methods Journal",
        "abstract": "Metadata only.",
        "source_database": "Europe PMC",
        "source_metadata_response": '{"id":"%s"}' % asset_id,
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
    asset["role"] = role
    return asset


def _manifest(project: Path, *assets: dict) -> dict:
    return l4p.persist_l4a_discovery(
        project,
        "C1",
        {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "queries": [{
                "query_id": "Q1",
                "query": "interaction model method",
                "purpose": "Find implementation evidence.",
                "status": "completed",
                "receipt": "Europe PMC receipt",
            }],
            "assets": list(assets or (_asset(),)),
        },
        dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test"),
        question="Q",
        claim="H",
    )


def _paper_record(project: Path, *, name="paper.json", paper_type="primary", **fields) -> str:
    relative = Path("09_Literature_Database/evidence_packs/papers") / name
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "title": fields.pop("title", "Example method paper"),
        "metadata": fields.pop("metadata", {"year": 2026}),
        "paper_type": paper_type,
        **fields,
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return relative.as_posix()


def _artifact(manifest: dict, *, papers: list[dict], review_search: dict) -> dict:
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "run_id": "RUN2",
        "candidate_id": "C1",
        "project_id": "",
        "round_id": "",
        "profile_id": "",
        "node": "L4",
        "status": "completed",
        "path": "09_Literature_Database/evidence_packs/runs/RUN2.json",
        "papers": papers,
        "review_search": review_search,
        "method_components": [{
            "component_id": "model",
            "name": "Model",
            "required": True,
            "rationale": "Test component.",
        }],
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
    }


def _paper_reference(path: str, *, doi="", pmid="", url="", **_ignored) -> dict:
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
    unstaged = dict(artifact)
    for key in (
        "pipeline_schema", "pipeline_stage", "l4a_manifest_path",
        "l4a_manifest_sha256", "l4a_run_id",
    ):
        unstaged.pop(key, None)
    path.write_text(json.dumps(unstaged), encoding="utf-8")


def _method_text() -> str:
    return "Fit a linear model with species, region, and interaction terms."


def _payload_with_review(*, review: dict, review_status="not_retained") -> dict:
    source = "<article>" + (_method_text() + " detailed source context. ") * 40 + "</article>"
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["frozen L4A catalog only"],
        "method_components": [{
            "component_id": "model",
            "name": "Model",
            "required": True,
            "rationale": "Test component.",
        }],
        "method_candidates": [{
            "method_id": "m1",
            "component_id": "model",
            "name": "Linear model",
            "status": "eligible",
            "purpose": "Estimate interaction.",
            "applicable_to": ["expression"],
            "implementation_steps": ["fit model"],
            "assumptions": [],
            "expected_outputs": ["estimates"],
            "strengths": [],
            "limitations": [],
            "alternatives": [],
            "rejection_reasons": [],
            "method_anchor_ids": ["A1"],
            "missing_source": "",
        }],
        "papers": [
            {
                "doi": "10.1000/example",
                "pmid": "111",
                "url": "https://example.org/paper",
                "title": "Example method paper",
                "source_database": "Europe PMC",
                "metadata": {"year": 2026, "journal": "Methods Journal"},
                "source_metadata_response": {"id": "A1", "title": "Example"},
                "open_access": True,
                "content_type": "text/html",
                "source_payload": source,
                "paper_type": "primary",
                "user_source_id": "",
                "user_source_sha256": "",
                "extracts": [{
                    "anchor_id": "A1",
                    "section": "Methods",
                    "text": _method_text(),
                    "locator": "Methods paragraph 1",
                    "extraction_method": "source-located",
                    "verification_status": "located",
                    "method_component_ids": ["model"],
                    "method_ids": ["m1"],
                    "source_kind": "primary_study",
                }],
            },
            {
                **REAL_UNSELECTED_REVIEW,
                "source_database": "PubMed",
                "metadata": {"year": 2017, "journal": "Nature Reviews Genetics"},
                "source_metadata_response": {"id": "28479595", "title": REAL_UNSELECTED_REVIEW["title"]},
                "open_access": False,
                "content_type": "text/plain",
                "source_payload": "",
                "paper_type": "review",
                "user_source_id": "",
                "user_source_sha256": "",
                "extracts": [{
                    "section": "Conclusion",
                    "text": "Review conclusion.",
                    "locator": "Conclusion",
                    "extraction_method": "source-located",
                    "verification_status": "located",
                    "anchor_id": "",
                    "method_component_ids": [],
                    "method_ids": [],
                    "source_kind": "navigation_only",
                }],
            },
        ],
        "review_search": {
            "query": "frozen catalog review status",
            "status": review_status,
            "receipt": "No selected review in frozen L4A catalog; review navigation not retained.",
        },
        "verification": [],
    }


def test_l4a_prompt_and_frozen_catalog_define_asset_role_and_closed_handoff(tmp_path, monkeypatch):
    prompt = l4p.build_l4a_prompt("Q", "H")
    assert "role" in prompt
    review_schema = dr._runtime_schema("L4")["properties"]["review_search"]
    assert review_schema["properties"]["status"] == {
        "enum": ["completed", "none_found", "not_retained"]
    }
    manifest = _manifest(tmp_path, _asset(role="primary"))
    catalog = json.loads(l4p.frozen_l4a_catalog(manifest))
    assert catalog["assets"][0]["role"] == "primary"

    observed = {}

    def original(*args, **kwargs):
        observed["claim"] = args[4]
        return {"node": "L4", "status": "completed", "path": "runs/RUN2.json"}

    module = type("Module", (), {})()
    module.run_and_persist = original
    original_discovery = l4p.run_l4a_discovery
    l4p.run_l4a_discovery = lambda *args, **kwargs: manifest
    monkeypatch.setattr(l4p, "_persist_l4b_linkage", lambda *_args, **_kwargs: None)
    try:
        l4p.install(module)
        module.run_and_persist(
            tmp_path, "C1", "L4", "Q", "H",
            dr.RuntimeSpec("codex", "codex"), tmp_path / "work",
        )
    finally:
        l4p.run_l4a_discovery = original_discovery
    claim = observed["claim"]
    assert "MUST NOT perform online literature searches" in claim
    assert "not_retained" in claim
    assert "registered local sources" in claim


def test_selected_review_is_allowed_when_it_is_in_the_frozen_catalog(tmp_path):
    review = _asset(
        asset_id="R1",
        doi="10.1038/nrg.2017.19",
        pmid="28479595",
        url="https://pubmed.ncbi.nlm.nih.gov/28479595/",
        title=REAL_UNSELECTED_REVIEW["title"],
        year=2017,
        role="review",
    )
    manifest = _manifest(tmp_path, review)
    paper_path = _paper_record(
        tmp_path,
        title=REAL_UNSELECTED_REVIEW["title"],
        metadata={"year": 2017, "journal": "Nature Reviews Genetics"},
        paper_type="review",
        doi=REAL_UNSELECTED_REVIEW["doi"],
        pmid=REAL_UNSELECTED_REVIEW["pmid"],
        url=REAL_UNSELECTED_REVIEW["url"],
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, **REAL_UNSELECTED_REVIEW)],
        review_search={"query": "frozen review", "status": "completed", "receipt": "selected review"},
    )
    _write_unstaged_run(tmp_path, artifact)

    l4p._persist_l4b_linkage(tmp_path, artifact)

    assert json.loads((tmp_path / artifact["path"]).read_text(encoding="utf-8"))["pipeline_stage"] == "L4B"


def test_unselected_real_review_fails_closed(tmp_path):
    manifest = _manifest(tmp_path, _asset())
    paper_path = _paper_record(
        tmp_path,
        title=REAL_UNSELECTED_REVIEW["title"],
        metadata={"year": 2017, "journal": "Nature Reviews Genetics"},
        paper_type="review",
        **{key: value for key, value in REAL_UNSELECTED_REVIEW.items() if key != "title" and key != "year"},
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, **REAL_UNSELECTED_REVIEW)],
        review_search={"query": "frozen review", "status": "not_retained", "receipt": "not retained"},
    )
    _write_unstaged_run(tmp_path, artifact)

    with pytest.raises(dr.DeepResearchError, match="selected review|frozen L4A corpus"):
        l4p._persist_l4b_linkage(tmp_path, artifact)


def test_no_selected_review_requires_and_accepts_explicit_no_review_receipt(tmp_path):
    manifest = _manifest(tmp_path, _asset())
    paper_path = _paper_record(
        tmp_path,
        doi="10.1000/example",
        pmid="111",
        url="https://example.org/paper",
    )
    artifact = _artifact(
        manifest,
        papers=[_paper_reference(paper_path, doi="10.1000/example", pmid="111", url="https://example.org/paper")],
        review_search={
            "query": "frozen review",
            "status": "not_retained",
            "receipt": "No selected review in frozen L4A catalog; review navigation not retained.",
        },
    )
    _write_unstaged_run(tmp_path, artifact)

    l4p._persist_l4b_linkage(tmp_path, artifact)

    assert json.loads((tmp_path / artifact["path"]).read_text(encoding="utf-8"))["pipeline_stage"] == "L4B"


def test_l4b_pre_persistence_rejects_real_unselected_review(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path, _asset())
    monkeypatch.setattr(
        dr,
        "_l4b_frozen_manifest_context",
        (tmp_path, "C1", manifest),
        raising=False,
    )

    with pytest.raises(dr.DeepResearchError, match="selected review|frozen L4A corpus"):
        dr.persist_run(
            tmp_path,
            "C1",
            "L4",
            _payload_with_review(review=REAL_UNSELECTED_REVIEW),
            dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test"),
        )

    assert not (tmp_path / "09_Literature_Database/evidence_packs/papers").exists()


def test_review_navigation_cannot_claim_a_method_anchor():
    payload = _payload_with_review(review={"doi": "10.1000/review", "pmid": "9", "url": "https://example.org/review", "title": "Selected review", "year": 2026})
    review_extract = payload["papers"][1]["extracts"][0]
    review_extract.update({
        "anchor_id": "BAD",
        "method_component_ids": ["model"],
        "method_ids": ["m1"],
        "source_kind": "method_paper",
    })

    with pytest.raises(dr.DeepResearchError, match="review.*method-anchor|navigation"):
        dr.validate_payload(payload, node="L4", project_dir=Path("."), candidate_id="C1")
