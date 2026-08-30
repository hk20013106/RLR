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
from research_loop.l05_curie import multisource as l05_multisource


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


def _catalog_source_url(identifiers: dict) -> str:
    pmcid = l05_multisource.normalize_pmcid(identifiers.get("pmcid"))
    if pmcid:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    doi = l05_multisource.normalize_doi(identifiers.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    pmid = l05_multisource.normalize_pmid(identifiers.get("pmid"))
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return ""


def _native_known_source_catalog(
    project_dir: str | Path,
    candidate_id: str,
    profile_id: str,
    dr,
) -> tuple[dict | None, tuple[list[dict], dict] | None]:
    """Project frozen L0.5 metadata for L4A and load registry separately."""
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

    snapshot_by_paper: dict[str, dict] = {}
    for evidence in frozen.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        paper_id = str(evidence.get("paper_id") or "").strip()
        retrieval = evidence.get("retrieval")
        if not paper_id or not isinstance(retrieval, dict):
            continue
        if paper_id in snapshot_by_paper:
            continue
        snapshot_by_paper[paper_id] = {
            "source_path": str(retrieval.get("snapshot_path") or "").strip(),
            "source_sha256": str(retrieval.get("source_sha256") or "").strip(),
        }

    sources = []
    for paper in frozen.get("selected_papers") or []:
        if not isinstance(paper, dict):
            continue
        paper_id = str(paper.get("paper_id") or "").strip()
        identifiers = paper.get("identifiers")
        identifiers = identifiers if isinstance(identifiers, dict) else {}
        metadata = paper.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        snapshot = snapshot_by_paper.get(paper_id, {})
        source_sha256 = str(snapshot.get("source_sha256") or "")
        sources.append({
            "paper_id": paper_id,
            "doi": l05_multisource.normalize_doi(identifiers.get("doi")),
            "pmid": l05_multisource.normalize_pmid(identifiers.get("pmid")),
            "pmcid": l05_multisource.normalize_pmcid(identifiers.get("pmcid")),
            "url": _catalog_source_url(identifiers),
            "title": str(paper.get("title") or "").strip(),
            "year": int(metadata.get("year") or 0) if str(metadata.get("year") or "").isdigit() else 0,
            "source_path": str(snapshot.get("source_path") or ""),
            "source_sha256": source_sha256,
            "evidence_status": "frozen" if source_sha256 else "metadata_only",
        })

    catalog = {
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
        "sources": sources,
    }
    return catalog, (registry_entries, registry_receipt)


def build_prompt(
    question: str, claim: str, known_sources: dict | None = None
) -> str:
    known_block = ""
    if known_sources is not None:
        known_block = f"""

Frozen local-source catalog (metadata only; read-only):
{_canonical_json(known_sources)}

Local-source rules:
1. Decide the method inventory from the scientific question and selected claim.
2. The catalog may be used only to map an already identified method to a local
   paper. A paper appearing in the catalog does not authorize or require a method.
3. Reuse an exact local DOI, PMID, PMCID, URL, or paper_id when it matches an
   identified method. Do not invent or rewrite an identifier.
4. The catalog is the complete literature input visible to this cognitive step.
   Do not open source_path, do not read project files, and do not request full text.
"""
    return f"""RLR stage: L4A Offline Method Inventory
Scientific question: {question}
Selected hypothesis/claim: {claim}{known_block}

Identify the explicit statistical, computational, diagnostic, and alternative
methods implied by the authorized project context. Return those methods in
`method_inventory`. This is an inventory, not a final method choice: do not
create method components, eligibility decisions, required execution flags,
evidence anchors, or an analysis plan.

This cognitive step is OFFLINE. Do not use network access. Do not search the web.
Do not invoke browser, literature-search, PubMed, Crossref, OpenAlex, Semantic
Scholar, Europe PMC, or any external metadata/retrieval tool. External metadata
resolution, if needed, is performed deterministically after this response.

Only sources already present in the frozen local-source catalog may be emitted
as `assets` or referenced in `source_asset_ids`. For methods without a matching
local source, keep `source_asset_ids` and `source_hints` empty. Do not guess a
paper title, DOI, PMID, PMCID, URL, or source identifier from model memory.

Return metadata only. Do not retrieve full text or emit source payloads,
abstract-derived claims, or verbatim extracts. The `queries` array records this
offline inventory operation; it must not represent an external search receipt.
Your final response MUST contain JSON only and MUST conform exactly to the
supplied output schema. Do not include prose, Markdown, code fences,
commentary, or any text before or after the JSON object.
For `source_metadata_response`, return the local catalog metadata object as one
canonical JSON string: UTF-8, sorted keys, compact separators, finite JSON
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
    doi = l05_multisource.normalize_doi(asset.get("doi"))
    if doi:
        return "doi", doi
    pmid = l05_multisource.normalize_pmid(asset.get("pmid"))
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
        pmcid = l05_multisource.normalize_pmcid(match.group(0))
        if pmcid:
            return "pmcid", pmcid
    url = _normalized_url(asset.get("url"))
    if url:
        return "url", url
    return "asset", str(asset.get("asset_id") or "")


def _hint_identity(hint: dict) -> tuple[str, str]:
    doi = l05_multisource.normalize_doi(hint.get("doi"))
    if doi:
        return "doi", doi
    pmid = l05_multisource.normalize_pmid(hint.get("pmid"))
    if pmid:
        return "pmid", pmid
    pmcid = l05_multisource.normalize_pmcid(hint.get("pmcid"))
    if pmcid:
        return "pmcid", pmcid
    url = _normalized_url(hint.get("url"))
    if url:
        return "url", url
    return "", ""


def _hint_url(hint: dict) -> str:
    if str(hint.get("url") or "").strip():
        return str(hint["url"]).strip()
    pmcid = l05_multisource.normalize_pmcid(hint.get("pmcid"))
    if pmcid:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    doi = l05_multisource.normalize_doi(hint.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    pmid = l05_multisource.normalize_pmid(hint.get("pmid"))
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
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
    open_access = bool(l05_multisource.normalize_pmcid(hint.get("pmcid")) or explicit_locations)
    metadata = {
        "inventory_schema": INVENTORY_SCHEMA_VERSION,
        "method_id": method_id,
        "source_ref_id": source_ref_id,
        "pmcid": l05_multisource.normalize_pmcid(hint.get("pmcid")),
    }
    return {
        "asset_id": asset_id,
        "doi": l05_multisource.normalize_doi(hint.get("doi")),
        "pmid": l05_multisource.normalize_pmid(hint.get("pmid")),
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


def _normalized_method_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _select_unambiguous_method_record(method_name: str, records: list[dict]) -> dict | None:
    needle = _normalized_method_name(method_name)
    if not needle:
        return None
    matches = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        if needle not in _normalized_method_name(record.get("title")):
            continue
        paper_id = str(record.get("paper_id") or "").strip()
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        matches.append(record)
    return copy.deepcopy(matches[0]) if len(matches) == 1 else None


def _resolved_record_asset(record: dict, method_name: str) -> dict:
    identifiers = record.get("identifiers")
    identifiers = identifiers if isinstance(identifiers, dict) else {}
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    provenance = record.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    paper_id = str(record.get("paper_id") or "").strip()
    doi = l05_multisource.normalize_doi(identifiers.get("doi"))
    pmid = l05_multisource.normalize_pmid(identifiers.get("pmid"))
    pmcid = l05_multisource.normalize_pmcid(identifiers.get("pmcid"))
    url = _catalog_source_url({"doi": doi, "pmid": pmid, "pmcid": pmcid})
    year_text = str(metadata.get("year") or "").strip()
    year = int(year_text) if year_text.isdigit() else 0
    open_access = bool(pmcid or metadata.get("is_open_access"))
    asset_id = f"MR_{_safe(paper_id)}_{_sha(_canonical_json(identifiers or {'paper_id': paper_id}))[:8]}"
    return {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "title": str(record.get("title") or "").strip(),
        "year": year,
        "role": "method",
        "journal": str(metadata.get("journal") or "").strip(),
        "abstract": "",
        "source_database": str(provenance.get("provider") or "pubmed"),
        "source_metadata_response": {
            "paper_id": paper_id,
            "identifiers": copy.deepcopy(identifiers),
            "provenance": copy.deepcopy(provenance),
        },
        "open_access_status": "open" if open_access else "unknown",
        "full_text_status": "available_oa" if open_access else "metadata_only",
        "full_text_locations": [url] if url else [],
        "relevance_score": 10.0,
        "selection_status": "selected",
        "selection_reason": (
            f"Deterministic bounded metadata match for method {method_name}."
        ),
        "hypothesis_ids": [],
        "method_component_hints": [method_name],
        "diagnostic_requirements": [],
    }


def _resolve_missing_inventory_sources(
    project_dir: str | Path,
    candidate_id: str,
    inventory: list[dict],
) -> tuple[list[dict], list[dict], dict]:
    """Resolve each unique unresolved method name once, then stop on misses."""
    result = copy.deepcopy(inventory)
    unresolved_by_name: dict[str, list[dict]] = {}
    order = []
    for method in result:
        if method.get("source_asset_ids") or method.get("source_hints"):
            continue
        name = str(method.get("name") or "").strip()
        key = _normalized_method_name(name)
        if not key:
            continue
        if key not in unresolved_by_name:
            unresolved_by_name[key] = []
            order.append(key)
        unresolved_by_name[key].append(method)

    receipt = {
        "resolver": "l05_curie.multisource.PubMedTransport/v1",
        "queries": [],
        "gaps": [],
    }
    if not order:
        return result, [], receipt

    run_id = "L4A_META_" + _sha(_canonical_json({
        "candidate_id": candidate_id,
        "methods": [
            str(unresolved_by_name[key][0].get("name") or "") for key in order
        ],
    }))[:16]
    transport = l05_multisource.PubMedTransport(
        project_dir,
        candidate_id=candidate_id,
        run_id=run_id,
    )
    resolved_assets: dict[str, dict] = {}

    for index, key in enumerate(order, 1):
        methods = unresolved_by_name[key]
        method_name = str(methods[0].get("name") or "").strip()
        query_id = f"Q{index:03d}"
        selected = None
        try:
            batch = transport.search({
                "query_id": query_id,
                "query": method_name,
                "page_size": 5,
            })
            selected = _select_unambiguous_method_record(
                method_name, list(batch.get("records") or [])
            )
        except Exception:
            selected = None

        if selected is None:
            receipt["queries"].append({
                "method_name": method_name,
                "status": "gap",
                "attempt_count": 1,
                "paper_id": "",
            })
            receipt["gaps"].append({
                "method_ids": [str(method.get("method_id") or "") for method in methods],
                "method_name": method_name,
                "reason": "NO_UNAMBIGUOUS_METADATA_MATCH",
            })
            continue

        paper_id = str(selected.get("paper_id") or "").strip()
        if paper_id not in resolved_assets:
            resolved_assets[paper_id] = _resolved_record_asset(selected, method_name)
        asset_id = str(resolved_assets[paper_id]["asset_id"])
        for method in methods:
            method["source_asset_ids"] = [asset_id]
        receipt["queries"].append({
            "method_name": method_name,
            "status": "resolved",
            "attempt_count": 1,
            "paper_id": paper_id,
        })

    return result, list(resolved_assets.values()), receipt


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
    inventory, resolved_assets, resolution_receipt = _resolve_missing_inventory_sources(
        project_dir,
        candidate_id,
        inventory,
    )
    if resolved_assets:
        assets, resolution_duplicates, aliases = _deduplicate_assets(
            l4p, assets + resolved_assets
        )
        duplicates.extend(resolution_duplicates)
        inventory = _remap_inventory(inventory, aliases)
    receipt = dict(runtime_receipt)
    receipt["method_source_registry"] = registry_receipt
    receipt["metadata_resolution"] = resolution_receipt
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
            "selected_paper_count": len(known_sources["sources"]),
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
