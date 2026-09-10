"""Deterministic authorization projection for scientific data in one RLR round.

This module is deliberately not a registry.  It projects the authoritative
current L0 declaration plus the already-verified previous-round evidence
binding into the exact data references consumers may use in the current round.
Large files are never copied here; local file identity is path + SHA-256.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from research_loop import l0_contract, l0_plan_intake
from research_loop.hypothesis_ledger import binding_path
from research_loop.l0_state import (
    EVIDENCE_BINDING_SCHEMA,
    _hash_path,
    _project_identity,
    _resolve_registered_path,
    _stored_path,
)
from research_loop.paths import _candidate_file
from research_loop.yamlio import _load_yaml_front


DATA_BINDING_SCHEMA = "CurrentRoundDataBinding/v1"
ELIGIBLE_INHERITED_CLASSES = {"source", "intermediate", "result"}


class L0DataError(RuntimeError):
    """Fail-closed current-round data authorization error."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def current_round_data_binding_path(project_dir, cand_id) -> Path:
    return (Path(project_dir) / "08_Audit" / "l0_data" /
            f"{cand_id}_current_round_data_binding.json")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_local(project: Path, value: str) -> Path:
    return _resolve_registered_path(project, value)


def _validate_contract(project: Path, cand_id: str) -> tuple[dict, Path, bytes, dict]:
    contract, contract_path, raw = l0_contract.load_contract(project, cand_id)
    if contract is None or raw is None:
        raise L0DataError("L0_DATA_CONTRACT_INVALID", f"missing/unreadable contract: {contract_path}")
    cf = _candidate_file(project, cand_id)
    fm = _load_yaml_front(cf) if cf.is_file() else {}
    errors = l0_contract.validate_l0_input_contract(
        contract, fm, project, cand_id, artifact_path=contract_path, raw_bytes=raw)
    if errors:
        raise L0DataError("L0_DATA_CONTRACT_INVALID", errors[0])
    return contract, Path(contract_path), raw, fm


def _current_file_records(project: Path, source: dict | None) -> tuple[list[dict], list[dict]]:
    if not isinstance(source, dict):
        return [], []

    manifest = source.get("file_manifest")
    records: list[dict] = []
    non_files: list[dict] = []
    description = str(source.get("description") or "current-round source")

    if isinstance(manifest, list) and manifest:
        for index, entry in enumerate(manifest):
            if not isinstance(entry, dict):
                raise L0DataError(
                    "L0_DATA_CURRENT_MANIFEST_INVALID",
                    f"source_input.file_manifest[{index}] must be a mapping",
                )
            value = str(entry.get("path") or "")
            if not value:
                raise L0DataError(
                    "L0_DATA_CURRENT_MANIFEST_INVALID",
                    f"source_input.file_manifest[{index}].path is missing",
                )
            path = _resolve_local(project, value)
            if not path.is_file():
                raise L0DataError("L0_DATA_CURRENT_MISSING", value)
            actual = _hash_path(path)
            expected = str(entry.get("sha256") or "")
            if expected and actual != expected:
                raise L0DataError(
                    "L0_DATA_CURRENT_HASH_MISMATCH",
                    f"{value}: expected={expected} actual={actual}",
                )
            declared_bytes = entry.get("bytes")
            if declared_bytes is not None and int(declared_bytes) != path.stat().st_size:
                raise L0DataError(
                    "L0_DATA_CURRENT_SIZE_MISMATCH",
                    f"{value}: expected={declared_bytes} actual={path.stat().st_size}",
                )
            records.append({
                "path": _stored_path(project, path),
                "sha256": actual,
                "bytes": path.stat().st_size,
                "role": str(entry.get("role") or "current_source"),
                "origin": "current_round",
                "reason": description,
            })
        return records, non_files

    raw_paths = list(source.get("files") or [])
    if not raw_paths and source.get("input_type") in {"files", "directory"} and source.get("location"):
        raw_paths = [source["location"]]
    for value in raw_paths:
        path = _resolve_local(project, str(value))
        if path.is_dir():
            for child in sorted(p for p in path.rglob("*") if p.is_file()):
                records.append({
                    "path": _stored_path(project, child),
                    "sha256": _hash_path(child),
                    "bytes": child.stat().st_size,
                    "role": "current_source",
                    "origin": "current_round",
                    "reason": description,
                })
            continue
        if not path.is_file():
            raise L0DataError("L0_DATA_CURRENT_MISSING", str(value))
        records.append({
            "path": _stored_path(project, path),
            "sha256": _hash_path(path),
            "bytes": path.stat().st_size,
            "role": "current_source",
            "origin": "current_round",
            "reason": description,
        })

    # Keep the binding vocabulary aligned with the authoritative L0 contract.
    # dataset/inline/other are all legal non-file source types.  Represent them
    # here rather than rejecting a contract that the declaration validator has
    # already accepted.  L7 remains a separate consumer boundary and requires
    # regular files before execution.
    input_type = str(source.get("input_type") or "")
    if input_type in {"dataset", "inline", "other"} and not raw_paths:
        non_files.append({
            "origin": "current_round",
            "kind": input_type,
            "location": str(source.get("location") or ""),
            "role": input_type,
            "description": description,
            "verification_status": str(source.get("verification_status") or ""),
            "reason": str(source.get("reason") or ""),
        })
    return records, non_files


def _canonical_source_path(value: str | Path) -> str:
    """Reuse structured-intake path normalization for authority joins."""
    _resolved, normalized = l0_plan_intake._normalize_path(str(value))
    return normalized


def _manifest_identity(manifest: Any) -> tuple | None:
    """Return the order-independent byte identity of a verified file manifest."""
    if not isinstance(manifest, list):
        return None
    rows = []
    for item in manifest:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return None
        try:
            normalized_path = _canonical_source_path(item["path"])
        except (OSError, RuntimeError, ValueError):
            return None
        rows.append(
            (
                str(item.get("role") or ""),
                normalized_path,
                str(item.get("bytes") or ""),
                str(item.get("sha256") or ""),
            )
        )
    return tuple(sorted(rows))


def _upstream_snapshot(project: Path, contract: dict) -> dict | None:
    """Verify the byte-frozen plan snapshot before trusting its declaration."""
    if "upstream_completed_inputs" not in contract:
        return None
    provenance = contract.get("provenance")
    if not isinstance(provenance, dict):
        raise L0DataError(
            "L0_DATA_UPSTREAM_PLAN_INVALID",
            "typed upstream authority requires contract provenance",
        )
    stored_value = str(provenance.get("research_plan_snapshot_path") or "")
    expected_hash = str(provenance.get("research_plan_snapshot_sha256") or "")
    if not stored_value:
        raise L0DataError(
            "L0_DATA_UPSTREAM_PLAN_INVALID",
            "provenance.research_plan_snapshot_path is missing",
        )
    path = _resolve_local(project, stored_value)
    if not path.is_file():
        raise L0DataError("L0_DATA_UPSTREAM_PLAN_MISSING", str(path))
    raw = path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash:
        raise L0DataError(
            "L0_DATA_UPSTREAM_PLAN_HASH_MISMATCH",
            f"{stored_value}: expected={expected_hash} actual={actual_hash}",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise L0DataError(
            "L0_DATA_UPSTREAM_PLAN_INVALID",
            f"snapshot is not valid UTF-8: {exc}",
        ) from exc
    parsed, errors = l0_plan_intake.parse_plan_text_strict(text)
    if errors:
        raise L0DataError(
            "L0_DATA_UPSTREAM_PLAN_INVALID",
            "; ".join(errors),
        )
    declared = l0_plan_intake.extract_upstream_completed_inputs(
        parsed.get("research_plan") if isinstance(parsed, dict) else None
    )
    if declared != contract.get("upstream_completed_inputs"):
        raise L0DataError(
            "L0_DATA_UPSTREAM_PLAN_MISMATCH",
            "snapshot upstream_completed_inputs differs from the L0 contract",
        )
    snapshot_source = parsed.get("source_input") if isinstance(parsed, dict) else None
    contract_source = contract.get("source_input")
    snapshot_manifest = (
        snapshot_source.get("file_manifest")
        if isinstance(snapshot_source, dict)
        else None
    )
    contract_manifest = (
        contract_source.get("file_manifest")
        if isinstance(contract_source, dict)
        else None
    )
    if _manifest_identity(snapshot_manifest) != _manifest_identity(contract_manifest):
        raise L0DataError(
            "L0_DATA_UPSTREAM_PLAN_MISMATCH",
            "snapshot source_input.file_manifest differs from the L0 contract",
        )
    return {
        "path": _stored_path(project, path),
        "bytes": len(raw),
        "sha256": actual_hash,
    }


def _read_feature_ids(path: Path, role: str, key: str) -> tuple[list[str], int]:
    """Read only feature identifiers and row count; never rewrite source data."""
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = csv.reader(handle, delimiter="\t")
            header = next(rows, None)
            if not header or header[0] != key or len(header) < 2:
                raise L0DataError(
                    "L0_DATA_FEATURE_SPACE_MISMATCH",
                    f"{role}: expected a tabular header beginning with {key!r} and at least one data column",
                )
            identifiers: list[str] = []
            seen: set[str] = set()
            for line_number, row in enumerate(rows, start=2):
                if not row or not row[0]:
                    raise L0DataError(
                        "L0_DATA_FEATURE_SPACE_MISMATCH",
                        f"{role}: empty feature identifier at line {line_number}",
                    )
                identifier = row[0]
                if identifier in seen:
                    raise L0DataError(
                        "L0_DATA_FEATURE_SPACE_MISMATCH",
                        f"{role}: duplicate feature identifier {identifier!r}",
                    )
                seen.add(identifier)
                identifiers.append(identifier)
    except OSError as exc:
        raise L0DataError(
            "L0_DATA_FEATURE_SPACE_MISMATCH",
            f"{role}: cannot read {path}: {exc}",
        ) from exc
    except UnicodeDecodeError as exc:
        raise L0DataError(
            "L0_DATA_FEATURE_SPACE_MISMATCH",
            f"{role}: source is not valid UTF-8: {exc}",
        ) from exc
    return identifiers, len(identifiers)


def _bind_upstream_completed_inputs(
    project: Path,
    contract: dict,
    current_records: list[dict],
) -> dict | None:
    """Build the typed projection inside the one canonical L0 data binding."""
    if "upstream_completed_inputs" not in contract:
        return None

    snapshot = _upstream_snapshot(project, contract)
    declared = contract["upstream_completed_inputs"]
    orthology = declared["orthology"]
    feature = orthology["feature_space"]
    key = feature["key"]
    expected_rows = feature["rows"]

    records_by_key = {}
    for record in current_records:
        records_by_key[
            (_canonical_source_path(record["path"]), str(record.get("role") or ""))
        ] = record

    source_files: list[dict] = []
    observed_rows: dict[str, int] = {}
    row_orders: dict[str, list[str]] = {}
    aligned = feature["aligned_source_files"]
    for role in l0_contract.ORTHOLOGY_SOURCE_ROLES:
        item = next(
            (candidate for candidate in aligned if candidate.get("role") == role),
            None,
        )
        if item is None:
            raise L0DataError(
                "L0_DATA_UPSTREAM_SOURCE_NOT_BOUND",
                f"missing aligned source declaration for role {role!r}",
            )
        source_path = _resolve_local(project, str(item["path"]))
        record = records_by_key.get(
            (_canonical_source_path(source_path), role)
        )
        if record is None or record.get("origin") != "current_round":
            raise L0DataError(
                "L0_DATA_UPSTREAM_SOURCE_NOT_BOUND",
                f"{role}: {item['path']!r} is not an authorized current-round source",
            )
        identifiers, row_count = _read_feature_ids(source_path, role, key)
        observed_rows[role] = row_count
        row_orders[role] = identifiers
        source_files.append({
            "path": record["path"],
            "bytes": record["bytes"],
            "sha256": record["sha256"],
            "role": role,
            "origin": record.get("origin", "current_round"),
            "reason": record.get("reason", ""),
        })

    if any(value != expected_rows for value in observed_rows.values()):
        raise L0DataError(
            "L0_DATA_FEATURE_SPACE_MISMATCH",
            f"declared rows={expected_rows} observed={observed_rows}",
        )
    baseline = row_orders[l0_contract.ORTHOLOGY_SOURCE_ROLES[0]]
    if any(order != baseline for order in row_orders.values()):
        raise L0DataError(
            "L0_DATA_FEATURE_SPACE_MISMATCH",
            "aligned source files do not have identical feature row order",
        )

    return {
        "orthology": {
            "status": orthology["status"],
            "method": orthology["method"],
            "policy": orthology["policy"],
            "orthogroup_count": orthology["orthogroup_count"],
            "species_tree": orthology["species_tree"],
            "formal_species": list(orthology["formal_species"]),
            "feature_space": {
                "key": key,
                "rows": expected_rows,
                "source_files": source_files,
                "validation": {
                    "observed_rows": {
                        role: observed_rows[role]
                        for role in l0_contract.ORTHOLOGY_SOURCE_ROLES
                    },
                    "row_order_matches": True,
                },
            },
        },
        "source_preplan": snapshot,
    }


def _verified_index(evidence_binding: dict | None) -> tuple[dict[tuple[str, str], dict], dict[str, list[dict]]]:
    exact: dict[tuple[str, str], dict] = {}
    by_path: dict[str, list[dict]] = {}
    if not isinstance(evidence_binding, dict):
        return exact, by_path
    for item in evidence_binding.get("verified_artifacts") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        digest = str(item.get("sha256") or "")
        if not path or not digest:
            continue
        exact[(path, digest)] = item
        by_path.setdefault(path, []).append(item)
    return exact, by_path


def _inherited_records(project: Path, contract: dict, evidence_binding: dict | None) -> list[dict]:
    selectors = contract.get("inherited_inputs") or []
    if not selectors:
        return []
    if not isinstance(evidence_binding, dict) or evidence_binding.get("schema_version") != EVIDENCE_BINDING_SCHEMA:
        raise L0DataError("L0_DATA_EVIDENCE_BINDING_REQUIRED", "continuation inherited_inputs require L0EvidenceBinding/v1")
    if evidence_binding.get("binding_status") != "PASS":
        raise L0DataError("L0_DATA_EVIDENCE_BINDING_REQUIRED", "previous-round evidence binding did not PASS")

    exact, by_path = _verified_index(evidence_binding)
    out: list[dict] = []
    for selector in selectors:
        path_value = str(selector.get("path") or "")
        digest = str(selector.get("sha256") or "")
        item = exact.get((path_value, digest))
        if item is None:
            if path_value in by_path:
                raise L0DataError(
                    "L0_DATA_INHERITED_NOT_VERIFIED",
                    f"verified path exists but selector hash differs: {path_value}",
                )
            raise L0DataError(
                "L0_DATA_INHERITED_NOT_VERIFIED",
                f"selector is absent from verified previous-round artifacts: {path_value}",
            )
        klass = str(item.get("class") or "")
        if klass not in ELIGIBLE_INHERITED_CLASSES:
            raise L0DataError(
                "L0_DATA_INHERITED_CLASS_FORBIDDEN",
                f"{path_value}: class={klass!r}; allowed={sorted(ELIGIBLE_INHERITED_CLASSES)}",
            )
        path = _resolve_local(project, path_value)
        if not path.exists():
            raise L0DataError("L0_DATA_INHERITED_MISSING", path_value)
        actual = _hash_path(path)
        if actual != digest:
            raise L0DataError(
                "L0_DATA_INHERITED_HASH_MISMATCH",
                f"{path_value}: expected={digest} actual={actual}",
            )
        out.append({
            "path": path_value,
            "sha256": digest,
            "bytes": path.stat().st_size if path.is_file() else None,
            "role": str(selector.get("role") or "inherited"),
            "origin": "inherited",
            "reason": str(selector.get("reuse_reason") or ""),
            "artifact_id": str(item.get("artifact_id") or ""),
            "artifact_class": klass,
            "source_candidate_id": str(evidence_binding.get("previous_candidate_id") or ""),
            "source_round_id": str(evidence_binding.get("previous_round_id") or ""),
        })
    return out


def _deduplicate(records: list[dict]) -> list[dict]:
    by_path: dict[str, dict] = {}
    for item in records:
        path = str(item["path"])
        existing = by_path.get(path)
        if existing is None:
            by_path[path] = item
            continue
        if existing.get("sha256") != item.get("sha256"):
            raise L0DataError(
                "L0_DATA_PATH_HASH_CONFLICT",
                f"{path}: {existing.get('sha256')} != {item.get('sha256')}",
            )
        # One physical object may be both newly declared and explicitly inherited
        # only if byte identity is exact. Prefer the current-round declaration as
        # the direct authority and retain no duplicate staging record.
        if existing.get("origin") == "inherited" and item.get("origin") == "current_round":
            by_path[path] = item
    return [by_path[key] for key in sorted(by_path)]


def build_current_round_data_binding(project_dir, cand_id, evidence_binding=None) -> dict:
    project = Path(project_dir)
    contract, contract_path, raw, _fm = _validate_contract(project, str(cand_id))
    current, non_files = _current_file_records(project, contract.get("source_input"))
    inherited = _inherited_records(project, contract, evidence_binding)
    authorized = _deduplicate(current + inherited)
    upstream_completed_inputs = _bind_upstream_completed_inputs(
        project, contract, current
    )

    if not authorized and not non_files:
        raise L0DataError(
            "L0_DATA_NO_AUTHORIZED_INPUTS",
            "current round has neither local authorized files nor a declared non-file input",
        )

    payload: dict[str, Any] = {
        "schema_version": DATA_BINDING_SCHEMA,
        "project_id": _project_identity(project),
        "candidate_id": str(cand_id),
        "round_id": str(contract.get("round_id") or ""),
        "round_type": str(contract.get("round_type") or ""),
        "l0_contract_path": _stored_path(project, contract_path),
        "l0_contract_sha256": hashlib.sha256(raw).hexdigest(),
        "authorized_inputs": authorized,
        "non_file_inputs": non_files,
    }
    if upstream_completed_inputs is not None:
        payload["upstream_completed_inputs"] = upstream_completed_inputs

    if inherited:
        evidence_path = (project / "08_Audit" / "l0_restore" /
                         f"{cand_id}_evidence_binding.json")
        payload.update({
            "previous_evidence_binding_path": _stored_path(project, evidence_path),
            "previous_evidence_binding_sha256": (
                _sha_file(evidence_path) if evidence_path.is_file() else ""
            ),
            "previous_candidate_id": str(evidence_binding.get("previous_candidate_id") or ""),
            "previous_round_id": str(evidence_binding.get("previous_round_id") or ""),
        })
    return payload


def write_current_round_data_binding(project_dir, cand_id, evidence_binding=None) -> tuple[Path, str]:
    project = Path(project_dir)
    payload = build_current_round_data_binding(project, cand_id, evidence_binding)
    path = current_round_data_binding_path(project, cand_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _canonical_json(payload)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise L0DataError("L0_DATA_BINDING_COLLISION", f"existing binding differs: {path}")
    else:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    return path, _sha_file(path)


def recover_current_round_data_binding(project_dir, cand_id, evidence_binding,
                                       *, expected_old_contract_sha256: str) -> tuple[Path, str]:
    """Refresh an empty derived binding during explicit continuation recovery.

    Normal creation remains collision-protected by
    :func:`write_current_round_data_binding`.  This narrowly scoped operation
    is callable only by the auditable defective-continuation recovery path: the
    existing binding must still point at the old contract and must authorize no
    files.  A binding with authorized inputs is evidence that the candidate has
    progressed and is therefore immutable here.
    """
    project = Path(project_dir)
    path = current_round_data_binding_path(project, cand_id)
    existing = load_current_round_data_binding(project, cand_id)
    if existing.get("l0_contract_sha256") != expected_old_contract_sha256:
        raise L0DataError(
            "L0_DATA_RECOVERY_BINDING_MISMATCH",
            "existing CurrentRoundDataBinding does not point at the defective contract",
        )
    if existing.get("authorized_inputs"):
        raise L0DataError(
            "L0_DATA_RECOVERY_PROGRESS_FORBIDDEN",
            "existing CurrentRoundDataBinding already authorizes local inputs",
        )
    payload = build_current_round_data_binding(project, cand_id, evidence_binding)
    text = _canonical_json(payload)
    path.write_text(text, encoding="utf-8")
    return path, _sha_file(path)


def load_current_round_data_binding(project_dir, cand_id) -> dict:
    path = current_round_data_binding_path(project_dir, cand_id)
    if not path.is_file():
        raise L0DataError("L0_DATA_BINDING_MISSING", str(path))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise L0DataError("L0_DATA_BINDING_INVALID", str(exc)) from exc
    if not isinstance(value, dict) or value.get("schema_version") != DATA_BINDING_SCHEMA:
        raise L0DataError("L0_DATA_BINDING_INVALID", f"expected {DATA_BINDING_SCHEMA}")
    return value


def verify_current_round_data_binding(project_dir, cand_id) -> dict:
    project = Path(project_dir)
    binding = load_current_round_data_binding(project, cand_id)
    if binding.get("project_id") != _project_identity(project):
        raise L0DataError("L0_DATA_BINDING_IDENTITY_MISMATCH", "project_id mismatch")
    if str(binding.get("candidate_id")) != str(cand_id):
        raise L0DataError("L0_DATA_BINDING_IDENTITY_MISMATCH", "candidate_id mismatch")

    contract, contract_path, raw, _fm = _validate_contract(project, str(cand_id))
    if binding.get("l0_contract_path") != _stored_path(project, contract_path):
        raise L0DataError("L0_DATA_BINDING_CONTRACT_MISMATCH", "L0 contract path changed")
    actual_contract_hash = hashlib.sha256(raw).hexdigest()
    if binding.get("l0_contract_sha256") != actual_contract_hash:
        raise L0DataError("L0_DATA_BINDING_CONTRACT_MISMATCH", "L0 contract hash changed")
    if str(binding.get("round_id")) != str(contract.get("round_id")):
        raise L0DataError("L0_DATA_BINDING_IDENTITY_MISMATCH", "round_id mismatch")

    current, _non_files = _current_file_records(project, contract.get("source_input"))
    expected_upstream = _bind_upstream_completed_inputs(
        project, contract, current
    )
    if expected_upstream is None:
        if "upstream_completed_inputs" in binding:
            raise L0DataError(
                "L0_DATA_UPSTREAM_BINDING_MISMATCH",
                "binding contains typed upstream authority absent from the contract",
            )
    elif binding.get("upstream_completed_inputs") != expected_upstream:
        raise L0DataError(
            "L0_DATA_UPSTREAM_BINDING_MISMATCH",
            "typed upstream authority changed after the current-round binding was written",
        )

    evidence_path_value = str(binding.get("previous_evidence_binding_path") or "")
    if evidence_path_value:
        evidence_path = _resolve_local(project, evidence_path_value)
        if not evidence_path.is_file():
            raise L0DataError("L0_DATA_EVIDENCE_BINDING_CHANGED", str(evidence_path))
        expected = str(binding.get("previous_evidence_binding_sha256") or "")
        if not expected or _sha_file(evidence_path) != expected:
            raise L0DataError("L0_DATA_EVIDENCE_BINDING_CHANGED", "previous evidence binding hash changed")

    for item in binding.get("authorized_inputs") or []:
        path = _resolve_local(project, str(item.get("path") or ""))
        if not path.exists():
            raise L0DataError("L0_DATA_BOUND_INPUT_MISSING", str(item.get("path") or ""))
        actual = _hash_path(path)
        if actual != item.get("sha256"):
            raise L0DataError(
                "L0_DATA_BOUND_INPUT_HASH_MISMATCH",
                f"{item.get('path')}: expected={item.get('sha256')} actual={actual}",
            )
    return binding
