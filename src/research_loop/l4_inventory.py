"""Identifier-bearing method inventory for staged L4 evidence acquisition.

This module leaves the historical L4A provider/persistence API readable while
adding an additive inventory contract for new staged runs. Exact method-source
identifiers are materialized as selected resolver assets so provenance checks
remain closed-corpus and deterministic even when ordinary literature selection
would otherwise omit the source.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


INVENTORY_SCHEMA_VERSION = "L4MethodInventory/v2"
_SOURCE_KINDS = {
    "primary_study",
    "method_paper",
    "protocol",
    "supplementary_methods",
    "official_documentation",
    "versioned_code",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _safe(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_.") or "source"


def _normalized_doi(value: Any) -> str:
    return re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        str(value or "").strip().casefold(),
    ).rstrip("/")


def _normalized_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def _source_hint_schema() -> dict:
    properties = {
        "source_ref_id": {"type": "string", "minLength": 1},
        "title": {"type": "string"},
        "year": {"type": "integer"},
        "doi": {"type": "string"},
        "pmid": {"type": "string"},
        "pmcid": {"type": "string"},
        "url": {"type": "string"},
        "source_kind": {"enum": sorted(_SOURCE_KINDS)},
        "rationale": {"type": "string", "minLength": 1},
        "full_text_locations": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _inventory_item_schema() -> dict:
    properties = {
        "method_id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "purpose": {"type": "string", "minLength": 1},
        "inventory_reason": {"type": "string", "minLength": 1},
        "source_asset_ids": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "source_hints": {
            "type": "array",
            "items": _source_hint_schema(),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def discovery_schema(l4p) -> dict:
    """Return the strict L4A wire schema used by new staged runs."""
    schema = copy.deepcopy(l4p.l4a_discovery_schema())
    schema["properties"]["method_inventory"] = {
        "type": "array",
        "minItems": 1,
        "items": _inventory_item_schema(),
    }
    schema["required"].append("method_inventory")
    return schema


def build_prompt(question: str, claim: str) -> str:
    return f"""Use the installed Academic Research Skills literature-search capability.

RLR stage: L4A Method Inventory and Source Metadata
Scientific question: {question}
Selected hypothesis/claim: {claim}

First identify the explicit statistical, computational, diagnostic, and
alternative methods implied by the authorized project context. Return those
methods in `method_inventory`. This is an inventory, not a final method choice:
do not create method components, eligibility decisions, required execution
flags, evidence anchors, or an analysis plan.

For every method, carry forward any DOI, PMID, PMCID, stable URL, or exact asset
identifier already present in the authorized context. A known identifier must
not be dropped merely because the corresponding paper is not selected as a
general literature asset. Search metadata only to fill missing identifiers.
Never invent an identifier. Use year 0 only when an exact source identifier is
known but its publication year is unavailable. When no exact source is found,
retain the method with empty source arrays so the next stage can record an
explicit evidence gap.

Return metadata only. Do not retrieve full text or emit source payloads or
verbatim extracts. Keep the ordinary `assets` catalog and selection receipts.
For `source_metadata_response`, return the complete database metadata object as
one canonical JSON string: UTF-8, sorted keys, compact separators, finite JSON
numbers, and no Markdown fences or explanatory text.
"""


def _validate_inventory_payload(l4p, dr, payload: dict) -> dict:
    base_payload = {
        "schema_version": payload.get("schema_version"),
        "queries": payload.get("queries"),
        "assets": payload.get("assets"),
    }
    canonical_base = l4p._canonicalize_l4a_provider_payload(base_payload)
    canonical = dict(canonical_base)
    canonical["method_inventory"] = payload.get("method_inventory")
    errors = sorted(
        Draft202012Validator(discovery_schema(l4p)).iter_errors(canonical),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "payload"
        raise dr.DeepResearchError(f"L4A inventory payload {path}: {error.message}")

    inventory = canonical["method_inventory"]
    method_ids = [str(item["method_id"]).strip() for item in inventory]
    if len(method_ids) != len(set(method_ids)):
        raise dr.DeepResearchError("L4A method_inventory method_id values must be unique")
    for item in inventory:
        refs = [str(hint["source_ref_id"]).strip() for hint in item["source_hints"]]
        if len(refs) != len(set(refs)):
            raise dr.DeepResearchError(
                f"L4A method {item['method_id']} source_ref_id values must be unique"
            )
        for hint in item["source_hints"]:
            if not any(
                str(hint.get(key) or "").strip()
                for key in ("doi", "pmid", "pmcid", "url")
            ):
                raise dr.DeepResearchError(
                    f"L4A source hint {hint['source_ref_id']} has no exact identifier"
                )
    return canonical


def _asset_identity(asset: dict) -> tuple[str, str]:
    doi = _normalized_doi(asset.get("doi"))
    if doi:
        return "doi", doi
    pmid = str(asset.get("pmid") or "").strip()
    if pmid:
        return "pmid", pmid
    metadata = asset.get("source_metadata_response")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    text = _canonical_json(metadata or {})
    match = re.search(r"\bPMC\d+\b", text, flags=re.IGNORECASE)
    if match:
        return "pmcid", match.group(0).upper()
    url = _normalized_url(asset.get("url"))
    if url:
        return "url", url
    return "asset", str(asset.get("asset_id") or "")


def _hint_identity(hint: dict) -> tuple[str, str]:
    doi = _normalized_doi(hint.get("doi"))
    if doi:
        return "doi", doi
    pmid = str(hint.get("pmid") or "").strip()
    if pmid:
        return "pmid", pmid
    pmcid = str(hint.get("pmcid") or "").strip().upper()
    if pmcid:
        return "pmcid", pmcid
    url = _normalized_url(hint.get("url"))
    if url:
        return "url", url
    return "", ""


def _hint_url(hint: dict) -> str:
    if str(hint.get("url") or "").strip():
        return str(hint["url"]).strip()
    if str(hint.get("pmcid") or "").strip():
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{str(hint['pmcid']).strip().upper()}/"
    if str(hint.get("doi") or "").strip():
        return f"https://doi.org/{_normalized_doi(hint['doi'])}"
    if str(hint.get("pmid") or "").strip():
        return f"https://pubmed.ncbi.nlm.nih.gov/{str(hint['pmid']).strip()}/"
    return ""


def _role(source_kind: str) -> str:
    return {
        "primary_study": "primary",
        "method_paper": "method",
        "protocol": "protocol",
        "supplementary_methods": "method",
        "official_documentation": "method",
        "versioned_code": "method",
    }.get(str(source_kind), "method")


def _pseudo_asset(method: dict, hint: dict) -> dict:
    source_ref_id = str(hint["source_ref_id"])
    method_id = str(method["method_id"])
    identity = "|".join(_hint_identity(hint))
    asset_id = f"MI_{_safe(method_id)}_{_safe(source_ref_id)}_{_sha(identity)[:8]}"
    url = _hint_url(hint)
    metadata = {
        "inventory_schema": INVENTORY_SCHEMA_VERSION,
        "method_id": method_id,
        "source_ref_id": source_ref_id,
        "pmcid": str(hint.get("pmcid") or "").strip().upper(),
    }
    explicit_locations = [
        str(value).strip()
        for value in hint.get("full_text_locations") or []
        if str(value).strip()
    ]
    locations = []
    for value in explicit_locations + ([url] if url else []):
        if value not in locations:
            locations.append(value)
    open_access = bool(str(hint.get("pmcid") or "").strip() or explicit_locations)
    return {
        "asset_id": asset_id,
        "doi": _normalized_doi(hint.get("doi")),
        "pmid": str(hint.get("pmid") or "").strip(),
        "url": url,
        "title": str(hint.get("title") or "").strip() or f"{method['name']} canonical source",
        "year": int(hint.get("year") or 0),
        "role": _role(str(hint.get("source_kind") or "method_paper")),
        "journal": "",
        "abstract": "",
        "source_database": "method_inventory_exact_identifier",
        "source_metadata_response": _canonical_json(metadata),
        "open_access_status": "open" if open_access else "unknown",
        "full_text_status": "available_oa" if open_access else "metadata_only",
        "full_text_locations": locations,
        "relevance_score": 10.0,
        "selection_status": "selected",
        "selection_reason": (
            f"Exact source for method inventory item {method_id}; "
            "selected for deterministic evidence resolution."
        ),
        "hypothesis_ids": [],
        "method_component_hints": [method_id],
        "diagnostic_requirements": [],
    }


def _augment_assets(payload: dict, dr) -> tuple[list[dict], list[dict]]:
    assets = [dict(asset) for asset in payload["assets"]]
    by_id = {str(asset["asset_id"]): asset for asset in assets}
    identities = {_asset_identity(asset): str(asset["asset_id"]) for asset in assets}
    normalized_inventory = copy.deepcopy(payload["method_inventory"])

    for method in normalized_inventory:
        linked_ids = []
        for asset_id in method["source_asset_ids"]:
            asset_id = str(asset_id)
            if asset_id not in by_id:
                raise dr.DeepResearchError(
                    f"L4A method {method['method_id']} references unknown asset {asset_id}"
                )
            asset = by_id[asset_id]
            asset["selection_status"] = "selected"
            asset["selection_reason"] = (
                f"Exact source referenced by method inventory item {method['method_id']}."
            )
            if asset_id not in linked_ids:
                linked_ids.append(asset_id)

        for hint in method["source_hints"]:
            identity = _hint_identity(hint)
            asset_id = identities.get(identity) if identity[0] else None
            if asset_id is None:
                asset = _pseudo_asset(method, hint)
                asset_id = str(asset["asset_id"])
                assets.append(asset)
                by_id[asset_id] = asset
                identities[_asset_identity(asset)] = asset_id
            else:
                asset = by_id[asset_id]
                asset["selection_status"] = "selected"
                asset["selection_reason"] = (
                    f"Exact source matched by method inventory item {method['method_id']}."
                )
            hint["asset_id"] = asset_id
            if asset_id not in linked_ids:
                linked_ids.append(asset_id)
        method["source_asset_ids"] = linked_ids
    return assets, normalized_inventory


def persist_discovery(
    l4p,
    dr,
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
    canonical = _validate_inventory_payload(l4p, dr, payload)
    assets, inventory = _augment_assets(canonical, dr)
    receipt = dict(runtime_receipt)
    receipt["method_inventory_sha256"] = _sha(_canonical_json(inventory))
    base_payload = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": canonical["queries"],
        "assets": assets,
    }
    artifact = l4p.persist_l4a_discovery(
        project_dir,
        candidate_id,
        base_payload,
        receipt,
        question=question,
        claim=claim,
        project_id=project_id,
        round_id=round_id,
        profile_id=profile_id,
    )
    artifact["inventory_schema"] = INVENTORY_SCHEMA_VERSION
    artifact["method_inventory"] = inventory
    unsigned = dict(artifact)
    unsigned.pop("manifest_sha256", None)
    artifact["manifest_sha256"] = l4p._sha256_json(unsigned)
    path = Path(project_dir) / str(artifact["path"])
    path.write_text(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    ok, reason = l4p.validate_l4a_manifest(project_dir, artifact)
    if not ok:
        raise dr.DeepResearchError(f"persisted L4A inventory manifest failed validation: {reason}")
    return artifact


def run_discovery(
    l4p,
    dr,
    project_dir: str | Path,
    candidate_id: str,
    question: str,
    claim: str,
    spec,
    work_dir: str | Path,
    skill_version: str = "unknown",
    *,
    project_id: str = "",
    round_id: str = "",
    profile_id: str = "",
) -> dict:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    # Keep the historical schema path stable for diagnostics and compatibility
    # tests. The new L4A provider receives its own explicit inventory schema.
    legacy_schema_path = work / "deep_research_output.schema.json"
    inventory_schema_path = work / "l4a_method_inventory_output.schema.json"
    legacy_schema_path.write_text(
        json.dumps(dr._runtime_schema("L4"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    inventory_schema_path.write_text(
        json.dumps(discovery_schema(l4p), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    command, _ = dr.build_invocation(spec, "L4", question, claim, work)
    command = [
        str(inventory_schema_path) if value == str(legacy_schema_path) else value
        for value in command
    ]
    prompt = build_prompt(question, claim)
    command[0] = dr.resolve_subprocess_executable(command[0])
    execution_command, invocation_kwargs = dr.subprocess_invocation(command, prompt)
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
        raise dr.DeepResearchError(f"L4A method-inventory invocation failed: {exc}") from exc
    receipt = dr.skill_receipt(
        spec.backend,
        command,
        prompt,
        skill_version,
        exit_code=completed.returncode,
        stdout_hash=_sha(completed.stdout),
        model=spec.model,
    )
    if completed.returncode != 0:
        raise dr.DeepResearchError(
            f"L4A method-inventory CLI exited {completed.returncode}: {completed.stderr.strip()}"
        )
    return persist_discovery(
        l4p,
        dr,
        project_dir,
        candidate_id,
        dr._parse_cli_output(completed.stdout),
        receipt,
        question=question,
        claim=claim,
        project_id=project_id,
        round_id=round_id,
        profile_id=profile_id,
    )


def inventory_sources(manifest: dict) -> tuple[list[dict], list[dict]]:
    """Return exact resolver assets plus inventory items lacking any source."""
    assets = {str(asset.get("asset_id") or ""): asset for asset in manifest.get("assets") or []}
    linked: dict[str, dict] = {}
    no_source = []
    for method in manifest.get("method_inventory") or []:
        method_id = str(method.get("method_id") or "")
        source_ids = [str(value) for value in method.get("source_asset_ids") or []]
        if not source_ids:
            no_source.append(copy.deepcopy(method))
            continue
        for index, asset_id in enumerate(source_ids):
            raw = assets.get(asset_id)
            if raw is None:
                continue
            item = linked.setdefault(asset_id, copy.deepcopy(raw))
            item.setdefault("inventory_method_ids", [])
            item.setdefault("inventory_source_ref_ids", [])
            if method_id not in item["inventory_method_ids"]:
                item["inventory_method_ids"].append(method_id)
            ref_ids = [
                str(hint.get("source_ref_id") or "")
                for hint in method.get("source_hints") or []
                if str(hint.get("asset_id") or "") == asset_id
            ] or [f"asset:{asset_id}:{index + 1}"]
            for ref_id in ref_ids:
                if ref_id and ref_id not in item["inventory_source_ref_ids"]:
                    item["inventory_source_ref_ids"].append(ref_id)
    return list(linked.values()), no_source
