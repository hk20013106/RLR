"""Backward-compatible semantic admission extension for EvidencePack/v1.

Legacy packs remain byte-compatible when ``semantic_verifications`` is omitted.
New Phase 7 packs may freeze semantic admission records; whenever present, the
records are revalidated at build, freeze, and load boundaries and must map
one-to-one to every reasoning-authorized EvidenceExtract in the pack.
"""
from __future__ import annotations

import copy

from .contracts import CurieContractError


def _validate_semantic_pack(pack: dict) -> dict:
    if "semantic_verifications" not in pack:
        return pack
    values = pack.get("semantic_verifications")
    if not isinstance(values, list) or not values:
        raise CurieContractError(
            "EvidencePack semantic_verifications must be a non-empty list when present"
        )
    from .semantic_verifier import (
        reasoning_authorized,
        validate_semantic_verification,
    )

    evidence = pack.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise CurieContractError(
            "semantic EvidencePack requires non-empty evidence"
        )
    evidence_by_id = {str(item.get("evidence_id") or ""): item for item in evidence}
    if "" in evidence_by_id or len(evidence_by_id) != len(evidence):
        raise CurieContractError(
            "semantic EvidencePack evidence identities are invalid or duplicated"
        )
    semantic_by_id = {}
    for value in values:
        result = validate_semantic_verification(value)
        evidence_id = result["evidence_id"]
        if evidence_id in semantic_by_id:
            raise CurieContractError(
                f"duplicate semantic verification for evidence {evidence_id}"
            )
        semantic_by_id[evidence_id] = result
    if set(semantic_by_id) != set(evidence_by_id):
        raise CurieContractError(
            "semantic verification evidence IDs must match EvidencePack evidence exactly"
        )
    for evidence_id, result in semantic_by_id.items():
        extract = evidence_by_id[evidence_id]
        if str(result["paper_id"]) != str(extract.get("paper_id") or ""):
            raise CurieContractError(
                f"semantic verification paper identity mismatch for evidence {evidence_id}"
            )
        if not reasoning_authorized(result):
            raise CurieContractError(
                f"semantic verification for evidence {evidence_id} is not reasoning-authorized"
            )
    return pack


def install(store_module) -> None:
    if getattr(store_module, "_semantic_pack_installed", False):
        return
    original_build = store_module.build_evidence_pack
    original_freeze = store_module.freeze_evidence_pack
    original_load = store_module.load_frozen_evidence_pack

    def build_evidence_pack(*, semantic_verifications=None, **kwargs):
        pack = original_build(**kwargs)
        if semantic_verifications is None:
            return pack
        pack = copy.deepcopy(pack)
        pack["semantic_verifications"] = copy.deepcopy(semantic_verifications)
        _validate_semantic_pack(pack)
        pack["content_sha256"] = store_module._content_sha256(pack)
        pack = store_module._validate_pack_structure(
            pack, expected_status="READY_TO_FREEZE"
        )
        _validate_semantic_pack(pack)
        return pack

    def freeze_evidence_pack(project_dir, pack):
        _validate_semantic_pack(pack)
        return original_freeze(project_dir, pack)

    def load_frozen_evidence_pack(project_dir, manifest, *, candidate_id,
                                  round_id, seed_sha256):
        pack = original_load(
            project_dir,
            manifest,
            candidate_id=candidate_id,
            round_id=round_id,
            seed_sha256=seed_sha256,
        )
        _validate_semantic_pack(pack)
        return pack

    store_module.build_evidence_pack = build_evidence_pack
    store_module.freeze_evidence_pack = freeze_evidence_pack
    store_module.load_frozen_evidence_pack = load_frozen_evidence_pack
    store_module._semantic_pack_installed = True
