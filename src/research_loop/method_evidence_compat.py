"""Compatibility normalization for registered L4 user sources."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def _normalized_payload(payload: dict, node: str | None) -> dict:
    if node != "L4" or not payload.get("method_components"):
        return payload
    normalized = copy.deepcopy(payload)
    for paper in normalized.get("papers", []):
        user_source_id = str(paper.get("user_source_id") or "").strip()
        if (
            user_source_id
            and not any(
                str(paper.get(key) or "").strip()
                for key in ("doi", "pmid", "url")
            )
        ):
            # The registered source ID is a stable, candidate-scoped local
            # identifier. It is not an internet URL and never bypasses the
            # subsequent candidate/SHA256 verification.
            paper["url"] = f"user-source:{user_source_id}"
    return normalized


def _normalize_receipt_schema(project_dir, artifact: dict) -> dict:
    if artifact.get("node") != "L4" or not artifact.get("method_components"):
        return artifact
    # EvidenceRunReceipt/v1.1 permits additive fields and is the receipt identity
    # currently bound by ContextManifest/v2. Keep that identity until a dedicated
    # receipt-schema migration changes the context contract atomically.
    artifact["evidence_receipt_schema"] = "EvidenceRunReceipt/v1.1"
    path = Path(project_dir) / str(artifact.get("path") or "")
    if path.is_file():
        path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return artifact


def install(deep_research_module) -> None:
    dr = deep_research_module
    if getattr(dr, "_METHOD_EVIDENCE_COMPAT_INSTALLED", False):
        return
    original_validate = dr.validate_payload
    original_persist = dr.persist_run
    original_run = dr.run_and_persist

    def validate_payload(payload, *, node=None, project_dir=None, candidate_id=""):
        normalized = _normalized_payload(payload, node)
        if node == "L4" and normalized.get("method_components"):
            for paper in normalized.get("papers", []):
                source_payload = str(paper.get("source_payload") or "")
                if len(source_payload.encode("utf-8")) > dr._MAX_SOURCE_BYTES:
                    raise dr.DeepResearchError(
                        "L4 retained source payload exceeds 5 MiB limit"
                    )
        return original_validate(
            normalized,
            node=node,
            project_dir=project_dir,
            candidate_id=candidate_id,
        )

    def persist_run(
        project_dir,
        candidate_id,
        node,
        payload,
        receipt,
        result_context="",
        *,
        project_id="",
        round_id="",
        profile_id="",
        research_persona="Curie",
    ):
        artifact = original_persist(
            project_dir,
            candidate_id,
            node,
            _normalized_payload(payload, node),
            receipt,
            result_context,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            research_persona=research_persona,
        )
        return _normalize_receipt_schema(project_dir, artifact)

    def run_and_persist(
        project_dir,
        candidate_id,
        node,
        question,
        claim,
        spec,
        work_dir,
        skill_version="unknown",
        result_context="",
        *,
        project_id="",
        round_id="",
        profile_id="",
        research_persona="Curie",
    ):
        artifact = original_run(
            project_dir,
            candidate_id,
            node,
            question,
            claim,
            spec,
            work_dir,
            skill_version,
            result_context,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            research_persona=research_persona,
        )
        return _normalize_receipt_schema(project_dir, artifact)

    dr.validate_payload = validate_payload
    dr.persist_run = persist_run
    dr.run_and_persist = run_and_persist
    dr._METHOD_EVIDENCE_COMPAT_INSTALLED = True
