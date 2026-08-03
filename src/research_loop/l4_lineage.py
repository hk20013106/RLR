"""Fail-closed L4A lineage checks for staged L4B evidence artifacts."""
from __future__ import annotations

import json
from pathlib import Path

from research_loop.l4_pipeline import (
    PIPELINE_SCHEMA_VERSION,
    _sha256_bytes,
    validate_l4a_manifest,
)


def _staged_artifact(module, project_dir, candidate_id, node, run_id):
    if node != "L4":
        return None
    artifact = module._artifact(
        project_dir, candidate_id, node, run_id=run_id
    )
    if not artifact or artifact.get("pipeline_schema") != PIPELINE_SCHEMA_VERSION:
        return None
    return artifact


def _validate_link(module, project_dir, artifact) -> tuple[bool, str, Path | None]:
    project = Path(project_dir)
    relative = Path(str(artifact.get("l4a_manifest_path") or ""))
    if relative.is_absolute() or ".." in relative.parts or not str(relative):
        return False, "L4A manifest path is invalid", None
    path = project / relative
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"L4A manifest is unreadable: {exc}", None
    ok, reason = validate_l4a_manifest(project, manifest)
    if not ok:
        return False, f"L4A manifest validation failed: {reason}", None
    if manifest.get("manifest_sha256") != artifact.get("l4a_manifest_sha256"):
        return False, "L4A manifest SHA256 does not match L4B linkage", None
    return True, "", path


def install(deep_research_module) -> None:
    if getattr(deep_research_module, "_l4_lineage_installed", False):
        return
    original_audit = deep_research_module.audit_evidence_pack
    original_manifest = deep_research_module.evidence_artifact_manifest

    def audit_evidence_pack(project_dir, candidate_id, node, *, run_id=None):
        ok, reason = original_audit(
            project_dir, candidate_id, node, run_id=run_id
        )
        if not ok:
            return ok, reason
        artifact = _staged_artifact(
            deep_research_module, project_dir, candidate_id, node, run_id
        )
        if artifact is None:
            return True, ""
        linked, linked_reason, _ = _validate_link(
            deep_research_module, project_dir, artifact
        )
        return linked, linked_reason

    def evidence_artifact_manifest(project_dir, candidate_id, node, run_id):
        manifest = original_manifest(project_dir, candidate_id, node, run_id)
        artifact = _staged_artifact(
            deep_research_module, project_dir, candidate_id, node, run_id
        )
        if artifact is None:
            return manifest
        ok, reason, path = _validate_link(
            deep_research_module, project_dir, artifact
        )
        if not ok or path is None:
            error_type = getattr(deep_research_module, "DeepResearchError", ValueError)
            raise error_type(reason)
        files = list(manifest.get("files") or [])
        files.append({
            "kind": "l4a_discovery",
            "path": path.relative_to(Path(project_dir)).as_posix(),
            "sha256": _sha256_bytes(path.read_bytes()),
        })
        manifest = dict(manifest)
        manifest["files"] = sorted(
            files, key=lambda item: (item["kind"], item["path"])
        )
        return manifest

    deep_research_module._l4_lineage_original_audit = original_audit
    deep_research_module._l4_lineage_original_manifest = original_manifest
    deep_research_module.audit_evidence_pack = audit_evidence_pack
    deep_research_module.evidence_artifact_manifest = evidence_artifact_manifest
    deep_research_module._l4_lineage_installed = True
