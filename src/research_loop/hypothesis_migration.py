"""Project-atomic legacy delta migration into the hypothesis ledger."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from research_loop.delta import DELTA_PERSONA
from research_loop.hypothesis_contracts import validate_submission
from research_loop.hypothesis_ledger import (
    HypothesisLedger,
    LedgerError,
    _uuid,
    canonical_json,
    content_hash,
)


MIGRATION_SCHEMA_VERSION = "1.0"
_NODE_RE = re.compile(r"(?:^|_)(L(?:8\.5|10[ab]|9[ab]|[0-8]))_")
_CANDIDATE_RE = re.compile(r"^(C[^_]+)_")


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, project_dir: Path) -> str:
    return path.relative_to(project_dir).as_posix()


def _candidate_rounds(project_dir: Path) -> dict[str, str]:
    rounds: dict[str, str] = {}
    for path in (project_dir / "01_Candidates").glob("C*.md"):
        text = path.read_text(encoding="utf-8")
        candidate = re.search(r"(?m)^candidate_id:\s*['\"]?([^'\"\r\n]+)", text)
        round_id = re.search(r"(?m)^round_id:\s*['\"]?([^'\"\r\n]+)", text)
        rounds[(candidate.group(1).strip() if candidate else path.stem)] = (
            round_id.group(1).strip() if round_id else ""
        )
    return rounds


def _legacy_sources(project_dir: Path) -> list[dict[str, Any]]:
    rounds = _candidate_rounds(project_dir)
    receipt_owners: dict[tuple[str, str], set[str]] = {}
    audit = project_dir / "08_Audit"
    for receipt_path in audit.glob("run_receipt_*.json") if audit.is_dir() else []:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            digest = str(receipt.get("output_delta_sha256") or "")
            candidate = str(receipt.get("candidate_id") or "")
            output = str(receipt.get("output_delta_path") or "")
            if digest and candidate:
                receipt_owners.setdefault((digest, Path(output).name), set()).add(candidate)
                receipt_owners.setdefault((digest, ""), set()).add(candidate)
        except (OSError, json.JSONDecodeError):
            continue
    sources: list[dict[str, Any]] = []
    notes = project_dir / "02_Agent_Notes"
    for path in sorted(notes.rglob("*_delta.json")) if notes.is_dir() else []:
        if path.name.endswith("_delta.v2.json"):
            continue
        raw_hash = _sha256_file(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sources.append({"source_path": _relative(path, project_dir),
                            "source_sha256": raw_hash, "reason": f"invalid JSON: {exc}"})
            continue
        match = _NODE_RE.search(path.name)
        node = match.group(1) if match else None
        candidate_id = str(data.get("candidate_id") or "")
        if not candidate_id:
            owner = _CANDIDATE_RE.match(path.name)
            candidate_id = owner.group(1) if owner else ""
        if not candidate_id:
            owners = receipt_owners.get((raw_hash, path.name), set())
            if not owners:
                owners = receipt_owners.get((raw_hash, ""), set())
            if len(owners) == 1:
                candidate_id = next(iter(owners))
        item = {"source_path": _relative(path, project_dir),
                "source_sha256": raw_hash, "candidate_id": candidate_id,
                "round_id": rounds.get(candidate_id, ""), "node": node or "",
                "data": data}
        reasons = []
        if not node:
            reasons.append("node cannot be proven from source path")
        if not candidate_id or candidate_id not in rounds:
            reasons.append("candidate ownership cannot be proven")
        if not item["round_id"]:
            reasons.append("round ownership cannot be proven")
        if node and not validate_submission(node, data):
            item["v2_delta"] = data
        else:
            reasons.append("legacy payload requires explicit v2 attribution")
        item["reason"] = "; ".join(reasons)
        sources.append(item)
    return sources


def dry_run(project_dir: str | Path, ledger: HypothesisLedger) -> tuple[dict[str, Any], Path]:
    project = Path(project_dir)
    sources = _legacy_sources(project)
    scan_material = [{key: value for key, value in item.items() if key != "data"}
                     for item in sources]
    scan_hash = content_hash(scan_material)
    project_id = _uuid("PROJECT", ledger.store_id, scan_hash)
    migration_id = _uuid("MIG", ledger.store_id, scan_hash)
    automatic = []
    unresolved = []
    for item in sources:
        public = {key: value for key, value in item.items() if key != "data"}
        (automatic if item.get("v2_delta") is not None and not item["reason"]
         else unresolved).append(public)
    report = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "migration_id": migration_id,
        "store_id": ledger.store_id,
        "project_id": project_id,
        "scan_hash": scan_hash,
        "automatic": automatic,
        "unresolved": unresolved,
    }
    report["dry_run_report_hash"] = content_hash(report)
    audit = project / "08_Audit" / "hypothesis_migration"
    audit.mkdir(parents=True, exist_ok=True)
    target = audit / f"{migration_id.replace(':', '_')}_dry_run.json"
    raw = canonical_json(report)
    if target.exists() and target.read_text(encoding="utf-8") != raw:
        raise LedgerError(f"migration dry-run report collision: {target}")
    if not target.exists():
        with target.open("x", encoding="utf-8") as handle:
            handle.write(raw)
    return report, target


def _load_resolution(project: Path, resolution_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    if resolution.get("schema_version") != MIGRATION_SCHEMA_VERSION:
        raise LedgerError("unsupported migration resolution schema_version")
    report_hash = resolution.get("dry_run_report_hash")
    reports = project / "08_Audit" / "hypothesis_migration"
    for path in reports.glob("*_dry_run.json") if reports.is_dir() else []:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("dry_run_report_hash") == report_hash:
            return resolution, report
    raise LedgerError("resolution dry_run_report_hash does not match a current dry-run report")


def _resolved_deltas(project: Path, resolution: dict[str, Any],
                     report: dict[str, Any]) -> list[dict[str, Any]]:
    unresolved = {item["source_path"]: item for item in report["unresolved"]}
    automatic = {item["source_path"]: item for item in report["automatic"]}
    entries = resolution.get("entries")
    if not isinstance(entries, list):
        raise LedgerError("resolution entries must be a list")
    seen: set[str] = set()
    resolved = []
    for entry in entries:
        source_path = str(entry.get("source_path") or "")
        if source_path in seen:
            raise LedgerError(f"duplicate migration resolution entry: {source_path}")
        seen.add(source_path)
        if source_path in automatic:
            raise LedgerError(f"automatic migration item cannot be overridden: {source_path}")
        expected = unresolved.get(source_path)
        if not expected:
            raise LedgerError(f"resolution references unknown source: {source_path}")
        for field in ("source_sha256", "candidate_id", "node"):
            if entry.get(field) != expected.get(field):
                raise LedgerError(f"resolution {field} mismatch for {source_path}")
        source = project / Path(source_path)
        if not source.is_file() or _sha256_file(source) != expected["source_sha256"]:
            raise LedgerError(f"migration source hash changed: {source_path}")
        delta = entry.get("v2_delta")
        errors = validate_submission(expected["node"], delta) if isinstance(delta, dict) else ["not an object"]
        if errors:
            raise LedgerError(f"resolved v2 delta rejected for {source_path}: {'; '.join(errors)}")
        resolved.append({**expected, "v2_delta": delta})
    missing = sorted(set(unresolved) - seen)
    if missing:
        raise LedgerError(f"resolution is incomplete; missing sources: {missing}")
    return [*report["automatic"], *resolved]


def _clone_database(source: Path, target: Path) -> None:
    source_con = sqlite3.connect(source)
    target_con = sqlite3.connect(target)
    try:
        source_con.backup(target_con)
    finally:
        target_con.close()
        source_con.close()


def _delta_key(node: str) -> str:
    matches = [key for key in DELTA_PERSONA if key.split("_", 1)[0] == node]
    if len(matches) != 1:
        raise LedgerError(f"cannot resolve delta key for migration node: {node}")
    return matches[0]


def _publish_exclusive(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise LedgerError(f"migration artifact collision: {target}")
        return
    os.replace(source, target)


def _write_exclusive(path: Path, raw: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise LedgerError(f"migration staging collision: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(raw)


def commit(project_dir: str | Path, ledger: HypothesisLedger,
           resolution_path: str | Path, resolved_by: str) -> dict[str, Any]:
    if not resolved_by.strip():
        raise LedgerError("--resolved-by must be non-empty")
    project = Path(project_dir)
    resolution, report = _load_resolution(project, Path(resolution_path))
    items = _resolved_deltas(project, resolution, report)
    order = {node: index for index, node in enumerate(
        ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8",
         "L8.5", "L9a", "L9b", "L10a", "L10b"))}
    items.sort(key=lambda item: (item["candidate_id"], order[item["node"]]))

    migration_id = report["migration_id"]
    audit = project / "08_Audit" / "hypothesis_migration"
    staging = audit / f".staging_{migration_id.replace(':', '_')}"
    staging.mkdir(parents=True, exist_ok=True)
    clone = audit / f".{migration_id.replace(':', '_')}.sqlite"
    if clone.exists():
        clone.unlink()
    source_checkpoint = ledger._connect()
    try:
        source_checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        source_checkpoint.close()
    _clone_database(ledger.path, clone)
    staged_ledger = HypothesisLedger(clone)
    staged_ledger.bind_project(staging, report["project_id"], activate=False,
                               bound_at=report.get("created_at") or "MIGRATION")
    artifacts = []
    for item in items:
        key = _delta_key(item["node"])
        persona = DELTA_PERSONA[key]
        target = staging / "02_Agent_Notes" / persona / f"{item['candidate_id']}_{key}_delta.v2.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        result = staged_ledger.commit_delta(
            project_dir=staging, candidate_id=item["candidate_id"],
            round_id=item["round_id"], node=item["node"], persona=persona,
            delta=item["v2_delta"], delta_path=target,
            _allow_unactivated_migration=True,
        )
        _write_exclusive(target, canonical_json(result.normalized_delta))
        receipt = {**result.receipt, "created_at": "MIGRATION"}
        receipt_path = staging / "08_Audit" / "hypothesis_commits" / (
            f"H{result.commit_seq:08d}_{item['candidate_id']}_{item['node']}.json"
        )
        _write_exclusive(receipt_path, canonical_json(receipt))
        staged_ledger.finalize_emission(
            result.delta_hash, artifact_sha256=_sha256_file(target),
            receipt_sha256=_sha256_file(receipt_path),
        )
        artifacts.extend([_relative(target, staging), _relative(receipt_path, staging)])
    manifest = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "migration_id": migration_id, "project_id": report["project_id"],
        "store_id": ledger.store_id, "scan_hash": report["scan_hash"],
        "dry_run_report_hash": report["dry_run_report_hash"],
        "resolution_sha256": _sha256_file(Path(resolution_path)),
        "resolved_by": resolved_by, "artifacts": sorted(artifacts),
    }
    manifest_hash = content_hash(manifest)
    manifest["manifest_hash"] = manifest_hash
    manifest_rel = f"08_Audit/hypothesis_migration/{migration_id.replace(':', '_')}_manifest.json"
    manifest_path = staging / manifest_rel
    _write_exclusive(manifest_path, canonical_json(manifest))
    staged_ledger.commit_migration(
        project_id=report["project_id"], migration_id=migration_id,
        scan_hash=report["scan_hash"], report_hash=report["dry_run_report_hash"],
        resolved_by=resolved_by, manifest_hash=manifest_hash, activated_at="MIGRATION",
    )
    checkpoint = staged_ledger._connect()
    try:
        checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        checkpoint.close()
    for source in sorted((path for path in staging.rglob("*") if path.is_file()),
                         key=lambda path: len(path.parts)):
        _publish_exclusive(source, project / source.relative_to(staging))
    os.replace(clone, ledger.path)
    return manifest
