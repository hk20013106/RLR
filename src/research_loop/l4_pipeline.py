"""Contracts for the staged L4 method-planning pipeline.

L4A owns metadata discovery. L4B delegates to the mature method-evidence
stack. L4C remains the existing ``L4_fisher`` cognitive node. L4.5 is a
non-LLM commit gate added after method design.
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
    {
        "stage_id": "L4A",
        "responsibility": "literature_discovery",
        "cognitive": True,
        "storage_key": "L4A_discovery",
    },
    {
        "stage_id": "L4B",
        "responsibility": "evidence_construction",
        "cognitive": True,
        "storage_key": "L4B_evidence",
    },
    {
        "stage_id": "L4C",
        "responsibility": "fisher_method_design",
        "cognitive": True,
        "storage_key": "L4_fisher",
    },
    {
        "stage_id": "L4.5",
        "responsibility": "deterministic_commit",
        "cognitive": False,
        "storage_key": "L45_method_commit",
    },
)


def _string_array_schema() -> dict:
    return {"type": "array", "items": {"type": "string", "minLength": 1}}


def l4a_discovery_schema() -> dict:
    """Return the strict metadata-only provider contract for L4A."""
    query = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query_id": {"type": "string", "minLength": 1},
            "query": {"type": "string", "minLength": 1},
            "purpose": {"type": "string", "minLength": 1},
            "status": {"enum": ["completed", "failed", "partial"]},
            "receipt": {"type": "string"},
        },
        "required": ["query_id", "query", "purpose", "status", "receipt"],
    }
    asset = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "asset_id": {"type": "string", "minLength": 1},
            "doi": {"type": "string"},
            "pmid": {"type": "string"},
            "url": {"type": "string"},
            "title": {"type": "string", "minLength": 1},
            "year": {"type": "integer"},
            "journal": {"type": "string"},
            "abstract": {"type": "string"},
            "source_database": {"type": "string", "minLength": 1},
            "source_metadata_response": {
                "type": "object",
                "additionalProperties": True,
            },
            "open_access_status": {"enum": ["open", "closed", "unknown"]},
            "full_text_status": {
                "enum": [
                    "available_local",
                    "available_oa",
                    "metadata_only",
                    "manual_required",
                ]
            },
            "full_text_locations": _string_array_schema(),
            "relevance_score": {"type": "number", "minimum": 0, "maximum": 10},
            "selection_status": {
                "enum": ["selected", "reserve", "rejected", "manual_review"]
            },
            "selection_reason": {"type": "string", "minLength": 1},
            "hypothesis_ids": _string_array_schema(),
            "method_component_hints": _string_array_schema(),
            "diagnostic_requirements": _string_array_schema(),
        },
        "required": [
            "asset_id", "doi", "pmid", "url", "title", "year", "journal",
            "abstract", "source_database", "source_metadata_response",
            "open_access_status", "full_text_status", "full_text_locations",
            "relevance_score", "selection_status", "selection_reason",
            "hypothesis_ids", "method_component_hints",
            "diagnostic_requirements",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "string",
                "const": L4A_DISCOVERY_SCHEMA_VERSION,
            },
            "queries": {"type": "array", "minItems": 1, "items": query},
            "assets": {"type": "array", "items": asset},
        },
        "required": ["schema_version", "queries", "assets"],
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_doi(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    return value


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


def deduplicate_l4a_assets(assets: list[dict]) -> tuple[list[dict], list[dict]]:
    """Deduplicate by stable identity while retaining an audit trail."""
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
        previous_score = float(previous.get("relevance_score", 0))
        current_score = float(asset.get("relevance_score", 0))
        if current_score > previous_score:
            chosen[identity] = asset
            duplicates.append({
                "identity": identity,
                "kept_asset_id": str(asset.get("asset_id", "")),
                "duplicate_asset_id": str(previous.get("asset_id", "")),
                "reason": "lower_relevance_score",
            })
        else:
            duplicates.append({
                "identity": identity,
                "kept_asset_id": str(previous.get("asset_id", "")),
                "duplicate_asset_id": str(asset.get("asset_id", "")),
                "reason": "lower_relevance_score",
            })
    return [chosen[key] for key in order], duplicates


def selected_l4a_assets(manifest: dict, *, require: bool = False) -> list[dict]:
    selected_ids = set(manifest.get("selected_asset_ids") or [])
    selected = [
        asset for asset in manifest.get("assets", [])
        if asset.get("asset_id") in selected_ids
    ]
    if require and not selected:
        raise _deep_research.DeepResearchError(
            "L4A discovery produced no selected literature assets"
        )
    return selected


def persist_l4a_discovery(
    project_dir: str | Path,
    candidate_id: str,
    payload: dict,
    runtime_receipt: dict,
    *,
    question: str,
    claim: str,
    project_id: str = "",
    round_id: str = "",
    profile_id: str = "",
) -> dict:
    """Persist an immutable, project-relative, hash-bound L4A manifest."""
    project = Path(project_dir)
    assets, duplicates = deduplicate_l4a_assets(list(payload.get("assets") or []))
    selected_ids = [
        str(asset["asset_id"])
        for asset in assets
        if asset.get("selection_status") == "selected"
    ]
    created_at = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    seed = {
        "candidate_id": candidate_id,
        "question": question,
        "claim": claim,
        "queries": payload.get("queries") or [],
        "assets": assets,
        "runtime_receipt": runtime_receipt,
    }
    run_id = _sha256_json(seed)[:20]
    relative = Path("09_Literature_Database") / "l4" / "discovery" / "manifests" / f"{candidate_id}_{run_id}.json"
    artifact = {
        "schema_version": L4A_DISCOVERY_SCHEMA_VERSION,
        "pipeline_schema": PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4A",
        "run_id": run_id,
        "project_id": project_id,
        "round_id": str(round_id),
        "candidate_id": candidate_id,
        "profile_id": profile_id,
        "created_at": created_at,
        "question": question,
        "claim": claim,
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "claim_sha256": hashlib.sha256(claim.encode("utf-8")).hexdigest(),
        "queries": payload.get("queries") or [],
        "assets": assets,
        "duplicates": duplicates,
        "selected_asset_ids": selected_ids,
        "runtime_receipt": runtime_receipt,
        "path": relative.as_posix(),
    }
    artifact["manifest_sha256"] = _sha256_json(artifact)
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != serialized:
            raise _deep_research.DeepResearchError(
                f"immutable L4A manifest already exists with different content: {path}"
            )
    else:
        path.write_text(serialized, encoding="utf-8")
    return artifact


def validate_l4a_manifest(project_dir: str | Path, manifest: dict) -> tuple[bool, str]:
    """Validate the manifest schema identity, path, persisted bytes and hash."""
    if manifest.get("schema_version") != L4A_DISCOVERY_SCHEMA_VERSION:
        return False, "unexpected L4A schema_version"
    if manifest.get("pipeline_schema") != PIPELINE_SCHEMA_VERSION:
        return False, "unexpected L4 pipeline schema"
    relative = Path(str(manifest.get("path") or ""))
    if not relative.as_posix() or relative.is_absolute() or ".." in relative.parts:
        return False, "L4A manifest path must be project-relative"
    path = Path(project_dir) / relative
    if not path.is_file():
        return False, f"L4A manifest missing: {relative.as_posix()}"
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"L4A manifest unreadable: {exc}"
    if persisted != manifest:
        return False, "L4A manifest content does not match persisted artifact"
    expected = dict(manifest)
    actual_hash = str(expected.pop("manifest_sha256", ""))
    if not actual_hash or _sha256_json(expected) != actual_hash:
        return False, "L4A manifest SHA256 mismatch"
    return True, ""
