"""Narrow compatibility boundary for staged L4 v2.

Native v2.1 Codex structured-output runs use the deterministic
inventory/evidence pipeline. Historical profiles and Claude plugin runs retain
the original L4 provider behavior until an inventory-schema adapter is verified
for that provider. Retrieval receipt text is canonicalized to UTF-8/LF after
persistence so its recorded hash is identical on Windows and POSIX hosts.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


_NATIVE_PROFILE_PREFIX = "v2.1"
_STAGED_BACKENDS = {"codex"}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonicalize_receipts(project_dir, artifact: dict) -> None:
    project = Path(project_dir).resolve()
    for ref in artifact.get("full_text_retrieval") or []:
        relative = Path(str(ref.get("path") or ""))
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("L4B retrieval receipt path is unsafe")
        path = (project / relative).resolve()
        try:
            path.relative_to(project)
        except ValueError as exc:
            raise ValueError("L4B retrieval receipt path escapes the project") from exc
        text = path.read_text(encoding="utf-8")
        raw = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        path.write_bytes(raw)
        expected = str(ref.get("sha256") or "")
        if not expected or _sha(raw) != expected:
            raise ValueError("L4B retrieval receipt canonical hash mismatch")


def _supports_staged_l4(spec, profile_id: str) -> bool:
    return (
        str(profile_id).startswith(_NATIVE_PROFILE_PREFIX)
        and str(getattr(spec, "backend", "")) in _STAGED_BACKENDS
    )


def install(deep_research_module, evidence_bundle_module) -> None:
    if getattr(deep_research_module, "_l4_runtime_compat_installed", False):
        return

    staged_run = deep_research_module.run_and_persist
    legacy_run = deep_research_module._l4_evidence_bundle_original_run
    deterministic_bundle = evidence_bundle_module.run_l4b_evidence

    def run_l4b_evidence(*args, **kwargs):
        artifact = deterministic_bundle(*args, **kwargs)
        project_dir = args[2] if len(args) > 2 else kwargs["project_dir"]
        _canonicalize_receipts(project_dir, artifact)
        return artifact

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
        if node == "L4" and not _supports_staged_l4(spec, profile_id):
            return legacy_run(
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
        return staged_run(
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

    evidence_bundle_module.run_l4b_evidence = run_l4b_evidence
    deep_research_module.run_and_persist = run_and_persist
    deep_research_module._l4_runtime_compat_staged_run = staged_run
    deep_research_module._l4_runtime_compat_legacy_run = legacy_run
    deep_research_module._l4_runtime_compat_installed = True
