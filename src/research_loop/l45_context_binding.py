"""Context-bound verification for deterministic L4.5 projections."""
from __future__ import annotations

from research_loop import deep_research
from research_loop.l4_pipeline import PIPELINE_SCHEMA_VERSION


def install(l4_pipeline_module) -> None:
    """Require staged L4.5 commits to match Fisher's exact evidence context."""
    if getattr(l4_pipeline_module, "_l45_context_binding_installed", False):
        return

    original = l4_pipeline_module.commit_l45_method_projection

    def commit_l45_method_projection(
        project_dir,
        candidate_id,
        evidence_artifact,
        l4c_delta_path,
        *,
        expected_evidence_manifest=None,
    ):
        staged = (
            evidence_artifact.get("pipeline_schema") == PIPELINE_SCHEMA_VERSION
            and evidence_artifact.get("pipeline_stage") == "L4B"
        )
        if staged:
            if not isinstance(expected_evidence_manifest, dict):
                raise deep_research.DeepResearchError(
                    "staged L4.5 requires the evidence manifest recorded at context assembly"
                )
            run_id = str(evidence_artifact.get("run_id") or "")
            current = deep_research.evidence_artifact_manifest(
                project_dir, str(candidate_id), "L4", run_id
            )
            if current != expected_evidence_manifest:
                raise deep_research.DeepResearchError(
                    "L4B evidence artifacts changed since context assembly"
                )

        artifact, path, created = original(
            project_dir,
            candidate_id,
            evidence_artifact,
            l4c_delta_path,
        )
        if staged and artifact.get("l4b_evidence_manifest") != expected_evidence_manifest:
            if created:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    raise deep_research.DeepResearchError(
                        "L4B evidence artifacts changed since context assembly; "
                        "failed to remove the new L4.5 projection"
                    ) from exc
            raise deep_research.DeepResearchError(
                "L4B evidence artifacts changed since context assembly"
            )
        return artifact, path, created

    l4_pipeline_module._l45_context_original_commit = original
    l4_pipeline_module.commit_l45_method_projection = commit_l45_method_projection
    l4_pipeline_module._l45_context_binding_installed = True
