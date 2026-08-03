"""Contracts and orchestration for the staged L4 method-planning pipeline.

L4A owns metadata discovery. L4B delegates to the mature method-evidence
stack. L4C remains the existing ``L4_fisher`` cognitive node. L4.5 is a
non-LLM commit gate added after method design.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import subprocess
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
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)


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


def frozen_l4a_catalog(manifest: dict) -> str:
    """Return the canonical metadata-only selection passed to L4B."""
    selected = selected_l4a_assets(manifest, require=True)
    catalog = {
        "schema_version": L4A_DISCOVERY_SCHEMA_VERSION,
        "selected_asset_ids": list(manifest.get("selected_asset_ids") or []),
        "assets": selected,
    }
    return _canonical_json(catalog)


def build_l4a_prompt(question: str, claim: str) -> str:
    """Build a discovery-only request for the installed ARS runtime."""
    return f"""Use the installed Academic Research Skills literature-search capability.

RLR stage: L4A Literature Discovery
Scientific question: {question}
Selected hypothesis/claim: {claim}

Search for method, protocol, software, diagnostic, and alternative-method
literature relevant to the selected hypothesis. Return metadata only, matching
the supplied JSON schema. Record actual query receipts and source metadata.
Do not retrieve or emit source payloads, verbatim extracts, method components,
method candidates, method anchors, or a final analysis plan. Never invent an
identifier, availability status, source receipt, or selection rationale.
"""


def run_l4a_discovery(
    project_dir: str | Path,
    candidate_id: str,
    question: str,
    claim: str,
    spec: _deep_research.RuntimeSpec,
    work_dir: str | Path,
    skill_version: str = "unknown",
    *,
    project_id: str = "",
    round_id: str = "",
    profile_id: str = "",
) -> dict:
    """Execute L4A with the configured ARS backend and persist its manifest."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    schema_path = work / "deep_research_output.schema.json"
    schema_path.write_text(json.dumps(l4a_discovery_schema(), indent=2), encoding="utf-8")
    command, _ = _deep_research.build_invocation(
        spec, "L4", question, claim, work
    )
    prompt = build_l4a_prompt(question, claim)
    command[0] = _deep_research.resolve_subprocess_executable(command[0])
    execution_command, invocation_kwargs = _deep_research.subprocess_invocation(command, prompt)
    try:
        completed = subprocess.run(
            execution_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=spec.timeout,
            check=False,
            **invocation_kwargs,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _deep_research.DeepResearchError(
            f"L4A Academic Research CLI invocation failed: {exc}"
        ) from exc
    receipt = _deep_research.skill_receipt(
        spec.backend,
        command,
        prompt,
        skill_version,
        exit_code=completed.returncode,
        stdout_hash=hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        model=spec.model,
    )
    if completed.returncode != 0:
        raise _deep_research.DeepResearchError(
            f"L4A Academic Research CLI exited {completed.returncode}: {completed.stderr.strip()}"
        )
    payload = _deep_research._parse_cli_output(completed.stdout)
    artifact = persist_l4a_discovery(
        project_dir,
        candidate_id,
        payload,
        receipt,
        question=question,
        claim=claim,
        project_id=project_id,
        round_id=round_id,
        profile_id=profile_id,
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
    temporary.write_text(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def install(deep_research_module) -> None:
    """Install L4A/L4B orchestration around the mature final L4 runtime."""
    if getattr(deep_research_module, "_l4_pipeline_installed", False):
        return
    original = deep_research_module.run_and_persist

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
        if node != "L4":
            return original(
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
        manifest = run_l4a_discovery(
            project_dir,
            candidate_id,
            question,
            claim,
            spec,
            work_dir,
            skill_version,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
        )
        catalog = frozen_l4a_catalog(manifest)
        l4b_claim = (
            f"{claim}\n\n=== FROZEN L4A DISCOVERY CORPUS ===\n{catalog}\n"
            "Use only these selected records as the discovery corpus. You may "
            "resolve their full text and registered local sources, but do not "
            "silently add new literature records."
        )
        artifact = original(
            project_dir,
            candidate_id,
            node,
            question,
            l4b_claim,
            spec,
            work_dir,
            skill_version,
            result_context,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            research_persona=research_persona,
        )
        artifact["pipeline_schema"] = PIPELINE_SCHEMA_VERSION
        artifact["pipeline_stage"] = "L4B"
        artifact["l4a_manifest_path"] = manifest["path"]
        artifact["l4a_manifest_sha256"] = manifest["manifest_sha256"]
        artifact["l4a_run_id"] = manifest["run_id"]
        _persist_l4b_linkage(project_dir, artifact)
        return artifact

    deep_research_module._l4_pipeline_original_run_and_persist = original
    deep_research_module.run_and_persist = run_and_persist
    deep_research_module._l4_pipeline_installed = True
