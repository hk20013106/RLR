"""Deterministic L0 cross-round evidence state.

Owns the physical evidence continuity contract only. Scientific interpretation
stays in cognitive nodes; current-round input validation stays in l0_contract.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from research_loop import l0_contract
from research_loop.compatibility import PROFILE_V20, get_profile
from research_loop.delta import _delta_for_candidate, artifact_for_node
from research_loop.hypothesis_ledger import binding_path
from research_loop.paths import _candidate_file
from research_loop.topology import DELTA_DAG_ORDER
from research_loop.yamlio import _load_yaml_front

ROUND_MANIFEST_SCHEMA = "RLRRoundEvidenceManifest/v1"
EVIDENCE_BINDING_SCHEMA = "L0EvidenceBinding/v1"


class L0StateError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_path(path: Path) -> str:
    if path.is_file():
        return _sha_bytes(path.read_bytes())
    if path.is_dir():
        h = hashlib.sha256()
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            rel = child.relative_to(path).as_posix().encode("utf-8")
            h.update(rel)
            h.update(b"\0")
            h.update(child.read_bytes())
            h.update(b"\0")
        return h.hexdigest()
    raise FileNotFoundError(path)


def _project_identity(project_dir: Path) -> str:
    binding = binding_path(project_dir)
    if binding.is_file():
        try:
            value = json.loads(binding.read_text(encoding="utf-8"))
            if value.get("project_id"):
                return str(value["project_id"])
        except (OSError, json.JSONDecodeError):
            pass
    return project_dir.resolve().name


def _project_profile(project_dir: Path):
    binding = binding_path(project_dir)
    if not binding.is_file():
        return get_profile(PROFILE_V20)
    try:
        value = json.loads(binding.read_text(encoding="utf-8"))
        return get_profile(str(value.get("profile_id") or PROFILE_V20))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise L0StateError("L0_ROUND_MANIFEST_PROFILE_INVALID", str(exc)) from exc


def _profile_delta_keys(project_dir: Path) -> list[str]:
    """Authoritative candidate delta keys for the project's immutable profile."""
    profile = _project_profile(project_dir)
    keys = []
    for key in DELTA_DAG_ORDER:
        storage_key = (artifact_for_node(profile, "L8").storage_key
                       if key == "L8_curie" else key)
        if storage_key not in keys:
            keys.append(storage_key)
    return keys


def _resolve_registered_path(project_dir: Path, value: str | Path) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    return project_dir / p


def _stored_path(project_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _artifact(project_dir: Path, path: Path, klass: str, *, producer_node: str = "",
              producer_receipt: str = "", created_in_round: str = "") -> dict:
    if not path.exists():
        raise L0StateError("L0_ROUND_MANIFEST_ARTIFACT_MISSING",
                           f"cannot register missing artifact: {path}")
    stored = _stored_path(project_dir, path)
    aid = hashlib.sha256(f"{klass}:{stored}".encode("utf-8")).hexdigest()[:20]
    return {
        "artifact_id": aid,
        "class": klass,
        "path": stored,
        "sha256": _hash_path(path),
        "producer_node": producer_node,
        "producer_receipt": producer_receipt,
        "created_in_round": str(created_in_round),
    }


def _input_contract_path(project_dir: Path, cand_id: str) -> Path | None:
    """Return the exact current-round L0 contract artifact, if present.

    The contract is itself evidence about how source data entered the round. It
    must therefore be hash-bound alongside the source bytes it registers.
    """
    contract, artifact_path, _raw = l0_contract.load_contract(project_dir, cand_id)
    if not isinstance(contract, dict) or artifact_path is None:
        return None
    path = Path(artifact_path)
    return path if path.is_file() else None


def _source_paths(project_dir: Path, cand_id: str) -> Iterable[Path]:
    contract, _, _ = l0_contract.load_contract(project_dir, cand_id)
    if not isinstance(contract, dict):
        return []
    source = contract.get("source_input") or {}
    paths = list(source.get("files") or [])
    if not paths and source.get("input_type") in ("files", "directory") and source.get("location"):
        paths = [source["location"]]
    return [_resolve_registered_path(project_dir, item) for item in paths]


def _l7_exec_manifest_path(project_dir: Path, cand_id: str) -> Path:
    return project_dir / "04_Analysis_Outputs" / "_exec_manifest" / f"{cand_id}_L7.json"


def _l7_delta_path(project_dir: Path, cand_id: str) -> Path | None:
    """Resolve the canonical L7 declaration used by round-manifest binding.

    Native projects must use the committed v2 delta.  An unbound project is a
    historical read/verification surface, where the candidate-owned v2 path is
    the only compatible declaration available to this evidence builder.
    """
    path = _delta_for_candidate(project_dir, "L7_turing", cand_id)
    if path and path.is_file():
        return path
    if binding_path(project_dir).is_file():
        return None
    compatibility_path = (
        project_dir / "02_Agent_Notes" / "Turing"
        / f"{cand_id}_L7_turing_delta.v2.json"
    )
    return compatibility_path if compatibility_path.is_file() else None


def _load_l7_declaration(project_dir: Path, cand_id: str):
    path = _l7_delta_path(project_dir, cand_id)
    if path is None:
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                           f"invalid L7 delta: {exc}") from exc
    if not isinstance(payload, dict):
        raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                           "L7 delta must be an object")

    workspace_value = payload.get("workspace")
    if workspace_value is None:
        return payload, None
    if not isinstance(workspace_value, str) or not workspace_value.strip():
        raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                           "L7 workspace must be a non-empty path")
    workspace = _resolve_registered_path(project_dir, workspace_value).resolve()
    try:
        workspace.relative_to(project_dir.resolve())
    except ValueError as exc:
        raise L0StateError(
            "L0_ROUND_MANIFEST_AUDIT_INVALID",
            f"L7 workspace is outside the project: {workspace_value}",
        ) from exc
    if not workspace.is_dir():
        raise L0StateError("L0_ROUND_MANIFEST_ARTIFACT_MISSING",
                           f"L7 workspace missing: {workspace}")
    return payload, workspace


def _normalise_l7_path(value) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    normalised = value.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_l7_reference(project_dir: Path, workspace: Path | None,
                          value: str) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        resolved = raw.resolve()
        if workspace is not None and not _path_is_under(resolved, workspace):
            raise L0StateError(
                "L0_ROUND_MANIFEST_AUDIT_INVALID",
                f"L7 absolute artifact path is outside the workspace: {value}",
            )
        return resolved
    if workspace is None:
        return project_dir / raw

    normalised = _normalise_l7_path(value)
    workspace_rel = workspace.relative_to(project_dir.resolve()).as_posix()
    project_roots = {
        "00_Preflight", "01_Candidates", "02_Agent_Notes",
        "04_Analysis_Outputs", "08_Audit", "08_Run_Receipts",
        "09_Literature_Database",
    }
    if (normalised == workspace_rel
            or normalised.startswith(f"{workspace_rel}/")
            or (Path(normalised).parts
                and Path(normalised).parts[0] in project_roots)):
        resolved = project_dir / raw
    else:
        resolved = workspace / raw
    if not _path_is_under(resolved, project_dir):
        raise L0StateError(
            "L0_ROUND_MANIFEST_AUDIT_INVALID",
            f"L7 artifact path escapes the project: {value}",
        )
    if not _path_is_under(resolved, workspace):
        raise L0StateError(
            "L0_ROUND_MANIFEST_AUDIT_INVALID",
            f"L7 artifact path escapes the workspace: {value}",
        )
    return resolved


def _l7_output_paths(project_dir: Path, cand_id: str) -> Iterable[Path]:
    manifest = _l7_exec_manifest_path(project_dir, cand_id)
    if not manifest.is_file():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise L0StateError("L0_ROUND_MANIFEST_RECEIPT_INVALID",
                           f"invalid L7 execution manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise L0StateError("L0_ROUND_MANIFEST_RECEIPT_INVALID",
                           "L7 execution manifest must be an object")
    scripts = payload.get("scripts", [])
    if not isinstance(scripts, list):
        raise L0StateError("L0_ROUND_MANIFEST_RECEIPT_INVALID",
                           "L7 execution manifest scripts must be a list")
    l7_payload, workspace = _load_l7_declaration(project_dir, cand_id)
    result_paths = (_l7_result_paths(project_dir, cand_id)
                    if l7_payload is not None else [])
    out = []
    for script in scripts:
        if not isinstance(script, dict):
            raise L0StateError("L0_ROUND_MANIFEST_RECEIPT_INVALID",
                               "L7 execution script declaration must be an object")
        output_files = script.get("output_files", [])
        if not isinstance(output_files, list):
            raise L0StateError("L0_ROUND_MANIFEST_RECEIPT_INVALID",
                               "L7 output_files must be a list")
        for value in output_files:
            if not isinstance(value, str) or not value.strip():
                raise L0StateError("L0_ROUND_MANIFEST_RECEIPT_INVALID",
                                   "L7 output_files must contain non-empty paths")
            if Path(value).is_absolute():
                matches = [
                    path for path, _hash in result_paths
                    if path.resolve() == Path(value).resolve()
                ]
            else:
                normalised = _normalise_l7_path(value)
                matches = []
                for path, _hash in result_paths:
                    candidates = {
                        _normalise_l7_path(_stored_path(project_dir, path))
                    }
                    if workspace is not None:
                        try:
                            candidates.add(
                                _normalise_l7_path(
                                    path.resolve().relative_to(workspace).as_posix()
                                )
                            )
                        except ValueError:
                            pass
                    if normalised in candidates:
                        matches.append(path)
            unique_matches = {path.resolve() for path in matches}
            if len(unique_matches) > 1:
                raise L0StateError("L0_ROUND_MANIFEST_ARTIFACT_AMBIGUOUS", value)
            out.append(
                matches[0] if matches
                else _resolve_l7_reference(project_dir, workspace, value)
            )
    return out


def _candidate_delta_paths(project_dir: Path, cand_id: str) -> list[tuple[str, Path]]:
    out = []
    for key in _profile_delta_keys(project_dir):
        path = _delta_for_candidate(project_dir, key, cand_id)
        if path and path.is_file():
            out.append((key, path))
    return out


def _l7_result_paths(project_dir: Path, cand_id: str) -> list[tuple[Path, str]]:
    """Return explicit result artifact refs declared by the L7 delta."""
    payload, workspace = _load_l7_declaration(project_dir, cand_id)
    if payload is None:
        return []
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                           "L7 results must be a list")
    if workspace is not None and not results:
        raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                           "workspace-bound L7 delta must declare results")
    out = []
    for result in results:
        if not isinstance(result, dict):
            raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                               "L7 result declaration must be an object")
        refs = result.get("artifact_refs", [])
        if not isinstance(refs, list):
            raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                               "L7 artifact_refs must be a list")
        if workspace is not None and not refs:
            raise L0StateError(
                "L0_ROUND_MANIFEST_AUDIT_INVALID",
                "workspace-bound L7 result must declare artifact_refs",
            )
        for ref in refs:
            if not isinstance(ref, dict) or not ref.get("path"):
                raise L0StateError("L0_ROUND_MANIFEST_AUDIT_INVALID",
                                   "L7 artifact reference must declare a path")
            declared_hash = str(ref.get("sha256") or "")
            if (workspace is not None and
                    (len(declared_hash) != 64 or
                     any(char not in "0123456789abcdef" for char in declared_hash))):
                raise L0StateError(
                    "L0_ROUND_MANIFEST_AUDIT_INVALID",
                    f"workspace-bound L7 artifact has invalid sha256: {ref['path']}",
                )
            artifact_path = _resolve_l7_reference(
                project_dir, workspace, str(ref["path"])
            )
            if declared_hash and artifact_path.exists():
                actual = _hash_path(artifact_path)
                if actual != declared_hash:
                    raise L0StateError(
                        "L0_ROUND_MANIFEST_ARTIFACT_HASH_MISMATCH",
                        f"{ref['path']}: declared={declared_hash} actual={actual}",
                    )
            out.append((artifact_path, declared_hash))
    return out


def _candidate_owned_literature(project_dir: Path, cand_id: str) -> Iterable[Path]:
    root = project_dir / "09_Literature_Database"
    if not root.is_dir():
        return []
    owned = []
    for path in sorted(root.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(value.get("candidate_id") or value.get("cand_id") or "") == str(cand_id):
            owned.append(path)
    return owned


def _candidate_reports(project_dir: Path, cand_id: str) -> Iterable[Path]:
    out = []
    for name in (f"FINAL_REPORT_{cand_id}.md", f"FINAL_REPORT_CN_{cand_id}.md"):
        p = project_dir / name
        if p.is_file():
            out.append(p)
    return out


def _candidate_receipts(project_dir: Path, cand_id: str) -> Iterable[Path]:
    root = project_dir / "08_Run_Receipts" / cand_id
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file())


def build_round_manifest(project_dir, cand_id) -> dict:
    project = Path(project_dir)
    cf = _candidate_file(project, cand_id)
    if not cf.is_file():
        raise L0StateError("L0_ROUND_MANIFEST_CANDIDATE_MISSING", str(cf))
    fm = _load_yaml_front(cf)
    round_id = str(fm.get("round_id") or "1")
    records: dict[str, dict] = {}

    def add(path: Path, klass: str, producer: str = "", producer_receipt: str = ""):
        if not path.exists():
            raise L0StateError("L0_ROUND_MANIFEST_ARTIFACT_MISSING", str(path))
        stored = _stored_path(project, path)
        existing = records.get(stored)
        if existing:
            old_class = existing["class"]
            if old_class == klass:
                if producer and not existing.get("producer_node"):
                    existing["producer_node"] = producer
                if producer_receipt and not existing.get("producer_receipt"):
                    existing["producer_receipt"] = producer_receipt
                return
            # A script output may later be explicitly declared as a scientific
            # result by L7. That is the one intentional class promotion.
            if old_class == "intermediate" and klass == "result":
                records[stored] = _artifact(
                    project, path, "result", producer_node=producer or "L7",
                    producer_receipt=producer_receipt or existing.get("producer_receipt", ""),
                    created_in_round=round_id,
                )
                return
            if old_class == "result" and klass == "intermediate":
                return
            raise L0StateError(
                "L0_ROUND_MANIFEST_CLASS_CONFLICT",
                f"{stored}: registered as both {old_class} and {klass}",
            )
        records[stored] = _artifact(
            project, path, klass, producer_node=producer,
            producer_receipt=producer_receipt, created_in_round=round_id,
        )

    input_contract = _input_contract_path(project, cand_id)
    if input_contract is not None:
        add(input_contract, "audit", "L0")
    for path in _source_paths(project, cand_id):
        add(path, "source", "L0")

    exec_manifest = _l7_exec_manifest_path(project, cand_id)
    exec_receipt = _stored_path(project, exec_manifest) if exec_manifest.is_file() else ""
    if exec_manifest.is_file():
        add(exec_manifest, "audit", "L7")
    for path in _l7_output_paths(project, cand_id):
        add(path, "intermediate", "L7", exec_receipt)
    for path, _declared_hash in _l7_result_paths(project, cand_id):
        add(path, "result", "L7", exec_receipt)

    for delta_key, path in _candidate_delta_paths(project, cand_id):
        add(path, "audit", delta_key.split("_", 1)[0])
    for path in _candidate_reports(project, cand_id):
        add(path, "result", "L10c")
    for path in _candidate_owned_literature(project, cand_id):
        add(path, "literature", "literature")
    for path in _candidate_receipts(project, cand_id):
        add(path, "receipt", "runtime")

    artifacts = sorted(
        records.values(),
        key=lambda item: (item["class"], item["path"], item["artifact_id"]),
    )
    return {
        "schema_version": ROUND_MANIFEST_SCHEMA,
        "project_id": _project_identity(project),
        "candidate_id": str(cand_id),
        "round_id": round_id,
        "artifacts": artifacts,
    }


def round_manifest_path(project_dir, cand_id, round_id=None) -> Path:
    project = Path(project_dir)
    if round_id is None:
        fm = _load_yaml_front(_candidate_file(project, cand_id))
        round_id = str(fm.get("round_id") or "1")
    return project / "08_Audit" / "round_manifests" / f"{cand_id}_round_{round_id}.json"


def _canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_round_manifest(project_dir, cand_id) -> tuple[Path, str]:
    project = Path(project_dir)
    payload = build_round_manifest(project, cand_id)
    path = round_manifest_path(project, cand_id, payload["round_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _canonical_json(payload)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise L0StateError("L0_ROUND_MANIFEST_COLLISION",
                               f"existing manifest differs: {path}")
    else:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    return path, _hash_path(path)


def load_round_manifest(path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise L0StateError("L0_RESTORE_MANIFEST_MISSING", str(p))
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise L0StateError("L0_RESTORE_MANIFEST_SCHEMA_INVALID", str(exc)) from exc
    if not isinstance(value, dict) or value.get("schema_version") != ROUND_MANIFEST_SCHEMA:
        raise L0StateError("L0_RESTORE_MANIFEST_SCHEMA_INVALID",
                           f"expected {ROUND_MANIFEST_SCHEMA}")
    if not isinstance(value.get("artifacts"), list):
        raise L0StateError("L0_RESTORE_MANIFEST_SCHEMA_INVALID", "artifacts must be a list")
    return value


def verify_round_manifest(project_dir, manifest: dict, *, expected_candidate: str,
                          expected_round: str) -> list[dict]:
    project = Path(project_dir)
    if manifest.get("project_id") != _project_identity(project):
        raise L0StateError("L0_RESTORE_PROJECT_MISMATCH",
                           f"manifest={manifest.get('project_id')!r} current={_project_identity(project)!r}")
    if str(manifest.get("candidate_id")) != str(expected_candidate):
        raise L0StateError("L0_RESTORE_CANDIDATE_MISMATCH",
                           f"manifest={manifest.get('candidate_id')!r} expected={expected_candidate!r}")
    if str(manifest.get("round_id")) != str(expected_round):
        raise L0StateError("L0_RESTORE_ROUND_MISMATCH",
                           f"manifest={manifest.get('round_id')!r} expected={expected_round!r}")
    verified = []
    for item in manifest.get("artifacts", []):
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            raise L0StateError("L0_RESTORE_MANIFEST_SCHEMA_INVALID", "invalid artifact record")
        path = _resolve_registered_path(project, item["path"])
        if not path.exists():
            raise L0StateError("L0_RESTORE_ARTIFACT_MISSING", item["path"])
        actual = _hash_path(path)
        if actual != item["sha256"]:
            raise L0StateError("L0_RESTORE_ARTIFACT_HASH_MISMATCH",
                               f"{item['path']}: expected={item['sha256']} actual={actual}")
        verified.append(dict(item))
    return verified


def _binding_path(project: Path, cand_id: str) -> Path:
    return project / "08_Audit" / "l0_restore" / f"{cand_id}_evidence_binding.json"


def write_evidence_binding(project_dir, cand_id, binding: dict) -> Path:
    path = _binding_path(Path(project_dir), cand_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _canonical_json(binding)
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise L0StateError("L0_RESTORE_BINDING_COLLISION", str(path))
    if not path.exists():
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    return path


def restore_previous_round(project_dir, cand_id) -> dict:
    project = Path(project_dir)
    cf = _candidate_file(project, cand_id)
    fm = _load_yaml_front(cf) if cf.is_file() else {}
    if not fm.get("from_memory") and str(fm.get("round_type") or "initial") != "continuation":
        return {
            "schema_version": EVIDENCE_BINDING_SCHEMA,
            "current_candidate_id": str(cand_id),
            "binding_status": "NOT_APPLICABLE",
            "verified_artifacts": [],
            "failures": [],
        }

    memory_value = fm.get("memory_file")
    if not memory_value:
        raise L0StateError("L0_RESTORE_MANIFEST_MISSING", "continuation has no memory_file")
    memory_path = _resolve_registered_path(project, memory_value)
    if not memory_path.is_file():
        raise L0StateError("L0_RESTORE_MANIFEST_MISSING", f"loop memory missing: {memory_path}")
    if fm.get("memory_hash") and _hash_path(memory_path) != str(fm.get("memory_hash")):
        raise L0StateError("L0_RESTORE_RECEIPT_INVALID", "loop memory hash mismatch")
    try:
        memory = json.loads(memory_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise L0StateError("L0_RESTORE_RECEIPT_INVALID", str(exc)) from exc

    rel = memory.get("round_manifest_path")
    expected_sha = memory.get("round_manifest_sha256")
    if not rel or not expected_sha:
        raise L0StateError("L0_RESTORE_MANIFEST_MISSING",
                           "loop memory lacks round_manifest_path/round_manifest_sha256")
    manifest_path = _resolve_registered_path(project, rel)
    if not manifest_path.is_file():
        raise L0StateError("L0_RESTORE_MANIFEST_MISSING", str(manifest_path))
    actual_manifest_sha = _hash_path(manifest_path)
    if actual_manifest_sha != expected_sha:
        raise L0StateError("L0_RESTORE_MANIFEST_HASH_MISMATCH",
                           f"expected={expected_sha} actual={actual_manifest_sha}")

    manifest = load_round_manifest(manifest_path)
    previous_candidate = str(fm.get("previous_candidate_id") or memory.get("source_candidate_id") or "")
    previous_round = str(memory.get("parent_round_id") or manifest.get("round_id") or "")
    verified = verify_round_manifest(
        project,
        manifest,
        expected_candidate=previous_candidate,
        expected_round=previous_round,
    )
    binding = {
        "schema_version": EVIDENCE_BINDING_SCHEMA,
        "current_candidate_id": str(cand_id),
        "previous_candidate_id": previous_candidate,
        "previous_round_id": previous_round,
        "manifest_path": _stored_path(project, manifest_path),
        "manifest_sha256": actual_manifest_sha,
        "verified_artifacts": verified,
        "failures": [],
        "binding_status": "PASS",
    }
    write_evidence_binding(project, cand_id, binding)
    return binding


def project_verified_source_selectors(project_dir, memory: dict, *,
                                      expected_candidate: str | None = None) -> list[dict]:
    """Project the prior candidate's declared source files into selectors.

    This is deliberately a projection, not a data registry.  The caller must
    provide the loop-memory identity, but the memory is used only to locate and
    hash-check the prior Round Manifest.  The parent L0 contract supplies the
    declaration of which source files are eligible for this same-dataset
    continuation; the verified manifest supplies the authoritative class and
    SHA-256.  No audit, literature, receipt, report, manifest, intermediate,
    or result artifact is selected by this rule.
    """
    project = Path(project_dir)
    if not isinstance(memory, dict):
        raise L0StateError(
            "L0_CONTINUATION_MEMORY_INVALID",
            "continuation memory must be a mapping",
        )

    parent_candidate = str(
        expected_candidate or memory.get("source_candidate_id") or ""
    ).strip()
    if not parent_candidate:
        raise L0StateError(
            "L0_CONTINUATION_MEMORY_INVALID",
            "continuation memory lacks source_candidate_id",
        )
    memory_candidate = str(memory.get("source_candidate_id") or "").strip()
    if memory_candidate and memory_candidate != parent_candidate:
        raise L0StateError(
            "L0_CONTINUATION_MEMORY_IDENTITY_MISMATCH",
            f"memory source_candidate_id={memory_candidate!r} != expected={parent_candidate!r}",
        )

    manifest_value = str(memory.get("round_manifest_path") or "").strip()
    expected_manifest_sha = str(memory.get("round_manifest_sha256") or "").strip()
    if not manifest_value or not expected_manifest_sha:
        raise L0StateError(
            "L0_CONTINUATION_MANIFEST_MISSING",
            "continuation memory must carry round_manifest_path and round_manifest_sha256",
        )
    manifest_path = _resolve_registered_path(project, manifest_value)
    if not manifest_path.is_file():
        raise L0StateError(
            "L0_CONTINUATION_MANIFEST_MISSING",
            f"prior round manifest missing: {manifest_value}",
        )
    actual_manifest_sha = _hash_path(manifest_path)
    if actual_manifest_sha != expected_manifest_sha:
        raise L0StateError(
            "L0_CONTINUATION_MANIFEST_HASH_MISMATCH",
            f"{manifest_value}: expected={expected_manifest_sha} actual={actual_manifest_sha}",
        )

    manifest = load_round_manifest(manifest_path)
    expected_round = str(
        memory.get("parent_round_id") or manifest.get("round_id") or ""
    ).strip()
    if not expected_round:
        raise L0StateError(
            "L0_CONTINUATION_MANIFEST_INVALID",
            "continuation memory/manifest lacks the prior round id",
        )
    verified = verify_round_manifest(
        project,
        manifest,
        expected_candidate=parent_candidate,
        expected_round=expected_round,
    )

    parent_contract, contract_path, _raw = l0_contract.load_contract(
        project, parent_candidate
    )
    if not isinstance(parent_contract, dict):
        raise L0StateError(
            "L0_CONTINUATION_PARENT_CONTRACT_INVALID",
            f"parent L0 contract missing/unreadable: {contract_path}",
        )
    source = parent_contract.get("source_input")
    if not isinstance(source, dict):
        raise L0StateError(
            "L0_CONTINUATION_SOURCE_UNAVAILABLE",
            f"parent L0 contract has no source_input: {contract_path}",
        )
    input_type = str(source.get("input_type") or "")
    if input_type not in {"files", "directory"}:
        raise L0StateError(
            "L0_CONTINUATION_SOURCE_UNAVAILABLE",
            f"same-dataset source projection requires a local files/directory source; got {input_type!r}",
        )

    def canonical_path(value: str) -> str:
        return _stored_path(project, _resolve_registered_path(project, value))

    verified_by_path: dict[str, list[dict]] = {}
    for item in verified:
        if not isinstance(item, dict):
            continue
        path_value = str(item.get("path") or "")
        if not path_value:
            continue
        verified_by_path.setdefault(canonical_path(path_value), []).append(item)

    declarations: list[tuple[str, str, str]] = []
    file_manifest = source.get("file_manifest")
    if isinstance(file_manifest, list) and file_manifest:
        for index, entry in enumerate(file_manifest):
            if not isinstance(entry, dict):
                raise L0StateError(
                    "L0_CONTINUATION_SOURCE_INVALID",
                    f"source_input.file_manifest[{index}] must be a mapping",
                )
            path_value = str(entry.get("path") or "").strip()
            digest = str(entry.get("sha256") or "").strip()
            if not path_value or not digest:
                raise L0StateError(
                    "L0_CONTINUATION_SOURCE_INVALID",
                    f"source_input.file_manifest[{index}] requires path and sha256",
                )
            declarations.append((path_value, digest, str(entry.get("role") or "")))
    else:
        raw_paths = list(source.get("files") or [])
        if not raw_paths and source.get("location"):
            raw_paths = [source["location"]]
        if not raw_paths:
            raise L0StateError(
                "L0_CONTINUATION_SOURCE_UNAVAILABLE",
                "parent local source_input declares no files or location",
            )
        for value in raw_paths:
            path_value = str(value).strip()
            if path_value:
                declarations.append((path_value, "", ""))

    selected: dict[str, dict] = {}
    for path_value, declared_sha, declared_role in declarations:
        resolved = _resolve_registered_path(project, path_value)
        if resolved.is_dir():
            matches = [
                item for stored, items in verified_by_path.items()
                if _path_is_under(
                    _resolve_registered_path(project, stored), resolved
                )
                for item in items
            ]
        else:
            matches = list(verified_by_path.get(canonical_path(path_value), []))
        if not matches:
            raise L0StateError(
                "L0_CONTINUATION_SOURCE_NOT_VERIFIED",
                f"parent source declaration is absent from verified manifest: {path_value}",
            )
        for item in matches:
            klass = str(item.get("class") or "")
            if klass != "source":
                raise L0StateError(
                    "L0_CONTINUATION_SOURCE_CLASS_FORBIDDEN",
                    f"{item.get('path')}: manifest class={klass!r}; same-dataset projection allows source only",
                )
            stored = canonical_path(str(item["path"]))
            manifest_sha = str(item.get("sha256") or "")
            if declared_sha and manifest_sha != declared_sha:
                raise L0StateError(
                    "L0_CONTINUATION_SOURCE_HASH_MISMATCH",
                    f"{stored}: parent contract={declared_sha} manifest={manifest_sha}",
                )
            prior = selected.get(stored)
            role = declared_role or "inherited_source"
            if prior is not None and prior["sha256"] != manifest_sha:
                raise L0StateError(
                    "L0_CONTINUATION_SOURCE_HASH_CONFLICT",
                    f"duplicate source declaration has conflicting hashes: {stored}",
                )
            selected[stored] = {
                "path": stored,
                "sha256": manifest_sha,
                "role": role,
                "reuse_reason": (
                    f"reuse verified source input declared by prior candidate "
                    f"{parent_candidate} round {expected_round}"
                ),
            }

    if not selected:
        raise L0StateError(
            "L0_CONTINUATION_SOURCE_UNAVAILABLE",
            "parent source declaration produced no verified source selectors",
        )
    return [selected[key] for key in sorted(selected)]
