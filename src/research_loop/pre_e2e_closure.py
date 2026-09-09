"""Deterministic pre-E2E closure audit for the native RLR DAG.

This module does not create a second contract registry.  It reads the existing
owners -- topology, typed authority registry, hypothesis contracts, the L4
handle binder, RunReceipt, and run_loop recovery -- and reports whether those
owners compose into one reachable path before a real provider is invoked.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
from pathlib import Path
from typing import Any

from research_loop.authority import AUTHORITY_REGISTRY
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE, get_profile
from research_loop.hypothesis_contracts import (
    PERSISTED_SCHEMA_REGISTRY,
    SCHEMA_REGISTRY,
    provider_schema_for_profile,
)
from research_loop import l0_data, l4_evidence_bundle, method_contracts
from research_loop.providers.base import RunReceipt
from research_loop.topology import topology_for_profile


CLOSED = "CLOSED"
NA = "N/A"


def _schema_paths(schema: Any, prefix: str = "") -> tuple[set[str], set[str]]:
    """Return recursive property paths and required paths for one JSON schema."""
    properties: set[str] = set()
    required: set[str] = set()
    if not isinstance(schema, dict):
        return properties, required

    props = schema.get("properties")
    required_names = set(schema.get("required") or [])
    if isinstance(props, dict):
        for name, child in props.items():
            path = f"{prefix}.{name}" if prefix else str(name)
            properties.add(path)
            if name in required_names:
                required.add(path)
            child_prefix = path
            if isinstance(child, dict) and child.get("type") == "array":
                child_prefix = path + "[]"
                properties.add(child_prefix)
                child = child.get("items")
            child_props, child_required = _schema_paths(child, child_prefix)
            properties.update(child_props)
            required.update(child_required)

    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            for branch in branches:
                child_props, child_required = _schema_paths(branch, prefix)
                properties.update(child_props)
                required.update(child_required)
    for keyword in ("if", "then", "else"):
        child_props, child_required = _schema_paths(schema.get(keyword), prefix)
        properties.update(child_props)
        required.update(child_required)
    return properties, required


def _rename_paths(paths: set[str], mapping: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        parts = path.split(".")
        renamed = []
        for part in parts:
            suffix = "[]" if part.endswith("[]") else ""
            base = part[:-2] if suffix else part
            renamed.append(mapping.get(base, base) + suffix)
        out.add(".".join(renamed))
    return out


def _contract_closure(profile_id: str) -> dict[str, dict[str, str]]:
    profile = get_profile(profile_id)
    version = profile.delta_schema_version
    canonical = SCHEMA_REGISTRY.get(version, {})
    persisted = PERSISTED_SCHEMA_REGISTRY.get(version, {})
    result: dict[str, dict[str, str]] = {}
    inverse_l4 = {
        provider_name: canonical_name
        for canonical_name, provider_name in method_contracts._L4C_REFERENCE_FIELDS.items()
    }

    for node, canonical_schema in canonical.items():
        wire = provider_schema_for_profile(profile_id, node, version)
        persisted_schema = persisted.get(node)
        wire_status = "CONTRACT_MISMATCH"
        persisted_status = "CONTRACT_MISMATCH"
        binding_status = NA
        if isinstance(wire, dict):
            canonical_props, canonical_required = _schema_paths(canonical_schema)
            wire_props, wire_required = _schema_paths(wire)
            if node == "L4" and profile_id == DEFAULT_NATIVE_PROFILE:
                wire_props = _rename_paths(wire_props, inverse_l4)
                wire_required = _rename_paths(wire_required, inverse_l4)
            if canonical_props <= wire_props and canonical_required <= wire_required:
                wire_status = CLOSED
        if isinstance(persisted_schema, dict):
            canonical_props, canonical_required = _schema_paths(canonical_schema)
            persisted_props, persisted_required = _schema_paths(persisted_schema)
            if canonical_props <= persisted_props and canonical_required <= persisted_required:
                persisted_status = CLOSED

        if node == "L4" and profile_id == DEFAULT_NATIVE_PROFILE:
            wire_candidate = (
                wire.get("properties", {}).get("method_candidates", {}).get("items", {})
                if isinstance(wire, dict) else {}
            )
            canonical_candidate = canonical_schema.get("properties", {}).get(
                "method_candidates", {}
            ).get("items", {})
            wire_fields = set(wire_candidate.get("properties", {}))
            canonical_fields = set(canonical_candidate.get("properties", {}))
            mapping_ok = all(
                provider_name in wire_fields
                and canonical_name not in wire_fields
                and canonical_name in canonical_fields
                and provider_name not in canonical_fields
                for canonical_name, provider_name
                in method_contracts._L4C_REFERENCE_FIELDS.items()
            )
            binding_status = (
                CLOSED if mapping_ok
                and callable(l4_evidence_bundle.resolve_l4c_reference_handles)
                else "CONTRACT_MISMATCH"
            )

        result[node] = {
            "wire": wire_status,
            "binding": binding_status,
            "persisted": persisted_status,
        }
    return result


def _authority_closure(node_map: dict[str, dict]) -> tuple[dict[str, str], list[dict]]:
    statuses = {node: CLOSED for node in node_map}
    unresolved: list[dict] = []

    for name, spec in AUTHORITY_REGISTRY.items():
        producer = node_map.get(spec.producer)
        producer_ok = (
            producer is not None
            and name in (producer.get("produces_authorities") or [])
        )
        schema_ok = not (
            name == "current_round_data_binding"
            and spec.schema_version != l0_data.DATA_BINDING_SCHEMA
        )
        if not producer_ok or not schema_ok:
            status = "NO_PRODUCER" if producer is None else "TYPE_MISMATCH"
            unresolved.append({
                "authority": name,
                "node": spec.producer,
                "status": status,
            })
            if producer is not None:
                statuses[spec.producer] = status

        allowed = spec.context_consumers | spec.execution_consumers
        for consumer in sorted(allowed):
            node = node_map.get(consumer)
            if node is None:
                unresolved.append({
                    "authority": name, "node": consumer, "status": "UNREACHABLE"
                })
                continue
            if name not in (node.get("requires_authorities") or []):
                statuses[consumer] = "UNBOUND"
                unresolved.append({
                    "authority": name, "node": consumer, "status": "UNBOUND"
                })

    for node_id, node in node_map.items():
        for name in node.get("requires_authorities") or []:
            spec = AUTHORITY_REGISTRY.get(name)
            if spec is None:
                statuses[node_id] = "NO_PRODUCER"
                unresolved.append({
                    "authority": name, "node": node_id, "status": "NO_PRODUCER"
                })
                continue
            if node_id not in (spec.context_consumers | spec.execution_consumers):
                statuses[node_id] = "UNAUTHORIZED"
                unresolved.append({
                    "authority": name, "node": node_id, "status": "UNAUTHORIZED"
                })
    return statuses, unresolved


def _context_dependency_closure(node_map: dict[str, dict], sequence: list[str]) -> tuple[dict[str, str], list[dict]]:
    statuses = {node: CLOSED for node in node_map}
    unresolved: list[dict] = []
    order = [item for item in sequence if item in node_map]
    positions = {node: index for index, node in enumerate(order)}
    specials = {"candidate_frontmatter", "ALL"}

    for node_id, node in node_map.items():
        for dependency in node.get("context_inputs") or []:
            if dependency in specials:
                continue
            if dependency not in node_map:
                statuses[node_id] = "NO_PRODUCER"
                unresolved.append({
                    "node": node_id,
                    "dependency": dependency,
                    "status": "NO_PRODUCER",
                })
                continue
            if positions.get(dependency, -1) >= positions.get(node_id, 10**6):
                statuses[node_id] = "UNREACHABLE"
                unresolved.append({
                    "node": node_id,
                    "dependency": dependency,
                    "status": "UNREACHABLE",
                })
    return statuses, unresolved


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _called_names(function: ast.FunctionDef | None) -> list[str]:
    if function is None:
        return []
    names: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _source_tree(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _execution_receipt_closure() -> dict[str, Any]:
    required_fields = {
        "exit_code", "timed_out", "terminal_state", "execution_status"
    }
    dataclass_fields = {field.name for field in dataclasses.fields(RunReceipt)}
    run_loop_path = Path(__file__).resolve().parents[1] / "run_loop.py"
    tree = _source_tree(run_loop_path)
    writer = _function(tree, "write_receipt") if tree else None
    failure_writer = _function(tree, "_write_provider_failure_receipt") if tree else None

    writer_keywords: set[str] = set()
    if writer is not None:
        for node in ast.walk(writer):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = target.attr if isinstance(target, ast.Attribute) else (
                target.id if isinstance(target, ast.Name) else ""
            )
            if name == "RunReceipt":
                writer_keywords.update(
                    keyword.arg for keyword in node.keywords if keyword.arg
                )
    failure_calls = _called_names(failure_writer)
    failure_has_status = False
    if failure_writer is not None:
        for node in ast.walk(failure_writer):
            if isinstance(node, ast.Call):
                target = node.func
                name = target.id if isinstance(target, ast.Name) else (
                    target.attr if isinstance(target, ast.Attribute) else ""
                )
                if name != "write_receipt":
                    continue
                for keyword in node.keywords:
                    if (keyword.arg == "execution_status"
                            and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value == "failed"):
                        failure_has_status = True

    checks = {
        "receipt_fields": required_fields <= dataclass_fields,
        "runtime_to_receipt_binding": required_fields <= writer_keywords,
        "failure_receipt": "write_receipt" in failure_calls and failure_has_status,
    }
    return {
        **checks,
        "overall": CLOSED if all(checks.values()) else "CONTRACT_MISMATCH",
    }


def _state_recovery_closure() -> dict[str, Any]:
    run_loop_path = Path(__file__).resolve().parents[1] / "run_loop.py"
    tree = _source_tree(run_loop_path)
    run_round = _function(tree, "run_round") if tree else None
    recover = _function(tree, "_recover_committed_advance") if tree else None
    round_calls = _called_names(run_round)
    recover_calls = _called_names(recover)

    try:
        recover_index = round_calls.index("_recover_committed_advance")
        dispatch_indexes = [
            round_calls.index(name) for name in ("exec_cognitive", "exec_turing")
            if name in round_calls
        ]
        recovery_before_dispatch = bool(dispatch_indexes) and all(
            recover_index < index for index in dispatch_indexes
        )
    except ValueError:
        recovery_before_dispatch = False

    recovery_only_advances = (
        "advance" in recover_calls
        and "provider_for" not in recover_calls
        and "exec_cognitive" not in recover_calls
        and "exec_turing" not in recover_calls
    )
    checks = {
        "recovery_hook": recover is not None,
        "recovery_before_provider_dispatch": recovery_before_dispatch,
        "committed_recovery_is_advance_only": recovery_only_advances,
    }
    return {
        **checks,
        "overall": CLOSED if all(checks.values()) else "CONTRACT_MISMATCH",
    }


def _execution_authority_consumer_closed() -> bool:
    path = Path(__file__).resolve().parent / "commands" / "execution.py"
    tree = _source_tree(path)
    function = _function(tree, "_bound_local_inputs") if tree else None
    calls = _called_names(function)
    return "resolve_authority" in calls


def audit_static_closure(profile_id: str = DEFAULT_NATIVE_PROFILE) -> dict[str, Any]:
    """Audit static native dependency closure without running a provider."""
    profile = get_profile(profile_id)
    nodes, node_map, sequence = topology_for_profile(profile_id)
    contracts = _contract_closure(profile_id)
    context_status, context_unresolved = _context_dependency_closure(
        node_map, sequence
    )
    authority_status, authority_unresolved = _authority_closure(node_map)
    unresolved = [*context_unresolved, *authority_unresolved]

    if profile_id == DEFAULT_NATIVE_PROFILE and not _execution_authority_consumer_closed():
        authority_status["L7"] = "UNREACHABLE"
        unresolved.append({
            "authority": "current_round_data_binding",
            "node": "L7",
            "status": "UNREACHABLE",
            "detail": "execution consumer bypasses the generic authority resolver",
        })

    node_rows: dict[str, dict[str, str]] = {}
    for item in nodes:
        node = item["node"]
        contract = contracts.get(node)
        contract_status = CLOSED
        if contract:
            if contract["wire"] != CLOSED or contract["persisted"] != CLOSED:
                contract_status = "CONTRACT_MISMATCH"
            if contract["binding"] not in {CLOSED, NA}:
                contract_status = "CONTRACT_MISMATCH"
        statuses = [context_status[node], authority_status[node], contract_status]
        overall = CLOSED if all(status == CLOSED for status in statuses) else next(
            status for status in statuses if status != CLOSED
        )
        node_rows[node] = {
            "context_dependencies": context_status[node],
            "authorities": authority_status[node],
            "contracts": contract_status,
            "overall": overall,
        }
        if overall != CLOSED and not any(
            row.get("node") == node for row in unresolved
        ):
            unresolved.append({"node": node, "status": overall})

    execution_receipt = _execution_receipt_closure()
    state_recovery = _state_recovery_closure()
    if execution_receipt["overall"] != CLOSED:
        unresolved.append({
            "node": "provider_runtime",
            "status": execution_receipt["overall"],
        })
    if state_recovery["overall"] != CLOSED:
        unresolved.append({
            "node": "state_recovery",
            "status": state_recovery["overall"],
        })

    return {
        "schema_version": "PreE2EClosureReport/v1",
        "profile_id": profile.profile_id,
        "nodes": node_rows,
        "contract_transforms": contracts,
        "execution_receipt": execution_receipt,
        "state_recovery": state_recovery,
        "unresolved_required_paths": unresolved,
        "e2e_start_allowed": not unresolved,
    }
