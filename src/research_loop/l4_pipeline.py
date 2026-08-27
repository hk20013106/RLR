"""Staged L4 method-planning pipeline.

L4A performs metadata-only discovery. L4B delegates to the existing strict
method-evidence runtime. L4C remains the existing ``L4_fisher`` node. L4.5 is
a deterministic commit gate and never calls a model.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from research_loop import deep_research as _deep_research

PIPELINE_SCHEMA_VERSION = "L4MethodPlanningPipeline/v1"
L4A_DISCOVERY_SCHEMA_VERSION = "L4ADiscoveryManifest/v1"
L45_COMMIT_SCHEMA_VERSION = "L45MethodCommit/v1"

L4_PIPELINE_STAGES = (
    {"stage_id": "L4A", "responsibility": "literature_discovery", "cognitive": True, "storage_key": "L4A_discovery"},
    {"stage_id": "L4B", "responsibility": "evidence_construction", "cognitive": True, "storage_key": "L4B_evidence"},
    {"stage_id": "L4C", "responsibility": "fisher_method_design", "cognitive": True, "storage_key": "L4_fisher"},
    {"stage_id": "L4.5", "responsibility": "deterministic_commit", "cognitive": False, "storage_key": "L45_method_commit"},
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _string_array_schema() -> dict:
    return {"type": "array", "items": {"type": "string", "minLength": 1}}


def l4a_discovery_schema() -> dict:
    query = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "query_id": {"type": "string", "minLength": 1},
            "query": {"type": "string", "minLength": 1},
            "purpose": {"type": "string", "minLength": 1},
            "status": {"enum": ["completed", "failed", "partial"]},
            "receipt": {"type": "string"},
        },
        "required": ["query_id", "query", "purpose", "status", "receipt"],
    }
    asset_properties = {
        "asset_id": {"type": "string", "minLength": 1},
        "doi": {"type": "string"}, "pmid": {"type": "string"},
        "url": {"type": "string"},
        "title": {"type": "string", "minLength": 1},
        "year": {"type": "integer"}, "journal": {"type": "string"},
        "role": {
            "enum": [
                "primary", "method", "protocol", "review", "navigation",
                "other", "unspecified",
            ]
        },
        "abstract": {"type": "string"},
        "source_database": {"type": "string", "minLength": 1},
        # Provider wire form after the shared raw-result adapter. Codex
        # structured outputs require every object to be closed, while database
        # metadata is heterogeneous; the semantic object is therefore carried
        # as canonical JSON text here and restored to an object for persistence.
        "source_metadata_response": {"type": "string", "minLength": 2},
        "open_access_status": {"enum": ["open", "closed", "unknown"]},
        "full_text_status": {"enum": ["available_local", "available_oa", "metadata_only", "manual_required"]},
        "full_text_locations": _string_array_schema(),
        "relevance_score": {"type": "number", "minimum": 0, "maximum": 10},
        "selection_status": {"enum": ["selected", "reserve", "rejected", "manual_review"]},
        "selection_reason": {"type": "string", "minLength": 1},
        "hypothesis_ids": _string_array_schema(),
        "method_component_hints": _string_array_schema(),
        "diagnostic_requirements": _string_array_schema(),
    }
    asset = {
        "type": "object", "additionalProperties": False,
        "properties": asset_properties,
        # Codex structured outputs require every declared property to be
        # required.  Historical persisted manifests are normalized with
        # ``role=unspecified`` before they are validated at the persistence
        # boundary.
        "required": list(asset_properties),
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": L4A_DISCOVERY_SCHEMA_VERSION},
            "queries": {"type": "array", "minItems": 1, "items": query},
            "assets": {"type": "array", "items": asset},
        },
        "required": ["schema_version", "queries", "assets"],
    }


def _normalized_doi(value: str) -> str:
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", str(value or "").strip().lower())


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _asset_identity(asset: dict) -> str:
    doi = _normalized_doi(asset.get("doi", ""))
    if doi:
        return f"doi:{doi}"
    pmid = str(asset.get("pmid") or "").strip().lower()
    if pmid:
        return f"pmid:{pmid}"
    url = str(asset.get("url") or "").strip().lower().rstrip("/")
    if url:
        return f"url:{url}"
    return f"title:{_normalized_title(asset.get('title', ''))}|year:{asset.get('year', '')}"


def _parse_source_metadata_response(value: Any, *, asset_id: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        fenced = re.fullmatch(
            r"```[ \t]*(?:json)?[ \t]*\r?\n?(.*?)\r?\n?```",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if fenced:
            text = fenced.group(1).strip()

        def reject_non_json_constant(constant: str) -> None:
            raise ValueError(f"non-standard JSON constant {constant}")

        try:
            parsed = json.loads(text, parse_constant=reject_non_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise _deep_research.DeepResearchError(
                f"L4A source_metadata_response for asset {asset_id or '<unknown>'} "
                "must be valid JSON"
            ) from exc
    else:
        raise _deep_research.DeepResearchError(
            f"L4A source_metadata_response for asset {asset_id or '<unknown>'} "
            "must be a non-empty JSON object or JSON string"
        )

    try:
        parsed = json.loads(
            json.dumps(
                parsed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise _deep_research.DeepResearchError(
            f"L4A source_metadata_response for asset {asset_id or '<unknown>'} "
            "must be JSON-serializable"
        ) from exc
    if not isinstance(parsed, dict):
        raise _deep_research.DeepResearchError(
            f"L4A source_metadata_response for asset {asset_id or '<unknown>'} "
            "must decode to a JSON object"
        )
    return parsed


def _canonicalize_l4a_provider_payload(payload: Any) -> Any:
    """Validate raw L4A metadata and convert it to the strict provider wire form.

    The adapter is the single ingress boundary for compatible object/string
    forms. It only emits a canonical JSON string after the value has decoded to
    an object; ordinary text and non-object JSON never reach schema validation.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        return payload
    normalized = dict(payload)
    normalized_assets = []
    for raw in payload["assets"]:
        if not isinstance(raw, dict) or "source_metadata_response" not in raw:
            normalized_assets.append(raw)
            continue
        asset = dict(raw)
        metadata = _parse_source_metadata_response(
            asset["source_metadata_response"],
            asset_id=str(asset.get("asset_id") or ""),
        )
        asset["source_metadata_response"] = _canonical_json(metadata)
        normalized_assets.append(asset)
    normalized["assets"] = normalized_assets
    return normalized


def _normalize_l4a_assets(assets: list[Any]) -> list[dict]:
    """Restore canonical provider strings to persisted metadata objects."""
    normalized = []
    for index, raw in enumerate(assets):
        if not isinstance(raw, dict):
            raise _deep_research.DeepResearchError(
                f"L4A asset at index {index} must be an object"
            )
        asset = dict(raw)
        asset.setdefault("role", "unspecified")
        asset["source_metadata_response"] = _parse_source_metadata_response(
            asset.get("source_metadata_response"),
            asset_id=str(asset.get("asset_id") or ""),
        )
        normalized.append(asset)
    return normalized


def deduplicate_l4a_assets(assets: list[dict]) -> tuple[list[dict], list[dict]]:
    chosen: dict[str, dict] = {}
    order: list[str] = []
    duplicates: list[dict] = []
    for raw in assets:
        asset = dict(raw)
        identity = _asset_identity(asset)
        if identity not in chosen:
            chosen[identity] = asset
            order.append(identity)
            continue
        previous = chosen[identity]
        if float(asset.get("relevance_score", 0)) > float(previous.get("relevance_score", 0)):
            chosen[identity] = asset
            kept, duplicate = asset, previous
        else:
            kept, duplicate = previous, asset
        duplicates.append({
            "identity": identity,
            "kept_asset_id": str(kept.get("asset_id", "")),
            "duplicate_asset_id": str(duplicate.get("asset_id", "")),
            "reason": "lower_relevance_score",
        })
    return [chosen[key] for key in order], duplicates


def selected_l4a_assets(manifest: dict, *, require: bool = False) -> list[dict]:
    selected_ids = set(manifest.get("selected_asset_ids") or [])
    selected = [a for a in manifest.get("assets", []) if a.get("asset_id") in selected_ids]
    if require and not selected:
        raise _deep_research.DeepResearchError("L4A discovery produced no selected literature assets")
    return selected


def persist_l4a_discovery(
    project_dir: str | Path, candidate_id: str, payload: dict,
    runtime_receipt: dict, *, question: str, claim: str,
    project_id: str = "", round_id: str = "", profile_id: str = "",
) -> dict:
    project = Path(project_dir)
    assets, duplicates = deduplicate_l4a_assets(
        _normalize_l4a_assets(list(payload.get("assets") or []))
    )
    selected_ids = [str(a["asset_id"]) for a in assets if a.get("selection_status") == "selected"]
    seed = {
        "candidate_id": candidate_id, "question": question, "claim": claim,
        "queries": payload.get("queries") or [], "assets": assets,
        "runtime_receipt": runtime_receipt,
    }
    run_id = _sha256_json(seed)[:20]
    relative = Path("09_Literature_Database/l4/discovery/manifests") / f"{candidate_id}_{run_id}.json"
    artifact = {
        "schema_version": L4A_DISCOVERY_SCHEMA_VERSION,
        "pipeline_schema": PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4A", "run_id": run_id,
        "project_id": project_id, "round_id": str(round_id),
        "candidate_id": candidate_id, "profile_id": profile_id,
        "created_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "question": question, "claim": claim,
        "question_sha256": _sha256_bytes(question.encode("utf-8")),
        "claim_sha256": _sha256_bytes(claim.encode("utf-8")),
        "queries": payload.get("queries") or [], "assets": assets,
        "duplicates": duplicates, "selected_asset_ids": selected_ids,
        "runtime_receipt": runtime_receipt, "path": relative.as_posix(),
    }
    artifact["manifest_sha256"] = _sha256_json(artifact)
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") != raw:
        raise _deep_research.DeepResearchError(f"immutable L4A manifest already exists with different content: {target}")
    if not target.exists():
        target.write_text(raw, encoding="utf-8")
    return artifact


def validate_l4a_manifest(project_dir: str | Path, manifest: dict) -> tuple[bool, str]:
    if manifest.get("schema_version") != L4A_DISCOVERY_SCHEMA_VERSION:
        return False, "unexpected L4A schema_version"
    if manifest.get("pipeline_schema") != PIPELINE_SCHEMA_VERSION:
        return False, "unexpected L4 pipeline schema"
    relative = Path(str(manifest.get("path") or ""))
    if relative.is_absolute() or ".." in relative.parts or not str(relative):
        return False, "L4A manifest path must be project-relative"
    path = Path(project_dir) / relative
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"L4A manifest unreadable: {exc}"
    if persisted != manifest:
        return False, "L4A manifest content does not match persisted artifact"
    unsigned = dict(manifest)
    actual = str(unsigned.pop("manifest_sha256", ""))
    if not actual or _sha256_json(unsigned) != actual:
        return False, "L4A manifest SHA256 mismatch"
    return True, ""


def validate_native_l4a_manifest(
    project_dir: str | Path, manifest: dict
) -> tuple[bool, str]:
    """Validate the immutable native-v2 L4A handoff consumed by L4B.

    ``validate_l4a_manifest`` remains deliberately readable for historical
    metadata-only L4A artifacts.  L4B has a narrower contract: it may consume
    only a native method-inventory manifest whose selected corpus and source
    references are internally closed.  Keeping this stricter validator at the
    L4B boundary prevents legacy artifacts from being silently upgraded.
    """
    ok, reason = validate_l4a_manifest(project_dir, manifest)
    if not ok:
        return False, reason

    missing = [
        field for field in ("inventory_schema", "method_inventory")
        if field not in manifest
    ]
    if missing:
        return (
            False,
            "LEGACY_L4A_MANIFEST_INCOMPATIBLE: native L4A resume requires "
            + ", ".join(missing),
        )

    # Import lazily so l4_inventory can continue to use l4_pipeline's
    # persistence helpers without creating an import cycle.
    from research_loop import l4_inventory

    if manifest.get("inventory_schema") != l4_inventory.INVENTORY_SCHEMA_VERSION:
        return False, "NATIVE_L4A_MANIFEST_INCOMPATIBLE: unexpected inventory_schema"

    required_identity = ("run_id", "candidate_id", "project_id", "round_id", "profile_id")
    missing_identity = [
        field for field in required_identity
        if not str(manifest.get(field) or "").strip()
    ]
    if missing_identity:
        return (
            False,
            "NATIVE_L4A_MANIFEST_INCOMPATIBLE: missing identity fields "
            + ", ".join(missing_identity),
        )

    assets = manifest.get("assets")
    selected_ids = manifest.get("selected_asset_ids")
    methods = manifest.get("method_inventory")
    if not isinstance(assets, list) or not assets:
        return False, "NATIVE_L4A_MANIFEST_INCOMPATIBLE: assets must be non-empty"
    if not isinstance(selected_ids, list) or not selected_ids:
        return False, "NATIVE_L4A_MANIFEST_INCOMPATIBLE: selected_asset_ids must be non-empty"
    if not isinstance(methods, list) or not methods:
        return False, "NATIVE_L4A_MANIFEST_INCOMPATIBLE: method_inventory must be non-empty"

    asset_by_id = {}
    for index, raw_asset in enumerate(assets):
        if not isinstance(raw_asset, dict):
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: asset {index} is not an object"
        asset_id = str(raw_asset.get("asset_id") or "").strip()
        if not asset_id:
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: asset {index} lacks asset_id"
        if asset_id in asset_by_id:
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: duplicate asset_id {asset_id}"
        asset_by_id[asset_id] = raw_asset

    selected_values = [str(value).strip() for value in selected_ids]
    if any(not value for value in selected_values):
        return False, "NATIVE_L4A_MANIFEST_INCOMPATIBLE: selected_asset_ids contains an empty id"
    if len(selected_values) != len(set(selected_values)):
        return False, "NATIVE_L4A_MANIFEST_INCOMPATIBLE: selected_asset_ids must be unique"
    selected_set = set(selected_values)
    if not selected_set <= set(asset_by_id):
        missing_assets = sorted(selected_set - set(asset_by_id))
        return (
            False,
            "NATIVE_L4A_MANIFEST_INCOMPATIBLE: selected asset is not registered: "
            + ", ".join(missing_assets),
        )
    actual_selected = {
        asset_id for asset_id, asset in asset_by_id.items()
        if str(asset.get("selection_status") or "") == "selected"
    }
    if actual_selected != selected_set:
        return (
            False,
            "NATIVE_L4A_MANIFEST_INCOMPATIBLE: selected_asset_ids do not match "
            "asset selection_status",
        )

    method_ids = []
    for index, method in enumerate(methods):
        if not isinstance(method, dict):
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {index} is not an object"
        method_id = str(method.get("method_id") or "").strip()
        if not method_id:
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {index} lacks method_id"
        if method_id in method_ids:
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: duplicate method_id {method_id}"
        method_ids.append(method_id)
        for field in ("name", "purpose", "inventory_reason"):
            if not str(method.get(field) or "").strip():
                return (
                    False,
                    f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} lacks {field}",
                )
        source_ids = method.get("source_asset_ids")
        source_hints = method.get("source_hints")
        if not isinstance(source_ids, list) or not isinstance(source_hints, list):
            return (
                False,
                f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} source fields are invalid",
            )
        normalized_source_ids = [str(value).strip() for value in source_ids]
        if any(not value for value in normalized_source_ids):
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} has an empty source_asset_id"
        if len(normalized_source_ids) != len(set(normalized_source_ids)):
            return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} source_asset_ids must be unique"
        if source_hints and not normalized_source_ids:
            return (
                False,
                f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} "
                "source_hints must be materialized as selected assets",
            )
        for asset_id in normalized_source_ids:
            if asset_id not in asset_by_id or asset_id not in selected_set:
                return (
                    False,
                    f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} source_asset_ids "
                    f"must reference selected L4A assets ({asset_id})",
                )
        source_ref_ids = []
        for hint in source_hints:
            if not isinstance(hint, dict):
                return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} source hint is invalid"
            source_ref_id = str(hint.get("source_ref_id") or "").strip()
            if not source_ref_id or source_ref_id in source_ref_ids:
                return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: method {method_id} source_ref_id values must be unique"
            source_ref_ids.append(source_ref_id)
            if not any(str(hint.get(key) or "").strip() for key in ("doi", "pmid", "pmcid", "url")):
                return False, f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: source hint {source_ref_id} has no exact identifier"
            hint_asset_id = str(hint.get("asset_id") or "").strip()
            if source_hints and not hint_asset_id:
                return (
                    False,
                    f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: source hint {source_ref_id} "
                    "lacks materialized asset_id",
                )
            if hint_asset_id and hint_asset_id not in normalized_source_ids:
                return (
                    False,
                    f"NATIVE_L4A_MANIFEST_INCOMPATIBLE: source hint {source_ref_id} "
                    "is outside its method source_asset_ids",
                )

    # The projection must account for every inventory item before resolution;
    # audit-time discovery of an omitted method is too late.
    sources, no_source_methods = l4_inventory.inventory_sources(manifest)
    projected_ids = {
        str(method_id)
        for source in sources
        for method_id in source.get("inventory_method_ids") or []
    }
    projected_ids.update(
        str(method.get("method_id") or "") for method in no_source_methods
    )
    expected_ids = set(method_ids)
    if projected_ids != expected_ids:
        return (
            False,
            "NATIVE_L4A_MANIFEST_INCOMPATIBLE: inventory methods cannot be fully "
            "projected to evidence or explicit gaps",
        )
    return True, ""


def frozen_l4a_catalog(manifest: dict) -> str:
    assets = []
    for raw in selected_l4a_assets(manifest, require=True):
        asset = dict(raw)
        asset.setdefault("role", "unspecified")
        assets.append(asset)
    return _canonical_json({
        "schema_version": L4A_DISCOVERY_SCHEMA_VERSION,
        "selected_asset_ids": list(manifest.get("selected_asset_ids") or []),
        "assets": assets,
    })


def build_l4a_prompt(question: str, claim: str) -> str:
    return f"""Use the installed Academic Research Skills literature-search capability.

RLR stage: L4A Literature Discovery
Scientific question: {question}
Selected hypothesis/claim: {claim}

Search for method, protocol, software, diagnostic, and alternative-method
literature. Return metadata only, matching the supplied JSON schema. Record
actual query receipts and source metadata. Classify every asset with role
primary, method, protocol, review, navigation, other, or unspecified. For
source_metadata_response, return
the complete database metadata object encoded as one canonical JSON string:
UTF-8, sorted keys, compact separators, finite JSON numbers only, and no
leading/trailing whitespace. Do not use Python repr, Markdown fences, or
explanatory text. Do not emit source payloads,
verbatim extracts, method components, method candidates, method anchors, or a
final analysis plan. Never invent identifiers, availability, or receipts.
"""


def run_l4a_discovery(
    project_dir: str | Path, candidate_id: str, question: str, claim: str,
    spec: _deep_research.RuntimeSpec, work_dir: str | Path,
    skill_version: str = "unknown", *, project_id: str = "",
    round_id: str = "", profile_id: str = "",
) -> dict:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    (work / "deep_research_output.schema.json").write_text(
        json.dumps(l4a_discovery_schema(), indent=2), encoding="utf-8"
    )
    command, _ = _deep_research.build_invocation(spec, "L4", question, claim, work)
    prompt = build_l4a_prompt(question, claim)
    command[0] = _deep_research.resolve_subprocess_executable(command[0])
    execution_command, invocation_kwargs = _deep_research.subprocess_invocation(command, prompt)
    completed = _deep_research.execute_provider_invocation(
        execution_command, invocation_kwargs, timeout=spec.timeout,
        label='L4A Academic Research CLI',
    )
    receipt = _deep_research.skill_receipt(
        spec.backend, command, prompt, skill_version,
        exit_code=completed.returncode,
        stdout_hash=_sha256_bytes(completed.stdout.encode("utf-8")), model=spec.model,
    )
    if completed.returncode != 0:
        raise _deep_research.DeepResearchError(
            f"L4A Academic Research CLI exited {completed.returncode}: {completed.stderr.strip()}"
        )
    artifact = persist_l4a_discovery(
        project_dir, candidate_id, _deep_research._parse_cli_output(completed.stdout), receipt,
        question=question, claim=claim, project_id=project_id,
        round_id=round_id, profile_id=profile_id,
    )
    selected_l4a_assets(artifact, require=True)
    return artifact


def _persist_l4b_linkage(project_dir: str | Path, artifact: dict) -> None:
    relative = str(artifact.get("path") or "")
    if not relative:
        return
    path = Path(project_dir) / relative
    if not path.is_file():
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def install(deep_research_module) -> None:
    if getattr(deep_research_module, "_l4_pipeline_installed", False):
        return
    original = deep_research_module.run_and_persist

    def run_and_persist(
        project_dir, candidate_id, node, question, claim, spec, work_dir,
        skill_version="unknown", result_context="", *, project_id="",
        round_id="", profile_id="", research_persona="Curie",
    ):
        if node != "L4":
            return original(
                project_dir, candidate_id, node, question, claim, spec, work_dir,
                skill_version, result_context, project_id=project_id,
                round_id=round_id, profile_id=profile_id,
                research_persona=research_persona,
            )
        manifest = run_l4a_discovery(
            project_dir, candidate_id, question, claim, spec, work_dir,
            skill_version, project_id=project_id, round_id=round_id,
            profile_id=profile_id,
        )
        catalog = frozen_l4a_catalog(manifest)
        frozen_claim = (
            f"{claim}\n\n=== FROZEN L4B HANDOFF ===\n"
            "This L4B run is closed over the exact L4A selected-asset catalog "
            "below. MUST NOT perform online literature searches, follow-up "
            "review searches, add new citations, or create new online paper "
            "records. Use only the selected records in this catalog and "
            "formally registered local sources. Full-text resolution may use "
            "an alias URL for the same selected DOI/PMID; it does not add a "
            "paper. A review or navigation paper is admissible only when a "
            "selected catalog asset has role=review. If no selected asset has "
            "role=review, do not search for one and return a review_search "
            "receipt with status=not_retained explaining that no selected "
            "review was retained; emit no review paper. Review/navigation "
            "extracts must never claim method anchors.\n\n"
            "=== FROZEN L4A DISCOVERY CORPUS (complete selected catalog) ===\n"
            f"{catalog}\n"
        )
        previous_context = getattr(
            _deep_research, "_l4b_frozen_manifest_context", None
        )
        _deep_research._l4b_frozen_manifest_context = (
            Path(project_dir).resolve(), str(candidate_id), manifest
        )
        try:
            artifact = original(
                project_dir, candidate_id, node, question, frozen_claim, spec,
                work_dir, skill_version, result_context, project_id=project_id,
                round_id=round_id, profile_id=profile_id,
                research_persona=research_persona,
            )
        finally:
            if previous_context is None:
                delattr(_deep_research, "_l4b_frozen_manifest_context")
            else:
                _deep_research._l4b_frozen_manifest_context = previous_context
        artifact.update({
            "pipeline_schema": PIPELINE_SCHEMA_VERSION,
            "pipeline_stage": "L4B",
            "l4a_manifest_path": manifest["path"],
            "l4a_manifest_sha256": manifest["manifest_sha256"],
            "l4a_run_id": manifest["run_id"],
        })
        _persist_l4b_linkage(project_dir, artifact)
        return artifact

    deep_research_module._l4_pipeline_original_run_and_persist = original
    deep_research_module.run_and_persist = run_and_persist
    deep_research_module._l4_pipeline_installed = True


def _bound_project_path(project: Path, value: str, label: str) -> Path:
    path = (project / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError as exc:
        raise _deep_research.DeepResearchError(f"{label} path escapes the project") from exc
    return path


def _ids(records: list[dict], key: str) -> list[str]:
    values = {str(record.get(key) or "").strip() for record in records}
    values.discard("")
    return sorted(values)


def commit_l45_method_projection(
    project_dir: str | Path,
    candidate_id: str,
    evidence_artifact: dict,
    l4c_delta_path: str | Path,
) -> tuple[dict, Path, bool]:
    """Validate L4A/L4B/L4C lineage and persist an immutable L4.5 projection."""
    if evidence_artifact.get("pipeline_schema") != PIPELINE_SCHEMA_VERSION:
        raise _deep_research.DeepResearchError("L4.5 requires a staged L4B evidence artifact")
    if evidence_artifact.get("pipeline_stage") != "L4B":
        raise _deep_research.DeepResearchError("L4.5 received a non-L4B evidence artifact")
    if str(evidence_artifact.get("candidate_id") or "") != str(candidate_id):
        raise _deep_research.DeepResearchError("L4B candidate does not match L4.5 commit")

    project = Path(project_dir)
    manifest_path = _bound_project_path(project, str(evidence_artifact.get("l4a_manifest_path") or ""), "L4A manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _deep_research.DeepResearchError(f"L4A manifest is unreadable: {exc}") from exc
    ok, reason = validate_l4a_manifest(project, manifest)
    if not ok:
        raise _deep_research.DeepResearchError(f"L4A manifest validation failed: {reason}")
    if manifest.get("manifest_sha256") != evidence_artifact.get("l4a_manifest_sha256"):
        raise _deep_research.DeepResearchError("L4A manifest SHA256 does not match L4B linkage")

    run_id = str(evidence_artifact.get("run_id") or "")
    ok, reason = _deep_research.audit_evidence_pack(project, candidate_id, "L4", run_id=run_id)
    if not ok:
        raise _deep_research.DeepResearchError(f"L4B evidence audit failed: {reason}")
    evidence_manifest = _deep_research.evidence_artifact_manifest(project, candidate_id, "L4", run_id)

    delta_path = _bound_project_path(project, str(l4c_delta_path), "L4C delta")
    if not delta_path.is_file():
        raise _deep_research.DeepResearchError("L4C delta is missing")
    delta_sha = _sha256_bytes(delta_path.read_bytes())
    delta_relative = delta_path.relative_to(project.resolve()).as_posix()

    artifact = {
        "schema_version": L45_COMMIT_SCHEMA_VERSION,
        "pipeline_schema": PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4.5",
        "candidate_id": str(candidate_id),
        "project_id": str(evidence_artifact.get("project_id") or ""),
        "round_id": str(evidence_artifact.get("round_id") or ""),
        "profile_id": str(evidence_artifact.get("profile_id") or ""),
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4b_run_id": run_id,
        "l4b_evidence_manifest": evidence_manifest,
        "l4c_delta_path": delta_relative,
        "l4c_delta_sha256": delta_sha,
        "component_ids": _ids(evidence_artifact.get("method_components") or [], "component_id"),
        "method_ids": _ids(evidence_artifact.get("method_candidates") or [], "method_id"),
        "anchor_ids": _ids(evidence_artifact.get("method_anchors") or [], "anchor_id"),
    }
    identity = _sha256_json(artifact)[:20]
    relative = Path("08_Audit/l4_method_commits") / f"{candidate_id}_{run_id}_{identity}.json"
    artifact["path"] = relative.as_posix()
    artifact["commit_sha256"] = _sha256_json(artifact)
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != raw:
            raise _deep_research.DeepResearchError(f"L4.5 immutable commit collision: {target}")
        return artifact, target, False
    target.write_text(raw, encoding="utf-8")
    return artifact, target, True


def validate_l45_method_commit(project_dir: str | Path, commit: dict) -> tuple[bool, str]:
    project = Path(project_dir)
    if commit.get("schema_version") != L45_COMMIT_SCHEMA_VERSION:
        raise _deep_research.DeepResearchError("unexpected L4.5 commit schema")
    unsigned = dict(commit)
    actual = str(unsigned.pop("commit_sha256", ""))
    if not actual or _sha256_json(unsigned) != actual:
        raise _deep_research.DeepResearchError("L4.5 commit SHA256 mismatch")
    manifest_path = _bound_project_path(project, str(commit.get("l4a_manifest_path") or ""), "L4A manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _deep_research.DeepResearchError(f"L4A manifest is unreadable: {exc}") from exc
    ok, reason = validate_l4a_manifest(project, manifest)
    if not ok or manifest.get("manifest_sha256") != commit.get("l4a_manifest_sha256"):
        raise _deep_research.DeepResearchError(f"L4A manifest validation failed: {reason or 'hash mismatch'}")
    delta = _bound_project_path(project, str(commit.get("l4c_delta_path") or ""), "L4C delta")
    if not delta.is_file() or _sha256_bytes(delta.read_bytes()) != commit.get("l4c_delta_sha256"):
        raise _deep_research.DeepResearchError("L4C delta SHA256 mismatch")
    target = _bound_project_path(project, str(commit.get("path") or ""), "L4.5 commit")
    if target.is_file():
        try:
            persisted = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _deep_research.DeepResearchError(f"L4.5 commit is unreadable: {exc}") from exc
        if persisted != commit:
            raise _deep_research.DeepResearchError("L4.5 persisted commit differs from supplied commit")
    return True, ""
