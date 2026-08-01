"""Immutable registration of user-supplied literature PDFs.

Registration proves file identity and candidate ownership only. It never
converts a PDF into accepted L4 evidence; extraction and evidence validation
remain separate fail-closed steps.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path


class UserSourceError(ValueError):
    """Raised when a user literature source cannot be registered or verified."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_filename(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "source"
    return f"{stem}.pdf"


def _candidate_file(project_dir: Path, candidate_id: str) -> Path:
    return project_dir / "01_Candidates" / f"{candidate_id}.md"


def _candidate_dir(project_dir: Path, candidate_id: str) -> Path:
    return project_dir / "09_Literature_Database" / "user_sources" / candidate_id


def _load_record(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserSourceError(f"invalid user-source sidecar: {path}") from exc
    if not isinstance(value, dict):
        raise UserSourceError(f"invalid user-source sidecar: {path}")
    return value


def _verified_record(project: Path, sidecar: Path, candidate_id: str) -> dict:
    record = _load_record(sidecar)
    if record.get("candidate_id") != candidate_id:
        raise UserSourceError(f"user-source sidecar belongs to another candidate: {sidecar}")
    stored = project / str(record.get("stored_path") or "")
    if not stored.is_file():
        raise UserSourceError(f"registered PDF is missing: {stored}")
    try:
        digest = hashlib.sha256(stored.read_bytes()).hexdigest()
    except OSError as exc:
        raise UserSourceError(f"registered PDF is unreadable: {stored}") from exc
    if digest != record.get("sha256"):
        raise UserSourceError(f"registered PDF bytes do not match sidecar: {stored}")
    return record


def register_pdf(
    project_dir: str | Path,
    candidate_id: str,
    source_file: str | Path,
    *,
    doi: str = "",
    pmid: str = "",
    url: str = "",
) -> dict:
    """Copy a readable PDF into candidate-scoped immutable storage.

    Re-registering identical bytes for the same candidate is idempotent even
    when the operator supplies a different local filename.
    """
    project = Path(project_dir)
    candidate_id = str(candidate_id).strip()
    if not candidate_id or not _candidate_file(project, candidate_id).is_file():
        raise UserSourceError(f"candidate not found: {candidate_id or '<empty>'}")

    source = Path(source_file)
    if not source.is_file():
        raise UserSourceError(f"PDF source is not a readable file: {source}")
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise UserSourceError(f"PDF source is not readable: {source}") from exc
    if not data.startswith(b"%PDF-"):
        raise UserSourceError(f"source is not a PDF: {source}")

    digest = hashlib.sha256(data).hexdigest()
    user_source_id = f"USR_{digest[:16]}"
    target_dir = _candidate_dir(project, candidate_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Identity is candidate + complete content hash, not the incoming filename.
    # This prevents duplicate registrations when the same PDF is renamed.
    for existing_sidecar in sorted(target_dir.glob("*.json")):
        try:
            record = _verified_record(project, existing_sidecar, candidate_id)
        except UserSourceError:
            continue
        if (record.get("sha256") == digest
                and record.get("user_source_id") == user_source_id):
            return record

    target = target_dir / f"{digest[:16]}_{_safe_filename(source.name)}"
    sidecar = target.with_suffix(".json")
    if target.exists() or sidecar.exists():
        raise UserSourceError(f"user-source target already exists unexpectedly: {target}")
    target.write_bytes(data)

    record = {
        "schema_version": "UserLiteratureSource/v1",
        "user_source_id": user_source_id,
        "candidate_id": candidate_id,
        "original_filename": source.name,
        "stored_path": target.relative_to(project).as_posix(),
        "bytes": len(data),
        "sha256": digest,
        "doi": str(doi or "").strip(),
        "pmid": str(pmid or "").strip(),
        "url": str(url or "").strip(),
        "registered_at": _now(),
        "status": "registered",
        "extraction_status": "not_run",
        "consuming_evidence_run_ids": [],
        "registration_satisfies_l4": False,
    }
    sidecar.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return record


def registered_sources(project_dir: str | Path, candidate_id: str) -> list[dict]:
    """Return valid sidecar records registered for one candidate."""
    project = Path(project_dir)
    candidate_id = str(candidate_id)
    directory = _candidate_dir(project, candidate_id)
    if not directory.is_dir():
        return []
    records = []
    seen_hashes = set()
    for sidecar in sorted(directory.glob("*.json")):
        try:
            record = _verified_record(project, sidecar, candidate_id)
        except UserSourceError:
            continue
        digest = str(record.get("sha256") or "")
        if not digest or digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        records.append(record)
    return records


def verify_registered_source(
    project_dir: str | Path,
    candidate_id: str,
    user_source_id: str,
    sha256: str,
) -> tuple[bool, str]:
    """Verify candidate ownership and byte identity for a registered PDF."""
    for record in registered_sources(project_dir, candidate_id):
        if record.get("user_source_id") != user_source_id:
            continue
        if record.get("sha256") != sha256:
            return False, "registered PDF SHA256 does not match the evidence source"
        return True, ""
    return False, "registered PDF is not owned by this candidate"
