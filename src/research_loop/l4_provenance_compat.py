"""Compatibility for pre-persistence staged-L4 DTOs.

Canonical staged artifacts are persisted before lineage or L4.5 validation and
therefore carry an artifact path plus explicit candidate/run identities. Older
unit-test and third-party wrapper DTOs may exist only in memory and omit those
redundant fields. This bridge preserves that narrow compatibility without
relaxing validation for persisted artifacts or explicit identity mismatches.
"""
from __future__ import annotations

from pathlib import Path


def install(l4_pipeline_module, provenance_module) -> None:
    if getattr(l4_pipeline_module, "_l4_provenance_compat_installed", False):
        return

    strict_identity_reason = provenance_module._identity_reason

    def identity_reason(
        manifest,
        artifact,
        *,
        expected_candidate_id="",
    ):
        compatible = dict(artifact)
        persisted_reference = bool(str(compatible.get("path") or "").strip())
        if not persisted_reference:
            if not str(compatible.get("candidate_id") or "").strip():
                compatible["candidate_id"] = str(
                    expected_candidate_id or manifest.get("candidate_id") or ""
                )
            if not str(compatible.get("l4a_run_id") or "").strip():
                compatible["l4a_run_id"] = str(manifest.get("run_id") or "")
        return strict_identity_reason(
            manifest,
            compatible,
            expected_candidate_id=expected_candidate_id,
        )

    provenance_module._identity_reason = identity_reason

    strict_persist_linkage = l4_pipeline_module._persist_l4b_linkage
    base_persist_linkage = (
        l4_pipeline_module._l4_provenance_original_persist_linkage
    )

    def persist_l4b_linkage(project_dir, artifact):
        relative = str(artifact.get("path") or "").strip()
        if not relative:
            return base_persist_linkage(project_dir, artifact)
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            return strict_persist_linkage(project_dir, artifact)
        if not (Path(project_dir) / path).is_file():
            # The captured historical implementation is intentionally a no-op
            # for an artifact that has not yet been persisted.
            return base_persist_linkage(project_dir, artifact)
        return strict_persist_linkage(project_dir, artifact)

    l4_pipeline_module._persist_l4b_linkage = persist_l4b_linkage
    l4_pipeline_module._l4_provenance_compat_strict_identity = (
        strict_identity_reason
    )
    l4_pipeline_module._l4_provenance_compat_strict_linkage = (
        strict_persist_linkage
    )
    l4_pipeline_module._l4_provenance_compat_installed = True
