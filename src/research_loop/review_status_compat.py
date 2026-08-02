"""Normalize semantically equivalent ARS review-search status labels."""
from __future__ import annotations

import json
from pathlib import Path


_STATUS_ALIASES = {
    "relevant_review_located": "completed",
    "review_located": "completed",
    "no_relevant_review_found": "none_found",
    "zero_results": "none_found",
}


def _normalize_artifact(project_dir, artifact: dict) -> dict:
    if artifact.get("node") != "L4":
        return artifact
    review = artifact.get("review_search")
    if not isinstance(review, dict):
        return artifact
    status = str(review.get("status") or "").strip().lower()
    canonical = _STATUS_ALIASES.get(status)
    if not canonical:
        return artifact
    review["status"] = canonical
    review["reported_status"] = status
    path = Path(project_dir) / str(artifact.get("path") or "")
    if path.is_file():
        path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return artifact


def install(deep_research_module) -> None:
    dr = deep_research_module
    if getattr(dr, "_REVIEW_STATUS_COMPAT_INSTALLED", False):
        return
    original_persist = dr.persist_run
    original_run = dr.run_and_persist

    def persist_run(project_dir, candidate_id, node, payload, receipt,
                    result_context="", *, project_id="", round_id="",
                    profile_id="", research_persona="Curie"):
        artifact = original_persist(
            project_dir, candidate_id, node, payload, receipt, result_context,
            project_id=project_id, round_id=round_id, profile_id=profile_id,
            research_persona=research_persona,
        )
        return _normalize_artifact(project_dir, artifact)

    def run_and_persist(project_dir, candidate_id, node, question, claim, spec,
                        work_dir, skill_version="unknown", result_context="", *,
                        project_id="", round_id="", profile_id="",
                        research_persona="Curie"):
        artifact = original_run(
            project_dir, candidate_id, node, question, claim, spec, work_dir,
            skill_version, result_context, project_id=project_id,
            round_id=round_id, profile_id=profile_id,
            research_persona=research_persona,
        )
        return _normalize_artifact(project_dir, artifact)

    dr.persist_run = persist_run
    dr.run_and_persist = run_and_persist
    dr._REVIEW_STATUS_COMPAT_INSTALLED = True
