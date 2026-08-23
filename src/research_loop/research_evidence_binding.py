"""Canonical immutable binding from the L0 ResearchSeed to the L0.5 evidence run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_loop import deep_research, research_seed


SCHEMA_VERSION = "L0.5ResearchEvidenceBinding/v1"
TARGET_NODE = "L0.5"


class ResearchEvidenceBindingError(ValueError):
    """Raised when the canonical L0.5 evidence handoff is missing or drifts."""


def _binding_path(project_dir, seed) -> Path:
    """One immutable binding per canonical ResearchSeed.

    Using only the seed hash deliberately prevents a second successful research
    run from silently replacing the frozen corpus for the same scientific state.
    """
    suffix = research_seed.seed_sha256(seed)[:24]
    return (
        Path(project_dir)
        / "08_Audit"
        / "research_seed_bindings"
        / f"L0_5_{suffix}.json"
    )


def binding_path(project_dir, seed) -> Path:
    return _binding_path(project_dir, seed)


def _evidence_run_entry(project_dir, seed, run_id) -> dict:
    try:
        evidence = deep_research.evidence_artifact_manifest(
            project_dir,
            str(seed["candidate_id"]),
            TARGET_NODE,
            str(run_id),
        )
    except deep_research.DeepResearchError as exc:
        raise ResearchEvidenceBindingError(
            f"L0.5 evidence run is invalid: {exc}"
        ) from exc

    expected = {
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "target_node": TARGET_NODE,
    }
    for field, expected_value in expected.items():
        if str(evidence.get(field) or "") != expected_value:
            raise ResearchEvidenceBindingError(
                f"L0.5 evidence run {field} does not match canonical ResearchSeed"
            )
    run_file = next(
        (item for item in evidence.get("files", []) if item.get("kind") == "run"),
        None,
    )
    if not isinstance(run_file, dict):
        raise ResearchEvidenceBindingError(
            "L0.5 evidence manifest has no immutable run file"
        )
    return {
        "run_id": str(run_id),
        "path": str(run_file["path"]),
        "sha256": str(run_file["sha256"]),
    }


def write_binding(project_dir, seed, run_id) -> dict:
    project_dir = Path(project_dir)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "research_seed": research_seed.manifest_entry(seed),
        "evidence_run": _evidence_run_entry(project_dir, seed, run_id),
    }
    path = _binding_path(project_dir, seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResearchEvidenceBindingError(
                f"L0.5 evidence binding is unreadable: {exc}"
            ) from exc
        if existing != payload:
            raise ResearchEvidenceBindingError(
                "this ResearchSeed is already frozen to a different L0.5 evidence run"
            )
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    return manifest_entry(project_dir, seed)


def load_binding(project_dir, seed) -> dict:
    project_dir = Path(project_dir)
    path = _binding_path(project_dir, seed)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchEvidenceBindingError(
            f"L0.5 ResearchSeed evidence binding is missing or invalid: {exc}"
        ) from exc

    expected_seed = research_seed.manifest_entry(seed)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ResearchEvidenceBindingError("L0.5 evidence binding schema is invalid")
    if str(payload.get("candidate_id") or "") != str(seed["candidate_id"]):
        raise ResearchEvidenceBindingError("L0.5 binding candidate does not match ResearchSeed")
    if str(payload.get("round_id") or "") != str(seed["round_id"]):
        raise ResearchEvidenceBindingError("L0.5 binding round does not match ResearchSeed")
    if payload.get("research_seed") != expected_seed:
        raise ResearchEvidenceBindingError("L0.5 binding ResearchSeed has changed")

    run_id = str((payload.get("evidence_run") or {}).get("run_id") or "")
    if not run_id:
        raise ResearchEvidenceBindingError("L0.5 binding has no evidence run id")
    current_run = _evidence_run_entry(project_dir, seed, run_id)
    if payload.get("evidence_run") != current_run:
        raise ResearchEvidenceBindingError(
            "L0.5 evidence run has changed since it was frozen to the ResearchSeed"
        )
    return payload


def manifest_entry(project_dir, seed) -> dict:
    project_dir = Path(project_dir)
    payload = load_binding(project_dir, seed)
    path = _binding_path(project_dir, seed)
    evidence_run = payload["evidence_run"]
    try:
        relative = path.relative_to(project_dir).as_posix()
    except ValueError:
        relative = path.as_posix()
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_path": relative,
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidate_id": str(seed["candidate_id"]),
        "round_id": str(seed["round_id"]),
        "seed_sha256": str(payload["research_seed"]["seed_sha256"]),
        "evidence_run_id": str(evidence_run["run_id"]),
        "evidence_run_sha256": str(evidence_run["sha256"]),
        "target_node": TARGET_NODE,
    }


def run_id_for_seed(project_dir, seed) -> str:
    return str(load_binding(project_dir, seed)["evidence_run"]["run_id"])


def binding_state(project_dir, seed) -> tuple[str, str]:
    """Return (missing|valid|invalid, detail) without masking tampering."""
    path = _binding_path(project_dir, seed)
    if not path.is_file():
        return "missing", "no frozen L0.5 evidence binding for current ResearchSeed"
    try:
        entry = manifest_entry(project_dir, seed)
    except ResearchEvidenceBindingError as exc:
        return "invalid", str(exc)
    return "valid", str(entry["evidence_run_id"])
