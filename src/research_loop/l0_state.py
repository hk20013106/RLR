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
from research_loop.paths import _candidate_file
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
    binding = project_dir / "00_Preflight" / "hypothesis_store_binding.json"
    if binding.is_file():
        try:
            value = json.loads(binding.read_text(encoding="utf-8"))
            if value.get("project_id"):
                return str(value["project_id"])
        except (OSError, json.JSONDecodeError):
            pass
    return project_dir.resolve().name


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


def _source_paths(project_dir: Path, cand_id: str) -> Iterable[Path]:
    contract, _, _ = l0_contract.load_contract(project_dir, cand_id)
    if not isinstance(contract, dict):
        return []
    source = contract.get("source_input") or {}
    paths = list(source.get("files") or [])
    if not paths and source.get("input_type") in ("files", "directory") and source.get("location"):
        paths = [source["location"]]
    return [_resolve_registered_path(project_dir, item) for item in paths]


def _l7_output_paths(project_dir: Path, cand_id: str) -> Iterable[Path]:
    manifest = project_dir / "04_Analysis_Outputs" / "_exec_manifest" / f"{cand_id}_L7.json"
    if not manifest.is_file():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out = []
    for script in payload.get("scripts", []) or []:
        for value in script.get("output_files", []) or []:
            out.append(_resolve_registered_path(project_dir, value))
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
    artifacts = []
    seen = set()

    def add(path: Path, klass: str, producer: str = ""):
        if not path.exists():
            raise L0StateError("L0_ROUND_MANIFEST_ARTIFACT_MISSING", str(path))
        stored = _stored_path(project, path)
        key = (klass, stored)
        if key in seen:
            return
        seen.add(key)
        artifacts.append(_artifact(project, path, klass, producer_node=producer,
                                   created_in_round=round_id))

    for path in _source_paths(project, cand_id):
        add(path, "source", "L0")
    for path in _l7_output_paths(project, cand_id):
        add(path, "intermediate", "L7")
    for path in _candidate_reports(project, cand_id):
        add(path, "result", "L10c")
    for path in _candidate_owned_literature(project, cand_id):
        add(path, "literature", "literature")
    for path in _candidate_receipts(project, cand_id):
        add(path, "receipt", "runtime")

    artifacts.sort(key=lambda item: (item["class"], item["path"], item["artifact_id"]))
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
