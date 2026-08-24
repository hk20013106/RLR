"""Native v2.1 ResearchSeed -> frozen Curie EvidencePack binding.

This module is the native evidence-binding implementation. It deliberately does
not inspect or require legacy Deep Research run artifacts. The public functions
are installed on ``research_loop.research_seed`` so callers retain one semantic
owner for the L0 -> L0.5 -> L1 boundary while historical v2 compatibility APIs
remain untouched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION = "L1NativeEvidenceBinding/v1"
_ROOT = Path("08_Audit") / "research_seed_bindings" / "native"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must be a non-empty string")
    return text


def _binding_dir(project_dir: str | Path, seed: dict) -> Path:
    candidate_id = _text(seed.get("candidate_id"), "native binding candidate_id")
    round_id = _text(seed.get("round_id"), "native binding round_id")
    return Path(project_dir) / _ROOT / candidate_id / round_id


def _binding_path(project_dir: str | Path, seed: dict, acquisition_run_id: str) -> Path:
    run_id = _text(acquisition_run_id, "native binding acquisition_run_id")
    identity = f"{seed['candidate_id']}:{seed['round_id']}:{run_id}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return _binding_dir(project_dir, seed) / f"L1_native_{suffix}.json"


def _load_pack(project_dir: Path, seed: dict, pack_manifest: dict, research_seed_module):
    from research_loop import l05_curie

    try:
        return l05_curie.load_frozen_evidence_pack(
            project_dir,
            pack_manifest,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed_module.seed_sha256(seed),
        )
    except l05_curie.CurieContractError as exc:
        raise research_seed_module.ResearchSeedError(
            f"frozen L0.5 EvidencePack is invalid: {exc}"
        ) from exc


def _payload(project_dir: Path, seed: dict, pack_manifest: dict,
             acquisition_run_id: str, research_seed_module) -> dict:
    run_id = _text(acquisition_run_id, "native binding acquisition_run_id")
    frozen = _load_pack(project_dir, seed, pack_manifest, research_seed_module)
    if str(frozen.get("source_run_id") or "") != run_id:
        raise research_seed_module.ResearchSeedError(
            "frozen L0.5 EvidencePack source_run_id does not match native acquisition_run_id"
        )
    return {
        "schema_version": NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION,
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "research_seed": research_seed_module.manifest_entry(seed),
        "acquisition_run_id": run_id,
        "evidence_pack": dict(pack_manifest),
        "pack_lineage": {
            "version": int(frozen["version"]),
            "parent_pack_sha256": frozen.get("parent_pack_sha256"),
            "source_gap_request_id": frozen.get("source_gap_request_id"),
            "content_sha256": str(frozen["content_sha256"]),
        },
    }


def _entry(project_dir: Path, seed: dict, acquisition_run_id: str,
           payload: dict) -> dict:
    path = _binding_path(project_dir, seed, acquisition_run_id)
    try:
        relative = path.relative_to(project_dir).as_posix()
    except ValueError:
        relative = path.as_posix()
    manifest = payload["evidence_pack"]
    return {
        "schema_version": NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION,
        "artifact_path": relative,
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "seed_sha256": str(payload["research_seed"]["seed_sha256"]),
        "evidence_run_id": str(payload["acquisition_run_id"]),
        "evidence_pack_id": str(manifest["pack_id"]),
        "evidence_pack_version": int(manifest["version"]),
        "evidence_pack_path": str(manifest["artifact_path"]),
        "evidence_pack_sha256": str(manifest["artifact_sha256"]),
        "evidence_pack_content_sha256": str(manifest["content_sha256"]),
    }


def _validate_payload(project_dir: Path, seed: dict, acquisition_run_id: str,
                      payload: dict, research_seed_module) -> dict:
    run_id = _text(acquisition_run_id, "native binding acquisition_run_id")
    if not isinstance(payload, dict):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding must be an object")
    if payload.get("schema_version") != NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION:
        raise research_seed_module.ResearchSeedError("native L1 evidence binding schema is invalid")
    if str(payload.get("candidate_id") or "") != str(seed["candidate_id"]):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding candidate mismatch")
    if str(payload.get("round_id") or "") != str(seed["round_id"]):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding round mismatch")
    if payload.get("research_seed") != research_seed_module.manifest_entry(seed):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding research seed has changed")
    if str(payload.get("acquisition_run_id") or "") != run_id:
        raise research_seed_module.ResearchSeedError("native L1 evidence binding acquisition_run_id mismatch")
    manifest = payload.get("evidence_pack")
    if not isinstance(manifest, dict):
        raise research_seed_module.ResearchSeedError("native L1 evidence binding has no frozen EvidencePack")
    frozen = _load_pack(project_dir, seed, manifest, research_seed_module)
    if str(frozen.get("source_run_id") or "") != run_id:
        raise research_seed_module.ResearchSeedError(
            "frozen L0.5 EvidencePack source_run_id changed since native binding"
        )
    expected_lineage = {
        "version": int(frozen["version"]),
        "parent_pack_sha256": frozen.get("parent_pack_sha256"),
        "source_gap_request_id": frozen.get("source_gap_request_id"),
        "content_sha256": str(frozen["content_sha256"]),
    }
    if payload.get("pack_lineage") != expected_lineage:
        raise research_seed_module.ResearchSeedError("native L1 evidence binding pack lineage has changed")
    return payload


def install(research_seed_module) -> None:
    """Install native binding APIs on the canonical research_seed module."""
    if getattr(research_seed_module, "_l05_native_binding_installed", False):
        return
    legacy_evidence_binding_manifest_entry = (
        research_seed_module.evidence_binding_manifest_entry
    )

    def write_l1_native_evidence_binding(project_dir, seed, pack_manifest,
                                         acquisition_run_id) -> dict:
        project = Path(project_dir)
        try:
            payload = _payload(
                project, seed, pack_manifest, acquisition_run_id, research_seed_module
            )
        except ValueError as exc:
            raise research_seed_module.ResearchSeedError(str(exc)) from exc
        path = _binding_path(project, seed, acquisition_run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical_bytes(payload)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L1 evidence binding is unreadable: {exc}"
                ) from exc
            if existing != payload:
                raise research_seed_module.ResearchSeedError(
                    "native L1 evidence binding already exists with different provenance"
                )
        else:
            path.write_bytes(raw)
        validated = _validate_payload(
            project, seed, acquisition_run_id, payload, research_seed_module
        )
        return _entry(project, seed, acquisition_run_id, validated)

    def load_l1_native_evidence_binding(project_dir, seed, acquisition_run_id) -> dict:
        project = Path(project_dir)
        try:
            path = _binding_path(project, seed, acquisition_run_id)
        except ValueError as exc:
            raise research_seed_module.ResearchSeedError(str(exc)) from exc
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise research_seed_module.ResearchSeedError(
                f"native L1 evidence binding is missing or invalid: {exc}"
            ) from exc
        return _validate_payload(
            project, seed, acquisition_run_id, payload, research_seed_module
        )

    def native_evidence_binding_manifest_entry(project_dir, seed,
                                               acquisition_run_id) -> dict:
        project = Path(project_dir)
        payload = load_l1_native_evidence_binding(project, seed, acquisition_run_id)
        return _entry(project, seed, acquisition_run_id, payload)

    def evidence_binding_manifest_entry(project_dir, seed, evidence_run_id) -> dict:
        """Return the authoritative receipt for this run, native when present."""
        project = Path(project_dir)
        native_path = _binding_path(project, seed, evidence_run_id)
        if native_path.is_file():
            return native_evidence_binding_manifest_entry(
                project, seed, evidence_run_id
            )
        return legacy_evidence_binding_manifest_entry(
            project_dir, seed, evidence_run_id
        )

    def unique_l1_native_evidence_run_id(project_dir, seed):
        project = Path(project_dir)
        root = _binding_dir(project, seed)
        if not root.is_dir():
            return None
        run_ids = []
        for path in sorted(root.glob("L1_native_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise research_seed_module.ResearchSeedError(
                    f"native L1 evidence binding is unreadable: {exc}"
                ) from exc
            run_id = str(payload.get("acquisition_run_id") or "")
            if not run_id:
                raise research_seed_module.ResearchSeedError(
                    "native L1 evidence binding has no acquisition_run_id"
                )
            expected_path = _binding_path(project, seed, run_id).resolve()
            if path.resolve() != expected_path:
                raise research_seed_module.ResearchSeedError(
                    "native L1 evidence binding path does not match its acquisition_run_id"
                )
            _validate_payload(project, seed, run_id, payload, research_seed_module)
            if run_id not in run_ids:
                run_ids.append(run_id)
        return run_ids[0] if len(run_ids) == 1 else None

    research_seed_module.NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION = (
        NATIVE_EVIDENCE_BINDING_SCHEMA_VERSION
    )
    research_seed_module.write_l1_native_evidence_binding = (
        write_l1_native_evidence_binding
    )
    research_seed_module.load_l1_native_evidence_binding = (
        load_l1_native_evidence_binding
    )
    research_seed_module.native_evidence_binding_manifest_entry = (
        native_evidence_binding_manifest_entry
    )
    research_seed_module.evidence_binding_manifest_entry = (
        evidence_binding_manifest_entry
    )
    research_seed_module.unique_l1_native_evidence_run_id = (
        unique_l1_native_evidence_run_id
    )
    research_seed_module._l05_native_binding_installed = True
