"""Close L4 method-registry matching and persisted exact-source metadata.

The registry still applies only to methods already present in the L4A method
inventory. Exact DOI/PMID/PMCID/stable-URL overlap may identify a canonical
entry; partial identifier conflicts fail closed. Registry metadata is merged
into the selected asset before the immutable L4A manifest is written.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any


_STRONG_IDS = ("doi", "pmid", "pmcid")
_PMC_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"


def _doi(value: Any) -> str:
    return re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        str(value or "").strip().casefold(),
    ).rstrip("/")


def _url(value: Any) -> str:
    return str(value or "").strip().casefold().rstrip("/")


def _metadata(value: Any) -> dict:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return copy.deepcopy(parsed) if isinstance(parsed, dict) else {}
    return {}


def _pmcid(record: dict) -> str:
    value = str(record.get("pmcid") or "").strip().upper()
    if value:
        return value
    metadata = _metadata(record.get("source_metadata_response"))
    for key in ("pmcid", "PMCID", "pmc", "PMC"):
        value = str(metadata.get(key) or "").strip().upper()
        if value:
            return value
    match = re.search(r"\bPMC\d+\b", json.dumps(metadata), flags=re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _identifiers(record: dict) -> dict[str, set[str]]:
    result = {"doi": set(), "pmid": set(), "pmcid": set(), "url": set()}
    values = {
        "doi": _doi(record.get("doi")),
        "pmid": str(record.get("pmid") or "").strip(),
        "pmcid": _pmcid(record),
        "url": _url(record.get("url")),
    }
    for key, value in values.items():
        if value:
            result[key].add(value)
    return result


def _matches_exact(record: dict, hint: dict, registry_module, canonical_id: str) -> bool:
    left = _identifiers(record)
    right = _identifiers(hint)
    strong_overlap = any(left[key] & right[key] for key in _STRONG_IDS)
    if strong_overlap:
        for key in _STRONG_IDS:
            if left[key] and right[key] and not left[key] & right[key]:
                raise registry_module.MethodRegistryError(
                    f"method source {key.upper()} conflict for canonical method "
                    f"{canonical_id}"
                )
        return True
    return bool(left["url"] & right["url"])


def _method_records(method: dict, assets: dict[str, dict]) -> list[dict]:
    records = [
        item for item in method.get("source_hints") or []
        if isinstance(item, dict)
    ]
    for asset_id in method.get("source_asset_ids") or []:
        asset = assets.get(str(asset_id))
        if asset is not None:
            records.append(asset)
    return records


def _merge_hint(target: dict, canonical: dict) -> None:
    locations = []
    for value in list(target.get("full_text_locations") or []) + list(
        canonical.get("full_text_locations") or []
    ):
        value = str(value).strip()
        if value and value not in locations:
            locations.append(value)
    target.clear()
    target.update(copy.deepcopy(canonical))
    target["full_text_locations"] = locations


def _apply_registry(
    registry_module, project_dir, inventory, assets=None, *, loaded_registry=None
):
    if loaded_registry is None:
        entries, receipt = registry_module.load_registry(project_dir)
    else:
        entries, receipt = loaded_registry
        entries = copy.deepcopy(list(entries))
        receipt = copy.deepcopy(dict(receipt))
    result = copy.deepcopy(inventory)
    assets_by_id = {
        str(asset.get("asset_id") or ""): copy.deepcopy(asset)
        for asset in (assets or [])
        if isinstance(asset, dict)
    }
    matches = []

    for method in result:
        matched_ids = []
        records = _method_records(method, assets_by_id)
        for entry in entries:
            canonical_id = str(entry["canonical_method_id"])
            exact_match = any(
                _matches_exact(record, hint, registry_module, canonical_id)
                for record in records
                for hint in entry["source_hints"]
            )
            if not registry_module._matches(method, entry) and not exact_match:
                continue

            matched_ids.append(canonical_id)
            for canonical_hint in entry["source_hints"]:
                existing_match = None
                for existing_hint in method.get("source_hints") or []:
                    if _matches_exact(
                        existing_hint,
                        canonical_hint,
                        registry_module,
                        canonical_id,
                    ):
                        existing_match = existing_hint
                        break
                if existing_match is None:
                    method.setdefault("source_hints", []).append(
                        copy.deepcopy(canonical_hint)
                    )
                else:
                    _merge_hint(existing_match, canonical_hint)
            records = _method_records(method, assets_by_id)

        if matched_ids:
            matches.append({
                "method_id": str(method.get("method_id") or ""),
                "canonical_method_ids": sorted(set(matched_ids)),
            })

    receipt["matches"] = matches
    receipt["applied_inventory_sha256"] = registry_module._sha(
        registry_module._canonical_json(result)
    )
    return result, receipt


def _asset_hint(asset: dict) -> dict:
    role = str(asset.get("role") or "")
    source_kind = {
        "primary": "primary_study",
        "method": "method_paper",
        "protocol": "protocol",
    }.get(role, "method_paper")
    asset_id = str(asset.get("asset_id") or "")
    return {
        "source_ref_id": f"asset:{asset_id}",
        "title": str(asset.get("title") or "").strip(),
        "year": int(asset.get("year") or 0),
        "doi": _doi(asset.get("doi")),
        "pmid": str(asset.get("pmid") or "").strip(),
        "pmcid": _pmcid(asset),
        "url": str(asset.get("url") or "").strip(),
        "source_kind": source_kind,
        "rationale": f"Exact source asset linked by method inventory: {asset_id}.",
        "full_text_locations": [
            str(value).strip()
            for value in asset.get("full_text_locations") or []
            if str(value).strip()
        ],
    }


def _overlaps(left: dict, right: dict) -> bool:
    left_ids = _identifiers(left)
    right_ids = _identifiers(right)
    return any(left_ids[key] & right_ids[key] for key in left_ids)


def _materialize_linked_assets(canonical: dict) -> dict:
    result = copy.deepcopy(canonical)
    assets = {
        str(asset.get("asset_id") or ""): asset
        for asset in result.get("assets") or []
    }
    for method in result.get("method_inventory") or []:
        existing = method.get("source_hints") or []
        refs = {str(item.get("source_ref_id") or "") for item in existing}
        for asset_id in method.get("source_asset_ids") or []:
            asset = assets.get(str(asset_id))
            if asset is None:
                continue
            hint = _asset_hint(asset)
            if any(_overlaps(item, hint) for item in existing):
                continue
            if hint["source_ref_id"] in refs:
                raise ValueError(
                    f"duplicate materialized source_ref_id {hint['source_ref_id']}"
                )
            existing.append(hint)
            refs.add(hint["source_ref_id"])
        method["source_hints"] = existing
    return result


def _merge_asset(asset: dict, hint: dict, dr) -> None:
    existing_doi = _doi(asset.get("doi"))
    hint_doi = _doi(hint.get("doi"))
    if existing_doi and hint_doi and existing_doi != hint_doi:
        raise dr.DeepResearchError("L4A registry DOI conflicts with matched asset")

    existing_pmid = str(asset.get("pmid") or "").strip()
    hint_pmid = str(hint.get("pmid") or "").strip()
    if existing_pmid and hint_pmid and existing_pmid != hint_pmid:
        raise dr.DeepResearchError("L4A registry PMID conflicts with matched asset")

    metadata = _metadata(asset.get("source_metadata_response"))
    existing_pmcid = _pmcid({"source_metadata_response": metadata})
    hint_pmcid = str(hint.get("pmcid") or "").strip().upper()
    if existing_pmcid and hint_pmcid and existing_pmcid != hint_pmcid:
        raise dr.DeepResearchError("L4A registry PMCID conflicts with matched asset")

    if not existing_doi and hint_doi:
        asset["doi"] = hint_doi
    if not existing_pmid and hint_pmid:
        asset["pmid"] = hint_pmid
    if not str(asset.get("url") or "").strip() and str(hint.get("url") or "").strip():
        asset["url"] = str(hint["url"]).strip()

    refs = [str(value) for value in metadata.get("method_source_ref_ids") or []]
    source_ref_id = str(hint.get("source_ref_id") or "").strip()
    if source_ref_id and source_ref_id not in refs:
        refs.append(source_ref_id)
    if refs:
        metadata["method_source_ref_ids"] = refs
    if hint_pmcid:
        metadata["pmcid"] = hint_pmcid
    asset["source_metadata_response"] = metadata

    locations = []
    for value in list(asset.get("full_text_locations") or []) + list(
        hint.get("full_text_locations") or []
    ):
        value = str(value).strip()
        if value and value not in locations:
            locations.append(value)
    if hint_pmcid:
        pmc_url = _PMC_URL.format(pmcid=hint_pmcid)
        if pmc_url not in locations:
            locations.append(pmc_url)
    asset["full_text_locations"] = locations
    if hint_pmcid or hint.get("full_text_locations"):
        asset["open_access_status"] = "open"
        asset["full_text_status"] = "available_oa"


def install(registry_module, inventory_module) -> None:
    if getattr(inventory_module, "_registry_projection_integrity_installed", False):
        return

    original_validate = inventory_module._validate_inventory_payload
    original_augment = inventory_module._augment_assets
    original_apply = registry_module.apply_registry

    def validate_inventory_payload(l4p, dr, payload):
        canonical = original_validate(l4p, dr, payload)
        try:
            return _materialize_linked_assets(canonical)
        except ValueError as exc:
            raise dr.DeepResearchError(str(exc)) from exc

    def apply_registry(
        project_dir, inventory, assets=None, *, loaded_registry=None
    ):
        return _apply_registry(
            registry_module,
            project_dir,
            inventory,
            assets=assets,
            loaded_registry=loaded_registry,
        )

    def augment_assets(l4p, dr, assets, inventory):
        final_assets, duplicates, final_inventory = original_augment(
            l4p, dr, assets, inventory
        )
        by_id = {
            str(asset.get("asset_id") or ""): asset
            for asset in final_assets
        }
        for method in final_inventory:
            for hint in method.get("source_hints") or []:
                asset = by_id.get(str(hint.get("asset_id") or ""))
                if asset is not None:
                    _merge_asset(asset, hint, dr)
        return final_assets, duplicates, final_inventory

    inventory_module._validate_inventory_payload = validate_inventory_payload
    inventory_module._augment_assets = augment_assets
    registry_module.apply_registry = apply_registry
    registry_module._registry_projection_original_apply = original_apply
    inventory_module._registry_projection_original_validate = original_validate
    inventory_module._registry_projection_original_augment = original_augment
    inventory_module._registry_projection_integrity_installed = True
