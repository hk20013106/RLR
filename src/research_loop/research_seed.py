"""Canonical L0 -> L1 research-seed projection.

The L0 sidecar remains the sole semantic authority.  This module does not
persist a second copy of the scientific question or hypothesis; it validates
the existing L0 contract at the boundary of use and projects the exact fields
needed by Curie (research) and Einstein (L1 reasoning).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_loop import l0_contract
from research_loop.paths import _candidate_file
from research_loop.yamlio import _load_yaml_front


SCHEMA_VERSION = "L1ResearchSeed/v1"


class ResearchSeedError(ValueError):
    """Raised when the canonical L0 contract cannot authorize an L1 seed."""


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_l1_research_seed(project_dir, cand_id):
    """Validate L0 and return the single canonical semantic seed for L1.

    No candidate-frontmatter ``question``/``claim`` fallback is permitted.  A
    missing, malformed, mismatched, or tampered L0 sidecar fails closed.
    """
    project_dir = Path(project_dir)
    candidate_path = _candidate_file(project_dir, cand_id)
    if not candidate_path.is_file():
        raise ResearchSeedError(f"candidate not found: {cand_id}")

    frontmatter = _load_yaml_front(candidate_path)
    contract, artifact_path, raw = l0_contract.load_contract(project_dir, cand_id)
    errors = l0_contract.validate_l0_input_contract(
        contract,
        frontmatter,
        project_dir,
        cand_id,
        artifact_path=artifact_path,
        raw_bytes=raw,
    )
    if errors:
        raise ResearchSeedError(
            "canonical L0 research seed is invalid: " + "; ".join(errors)
        )

    current_round = contract["current_round"]
    try:
        relative_path = artifact_path.relative_to(project_dir).as_posix()
    except ValueError:
        relative_path = artifact_path.as_posix()

    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": str(contract["candidate_id"]),
        "round_id": str(contract["round_id"]),
        "round_type": str(contract["round_type"]),
        "scientific_question": str(contract["scientific_question"]),
        "hypothesis_seed": str(current_round["hypothesis"]),
        "l0_contract_schema_version": str(contract["schema_version"]),
        "l0_contract_path": relative_path,
        "l0_contract_sha256": hashlib.sha256(raw).hexdigest(),
    }


def seed_sha256(seed) -> str:
    """Content address of the complete semantic projection."""
    return hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()


def manifest_entry(seed) -> dict:
    """Compact receipt binding; semantic text remains in L0, not the manifest."""
    return {
        "schema_version": str(seed["schema_version"]),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "round_type": str(seed["round_type"]),
        "l0_contract_path": str(seed["l0_contract_path"]),
        "l0_contract_sha256": str(seed["l0_contract_sha256"]),
        "seed_sha256": seed_sha256(seed),
    }


def render_context_block(seed) -> str:
    """Render the exact canonical semantics consumed by Einstein."""
    payload = {
        "schema_version": seed["schema_version"],
        "candidate_id": seed["candidate_id"],
        "round_id": seed["round_id"],
        "round_type": seed["round_type"],
        "scientific_question": seed["scientific_question"],
        "hypothesis_seed": seed["hypothesis_seed"],
        "l0_contract_sha256": seed["l0_contract_sha256"],
    }
    return (
        "=== L1 RESEARCH SEED (canonical L0 projection) ===\n"
        "AUTHORITY: validated L0 sidecar; candidate frontmatter question/claim "
        "are not semantic inputs to L1.\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    )
