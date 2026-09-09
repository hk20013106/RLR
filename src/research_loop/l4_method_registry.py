"""Versioned canonical-source registry for staged L4 method inventory.

The registry maps an already identified method entity to exact DOI/PMID/PMCID
records. It never decides that a method belongs in a study and never searches
for literature. Project entries may override built-in entries by canonical ID.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA_VERSION = "L4MethodSourceRegistry/v1"
_BUILTIN_RELATIVE_PATH = Path("research_loop/data/l4_method_source_registry.json")
_BUILTIN_PATH = Path(__file__).parent / "data" / "l4_method_source_registry.json"
_PROJECT_RELATIVE_PATH = Path(
    "09_Literature_Database/l4/method_source_registry.json"
)
_SOURCE_KINDS = {
    "primary_study",
    "method_paper",
    "protocol",
    "supplementary_methods",
    "official_documentation",
    "versioned_code",
}


class MethodRegistryError(ValueError):
    """Raised when a method-source registry is malformed."""


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


def _normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _normalized_doi(value: Any) -> str:
    return re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        str(value or "").strip().casefold(),
    ).rstrip("/")


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
    url = str(hint.get("url") or "").strip().casefold().rstrip("/")
    if url:
        return "url", url
    return "", ""


def _validate_hint(hint: Any, *, label: str) -> dict:
    if not isinstance(hint, dict):
        raise MethodRegistryError(f"{label} source hint must be an object")
    required = {
        "source_ref_id",
        "title",
        "year",
        "doi",
        "pmid",
        "pmcid",
        "url",
        "source_kind",
        "rationale",
        "full_text_locations",
    }
    if set(hint) != required:
        raise MethodRegistryError(
            f"{label} source hint fields do not match the registry contract"
        )
    if not str(hint["source_ref_id"]).strip():
        raise MethodRegistryError(f"{label} source_ref_id is empty")
    if not isinstance(hint["year"], int):
        raise MethodRegistryError(f"{label} year must be an integer")
    if hint["source_kind"] not in _SOURCE_KINDS:
        raise MethodRegistryError(f"{label} source_kind is invalid")
    if not str(hint["rationale"]).strip():
        raise MethodRegistryError(f"{label} rationale is empty")
    if not isinstance(hint["full_text_locations"], list) or any(
        not str(value).strip() for value in hint["full_text_locations"]
    ):
        raise MethodRegistryError(
            f"{label} full_text_locations must be non-empty strings"
        )
    if not _hint_identity(hint)[0]:
        raise MethodRegistryError(f"{label} has no exact source identifier")
    return copy.deepcopy(hint)


def _validate_registry(value: Any, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise MethodRegistryError(f"{label} registry must be an object")
    if set(value) != {"schema_version", "methods"}:
        raise MethodRegistryError(f"{label} registry fields are invalid")
    if value.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise MethodRegistryError(f"{label} registry schema_version is invalid")
    if not isinstance(value.get("methods"), list):
        raise MethodRegistryError(f"{label} methods must be an array")

    methods = []
    seen_ids = set()
    for index, raw in enumerate(value["methods"]):
        item_label = f"{label} methods[{index}]"
        if not isinstance(raw, dict) or set(raw) != {
            "canonical_method_id", "aliases", "source_hints"
        }:
            raise MethodRegistryError(f"{item_label} fields are invalid")
        canonical_id = str(raw["canonical_method_id"] or "").strip()
        if not canonical_id or canonical_id in seen_ids:
            raise MethodRegistryError(
                f"{item_label} canonical_method_id is empty or duplicated"
            )
        aliases = [str(value).strip() for value in raw["aliases"]]
        if not aliases or any(not alias for alias in aliases):
            raise MethodRegistryError(f"{item_label} aliases are invalid")
        if len({_normalized_text(value) for value in aliases}) != len(aliases):
            raise MethodRegistryError(f"{item_label} aliases are duplicated")
        if not isinstance(raw["source_hints"], list) or not raw["source_hints"]:
            raise MethodRegistryError(f"{item_label} source_hints are empty")
        hints = [
            _validate_hint(hint, label=f"{item_label} source_hints[{hint_index}]")
            for hint_index, hint in enumerate(raw["source_hints"])
        ]
        identities = [_hint_identity(hint) for hint in hints]
        if len(identities) != len(set(identities)):
            raise MethodRegistryError(
                f"{item_label} source_hints contain duplicate exact sources"
            )
        seen_ids.add(canonical_id)
        methods.append({
            "canonical_method_id": canonical_id,
            "aliases": aliases,
            "source_hints": hints,
        })
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "methods": methods,
    }


def _read_registry(path: Path, *, required: bool, label: str) -> dict | None:
    if not path.is_file():
        if required:
            raise MethodRegistryError(f"{label} registry is missing: {path}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MethodRegistryError(f"{label} registry is unreadable: {exc}") from exc
    return _validate_registry(value, label=label)


def load_registry(project_dir: str | Path) -> tuple[list[dict], dict]:
    """Load built-in entries, then replace matching IDs with project entries."""
    builtin = _read_registry(_BUILTIN_PATH, required=True, label="built-in")
    project_path = Path(project_dir) / _PROJECT_RELATIVE_PATH
    project = _read_registry(project_path, required=False, label="project")

    merged = {
        str(item["canonical_method_id"]): copy.deepcopy(item)
        for item in builtin["methods"]
    }
    if project:
        for item in project["methods"]:
            merged[str(item["canonical_method_id"])] = copy.deepcopy(item)
    receipt = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "builtin_path": _BUILTIN_RELATIVE_PATH.as_posix(),
        "builtin_sha256": _sha(_canonical_json(builtin)),
        "project_path": _PROJECT_RELATIVE_PATH.as_posix()
        if project else "",
        "project_sha256": _sha(_canonical_json(project)) if project else "",
        "canonical_method_ids": sorted(merged),
    }
    return [merged[key] for key in sorted(merged)], receipt


def _matches(method: dict, entry: dict) -> bool:
    method_values = {
        _normalized_text(method.get("method_id")),
        _normalized_text(method.get("name")),
    }
    method_values.discard("")
    aliases = {
        _normalized_text(entry.get("canonical_method_id")),
        *(_normalized_text(value) for value in entry.get("aliases") or []),
    }
    aliases.discard("")
    for method_value in method_values:
        for alias in aliases:
            if method_value == alias:
                return True
            if len(alias) >= 4 and alias in method_value:
                return True
    return False


def apply_registry(
    project_dir: str | Path, inventory: list[dict], *,
    loaded_registry: tuple[list[dict], dict] | None = None,
) -> tuple[list[dict], dict]:
    """Add exact hints for methods already present in the cognitive inventory."""
    if loaded_registry is None:
        entries, receipt = load_registry(project_dir)
    else:
        entries, receipt = loaded_registry
        entries = copy.deepcopy(list(entries))
        receipt = copy.deepcopy(dict(receipt))
    result = copy.deepcopy(inventory)
    matches = []
    for method in result:
        existing = {
            _hint_identity(hint)
            for hint in method.get("source_hints") or []
            if _hint_identity(hint)[0]
        }
        matched_ids = []
        for entry in entries:
            if not _matches(method, entry):
                continue
            canonical_id = str(entry["canonical_method_id"])
            matched_ids.append(canonical_id)
            for hint in entry["source_hints"]:
                identity = _hint_identity(hint)
                if identity not in existing:
                    method.setdefault("source_hints", []).append(copy.deepcopy(hint))
                    existing.add(identity)
        if matched_ids:
            matches.append({
                "method_id": str(method.get("method_id") or ""),
                "canonical_method_ids": sorted(set(matched_ids)),
            })
    receipt["matches"] = matches
    receipt["applied_inventory_sha256"] = _sha(_canonical_json(result))
    return result, receipt
