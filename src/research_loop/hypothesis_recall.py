"""Cursor-bound historical hypothesis recall over the finalized pool."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_loop.hypothesis_ledger import (
    HypothesisLedger,
    LedgerError,
    canonical_json,
    content_hash,
)
from research_loop.hypothesis_pool import build_pool


RECALL_SCHEMA_VERSION = "HypothesisRecall/v1"
_TOKEN = re.compile(r"[\w]+", flags=re.UNICODE)
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_component(value: str, label: str) -> str:
    value = str(value)
    if not value or not _SAFE_COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise LedgerError(f"invalid hypothesis-recall {label}: {value!r}")
    return value


def _terms(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", str(value)).casefold()
    return sorted(set(_TOKEN.findall(normalized.replace("-", " "))))


def _hash_body(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_hash", "generated_at"}
    }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recall_path(
    project_dir: str | Path,
    candidate_id: str,
    round_id: str,
) -> Path:
    candidate = _safe_component(candidate_id, "candidate_id")
    round_value = _safe_component(round_id, "round_id")
    return (
        Path(project_dir)
        / "08_Audit"
        / "hypothesis_recall"
        / f"{candidate}_round_{round_value}.json"
    )


def _result(record: dict[str, Any], query_terms: set[str]) -> dict[str, Any] | None:
    record_terms = set(_terms(
        " ".join([record["statement"], record["operationalization"]])
    ))
    overlap = query_terms & record_terms
    keyword_score = (
        len(overlap) / len(query_terms)
        if query_terms
        else 0.0
    )
    if query_terms and keyword_score <= 0:
        return None
    latest = record.get("latest_occurrence") or {}
    return {
        "hypothesis_id": record["hypothesis_id"],
        "hypothesis_family_id": record["hypothesis_family_id"],
        "statement": record["statement"],
        "operationalization": record["operationalization"],
        "falsification_criteria": record["falsification_criteria"],
        "epistemic_status": record["epistemic_status"],
        "latest_workflow_status": record["latest_workflow_status"],
        "reactivation_eligibility": record["reactivation_eligibility"],
        "reactivation_requirements": record["reactivation_requirements"],
        "source_occurrence_id": latest.get("occurrence_id"),
        "unresolved_blocker_event_ids": record["unresolved_blocker_event_ids"],
        "scores": {
            "exact_hypothesis": 0,
            "exact_family": 0,
            "fts": 0.0,
            "keyword": keyword_score,
        },
        "matched_terms": sorted(overlap),
    }


def create_recall(
    ledger: HypothesisLedger,
    project_dir: str | Path,
    candidate_id: str,
    round_id: str,
    *,
    query_text: str,
    limit: int = 50,
    as_of: int | None = None,
) -> dict[str, Any]:
    """Create an immutable deterministic recall artifact for one L1 round."""
    if limit < 1 or limit > 200:
        raise LedgerError("hypothesis-recall limit must be between 1 and 200")
    project = Path(project_dir)
    binding = ledger.require_activated_project(project)
    candidate = _safe_component(candidate_id, "candidate_id")
    round_value = _safe_component(round_id, "round_id")
    query_terms = set(_terms(query_text))
    pool = build_pool(ledger, as_of=as_of)

    results = []
    for record in pool["records"]:
        recalled = _result(record, query_terms)
        if recalled is not None:
            results.append(recalled)
    results.sort(
        key=lambda item: (
            -int(item["scores"]["exact_hypothesis"]),
            -int(item["scores"]["exact_family"]),
            -float(item["scores"]["fts"]),
            -float(item["scores"]["keyword"]),
            str(item["hypothesis_id"]),
        )
    )
    results = results[:limit]

    body = {
        "schema_version": RECALL_SCHEMA_VERSION,
        "store_id": ledger.store_id,
        "project_id": str(binding["project_id"]),
        "candidate_id": candidate,
        "round_id": round_value,
        "as_of_commit_seq": int(pool["as_of_commit_seq"]),
        "query": {
            "text": str(query_text),
            "normalized_terms": sorted(query_terms),
            "ranking_method": "token-overlap-v1",
            "limit": int(limit),
        },
        "results": results,
    }
    artifact = {
        **body,
        "generated_at": _now(),
        "artifact_hash": content_hash(body),
    }
    target = recall_path(project, candidate, round_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = load_recall(project, candidate, round_value)
        if existing["artifact_hash"] != artifact["artifact_hash"]:
            raise LedgerError(f"hypothesis-recall artifact collision: {target}")
        validate_recall(
            ledger,
            project,
            existing,
            expected_candidate_id=candidate,
            expected_round_id=round_value,
        )
        return existing
    target.write_text(canonical_json(artifact), encoding="utf-8")
    return artifact


def load_recall(
    project_dir: str | Path,
    candidate_id: str,
    round_id: str,
) -> dict[str, Any]:
    """Load and internally authenticate one recall artifact."""
    target = recall_path(project_dir, candidate_id, round_id)
    try:
        artifact = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"hypothesis-recall artifact is missing or invalid: {target}") from exc
    if artifact.get("schema_version") != RECALL_SCHEMA_VERSION:
        raise LedgerError("hypothesis-recall schema version is invalid")
    expected = content_hash(_hash_body(artifact))
    if artifact.get("artifact_hash") != expected:
        raise LedgerError(f"hypothesis-recall artifact hash mismatch: {target}")
    return artifact


def validate_recall(
    ledger: HypothesisLedger,
    project_dir: str | Path,
    artifact: dict[str, Any],
    *,
    expected_candidate_id: str,
    expected_round_id: str,
) -> None:
    """Validate recall identity and every referenced fact at its fixed cursor."""
    project = Path(project_dir)
    binding = ledger.require_activated_project(project)
    expected = {
        "schema_version": RECALL_SCHEMA_VERSION,
        "store_id": ledger.store_id,
        "project_id": str(binding["project_id"]),
        "candidate_id": str(expected_candidate_id),
        "round_id": str(expected_round_id),
    }
    for field, value in expected.items():
        if str(artifact.get(field) or "") != value:
            raise LedgerError(f"hypothesis-recall {field} mismatch")
    if artifact.get("artifact_hash") != content_hash(_hash_body(artifact)):
        raise LedgerError("hypothesis-recall artifact hash mismatch")
    try:
        cursor = int(artifact["as_of_commit_seq"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerError("hypothesis-recall cursor is invalid") from exc
    pool = build_pool(ledger, as_of=cursor)
    by_hypothesis = {
        record["hypothesis_id"]: record for record in pool["records"]
    }
    for result in artifact.get("results") or []:
        hypothesis_id = str(result.get("hypothesis_id") or "")
        record = by_hypothesis.get(hypothesis_id)
        if record is None:
            raise LedgerError(
                f"hypothesis-recall references non-finalized hypothesis: {hypothesis_id}"
            )
        if str(result.get("hypothesis_family_id") or "") != record["hypothesis_family_id"]:
            raise LedgerError(
                f"hypothesis-recall family mismatch: {hypothesis_id}"
            )
        occurrence_ids = {
            item["occurrence_id"] for item in record["occurrences"]
        }
        source_occurrence = result.get("source_occurrence_id")
        if source_occurrence and source_occurrence not in occurrence_ids:
            raise LedgerError(
                f"hypothesis-recall occurrence mismatch: {source_occurrence}"
            )
        blockers = set(result.get("unresolved_blocker_event_ids") or [])
        if not blockers.issubset(set(record["unresolved_blocker_event_ids"])):
            raise LedgerError(
                f"hypothesis-recall blocker mismatch: {hypothesis_id}"
            )


def recall_manifest_entry(
    project_dir: str | Path,
    candidate_id: str,
    round_id: str,
) -> dict[str, Any]:
    """Return exact file and content bindings for ContextManifest/v2."""
    target = recall_path(project_dir, candidate_id, round_id)
    artifact = load_recall(project_dir, candidate_id, round_id)
    return {
        "artifact_path": str(target),
        "artifact_sha256": _file_sha256(target),
        "artifact_hash": artifact["artifact_hash"],
        "as_of_commit_seq": artifact["as_of_commit_seq"],
        "returned_hypothesis_ids": [
            item["hypothesis_id"] for item in artifact["results"]
        ],
    }
