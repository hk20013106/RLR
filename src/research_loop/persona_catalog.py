"""Fail-closed persona-template catalog resolution for native v2.1 projects."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from research_loop.compatibility import CompatibilityProfile
from research_loop.paths import PERSONA_TEMPLATE_FILE


class PersonaCatalogError(ValueError):
    """Raised when catalog metadata or a template cannot be trusted."""


@dataclass(frozen=True)
class PersonaTemplateResolution:
    path: Path
    markdown_body: str
    persona_id: str
    display_name: str
    functional_title: str
    catalog_version: str
    catalog_sha256: str
    entry_sha256: str
    template_sha256: str
    body_sha256: str


_ALLOWED_ENTRY = {"catalog_schema", "catalog_version", "persona_id", "display_name", "functional_title", "template_version"}
_SUPPORTED_TEMPLATE_VERSION = "1.0"
_ROOT = Path(__file__).resolve().parents[2]


def _digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _split_frontmatter(path: Path) -> tuple[dict, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PersonaCatalogError(f"cannot read persona template {path.name}: {exc}") from exc
    if not text.startswith("---\n"):
        raise PersonaCatalogError(f"persona template {path.name} lacks YAML frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise PersonaCatalogError(f"persona template {path.name} has unterminated YAML frontmatter")
    try:
        entry = yaml.safe_load(text[4:marker])
    except yaml.YAMLError as exc:
        raise PersonaCatalogError(f"invalid YAML frontmatter in {path.name}: {exc}") from exc
    return entry, text[marker + 5:]


def _read_catalog() -> list[dict]:
    directory = _ROOT / "templates" / "personas" / "catalog-v1"
    entries = []
    seen_ids, seen_names = set(), set()
    for path in sorted(directory.glob("*.md"), key=lambda item: item.name):
        entry, body = _split_frontmatter(path)
        if not isinstance(entry, dict) or set(entry) != _ALLOWED_ENTRY:
            raise PersonaCatalogError("persona catalog entry has missing or unknown fields")
        if not all(isinstance(entry[k], str) and entry[k].strip() for k in _ALLOWED_ENTRY):
            raise PersonaCatalogError("persona catalog entry fields must be non-empty strings")
        if entry["catalog_schema"] != "persona-catalog/v1" or entry["catalog_version"] != "persona-catalog-1":
            raise PersonaCatalogError("unsupported persona catalog schema or version")
        if entry["template_version"] != _SUPPORTED_TEMPLATE_VERSION:
            raise PersonaCatalogError(
                f"unsupported persona template version: {entry['template_version']}"
            )
        if entry["persona_id"] in seen_ids or entry["display_name"] in seen_names:
            raise PersonaCatalogError("persona catalog has duplicate persona ID or display name")
        expected_name = PERSONA_TEMPLATE_FILE.get(entry["display_name"])
        if path.name != expected_name or entry["persona_id"] != entry["display_name"].lower():
            raise PersonaCatalogError("persona filename, ID, and display name must agree")
        if not body.strip() or not body.startswith(f"# {entry['display_name']}"):
            raise PersonaCatalogError("persona Markdown title does not match catalog entry")
        seen_ids.add(entry["persona_id"]); seen_names.add(entry["display_name"])
        entries.append({**entry, "path": path, "markdown_body": body})
    if seen_names != set(PERSONA_TEMPLATE_FILE):
        raise PersonaCatalogError("persona catalog must declare every known persona exactly once")
    return entries


def resolve_persona_template(profile: CompatibilityProfile, persona: str) -> PersonaTemplateResolution:
    """Return one template and immutable hashes selected by the profile binding."""
    if profile.persona_catalog_version == "body-only-1":
        path = _ROOT / "templates" / "personas" / PERSONA_TEMPLATE_FILE.get(persona, "")
        if not path.is_file():
            raise PersonaCatalogError(f"unknown persona template: {persona}")
        body = path.read_text(encoding="utf-8")
        digest = _digest(body)
        return PersonaTemplateResolution(path, body, persona.lower(), persona, "", "body-only-1", "", digest, digest, digest)
    if profile.persona_catalog_version != "persona-catalog-1":
        raise PersonaCatalogError(f"unsupported persona catalog version: {profile.persona_catalog_version}")
    entries = _read_catalog()
    entry = next((e for e in entries if e["display_name"] == persona), None)
    if entry is None:
        raise PersonaCatalogError(f"unknown persona: {persona}")
    path = entry["path"]
    body = entry["markdown_body"]
    entry_fields = {key: entry[key] for key in _ALLOWED_ENTRY}
    normalized_entries = [
        {"entry": {key: item[key] for key in _ALLOWED_ENTRY},
         "template_sha256": _digest(item["path"].read_bytes())}
        for item in sorted(entries, key=lambda item: item["persona_id"])
    ]
    catalog_hash = _digest(json.dumps(normalized_entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    entry_hash = _digest(json.dumps(entry_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    template_hash = _digest(path.read_bytes())
    return PersonaTemplateResolution(path, body, entry["persona_id"], entry["display_name"], entry["functional_title"], entry["catalog_version"], catalog_hash, entry_hash, template_hash, _digest(body))
