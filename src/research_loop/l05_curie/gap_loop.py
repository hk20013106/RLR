"""Append-only EvidenceGapRequest persistence and bounded retry authorization."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_loop import research_seed

from .contracts import (
    MAX_ACQUISITION_ROUNDS,
    CurieContractError,
    build_gap_request,
    validate_gap_request,
)
from .store import load_frozen_evidence_pack

AUTH_SCHEMA_VERSION = "L05GapRetryAuthorization/v1"
CONSUMPTION_SCHEMA_VERSION = "L05GapRetryConsumption/v1"
_ROOT = Path("08_Audit") / "l05_gap_requests"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _safe(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text).strip("._")
    if not safe:
        raise CurieContractError(f"{name} cannot be normalized to a safe token")
    return safe


def _root(project_dir: str | Path, seed: dict) -> Path:
    return (
        Path(project_dir)
        / _ROOT
        / _safe(seed.get("candidate_id"), "gap candidate_id")
        / _safe(seed.get("round_id"), "gap round_id")
    )


def _request_path(project_dir: str | Path, seed: dict, request_id: str) -> Path:
    return _root(project_dir, seed) / f"{_safe(request_id, 'gap request_id')}.json"


def _consumption_path(project_dir: str | Path, seed: dict, request_id: str) -> Path:
    return _root(project_dir, seed) / "consumed" / f"{_safe(request_id, 'gap request_id')}.json"


def _active_pack(project_dir: str | Path, seed: dict, manifest: dict) -> dict:
    try:
        return load_frozen_evidence_pack(
            project_dir,
            manifest,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed.seed_sha256(seed),
        )
    except (KeyError, research_seed.ResearchSeedError, CurieContractError) as exc:
        raise CurieContractError(f"active parent EvidencePack is invalid: {exc}") from exc


def _authorization_identity(request_id: str, parent_pack_sha256: str,
                            next_version: int) -> dict:
    return {
        "request_id": request_id,
        "parent_pack_sha256": parent_pack_sha256,
        "next_version": next_version,
    }


def _authorization_id(identity: dict) -> str:
    return "EGRA_" + hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:16]


def _validate_retry_authorization(seed: dict, authorization: dict) -> dict:
    if not isinstance(authorization, dict) or authorization.get("schema_version") != AUTH_SCHEMA_VERSION:
        raise CurieContractError("gap retry authorization schema is invalid")
    if str(authorization.get("candidate_id") or "") != str(seed["candidate_id"]):
        raise CurieContractError("gap retry authorization candidate mismatch")
    if str(authorization.get("round_id") or "") != str(seed["round_id"]):
        raise CurieContractError("gap retry authorization round mismatch")
    if str(authorization.get("seed_sha256") or "") != research_seed.seed_sha256(seed):
        raise CurieContractError("gap retry authorization ResearchSeed mismatch")

    raw_request_id = str(authorization.get("request_id") or "")
    request_id = _safe(raw_request_id, "gap request_id")
    if request_id != raw_request_id:
        raise CurieContractError("gap retry authorization request lineage is not canonical")
    if str(authorization.get("source_gap_request_id") or "") != request_id:
        raise CurieContractError("gap retry authorization request lineage mismatch")

    parent_version = authorization.get("parent_pack_version")
    next_version = authorization.get("next_version")
    if (
        isinstance(parent_version, bool)
        or not isinstance(parent_version, int)
        or isinstance(next_version, bool)
        or not isinstance(next_version, int)
    ):
        raise CurieContractError("gap retry authorization version lineage is invalid")
    if parent_version < 1 or next_version != parent_version + 1:
        raise CurieContractError("gap retry authorization version lineage is invalid")
    if next_version > MAX_ACQUISITION_ROUNDS:
        raise CurieContractError(
            f"gap retry authorization exceeds maximum of {MAX_ACQUISITION_ROUNDS} rounds"
        )

    parent_sha = str(authorization.get("parent_pack_sha256") or "")
    if len(parent_sha) != 64 or any(ch not in "0123456789abcdef" for ch in parent_sha):
        raise CurieContractError("gap retry authorization parent pack SHA is invalid")
    identity = _authorization_identity(request_id, parent_sha, next_version)
    expected_id = _authorization_id(identity)
    if str(authorization.get("authorization_id") or "") != expected_id:
        raise CurieContractError("gap retry authorization id does not match its lineage")
    return dict(authorization)


def open_gap_request(
    project_dir: str | Path,
    seed: dict,
    active_pack_manifest: dict,
    *,
    gaps: list[dict],
) -> dict:
    """Persist one immutable OPEN request against the exact active pack."""
    pack = _active_pack(project_dir, seed, active_pack_manifest)
    request = build_gap_request(
        candidate_id=str(seed["candidate_id"]),
        round_id=str(seed["round_id"]),
        seed_sha256=research_seed.seed_sha256(seed),
        pack_sha256=str(pack["content_sha256"]),
        gaps=gaps,
    )
    path = _request_path(project_dir, seed, request["request_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_bytes(request)
    if path.exists():
        if path.read_bytes() != raw:
            raise CurieContractError(
                "EvidenceGapRequest already exists with different content"
            )
    else:
        path.write_bytes(raw)
    return request


def load_open_gap_request(
    project_dir: str | Path,
    seed: dict,
    active_pack_manifest: dict,
    request_id: str,
) -> dict:
    """Reload and revalidate an OPEN request against the exact active parent."""
    pack = _active_pack(project_dir, seed, active_pack_manifest)
    path = _request_path(project_dir, seed, request_id)
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurieContractError(f"EvidenceGapRequest is missing or invalid: {exc}") from exc
    validate_gap_request(request)
    expected = {
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "seed_sha256": research_seed.seed_sha256(seed),
        "pack_sha256": str(pack["content_sha256"]),
    }
    for key, value in expected.items():
        if str(request.get(key) or "") != str(value):
            raise CurieContractError(
                f"EvidenceGapRequest {key} does not match the active parent pack"
            )
    if str(request.get("request_id") or "") != str(request_id):
        raise CurieContractError("EvidenceGapRequest id does not match its artifact path")
    return request


def authorize_gap_retry(
    project_dir: str | Path,
    seed: dict,
    active_pack_manifest: dict,
    request_id: str,
) -> dict:
    """Authorize exactly one next acquisition version, never a fourth round."""
    pack = _active_pack(project_dir, seed, active_pack_manifest)
    request = load_open_gap_request(
        project_dir, seed, active_pack_manifest, request_id
    )
    current_version = int(pack["version"])
    if current_version >= MAX_ACQUISITION_ROUNDS:
        raise CurieContractError(
            f"maximum of {MAX_ACQUISITION_ROUNDS} Curie acquisition rounds reached"
        )
    consumed = _consumption_path(project_dir, seed, request_id)
    if consumed.exists():
        raise CurieContractError("EvidenceGapRequest retry authorization was already consumed")
    identity = _authorization_identity(
        str(request_id), str(pack["content_sha256"]), current_version + 1
    )
    authorization = {
        "schema_version": AUTH_SCHEMA_VERSION,
        "authorization_id": _authorization_id(identity),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "seed_sha256": research_seed.seed_sha256(seed),
        "request_id": str(request_id),
        "source_gap_request_id": str(request_id),
        "parent_pack_sha256": str(pack["content_sha256"]),
        "parent_pack_version": current_version,
        "next_version": current_version + 1,
    }
    return _validate_retry_authorization(seed, authorization)


def consume_gap_retry_authorization(
    project_dir: str | Path,
    seed: dict,
    authorization: dict,
    acquisition_run_id: str,
) -> dict:
    """Persist append-only consumption after a successful authorized retry."""
    validated = _validate_retry_authorization(seed, authorization)
    request_id = str(validated["request_id"])
    run_id = _safe(acquisition_run_id, "acquisition_run_id")
    receipt = {
        "schema_version": CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": str(validated["authorization_id"]),
        "request_id": request_id,
        "acquisition_run_id": run_id,
        "next_version": int(validated["next_version"]),
        "parent_pack_sha256": str(validated["parent_pack_sha256"]),
    }
    path = _consumption_path(project_dir, seed, request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_bytes(receipt)
    if path.exists():
        if path.read_bytes() != raw:
            raise CurieContractError(
                "EvidenceGapRequest consumption receipt already exists with different provenance"
            )
    else:
        path.write_bytes(raw)
    return receipt
