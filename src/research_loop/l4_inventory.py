"""Identifier-bearing method inventory for staged L4 evidence acquisition.

New staged L4A runs keep the historical discovery-manifest contract readable,
but persist the method inventory and exact-source assets atomically. A
versioned registry maps methods already identified by L4A to canonical source
identifiers without re-running literature selection.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from research_loop import compatibility, l4_method_registry


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
    """Strict provider wire schema for new L4A inventory runs."""
    schema = copy.deepcopy(l4p.l4a_discovery_schema())
    schema["properties"]["method_inventory"] = {
        "type": "array",
        "minItems": 1,
        "items": _inventory_item_schema(),
    }
    schema["required"].append("method_inventory")
    return schema


def _native_known_source_catalog(
    project_dir: str | Path,
    candidate_id: str,
    profile_id: str,
    dr,
) -> tuple[dict | None, tuple[list[dict], dict] | None]:
    """Project the active frozen L0.5 sources and registry into L4A once."""
    if not str(profile_id or "").strip():
        return None, None
    try:
        profile = compatibility.get_profile(str(profile_id))
    except compatibility.CompatibilityError as exc:
        raise dr.DeepResearchError(f"L4A compatibility profile is invalid: {exc}") from exc
    if profile.delta_schema_version != "2.1":
        return None, None

    from research_loop import l05_curie, research_seed

    project = Path(project_dir)
    try:
        seed = research_seed.load_l1_research_seed(project, candidate_id)
        run_id = research_seed.active_l1_native_evidence_run_id(project, seed)
        if not run_id:
            raise dr.DeepResearchError(
                "native L4A requires an active frozen L0.5 EvidencePack before provider execution"
            )
        binding = research_seed.load_l1_native_evidence_binding(
            project, seed, run_id
        )
        pack_manifest = binding.get("evidence_pack")
        if not isinstance(pack_manifest, dict):
            raise dr.DeepResearchError(
                "native L4A active L0.5 binding has no frozen EvidencePack manifest"
            )
        frozen = l05_curie.load_frozen_evidence_pack(
            project,
            pack_manifest,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed.seed_sha256(seed),
        )
        registry_entries, registry_receipt = l4_method_registry.load_registry(project)
    except dr.DeepResearchError:
        raise
    except (
        research_seed.ResearchSeedError,
        l05_curie.CurieContractError,
        l4_method_registry.MethodRegistryError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise dr.DeepResearchError(
            f"native L4A local-literature gate failed: {exc}"
        ) from exc

    snapshots_by_paper: dict[str, list[dict]] = {}
    for evidence in frozen.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        paper_id = str(evidence.get("paper_id") or "").strip()
        retrieval = evidence.get("retrieval")
        if not paper_id or not isinstance(retrieval, dict):
            continue
        snapshot = {
            key: copy.deepcopy(retrieval[key])
            for key in (
                "engine", "source_sha256", "snapshot_path", "pmcid", "verifier"
            )
            if retrieval.get(key) not in (None, "", [], {})
        }
        if snapshot and snapshot not in snapshots_by_paper.setdefault(paper_id, []):
            snapshots_by_paper[paper_id].append(snapshot)

    selected_papers = []
    for paper in frozen.get("selected_papers") or []:
        if not isinstance(paper, dict):
            continue
        paper_id = str(paper.get("paper_id") or "").strip()
        provenance = paper.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        compact_provenance = {
            key: copy.deepcopy(provenance[key])
            for key in (
                "provider", "raw_record_sha256", "source", "ext_id",
                "originating_query_ids", "source_records",
            )
            if provenance.get(key) not in (None, "", [], {})
        }
        metadata = paper.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        compact_metadata = {
            key: copy.deepcopy(metadata[key])
            for key in (
                "authors", "year", "journal", "publication_types",
                "is_open_access", "in_europe_pmc",
            )
            if key in metadata
        }
        selected_papers.append({
            "paper_id": paper_id,
            "title": str(paper.get("title") or "").strip(),
            "identifiers": copy.deepcopy(paper.get("identifiers") or {}),
            "metadata": compact_metadata,
            "provenance": compact_provenance,
            "source_snapshots": copy.deepcopy(snapshots_by_paper.get(paper_id, [])),
        })

    discovery_receipts = []
    for batch in frozen.get("discovery_receipts") or []:
        if not isinstance(batch, dict):
            continue
        raw_receipt = batch.get("receipt")
        raw_receipt = raw_receipt if isinstance(raw_receipt, dict) else {}
        receipt = {
            key: copy.deepcopy(raw_receipt[key])
            for key in (
                "request_sha256", "response_sha256", "response_path", "endpoint"
            )
            if raw_receipt.get(key) not in (None, "", [], {})
        }
        discovery_receipts.append({
            "provider": str(batch.get("provider") or ""),
            "query_id": str(batch.get("query_id") or ""),
            "receipt": receipt,
        })

    catalog = {
        "local_project_root": str(project.resolve()),
        "evidence_pack": {
            "pack_id": str(frozen.get("pack_id") or pack_manifest.get("pack_id") or ""),
            "content_sha256": str(
                frozen.get("content_sha256")
                or pack_manifest.get("content_sha256")
                or ""
            ),
            "artifact_path": str(pack_manifest.get("artifact_path") or ""),
            "artifact_sha256": str(pack_manifest.get("artifact_sha256") or ""),
            "source_run_id": str(run_id),
        },
        "selected_papers": selected_papers,
        "discovery_receipts": discovery_receipts,
        "method_source_registry": {
            "receipt": copy.deepcopy(registry_receipt),
            "methods": copy.deepcopy(registry_entries),
        },
    }
    return catalog, (registry_entries, registry_receipt)


def build_prompt(
    question: str, claim: str, known_sources: dict | None = None
) -> str:
    known_block = ""
    if known_sources is not None:
        known_block = f"""

Frozen known-source catalog (read-only retrieval hints; NOT method-selection authority):
{_canonical_json(known_sources)}

Local-first rules:
1. Decide the method inventory from the scientific question and selected claim first.
   A method appearing in this catalog does not authorize or require that method.
2. After a method is identified, reuse matching selected-paper identifiers and
   method-registry source_hints before doing any external lookup.
3. Do not run an external search for a DOI, PMID, PMCID, stable URL, or exact
   source already present in this catalog. Do not re-query a known identifier.
4. When metadata needs verification, use the frozen response_path or
   source_snapshots under local_project_root before any network request.
5. External metadata search is permitted only for a source/identifier gap that
   remains after local EvidencePack and method-registry matching.
"""
    return f"""Use the installed Academic Research Skills literature-search capability.

RLR stage: L4A Method Inventory and Source Metadata
Scientific question: {question}
Selected hypothesis/claim: {claim}{known_block}

Identify the explicit statistical, computational, diagnostic, and alternative
methods implied by the authorized project context. Return those methods in
`method_inventory`. This is an inventory, not a final method choice: do not
create method components, eligibility decisions, required execution flags,
evidence anchors, or an analysis plan.

For every method, carry forward any DOI, PMID, PMCID, stable URL, or exact asset
identifier already present in authorized context. A known identifier must not
be dropped merely because the corresponding paper is not selected as a general
literature asset. Search metadata only to fill missing identifiers. Never
invent an identifier. Use year 0 only when an exact source identifier is known
but its publication year is unavailable. When no exact source is found, retain
the method with empty source arrays; a versioned deterministic registry may
supply a canonical source, otherwise L4B records an explicit evidence gap.

Return metadata only. Do not retrieve full text or emit source payloads or
verbatim extracts. Keep the ordinary `assets` catalog and selection receipts.
Your final response MUST contain JSON only and MUST conform exactly to the
supplied output schema. Do not include prose, Markdown, code fences,
commentary, or any text before or after the JSON object.
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
    canonical = dict(l4p._canonicalize_l4a_provider_payload(base_payload))
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
        asset_ids = [str(value).strip() for value in item["source_asset_ids"]]
        if len(asset_ids) != len(set(asset_ids)):
            raise dr.DeepResearchError(
                f"L4A method {item['method_id']} source_asset_ids must be unique"
            )
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
    match = re.search(
        r"\bPMC\d+\b", _canonical_json(metadata or {}), flags=re.IGNORECASE
    )
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
    metadata = {
        "inventory_schema": INVENTORY_SCHEMA_VERSION,
        "method_id": method_id,
        "source_ref_id": source_ref_id,
        "pmcid": str(hint.get("pmcid") or "").strip().upper(),
    }
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
        "source_database": "method_source_registry_or_exact_identifier",
        "source_metadata_response": metadata,
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


def _deduplicate_assets(l4p, assets: list[dict]) -> tuple[list[dict], list[dict], dict[str, str]]:
    deduplicated, duplicates = l4p.deduplicate_l4a_assets(
        l4p._normalize_l4a_assets(list(assets))
    )
    aliases = {
        str(item["duplicate_asset_id"]): str(item["kept_asset_id"])
        for item in duplicates
    }
    return deduplicated, duplicates, aliases


def _remap_inventory(inventory: list[dict], aliases: dict[str, str]) -> list[dict]:
    result = copy.deepcopy(inventory)
    for method in result:
        remapped = []
        for raw in method.get("source_asset_ids") or []:
            asset_id = aliases.get(str(raw), str(raw))
            if asset_id not in remapped:
                remapped.append(asset_id)
        method["source_asset_ids"] = remapped
    return result


def _augment_assets(l4p, dr, assets: list[dict], inventory: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    assets, duplicates, aliases = _deduplicate_assets(l4p, assets)
    inventory = _remap_inventory(inventory, aliases)
    by_id = {str(asset["asset_id"]): asset for asset in assets}
    identities = {_asset_identity(asset): str(asset["asset_id"]) for asset in assets}

    for method in inventory:
        linked_ids = []
        for raw_id in method["source_asset_ids"]:
            asset_id = str(raw_id)
            if asset_id not in by_id:
                raise dr.DeepResearchError(
                    f"L4A method {method['method_id']} references unknown asset {asset_id}"
                )
            asset = by_id[asset_id]
            asset["selection_status"] = "selected"
            asset["selection_reason"] = (
                f"Exact source referenced by method inventory item {method['method_id']}."
            )
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

    final_assets, later_duplicates, later_aliases = _deduplicate_assets(l4p, assets)
    inventory = _remap_inventory(inventory, later_aliases)
    return final_assets, duplicates + later_duplicates, inventory


def _manifest_base(
    l4p,
    dr,
    *,
    candidate_id: str,
    question: str,
    claim: str,
    queries: list,
    assets: list[dict],
    duplicates: list[dict],
    inventory: list[dict],
    runtime_receipt: dict,
    project_id: str,
    round_id: str,
    profile_id: str,
) -> dict:
    selected_ids = [
        str(asset["asset_id"])
        for asset in assets
        if asset.get("selection_status") == "selected"
    ]
    if not selected_ids:
        raise dr.DeepResearchError(
            "L4A discovery produced no selected literature assets"
        )
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4A",
        "project_id": project_id,
        "round_id": str(round_id),
        "candidate_id": candidate_id,
        "profile_id": profile_id,
        "question": question,
        "claim": claim,
        "question_sha256": _sha(question),
        "claim_sha256": _sha(claim),
        "queries": queries,
        "assets": assets,
        "duplicates": duplicates,
        "selected_asset_ids": selected_ids,
        "runtime_receipt": runtime_receipt,
        "inventory_schema": INVENTORY_SCHEMA_VERSION,
        "method_inventory": inventory,
    }


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
    registry_snapshot: tuple[list[dict], dict] | None = None,
) -> dict:
    canonical = _validate_inventory_payload(l4p, dr, payload)
    try:
        registry_inventory, registry_receipt = l4_method_registry.apply_registry(
            project_dir,
            canonical["method_inventory"],
            loaded_registry=registry_snapshot,
        )
    except l4_method_registry.MethodRegistryError as exc:
        raise dr.DeepResearchError(f"L4 method-source registry failed: {exc}") from exc
    assets, duplicates, inventory = _augment_assets(
        l4p,
        dr,
        canonical["assets"],
        registry_inventory,
    )
    receipt = dict(runtime_receipt)
    receipt["method_source_registry"] = registry_receipt
    receipt["method_inventory_sha256"] = _sha(_canonical_json(inventory))
    base = _manifest_base(
        l4p,
        dr,
        candidate_id=candidate_id,
        question=question,
        claim=claim,
        queries=list(canonical["queries"]),
        assets=assets,
        duplicates=duplicates,
        inventory=inventory,
        runtime_receipt=receipt,
        project_id=project_id,
        round_id=round_id,
        profile_id=profile_id,
    )
    run_seed = {
        key: value
        for key, value in base.items()
        if key not in {"pipeline_stage", "pipeline_schema"}
    }
    run_id = _sha(_canonical_json(run_seed))[:20]
    relative = (
        Path("09_Literature_Database/l4/discovery/manifests")
        / f"{candidate_id}_{run_id}.json"
    )
    target = Path(project_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise dr.DeepResearchError(
                f"immutable L4A inventory manifest is unreadable: {target}"
            ) from exc
        expected = dict(base)
        expected.update({
            "run_id": run_id,
            "created_at": existing.get("created_at"),
            "path": relative.as_posix(),
        })
        expected["manifest_sha256"] = l4p._sha256_json(expected)
        if existing != expected:
            raise dr.DeepResearchError(
                f"immutable L4A inventory manifest already exists with different content: {target}"
            )
        ok, reason = l4p.validate_l4a_manifest(project_dir, existing)
        if not ok:
            raise dr.DeepResearchError(
                f"persisted L4A inventory manifest failed validation: {reason}"
            )
        return existing

    artifact = dict(base)
    artifact.update({
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "path": relative.as_posix(),
    })
    artifact["manifest_sha256"] = l4p._sha256_json(artifact)
    target.write_text(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    ok, reason = l4p.validate_l4a_manifest(project_dir, artifact)
    if not ok:
        raise dr.DeepResearchError(
            f"persisted L4A inventory manifest failed validation: {reason}"
        )
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
    known_sources, registry_snapshot = _native_known_source_catalog(
        project_dir, candidate_id, profile_id, dr
    )
    command, _ = dr.build_invocation(spec, "L4", question, claim, work)
    command = [
        str(inventory_schema_path) if value == str(legacy_schema_path) else value
        for value in command
    ]
    prompt = build_prompt(question, claim, known_sources)
    command[0] = dr.resolve_subprocess_executable(command[0])
    execution_command, invocation_kwargs = dr.subprocess_invocation(command, prompt)
    completed = dr.execute_provider_invocation(
        execution_command, invocation_kwargs, timeout=spec.timeout,
        label='L4A method-inventory CLI',
    )
    receipt = dr.skill_receipt(
        spec.backend,
        command,
        prompt,
        skill_version,
        exit_code=completed.returncode,
        stdout_hash=_sha(completed.stdout),
        model=spec.model,
    )
    if known_sources is not None:
        pack = known_sources["evidence_pack"]
        receipt["known_source_catalog"] = {
            "catalog_sha256": _sha(_canonical_json(known_sources)),
            "evidence_pack_id": str(pack.get("pack_id") or ""),
            "evidence_pack_content_sha256": str(
                pack.get("content_sha256") or ""
            ),
            "evidence_pack_artifact_sha256": str(
                pack.get("artifact_sha256") or ""
            ),
            "selected_paper_count": len(known_sources["selected_papers"]),
        }
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
        registry_snapshot=registry_snapshot,
    )


def inventory_sources(manifest: dict) -> tuple[list[dict], list[dict]]:
    """Return exact resolver assets plus inventory items lacking any source."""
    assets = {
        str(asset.get("asset_id") or ""): asset
        for asset in manifest.get("assets") or []
    }
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
