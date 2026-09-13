"""Canonical L0 -> L0.5 -> L1 research-seed and evidence binding.

The L0 sidecar remains the sole source semantic authority and may preserve the
user's original Chinese or English wording. Before the scientific pipeline
consumes that semantic state, Chinese input is normalized exactly once into an
immutable English ResearchSeed projection. Every downstream consumer reads the
same English seed; none owns translation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_loop import l0_contract
from research_loop.l0_language import (
    L0LanguageError,
    classify_user_language,
    validate_internal_english,
)
from research_loop.paths import _candidate_file
from research_loop.yamlio import _load_yaml_front


SCHEMA_VERSION = "L1ResearchSeed/v1"
ENGLISH_SEED_ARTIFACT_SCHEMA_VERSION = "L1EnglishResearchSeedProjection/v1"
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


def _validated_l0_seed(project_dir, cand_id) -> dict:
    """Validate L0 and project the exact user-language semantic seed."""
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


def load_l0_research_seed(project_dir, cand_id) -> dict:
    """Return the validated raw L0 semantic projection before language normalization."""
    return _validated_l0_seed(project_dir, cand_id)


def _english_seed_path(project_dir, cand_id) -> Path:
    return (
        Path(project_dir)
        / "08_Audit"
        / "research_seed_bindings"
        / "english"
        / f"{cand_id}.json"
    )


def _english_projection(raw_seed: dict, fields: dict[str, str]) -> dict:
    question = validate_internal_english(
        fields.get("scientific_question"), name="ResearchSeed scientific_question"
    )
    hypothesis = validate_internal_english(
        fields.get("hypothesis_seed"), name="ResearchSeed hypothesis_seed"
    )
    result = dict(raw_seed)
    result["scientific_question"] = question
    result["hypothesis_seed"] = hypothesis
    return result


def write_english_research_seed(
    project_dir,
    raw_seed: dict,
    fields: dict[str, str],
    normalization_receipt: dict,
) -> dict:
    """Freeze the one English semantic projection for a Chinese L0 seed.

    This artifact is a derived projection, never a second L0 authority. It is
    byte-bound to the exact validated L0 seed and is immutable once written.
    """
    project = Path(project_dir)
    candidate_id = str(raw_seed.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ResearchSeedError("English ResearchSeed projection requires candidate_id")
    expected_raw = _validated_l0_seed(project, candidate_id)
    if expected_raw != raw_seed:
        raise ResearchSeedError(
            "English ResearchSeed projection source no longer matches canonical L0"
        )
    try:
        normalized_seed = _english_projection(raw_seed, fields)
    except L0LanguageError as exc:
        raise ResearchSeedError(str(exc)) from exc
    payload = {
        "schema_version": ENGLISH_SEED_ARTIFACT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": str(raw_seed["round_id"]),
        "source_l0_contract_sha256": str(raw_seed["l0_contract_sha256"]),
        "source_seed_sha256": seed_sha256(raw_seed),
        "normalized_seed": normalized_seed,
        "normalization_receipt": dict(normalization_receipt or {}),
    }
    path = _english_seed_path(project, candidate_id)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ResearchSeedError(
                f"English ResearchSeed projection is unreadable: {exc}"
            ) from exc
        if existing != raw:
            raise ResearchSeedError(
                "English ResearchSeed projection already exists with different bytes"
            )
    else:
        path.write_text(raw, encoding="utf-8")
    return normalized_seed


def _load_english_research_seed(project_dir, raw_seed: dict) -> dict:
    project = Path(project_dir)
    candidate_id = str(raw_seed["candidate_id"])
    path = _english_seed_path(project, candidate_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchSeedError(
            "Chinese L0 input requires a frozen English ResearchSeed projection: "
            f"{exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ResearchSeedError("English ResearchSeed projection must be an object")
    if payload.get("schema_version") != ENGLISH_SEED_ARTIFACT_SCHEMA_VERSION:
        raise ResearchSeedError("English ResearchSeed projection schema is invalid")
    expected = {
        "candidate_id": str(raw_seed["candidate_id"]),
        "round_id": str(raw_seed["round_id"]),
        "source_l0_contract_sha256": str(raw_seed["l0_contract_sha256"]),
        "source_seed_sha256": seed_sha256(raw_seed),
    }
    for field, value in expected.items():
        if str(payload.get(field) or "") != value:
            raise ResearchSeedError(
                f"English ResearchSeed projection {field} does not match canonical L0"
            )
    normalized = payload.get("normalized_seed")
    if not isinstance(normalized, dict):
        raise ResearchSeedError("English ResearchSeed projection has no normalized_seed")
    structural_fields = (
        "schema_version",
        "candidate_id",
        "round_id",
        "round_type",
        "l0_contract_schema_version",
        "l0_contract_path",
        "l0_contract_sha256",
    )
    for field in structural_fields:
        if str(normalized.get(field) or "") != str(raw_seed.get(field) or ""):
            raise ResearchSeedError(
                f"English ResearchSeed projection changed structural field {field}"
            )
    try:
        validate_internal_english(
            normalized.get("scientific_question"),
            name="ResearchSeed scientific_question",
        )
        validate_internal_english(
            normalized.get("hypothesis_seed"),
            name="ResearchSeed hypothesis_seed",
        )
    except L0LanguageError as exc:
        raise ResearchSeedError(str(exc)) from exc
    return normalized


def load_l1_research_seed(project_dir, cand_id):
    """Return the single canonical English semantic seed for the internal pipeline.

    English L0 input passes through unchanged. Chinese L0 input must first have
    one immutable English projection written by the L0.5 entry boundary. Other
    user languages fail closed and are never translated implicitly.
    """
    raw_seed = _validated_l0_seed(project_dir, cand_id)
    try:
        languages = {
            classify_user_language(
                raw_seed["scientific_question"],
                name="L0 scientific_question",
            ),
            classify_user_language(
                raw_seed["hypothesis_seed"],
                name="L0 hypothesis_seed",
            ),
        }
    except L0LanguageError as exc:
        raise ResearchSeedError(str(exc)) from exc
    if languages == {"en"}:
        try:
            validate_internal_english(
                raw_seed["scientific_question"],
                name="ResearchSeed scientific_question",
            )
            validate_internal_english(
                raw_seed["hypothesis_seed"],
                name="ResearchSeed hypothesis_seed",
            )
        except L0LanguageError as exc:
            raise ResearchSeedError(str(exc)) from exc
        return raw_seed
    return _load_english_research_seed(project_dir, raw_seed)


def seed_sha256(seed) -> str:
    """Content address of the complete semantic projection."""
    return hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()


def manifest_entry(seed) -> dict:
    """Compact receipt binding; semantic text remains in the canonical seed."""
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


def load_l1_evidence_binding(
    project_dir, seed, run_id, *, allow_legacy_source_identity: bool = False
) -> dict:
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
    if not isinstance(payload, dict):
        raise ResearchSeedError("L1 research-seed evidence binding must be an object")
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
            allow_legacy_source_identity=allow_legacy_source_identity,
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
    """Render the exact canonical English semantics consumed by Einstein."""
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
        "=== L1 RESEARCH SEED (canonical English L0 projection) ===\n"
        "AUTHORITY: validated L0 sidecar projected once into English; candidate "
        "frontmatter question/claim are not semantic inputs to L1.\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    )
