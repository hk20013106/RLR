"""Canonical L0 research-seed projection and evidence binding.

The L0 sidecar remains the sole semantic authority. This module validates that
contract at the boundary of use, projects the exact semantic seed consumed by
Curie/Einstein, and owns the single immutable provenance edge from a
ResearchSeed to an exact Deep Research evidence run.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from research_loop import l0_contract
from research_loop.paths import _candidate_file
from research_loop.yamlio import _load_yaml_front


SCHEMA_VERSION = "L1ResearchSeed/v1"
RESEARCH_EVIDENCE_BINDING_SCHEMA_VERSION = "ResearchSeedEvidenceBinding/v1"
EVIDENCE_BINDING_SCHEMA_VERSION = "L1ResearchEvidenceBinding/v1"  # legacy reader/writer
DEFAULT_RESEARCH_TARGET = "L0.5"


class ResearchSeedError(ValueError):
    """Raised when canonical L0 semantics or their evidence binding are invalid."""


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_l1_research_seed(project_dir, cand_id):
    """Validate L0 and return the single canonical semantic seed for research/L1.

    No candidate-frontmatter ``question``/``claim`` fallback is permitted. A
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
    """Compact ResearchSeed receipt; semantic text remains authoritative in L0."""
    return {
        "schema_version": str(seed["schema_version"]),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "round_type": str(seed["round_type"]),
        "l0_contract_path": str(seed["l0_contract_path"]),
        "l0_contract_sha256": str(seed["l0_contract_sha256"]),
        "seed_sha256": seed_sha256(seed),
    }


def _target_slug(target_node: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", str(target_node)).strip("_")
    if not value:
        raise ResearchSeedError("evidence binding target_node is required")
    return value


def research_evidence_binding_path(
    project_dir, seed, target_node: str = DEFAULT_RESEARCH_TARGET
) -> Path:
    """Return the one-per-ResearchSeed binding path for a research stage."""
    suffix = seed_sha256(seed)[:24]
    return (
        Path(project_dir)
        / "08_Audit"
        / "research_seed_bindings"
        / f"{_target_slug(target_node)}_{suffix}.json"
    )


def _legacy_l1_binding_path(project_dir, seed, run_id) -> Path:
    identity = f"{seed['candidate_id']}:{run_id}"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return (
        Path(project_dir)
        / "08_Audit"
        / "research_seed_bindings"
        / f"L1_{suffix}.json"
    )


def _current_evidence_run_entry(project_dir, seed, run_id, target_node: str) -> dict:
    from research_loop import deep_research

    try:
        evidence = deep_research.evidence_artifact_manifest(
            project_dir,
            str(seed["candidate_id"]),
            str(target_node),
            str(run_id),
        )
    except deep_research.DeepResearchError as exc:
        raise ResearchSeedError(
            f"{target_node} evidence run is invalid: {exc}"
        ) from exc

    expected = {
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "target_node": str(target_node),
    }
    for field, value in expected.items():
        if str(evidence.get(field) or "") != value:
            raise ResearchSeedError(
                f"{target_node} evidence run {field} does not match canonical ResearchSeed"
            )
    run_file = next(
        (item for item in evidence.get("files", []) if item.get("kind") == "run"),
        None,
    )
    if not isinstance(run_file, dict):
        raise ResearchSeedError(
            f"{target_node} evidence run manifest has no immutable run file"
        )
    return {
        "run_id": str(run_id),
        "path": str(run_file["path"]),
        "sha256": str(run_file["sha256"]),
    }


def _binding_payload(
    project_dir,
    seed,
    run_id,
    target_node: str,
    *,
    schema_version: str,
    include_target: bool,
) -> dict:
    payload = {
        "schema_version": schema_version,
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "research_seed": manifest_entry(seed),
        "evidence_run": _current_evidence_run_entry(
            project_dir, seed, run_id, target_node
        ),
    }
    if include_target:
        payload["target_node"] = str(target_node)
    return payload


def _validate_binding_payload(
    project_dir,
    seed,
    payload,
    *,
    target_node: str,
    allowed_schema_versions: set[str],
) -> dict:
    if not isinstance(payload, dict):
        raise ResearchSeedError("evidence binding must be a JSON object")
    if payload.get("schema_version") not in allowed_schema_versions:
        raise ResearchSeedError("evidence binding schema is invalid")
    if "target_node" in payload and str(payload.get("target_node") or "") != str(target_node):
        raise ResearchSeedError("evidence binding target node does not match request")
    if str(payload.get("candidate_id") or "") != str(seed["candidate_id"]):
        raise ResearchSeedError("evidence binding candidate does not match ResearchSeed")
    if str(payload.get("round_id") or "") != str(seed["round_id"]):
        raise ResearchSeedError("evidence binding round does not match ResearchSeed")
    expected_seed = manifest_entry(seed)
    if payload.get("research_seed") != expected_seed:
        raise ResearchSeedError("evidence binding ResearchSeed has changed")
    run_id = str((payload.get("evidence_run") or {}).get("run_id") or "")
    if not run_id:
        raise ResearchSeedError("evidence binding has no evidence run id")
    current_run = _current_evidence_run_entry(
        project_dir, seed, run_id, target_node
    )
    if payload.get("evidence_run") != current_run:
        raise ResearchSeedError(
            "evidence run has changed since it was frozen to the ResearchSeed"
        )
    return payload


def _write_binding(
    project_dir,
    seed,
    run_id,
    *,
    target_node: str,
    path: Path,
    schema_version: str,
    include_target: bool,
) -> dict:
    project_dir = Path(project_dir)
    payload = _binding_payload(
        project_dir,
        seed,
        str(run_id),
        target_node,
        schema_version=schema_version,
        include_target=include_target,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchSeedError(f"evidence binding is unreadable: {exc}") from exc
        if existing != payload:
            raise ResearchSeedError(
                f"ResearchSeed is already frozen to a different {target_node} evidence run"
            )
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    return payload


def _load_binding(
    project_dir,
    seed,
    *,
    target_node: str,
    path: Path,
    allowed_schema_versions: set[str],
) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchSeedError(
            f"{target_node} ResearchSeed evidence binding is missing or invalid: {exc}"
        ) from exc
    return _validate_binding_payload(
        Path(project_dir),
        seed,
        payload,
        target_node=target_node,
        allowed_schema_versions=allowed_schema_versions,
    )


def _binding_manifest_entry(project_dir, seed, payload, path: Path, target_node: str) -> dict:
    project_dir = Path(project_dir)
    try:
        relative_path = path.relative_to(project_dir).as_posix()
    except ValueError:
        relative_path = path.as_posix()
    evidence_run = payload["evidence_run"]
    return {
        "schema_version": str(payload["schema_version"]),
        "artifact_path": relative_path,
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "seed_sha256": str(payload["research_seed"]["seed_sha256"]),
        "evidence_run_id": str(evidence_run["run_id"]),
        "evidence_run_sha256": str(evidence_run["sha256"]),
        "target_node": str(target_node),
    }


def write_research_evidence_binding(
    project_dir,
    seed,
    run_id,
    target_node: str = DEFAULT_RESEARCH_TARGET,
) -> dict:
    """Freeze one exact evidence run to one ResearchSeed for ``target_node``."""
    path = research_evidence_binding_path(project_dir, seed, target_node)
    payload = _write_binding(
        project_dir,
        seed,
        run_id,
        target_node=target_node,
        path=path,
        schema_version=RESEARCH_EVIDENCE_BINDING_SCHEMA_VERSION,
        include_target=True,
    )
    return _binding_manifest_entry(project_dir, seed, payload, path, target_node)


def load_research_evidence_binding(
    project_dir,
    seed,
    target_node: str = DEFAULT_RESEARCH_TARGET,
) -> dict:
    """Load and revalidate the exact ResearchSeed -> evidence-run edge."""
    path = research_evidence_binding_path(project_dir, seed, target_node)
    return _load_binding(
        project_dir,
        seed,
        target_node=target_node,
        path=path,
        allowed_schema_versions={RESEARCH_EVIDENCE_BINDING_SCHEMA_VERSION},
    )


def research_evidence_binding_manifest_entry(
    project_dir,
    seed,
    target_node: str = DEFAULT_RESEARCH_TARGET,
) -> dict:
    payload = load_research_evidence_binding(project_dir, seed, target_node)
    path = research_evidence_binding_path(project_dir, seed, target_node)
    return _binding_manifest_entry(project_dir, seed, payload, path, target_node)


def research_evidence_run_id(
    project_dir,
    seed,
    target_node: str = DEFAULT_RESEARCH_TARGET,
) -> str:
    return str(
        load_research_evidence_binding(project_dir, seed, target_node)["evidence_run"]["run_id"]
    )


def research_evidence_binding_state(
    project_dir,
    seed,
    target_node: str = DEFAULT_RESEARCH_TARGET,
) -> tuple[str, str]:
    """Return ``(missing|valid|invalid, detail)`` without masking tampering."""
    path = research_evidence_binding_path(project_dir, seed, target_node)
    if not path.is_file():
        return "missing", f"no frozen {target_node} evidence binding for current ResearchSeed"
    try:
        entry = research_evidence_binding_manifest_entry(
            project_dir, seed, target_node
        )
    except ResearchSeedError as exc:
        return "invalid", str(exc)
    return "valid", str(entry["evidence_run_id"])


# Legacy L1 binding API. These names remain compatibility delegates only; all
# validation/persistence logic is shared with the generic implementation above.
def write_l1_evidence_binding(project_dir, seed, run_id) -> dict:
    path = _legacy_l1_binding_path(project_dir, seed, run_id)
    payload = _write_binding(
        project_dir,
        seed,
        run_id,
        target_node="L1",
        path=path,
        schema_version=EVIDENCE_BINDING_SCHEMA_VERSION,
        include_target=False,
    )
    return _binding_manifest_entry(project_dir, seed, payload, path, "L1")


def load_l1_evidence_binding(project_dir, seed, run_id) -> dict:
    path = _legacy_l1_binding_path(project_dir, seed, run_id)
    payload = _load_binding(
        project_dir,
        seed,
        target_node="L1",
        path=path,
        allowed_schema_versions={EVIDENCE_BINDING_SCHEMA_VERSION},
    )
    if str(payload["evidence_run"]["run_id"]) != str(run_id):
        raise ResearchSeedError("L1 evidence binding run id does not match request")
    return payload


def evidence_binding_manifest_entry(project_dir, seed, run_id) -> dict:
    payload = load_l1_evidence_binding(project_dir, seed, run_id)
    path = _legacy_l1_binding_path(project_dir, seed, run_id)
    return _binding_manifest_entry(project_dir, seed, payload, path, "L1")


def render_context_block(seed) -> str:
    """Render the exact canonical semantics consumed by Curie/Einstein."""
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
        "are not semantic inputs to research or L1.\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    )
