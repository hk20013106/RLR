"""Native Curie EvidencePack activation and bounded gap-retry runtime."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from research_loop import research_seed

from .contracts import CurieContractError
from .gap_loop import authorize_gap_retry
from .store import load_frozen_evidence_pack


def _load(project_dir: str | Path, seed: dict, manifest: dict) -> dict:
    try:
        return load_frozen_evidence_pack(
            project_dir,
            manifest,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed.seed_sha256(seed),
        )
    except (KeyError, research_seed.ResearchSeedError, CurieContractError) as exc:
        raise CurieContractError(f"native Curie EvidencePack is invalid: {exc}") from exc


def bind_initial_curie_pack(
    project_dir: str | Path,
    seed: dict,
    evidence_pack_manifest: dict,
    acquisition_run_id: str,
) -> dict:
    """Bind and activate the first native frozen EvidencePack for Einstein."""
    pack = _load(project_dir, seed, evidence_pack_manifest)
    if int(pack.get("version") or 0) != 1:
        raise CurieContractError("initial native Curie EvidencePack must be version 1")
    if pack.get("parent_pack_sha256") not in (None, ""):
        raise CurieContractError("initial native Curie EvidencePack must not have a parent")
    if pack.get("source_gap_request_id") not in (None, ""):
        raise CurieContractError("initial native Curie EvidencePack must not come from a gap request")
    if str(pack.get("source_run_id") or "") != str(acquisition_run_id):
        raise CurieContractError(
            "initial native Curie EvidencePack source_run_id does not match acquisition_run_id"
        )
    try:
        binding = research_seed.write_l1_native_evidence_binding(
            project_dir, seed, evidence_pack_manifest, acquisition_run_id
        )
        research_seed.activate_l1_native_evidence_binding(
            project_dir, seed, acquisition_run_id
        )
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(f"native Curie binding failed: {exc}") from exc
    return binding


def _validate_authorized_pack(
    project_dir: str | Path,
    seed: dict,
    parent_manifest: dict,
    authorization: dict,
    new_manifest: dict,
    acquisition_run_id: str,
) -> dict:
    parent = _load(project_dir, seed, parent_manifest)
    current_run = research_seed.active_l1_native_evidence_run_id(project_dir, seed)
    if not current_run:
        raise CurieContractError("native Curie retry requires an active parent binding")
    try:
        active_binding = research_seed.load_l1_native_evidence_binding(
            project_dir, seed, current_run
        )
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(f"active native Curie binding is invalid: {exc}") from exc
    active_sha = str(active_binding["pack_lineage"]["content_sha256"])
    if active_sha != str(parent["content_sha256"]):
        raise CurieContractError(
            "authorized retry parent EvidencePack is not the current active native pack"
        )

    pack = _load(project_dir, seed, new_manifest)
    expected = {
        "version": int(authorization["next_version"]),
        "parent_pack_sha256": str(authorization["parent_pack_sha256"]),
        "source_gap_request_id": str(authorization["source_gap_request_id"]),
        "source_run_id": str(acquisition_run_id),
    }
    for field, value in expected.items():
        observed = pack.get(field)
        if field == "version":
            if int(observed or 0) != value:
                raise CurieContractError(
                    f"authorized retry EvidencePack {field} does not match authorization"
                )
        elif str(observed or "") != value:
            raise CurieContractError(
                f"authorized retry EvidencePack {field} does not match authorization"
            )
    return pack


def run_authorized_retry(
    project_dir: str | Path,
    seed: dict,
    active_pack_manifest: dict,
    request_id: str,
    acquisition_run_id: str,
    acquire: Callable[[dict], dict],
    *,
    failure_step: str | None = None,
) -> dict:
    """Run one authorized Curie retry and atomically advance active evidence lineage.

    ``acquire`` receives the immutable retry authorization and must return a
    frozen EvidencePack manifest.  The new binding is not activated until all
    version, parent, gap-request and source-run lineage checks pass.
    """
    try:
        committed = research_seed.load_l1_native_retry_commit(
            project_dir, seed, request_id
        )
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(f"native Curie retry commit is invalid: {exc}") from exc
    if committed is not None:
        if str(committed["acquisition_run_id"]) != str(acquisition_run_id):
            raise CurieContractError(
                "native Curie retry replay acquisition_run_id does not match committed transaction"
            )
        return {
            "authorization": committed["authorization"],
            "consumption": committed["consumption"],
            "activation": committed["activation"],
            "binding": committed["binding_entry"],
            "evidence_pack": committed["evidence_pack"],
            "evidence_pack_content_sha256": str(
                committed["binding"]["pack_lineage"]["content_sha256"]
            ),
        }

    authorization = authorize_gap_retry(
        project_dir, seed, active_pack_manifest, request_id
    )
    new_manifest = acquire(dict(authorization))
    if not isinstance(new_manifest, dict):
        raise CurieContractError("authorized retry acquisition did not return an EvidencePack manifest")
    pack = _validate_authorized_pack(
        project_dir,
        seed,
        active_pack_manifest,
        authorization,
        new_manifest,
        acquisition_run_id,
    )
    try:
        committed = research_seed.commit_l1_native_retry(
            project_dir,
            seed,
            active_pack_manifest,
            new_manifest,
            acquisition_run_id,
            authorization,
            failure_step=failure_step,
        )
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(f"native Curie retry commit failed: {exc}") from exc
    return {
        "authorization": authorization,
        "consumption": committed["consumption"],
        "activation": committed["activation"],
        "binding": committed["binding_entry"],
        "evidence_pack": new_manifest,
        "evidence_pack_content_sha256": str(pack["content_sha256"]),
    }
