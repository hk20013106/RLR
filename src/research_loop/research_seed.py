"""Canonical L0 -> L0.5 -> L1 research-seed and evidence binding.

The L0 sidecar remains the sole semantic authority.  L0.5 Curie owns literature
acquisition and freezes an immutable EvidencePack.  Einstein receives the
canonical ResearchSeed plus that exact frozen evidence state; it does not gain
independent retrieval authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_loop import l0_contract
from research_loop.paths import _candidate_file
from research_loop.yamlio import _load_yaml_front


SCHEMA_VERSION = "L1ResearchSeed/v1"
EVIDENCE_BINDING_SCHEMA_VERSION = "L1ResearchEvidenceBinding/v2"


class ResearchSeedError(ValueError):
    """Raised when the canonical L0/L0.5 boundary cannot authorize L1."""


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


def _evidence_binding_path(project_dir, seed, run_id) -> Path:
    identity = f"{seed['candidate_id']}:{run_id}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return (
        Path(project_dir)
        / "08_Audit"
        / "research_seed_bindings"
        / f"L1_v2_{suffix}.json"
    )


def _current_evidence_run_entry(project_dir, seed, run_id) -> dict:
    from research_loop import deep_research

    try:
        evidence = deep_research.evidence_artifact_manifest(
            project_dir,
            str(seed["candidate_id"]),
            "L1",
            str(run_id),
        )
    except deep_research.DeepResearchError as exc:
        raise ResearchSeedError(f"L1 evidence run is invalid: {exc}") from exc

    expected = {
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "target_node": "L1",
    }
    for field, value in expected.items():
        if str(evidence.get(field) or "") != value:
            raise ResearchSeedError(
                f"L1 evidence run {field} does not match canonical research seed"
            )
    run_file = next(
        (item for item in evidence.get("files", []) if item.get("kind") == "run"),
        None,
    )
    if not isinstance(run_file, dict):
        raise ResearchSeedError("L1 evidence run manifest has no immutable run file")
    return {
        "run_id": str(run_id),
        "path": str(run_file["path"]),
        "sha256": str(run_file["sha256"]),
    }


def _current_evidence_pack_entry(project_dir, seed, run_id) -> dict:
    from research_loop import l05_curie

    seed_hash = seed_sha256(seed)
    try:
        manifest = l05_curie.freeze_l1_deep_research_run(
            project_dir,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=seed_hash,
            run_id=str(run_id),
        )
        frozen = l05_curie.load_frozen_evidence_pack(
            project_dir,
            manifest,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=seed_hash,
        )
    except l05_curie.CurieContractError as exc:
        raise ResearchSeedError(f"frozen L0.5 EvidencePack is invalid: {exc}") from exc
    if str(frozen.get("source_run_id") or "") != str(run_id):
        raise ResearchSeedError(
            "frozen L0.5 EvidencePack source_run_id does not match the selected L1 acquisition run"
        )
    return manifest


def write_l1_evidence_binding(project_dir, seed, run_id) -> dict:
    """Persist ResearchSeed -> acquisition run -> frozen L0.5 EvidencePack."""
    project_dir = Path(project_dir)
    run_id = str(run_id)
    payload = {
        "schema_version": EVIDENCE_BINDING_SCHEMA_VERSION,
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "research_seed": manifest_entry(seed),
        "evidence_run": _current_evidence_run_entry(project_dir, seed, run_id),
        "evidence_pack": _current_evidence_pack_entry(project_dir, seed, run_id),
    }
    path = _evidence_binding_path(project_dir, seed, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchSeedError(f"L1 evidence binding is unreadable: {exc}") from exc
        if existing != payload:
            raise ResearchSeedError(
                "L1 evidence binding already exists with different provenance"
            )
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    return evidence_binding_manifest_entry(project_dir, seed, run_id)


def load_l1_evidence_binding(project_dir, seed, run_id) -> dict:
    """Load and revalidate ResearchSeed, exact run, and frozen EvidencePack."""
    from research_loop import l05_curie

    project_dir = Path(project_dir)
    run_id = str(run_id)
    path = _evidence_binding_path(project_dir, seed, run_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchSeedError(
            f"L1 research-seed evidence binding is missing or invalid: {exc}"
        ) from exc
    expected_seed = manifest_entry(seed)
    if payload.get("schema_version") != EVIDENCE_BINDING_SCHEMA_VERSION:
        raise ResearchSeedError("L1 evidence binding schema is invalid")
    if str(payload.get("candidate_id") or "") != str(seed["candidate_id"]):
        raise ResearchSeedError("L1 evidence binding candidate does not match research seed")
    if str(payload.get("round_id") or "") != str(seed["round_id"]):
        raise ResearchSeedError("L1 evidence binding round does not match research seed")
    if payload.get("research_seed") != expected_seed:
        raise ResearchSeedError("L1 evidence binding research seed has changed")

    current_run = _current_evidence_run_entry(project_dir, seed, run_id)
    if payload.get("evidence_run") != current_run:
        raise ResearchSeedError(
            "L1 evidence run has changed since it was bound to the research seed"
        )
    evidence_pack = payload.get("evidence_pack")
    if not isinstance(evidence_pack, dict):
        raise ResearchSeedError("L1 evidence binding has no frozen L0.5 EvidencePack")
    try:
        frozen = l05_curie.load_frozen_evidence_pack(
            project_dir,
            evidence_pack,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=expected_seed["seed_sha256"],
        )
    except l05_curie.CurieContractError as exc:
        raise ResearchSeedError(f"frozen L0.5 EvidencePack is invalid: {exc}") from exc
    if str(frozen.get("source_run_id") or "") != run_id:
        raise ResearchSeedError(
            "frozen L0.5 EvidencePack source_run_id changed since binding"
        )
    return payload


def evidence_binding_manifest_entry(project_dir, seed, run_id) -> dict:
    """Compact receipt for the validated L0 -> L0.5 -> L1 provenance edge."""
    project_dir = Path(project_dir)
    run_id = str(run_id)
    payload = load_l1_evidence_binding(project_dir, seed, run_id)
    path = _evidence_binding_path(project_dir, seed, run_id)
    try:
        relative_path = path.relative_to(project_dir).as_posix()
    except ValueError:
        relative_path = path.as_posix()
    pack = payload["evidence_pack"]
    return {
        "schema_version": EVIDENCE_BINDING_SCHEMA_VERSION,
        "artifact_path": relative_path,
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "seed_sha256": str(payload["research_seed"]["seed_sha256"]),
        "evidence_run_id": run_id,
        "evidence_run_sha256": str(payload["evidence_run"]["sha256"]),
        "evidence_pack_id": str(pack["pack_id"]),
        "evidence_pack_version": int(pack["version"]),
        "evidence_pack_path": str(pack["artifact_path"]),
        "evidence_pack_sha256": str(pack["artifact_sha256"]),
        "evidence_pack_content_sha256": str(pack["content_sha256"]),
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
