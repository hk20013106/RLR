"""Typed cross-cutting authority resolution for native RLR nodes.

Node-to-node ``context_inputs`` remain the visibility contract for prior deltas.
This module owns the orthogonal authority contract for canonical artifacts that
are produced once but consumed by multiple runtime boundaries.  Resolvers call
the artifact owner's existing validator; they never reconstruct authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from research_loop.l0_data import (
    DATA_BINDING_SCHEMA,
    current_round_data_binding_path,
    verify_current_round_data_binding,
)


class AuthorityError(RuntimeError):
    """Fail-closed typed-authority resolution error."""


@dataclass(frozen=True)
class AuthoritySpec:
    name: str
    producer: str
    schema_version: str
    context_consumers: frozenset[str]
    execution_consumers: frozenset[str]


@dataclass(frozen=True)
class ResolvedAuthority:
    spec: AuthoritySpec
    artifact_path: Path
    artifact_sha256: str
    payload: dict[str, Any]


AUTHORITY_REGISTRY: dict[str, AuthoritySpec] = {
    "current_round_data_binding": AuthoritySpec(
        name="current_round_data_binding",
        producer="L0",
        schema_version=DATA_BINDING_SCHEMA,
        context_consumers=frozenset({"L4"}),
        execution_consumers=frozenset({"L7"}),
    ),
}

_MAX_PROJECTED_JSON_BYTES = 64 * 1024
_MAX_MAPPING_ITEMS = 32
_MAX_LIST_ITEMS = 12
_MAX_STRING_CHARS = 240
_MAX_DEPTH = 3


def node_authority_declarations(node_id: str, *, native: bool) -> dict[str, list[str]]:
    """Return profile-isolated typed authority declarations for one node."""
    declarations = {
        "requires_authorities": [],
        "optional_authorities": [],
        "produces_authorities": [],
    }
    if not native:
        return declarations
    for name, spec in AUTHORITY_REGISTRY.items():
        if spec.producer == node_id:
            declarations["produces_authorities"].append(name)
        if node_id in spec.context_consumers or node_id in spec.execution_consumers:
            declarations["requires_authorities"].append(name)
    for values in declarations.values():
        values.sort()
    return declarations


def authority_requirements(node_info: dict[str, Any]) -> tuple[str, ...]:
    values = node_info.get("requires_authorities") or []
    return tuple(str(value) for value in values)


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_bound_path(project: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project / path


def resolve_authority(
    project_dir: str | Path,
    cand_id: str,
    authority_name: str,
    *,
    consumer_node: str,
    mode: str,
) -> ResolvedAuthority:
    """Resolve one canonical authority through its owner's existing validator."""
    spec = AUTHORITY_REGISTRY.get(authority_name)
    if spec is None:
        raise AuthorityError(f"unknown authority: {authority_name}")
    allowed = (
        spec.context_consumers if mode == "context" else
        spec.execution_consumers if mode == "execution" else None
    )
    if allowed is None:
        raise AuthorityError(f"invalid authority consumption mode: {mode}")
    if consumer_node not in allowed:
        raise AuthorityError(
            f"{consumer_node} is not authorized to consume {authority_name} in {mode} mode"
        )

    project = Path(project_dir)
    if authority_name == "current_round_data_binding":
        try:
            payload = verify_current_round_data_binding(project, cand_id)
        except Exception as exc:  # owner-specific error is preserved as cause
            raise AuthorityError(
                f"{authority_name} failed canonical verification: {exc}"
            ) from exc
        path = current_round_data_binding_path(project, cand_id)
    else:  # registry/resolver ownership must remain exhaustive
        raise AuthorityError(f"authority has no resolver: {authority_name}")

    if not path.is_file():
        raise AuthorityError(f"canonical authority artifact is missing: {path}")
    if payload.get("schema_version") != spec.schema_version:
        raise AuthorityError(
            f"{authority_name} schema mismatch: expected {spec.schema_version}, "
            f"got {payload.get('schema_version')!r}"
        )
    return ResolvedAuthority(
        spec=spec,
        artifact_path=path,
        artifact_sha256=_sha_file(path),
        payload=payload,
    )


def _bounded_semantics(value: Any, *, depth: int = 0) -> Any:
    """Return a deterministic small semantic projection, never a bulk payload."""
    if depth >= _MAX_DEPTH:
        return "<bounded>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING_CHARS else value[:_MAX_STRING_CHARS] + "…"
    if isinstance(value, list):
        projected = [
            _bounded_semantics(item, depth=depth + 1)
            for item in value[:_MAX_LIST_ITEMS]
        ]
        if len(value) > _MAX_LIST_ITEMS:
            projected.append(f"<+{len(value) - _MAX_LIST_ITEMS} items>")
        return projected
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value)[:_MAX_MAPPING_ITEMS]
        projected = {
            key: _bounded_semantics(value[key], depth=depth + 1)
            for key in keys
        }
        if len(value) > _MAX_MAPPING_ITEMS:
            projected["<omitted_keys>"] = len(value) - _MAX_MAPPING_ITEMS
        return projected
    return str(value)[:_MAX_STRING_CHARS]


def _small_json_semantics(project: Path, item: dict[str, Any]) -> dict[str, Any] | None:
    """Project bounded semantics only for small, hash-verified JSON artifacts."""
    try:
        byte_count = int(item.get("bytes") or 0)
    except (TypeError, ValueError):
        return None
    if byte_count <= 0 or byte_count > _MAX_PROJECTED_JSON_BYTES:
        return None
    path = _resolve_bound_path(project, str(item.get("path") or ""))
    if path.suffix.lower() != ".json" or not path.is_file():
        return None
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != str(item.get("sha256") or ""):
        raise AuthorityError(f"authorized JSON input changed after binding: {item.get('path')}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return _bounded_semantics(value)


def _context_projection(resolved: ResolvedAuthority, project: Path) -> dict[str, Any]:
    payload = resolved.payload
    authorized = []
    for item in payload.get("authorized_inputs") or []:
        row = {
            key: item.get(key)
            for key in ("path", "sha256", "bytes", "role", "origin", "reason")
            if key in item
        }
        semantics = _small_json_semantics(project, item)
        if semantics is not None:
            row["semantic_projection"] = semantics
        authorized.append(row)
    return {
        "authority": resolved.spec.name,
        "producer": resolved.spec.producer,
        "schema_version": resolved.spec.schema_version,
        "artifact_path": str(resolved.artifact_path),
        "artifact_sha256": resolved.artifact_sha256,
        "candidate_id": payload.get("candidate_id"),
        "round_id": payload.get("round_id"),
        "authorized_inputs": authorized,
        "non_file_inputs": _bounded_semantics(payload.get("non_file_inputs") or []),
    }


def project_context_authorities(
    project_dir: str | Path,
    cand_id: str,
    node_info: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Resolve and render only authorities explicitly granted to this context."""
    project = Path(project_dir)
    node_id = str(node_info.get("node") or "")
    sections: list[str] = []
    manifest_rows: list[dict[str, Any]] = []
    for name in authority_requirements(node_info):
        spec = AUTHORITY_REGISTRY.get(name)
        if spec is None:
            raise AuthorityError(f"{node_id} requires unknown authority: {name}")
        # Execution-only requirements are validated/staged at their execution
        # boundary; least-context means they are not copied into the prompt.
        if node_id not in spec.context_consumers:
            if node_id not in spec.execution_consumers:
                raise AuthorityError(f"{node_id} has no authorized path for required authority {name}")
            continue
        resolved = resolve_authority(
            project, cand_id, name, consumer_node=node_id, mode="context"
        )
        projection = _context_projection(resolved, project)
        sections.append(f"=== AUTHORITY: {name} ===")
        sections.append(json.dumps(projection, ensure_ascii=False, sort_keys=True))
        sections.append("")
        manifest_rows.append({
            "authority": name,
            "producer": spec.producer,
            "schema_version": spec.schema_version,
            "artifact_path": str(resolved.artifact_path),
            "artifact_sha256": resolved.artifact_sha256,
            "authorized_input_count": len(resolved.payload.get("authorized_inputs") or []),
            "projection_sha256": hashlib.sha256(
                json.dumps(projection, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        })
    return sections, manifest_rows
