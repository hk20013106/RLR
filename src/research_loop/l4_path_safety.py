"""Reject candidate identifiers that could escape staged-L4 artifact roots."""
from __future__ import annotations

import re


_SAFE_CANDIDATE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def _require_safe_candidate_id(deep_research_module, value) -> str:
    candidate_id = str(value or "").strip()
    if not _SAFE_CANDIDATE_ID.fullmatch(candidate_id):
        raise deep_research_module.DeepResearchError(
            "staged L4 candidate_id must be a path-safe identifier"
        )
    return candidate_id


def install(l4_pipeline_module, deep_research_module) -> None:
    if getattr(l4_pipeline_module, "_l4_path_safety_installed", False):
        return

    original_persist = l4_pipeline_module.persist_l4a_discovery

    def persist_l4a_discovery(
        project_dir,
        candidate_id,
        payload,
        runtime_receipt,
        *,
        question,
        claim,
        project_id="",
        round_id="",
        profile_id="",
    ):
        safe_candidate = _require_safe_candidate_id(
            deep_research_module, candidate_id
        )
        return original_persist(
            project_dir,
            safe_candidate,
            payload,
            runtime_receipt,
            question=question,
            claim=claim,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
        )

    original_commit = l4_pipeline_module.commit_l45_method_projection

    def commit_l45_method_projection(
        project_dir,
        candidate_id,
        evidence_artifact,
        l4c_delta_path,
    ):
        safe_candidate = _require_safe_candidate_id(
            deep_research_module, candidate_id
        )
        return original_commit(
            project_dir,
            safe_candidate,
            evidence_artifact,
            l4c_delta_path,
        )

    l4_pipeline_module.persist_l4a_discovery = persist_l4a_discovery
    l4_pipeline_module.commit_l45_method_projection = commit_l45_method_projection
    l4_pipeline_module._l4_path_safety_original_persist = original_persist
    l4_pipeline_module._l4_path_safety_original_commit = original_commit
    l4_pipeline_module._l4_path_safety_installed = True
