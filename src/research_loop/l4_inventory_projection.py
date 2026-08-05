"""Project L4A method-source hints into exact resolver assets.

L4A assets and method inventory are persisted separately for compatibility.
When a registry hint matches an existing asset by DOI/PMID, this projection
merges the hint's PMCID and registered full-text locations into the in-memory
resolver asset. The persisted manifest remains immutable and records both the
original asset metadata and the registry-enriched method inventory.
"""
from __future__ import annotations

import copy
import json
from typing import Any


_PMC_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"


def _doi(value: Any) -> str:
    text = str(value or "").strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.rstrip("/")


def _metadata(asset: dict) -> dict:
    value = asset.get("source_metadata_response")
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return copy.deepcopy(parsed) if isinstance(parsed, dict) else {}
    return {}


def _existing_pmcid(metadata: dict) -> str:
    for key in ("pmcid", "PMCID", "pmc", "PMC"):
        value = str(metadata.get(key) or "").strip().upper()
        if value:
            return value
    return ""


def _merge_hint(asset: dict, hint: dict, dr) -> None:
    existing_doi = _doi(asset.get("doi"))
    hint_doi = _doi(hint.get("doi"))
    if existing_doi and hint_doi and existing_doi != hint_doi:
        raise dr.DeepResearchError("L4A registry DOI conflicts with matched asset")

    existing_pmid = str(asset.get("pmid") or "").strip()
    hint_pmid = str(hint.get("pmid") or "").strip()
    if existing_pmid and hint_pmid and existing_pmid != hint_pmid:
        raise dr.DeepResearchError("L4A registry PMID conflicts with matched asset")

    metadata = _metadata(asset)
    existing_pmcid = _existing_pmcid(metadata)
    hint_pmcid = str(hint.get("pmcid") or "").strip().upper()
    if existing_pmcid and hint_pmcid and existing_pmcid != hint_pmcid:
        raise dr.DeepResearchError("L4A registry PMCID conflicts with matched asset")

    if not existing_doi and hint_doi:
        asset["doi"] = hint_doi
    if not existing_pmid and hint_pmid:
        asset["pmid"] = hint_pmid
    if not str(asset.get("url") or "").strip() and str(hint.get("url") or "").strip():
        asset["url"] = str(hint["url"]).strip()
    if not str(asset.get("title") or "").strip() and str(hint.get("title") or "").strip():
        asset["title"] = str(hint["title"]).strip()
    if not int(asset.get("year") or 0) and int(hint.get("year") or 0):
        asset["year"] = int(hint["year"])

    source_ref_id = str(hint.get("source_ref_id") or "").strip()
    refs = list(metadata.get("method_source_ref_ids") or [])
    if source_ref_id and source_ref_id not in refs:
        refs.append(source_ref_id)
    if refs:
        metadata["method_source_ref_ids"] = refs
    if hint_pmcid:
        metadata["pmcid"] = hint_pmcid
    asset["source_metadata_response"] = metadata

    locations = []
    for value in asset.get("full_text_locations") or []:
        value = str(value).strip()
        if value and value not in locations:
            locations.append(value)
    for value in hint.get("full_text_locations") or []:
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


def enrich_inventory_sources(manifest: dict, assets: list[dict], no_source: list[dict], dr):
    methods = {
        str(method.get("method_id") or ""): method
        for method in manifest.get("method_inventory") or []
    }
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        ref_ids = set(asset.get("inventory_source_ref_ids") or [])
        for method_id in asset.get("inventory_method_ids") or []:
            method = methods.get(str(method_id), {})
            for hint in method.get("source_hints") or []:
                hint_asset_id = str(hint.get("asset_id") or "")
                hint_ref_id = str(hint.get("source_ref_id") or "")
                if hint_asset_id == asset_id or (hint_ref_id and hint_ref_id in ref_ids):
                    _merge_hint(asset, hint, dr)
    return assets, no_source


def install(l4_inventory_module, deep_research_module) -> None:
    if getattr(l4_inventory_module, "_source_projection_installed", False):
        return
    original = l4_inventory_module.inventory_sources

    def inventory_sources(manifest: dict):
        assets, no_source = original(manifest)
        return enrich_inventory_sources(
            manifest, assets, no_source, deep_research_module
        )

    l4_inventory_module.inventory_sources = inventory_sources
    l4_inventory_module._source_projection_original = original
    l4_inventory_module._source_projection_installed = True
