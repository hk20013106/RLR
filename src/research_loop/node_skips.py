"""Auditable conditional node-skip receipts."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path


L2_SKIP_THRESHOLD = 4
L2_SKIP_REASON = "hypothesis_count_lte_4"


class NodeSkipError(ValueError):
    """Raised when a node-skip receipt is missing or inconsistent."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt_path(project_dir: str | Path, candidate_id: str) -> Path:
    return Path(project_dir) / "08_Audit" / "node_skips" / f"{candidate_id}_L2.json"


def _load_l1(path: Path) -> tuple[dict, int]:
    try:
        delta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NodeSkipError(f"cannot read committed L1 delta: {path}") from exc
    hypotheses = delta.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise NodeSkipError("committed L1 delta has no hypothesis list")
    ids = []
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict):
            raise NodeSkipError("committed L1 hypothesis is not an object")
        hypothesis_id = str(hypothesis.get("hypothesis_id") or "").strip()
        if not hypothesis_id:
            raise NodeSkipError("committed L1 hypothesis lacks hypothesis_id")
        ids.append(hypothesis_id)
    if len(ids) != len(set(ids)):
        raise NodeSkipError("committed L1 hypothesis IDs are not unique")
    return delta, len(ids)


def l2_skip_decision(hypothesis_count: int) -> str:
    """Return ``invalid``, ``skip``, or ``run`` for an L1 hypothesis count."""
    if hypothesis_count <= 0:
        return "invalid"
    if hypothesis_count <= L2_SKIP_THRESHOLD:
        return "skip"
    return "run"


def ensure_l2_skip_receipt(
    project_dir: str | Path,
    candidate_id: str,
    l1_delta_path: str | Path,
) -> dict:
    """Create or return the deterministic, hash-bound L2 skip receipt."""
    project = Path(project_dir)
    l1_path = Path(l1_delta_path)
    _, count = _load_l1(l1_path)
    if l2_skip_decision(count) != "skip":
        raise NodeSkipError(
            f"L2 skip is not permitted for {count} hypotheses; threshold is {L2_SKIP_THRESHOLD}"
        )
    binding_path = project / "00_Preflight" / "hypothesis_store_binding.json"
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        project_id = str(binding["project_id"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise NodeSkipError("project ledger binding is required for an L2 skip") from exc
    try:
        relative_l1 = l1_path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError as exc:
        raise NodeSkipError("committed L1 delta is outside the project") from exc
    record = {
        "schema_version": "NodeSkipReceipt/v1",
        "project_id": project_id,
        "candidate_id": str(candidate_id),
        "skipped_node": "L2",
        "source_node": "L1",
        "l1_delta_path": relative_l1,
        "l1_delta_sha256": _sha256(l1_path),
        "hypothesis_count": count,
        "threshold": L2_SKIP_THRESHOLD,
        "reason": L2_SKIP_REASON,
        "created_at": _now(),
    }
    path = _receipt_path(project, candidate_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        ok, current = validate_l2_skip_receipt(project, candidate_id, l1_path)
        if not ok:
            raise NodeSkipError(str(current))
        return current
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return record


def validate_l2_skip_receipt(
    project_dir: str | Path,
    candidate_id: str,
    l1_delta_path: str | Path,
) -> tuple[bool, dict | str]:
    """Validate receipt identity, L1 hash, count, and threshold semantics."""
    project = Path(project_dir)
    l1_path = Path(l1_delta_path)
    path = _receipt_path(project, candidate_id)
    if not path.is_file():
        return False, "L2 skip receipt is missing"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        binding = json.loads(
            (project / "00_Preflight" / "hypothesis_store_binding.json").read_text(
                encoding="utf-8"
            )
        )
        _, count = _load_l1(l1_path)
        relative_l1 = l1_path.resolve().relative_to(project.resolve()).as_posix()
    except (OSError, ValueError, json.JSONDecodeError, NodeSkipError) as exc:
        return False, f"L2 skip receipt cannot be verified: {exc}"
    expected = {
        "schema_version": "NodeSkipReceipt/v1",
        "project_id": str(binding.get("project_id") or ""),
        "candidate_id": str(candidate_id),
        "skipped_node": "L2",
        "source_node": "L1",
        "l1_delta_path": relative_l1,
        "l1_delta_sha256": _sha256(l1_path),
        "hypothesis_count": count,
        "threshold": L2_SKIP_THRESHOLD,
        "reason": L2_SKIP_REASON,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            return False, f"L2 skip receipt {field} does not match the committed L1 delta"
    if l2_skip_decision(count) != "skip":
        return False, "L2 skip receipt is invalid for the current hypothesis count"
    if not str(record.get("created_at") or "").strip():
        return False, "L2 skip receipt lacks created_at"
    return True, record
