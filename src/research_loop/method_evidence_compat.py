"""Compatibility normalization for registered L4 user sources and references."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


_REFERENCE_CONTRACT = """
L4 reference-integrity contract:
- Every retained non-navigation anchor must list explicit `method_ids`.
- Its `method_component_ids` must include the declared `component_id` of every
  referenced `method_id`.
- Do not use L4A asset IDs as method or component IDs unless those IDs are
  separately declared in `method_candidates` or `method_components`.
- RLR may only add a missing component reference when it is deterministically
  implied by a valid, explicit method reference. Unknown or unresolved IDs must
  remain fail-closed.
"""


def _normalize_id(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _normalize_id_list(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    normalized = []
    for item in value:
        item = _normalize_id(item)
        if item not in normalized:
            normalized.append(item)
    return normalized


def _canonicalize_l4_references(payload: dict) -> dict:
    """Canonicalize IDs and close only deterministic method→component lineage.

    `method_ids` are authoritative explicit references. `method_component_ids`
    are redundant lineage metadata. When all declarations and references are
    valid and unique, missing component refs can be derived without guessing.
    Malformed, duplicate, unknown, or empty references are preserved for the
    existing validator to reject.
    """
    components = payload.get("method_components")
    candidates = payload.get("method_candidates")
    if not isinstance(components, list) or not isinstance(candidates, list):
        return payload

    for component in components:
        if isinstance(component, dict) and "component_id" in component:
            component["component_id"] = _normalize_id(component["component_id"])

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if "method_id" in candidate:
            candidate["method_id"] = _normalize_id(candidate["method_id"])
        if "component_id" in candidate:
            candidate["component_id"] = _normalize_id(candidate["component_id"])
        if "method_anchor_ids" in candidate:
            candidate["method_anchor_ids"] = _normalize_id_list(
                candidate["method_anchor_ids"]
            )

    for paper in payload.get("papers", []):
        if not isinstance(paper, dict):
            continue
        for extract in paper.get("extracts", []):
            if not isinstance(extract, dict):
                continue
            if "anchor_id" in extract:
                extract["anchor_id"] = _normalize_id(extract["anchor_id"])
            if "method_ids" in extract:
                extract["method_ids"] = _normalize_id_list(extract["method_ids"])
            if "method_component_ids" in extract:
                extract["method_component_ids"] = _normalize_id_list(
                    extract["method_component_ids"]
                )

    component_ids = [
        component.get("component_id")
        for component in components
        if isinstance(component, dict)
    ]
    if (
        len(component_ids) != len(components)
        or any(not isinstance(value, str) or not value for value in component_ids)
        or len(component_ids) != len(set(component_ids))
    ):
        return payload
    component_id_set = set(component_ids)

    method_to_component = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return payload
        method_id = candidate.get("method_id")
        component_id = candidate.get("component_id")
        if (
            not isinstance(method_id, str)
            or not method_id
            or method_id in method_to_component
            or not isinstance(component_id, str)
            or component_id not in component_id_set
        ):
            return payload
        method_to_component[method_id] = component_id

    for paper in payload.get("papers", []):
        if not isinstance(paper, dict):
            continue
        for extract in paper.get("extracts", []):
            if not isinstance(extract, dict):
                continue
            method_refs = extract.get("method_ids")
            component_refs = extract.get("method_component_ids")
            if (
                not isinstance(method_refs, list)
                or not method_refs
                or not isinstance(component_refs, list)
                or not component_refs
                or any(
                    not isinstance(value, str)
                    or not value
                    or value not in method_to_component
                    for value in method_refs
                )
                or any(
                    not isinstance(value, str)
                    or not value
                    or value not in component_id_set
                    for value in component_refs
                )
            ):
                continue
            for method_id in method_refs:
                component_id = method_to_component[method_id]
                if component_id not in component_refs:
                    component_refs.append(component_id)
    return payload


def _normalized_payload(payload: Any, node: str | None) -> Any:
    if (
        node != "L4"
        or not isinstance(payload, dict)
        or not payload.get("method_components")
    ):
        return payload
    normalized = copy.deepcopy(payload)
    for paper in normalized.get("papers", []):
        if not isinstance(paper, dict):
            continue
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
    return _canonicalize_l4_references(normalized)


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
    original_parse = dr._parse_cli_output
    original_validate = dr.validate_payload
    original_persist = dr.persist_run
    original_run = dr.run_and_persist

    def parse_cli_output(value):
        return _normalized_payload(original_parse(value), "L4")

    def validate_payload(payload, *, node=None, project_dir=None, candidate_id=""):
        normalized = _normalized_payload(payload, node)
        if node == "L4" and isinstance(normalized, dict) and normalized.get(
            "method_components"
        ):
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
        if node == "L4":
            claim = f"{claim.rstrip()}\n\n{_REFERENCE_CONTRACT.strip()}\n"
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

    dr._parse_cli_output = parse_cli_output
    dr.validate_payload = validate_payload
    dr.persist_run = persist_run
    dr.run_and_persist = run_and_persist
    dr.canonicalize_l4_references = _canonicalize_l4_references
    dr._METHOD_EVIDENCE_COMPAT_INSTALLED = True
