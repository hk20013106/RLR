"""Project-atomic legacy delta migration into the hypothesis ledger."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from research_loop.delta import DELTA_PERSONA
from research_loop.compatibility import PROFILE_V20, PROFILE_V21, get_profile
from research_loop.hypothesis_contracts import validate_persisted, validate_submission
from research_loop.hypothesis_ledger import (
    HypothesisLedger,
    LedgerError,
    _uuid,
    binding_path,
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
        if node and not validate_submission(node, data, schema_version="2.0"):
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
        errors = (validate_submission(expected["node"], delta, schema_version="2.0")
                  if isinstance(delta, dict) else ["not an object"])
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


_TERMINAL_STATUSES = {"KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED"}


def _profile_upgrade_findings(project: Path, con: sqlite3.Connection,
                              project_id: str) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT m.delta_hash,m.node,m.delta_path,c.artifact_sha256 "
        "FROM emissions m JOIN committed_emissions c "
        "ON c.delta_hash=m.delta_hash "
        "WHERE m.project_id=? AND m.node IN ('L1','L2','L3','L4','L5','L6') "
        "ORDER BY m.commit_seq",
        (project_id,),
    ).fetchall()
    findings = []
    for row in rows:
        relative = Path(str(row["delta_path"]))
        artifact = project / relative
        issues: list[str] = []
        delta = None
        if not artifact.is_file():
            issues.append("finalized legacy artifact is missing")
        elif _sha256_file(artifact) != str(row["artifact_sha256"]):
            issues.append("finalized legacy artifact hash does not match ledger")
        else:
            try:
                delta = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(f"finalized legacy artifact is invalid JSON: {exc}")
        if isinstance(delta, dict):
            target = json.loads(json.dumps(delta))
            target["schema_version"] = "2.1"
            issues.extend(validate_persisted(
                str(row["node"]), target, schema_version="2.1"
            ))
        if not issues:
            continue
        material = {
            "kind": "STRUCTURING_REQUIRED",
            "node": str(row["node"]),
            "delta_hash": str(row["delta_hash"]),
            "artifact_path": relative.as_posix(),
            "issues": issues,
        }
        findings.append({
            "finding_id": f"PF:{content_hash(material)}",
            **material,
        })
    return findings


def dry_run_profile_upgrade(project_dir: str | Path, ledger: HypothesisLedger) -> dict[str, Any]:
    """Assess a v2.0 project upgrade without writing ledger or project state."""
    project = Path(project_dir)
    wal_path = Path(f"{ledger.path}-wal")
    if wal_path.is_file() and wal_path.stat().st_size:
        raise LedgerError(
            "profile upgrade dry-run requires a checkpointed store with no active WAL"
        )
    target = binding_path(project)
    try:
        binding = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"invalid hypothesis ledger binding: {target}") from exc
    con = ledger._connect(readonly=True, immutable=True)
    try:
        store_id_row = con.execute(
            "SELECT value FROM ledger_meta WHERE key='store_id'"
        ).fetchone()
        store_id = str(store_id_row[0]) if store_id_row else ""
        if (binding.get("store_id") != store_id
                or not binding.get("project_id")):
            raise LedgerError(
                "hypothesis ledger binding does not match configured store"
            )
        if not con.execute(
            "SELECT 1 FROM project_activations WHERE project_id=?",
            (binding["project_id"],),
        ).fetchone():
            raise LedgerError("profile upgrade requires an activated project")
        has_transitions = con.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' "
            "AND name='profile_transitions'"
        ).fetchone()
        latest = None
        if has_transitions:
            columns = {
                str(row[1]) for row in con.execute(
                    "PRAGMA table_info(profile_transitions)"
                )
            }
            complete_columns = {
                "target_profile_id", "source_ledger_state_hash",
                "destination_ledger_state_hash", "receipt_json",
            }
            if complete_columns <= columns:
                latest = con.execute(
                    "SELECT target_profile_id,source_ledger_state_hash,"
                    "destination_ledger_state_hash,receipt_json "
                    "FROM profile_transitions WHERE project_id=? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (binding["project_id"],),
                ).fetchone()
            elif con.execute(
                "SELECT 1 FROM profile_transitions WHERE project_id=? LIMIT 1",
                (binding["project_id"],),
            ).fetchone():
                raise LedgerError(
                    "incomplete profile transition blocks profile upgrade"
                )
        if latest and (not latest[1] or not latest[2] or not latest[3]):
            raise LedgerError(
                "incomplete profile transition blocks profile upgrade"
            )
        source_profile = str(
            latest[0] if latest else binding.get("profile_id", PROFILE_V20)
        )
        get_profile(source_profile)
        source_through_commit_seq = int(con.execute(
            "SELECT COALESCE(MAX(commit_seq),0) FROM emissions WHERE project_id=?",
            (binding["project_id"],),
        ).fetchone()[0])
        source_ledger_state_hash = ledger._profile_state_hash(
            con, str(binding["project_id"]),
            through_commit_seq=source_through_commit_seq,
        )
        unfinalized = [
            {
                "finding_id": f"PF:{content_hash({'kind': 'UNFINALIZED_EMISSION', 'delta_hash': str(row[0])})}",
                "kind": "UNFINALIZED_EMISSION",
                "delta_hash": str(row[0]),
                "node": str(row[1]),
                "reason": "profile upgrade cannot proceed while an emission is not finalized",
            }
            for row in con.execute(
                "SELECT e.delta_hash,e.node FROM emissions e "
                "WHERE e.project_id=? AND NOT EXISTS ("
                "SELECT 1 FROM committed_emissions c WHERE c.delta_hash=e.delta_hash"
                ") ORDER BY e.commit_seq",
                (binding["project_id"],),
            ).fetchall()
        ]
        artifact_findings = _profile_upgrade_findings(
            project, con, str(binding["project_id"])
        )
    finally:
        con.close()
    candidate_paths = sorted((project / "01_Candidates").glob("C*.md"))
    candidate_state_hash = content_hash({
        path.relative_to(project).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
        for path in candidate_paths
    })
    candidates = []
    for path in candidate_paths:
        text = path.read_text(encoding="utf-8")
        candidate = re.search(r"(?m)^candidate_id:\s*['\"]?([^'\"\r\n]+)", text)
        status = re.search(r"(?m)^current_status:\s*['\"]?([^'\"\r\n]+)", text)
        candidates.append({"candidate_id": candidate.group(1).strip() if candidate else path.stem,
                           "status": status.group(1).strip() if status else "UNKNOWN"})
    nonterminal = [item for item in candidates if item["status"] not in _TERMINAL_STATUSES]
    findings = [
        {
            "finding_id": f"PF:{content_hash({'kind': 'NONTERMINAL_CANDIDATE', **item})}",
            "kind": "NONTERMINAL_CANDIDATE",
            **item,
            "reason": "project-wide upgrade requires every candidate to be terminal",
        }
        for item in nonterminal
    ]
    findings.extend(artifact_findings)
    report = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "project_id": binding["project_id"], "store_id": store_id,
        "source_profile_id": source_profile, "target_profile_id": PROFILE_V21,
        "source_through_commit_seq": source_through_commit_seq,
        "source_ledger_state_hash": source_ledger_state_hash,
        "candidate_state_hash": candidate_state_hash,
        "candidates": candidates, "nonterminal": nonterminal,
        "blocking_findings": unfinalized,
        "resolution_required": findings,
    }
    report["dry_run_report_hash"] = content_hash(report)
    return report


def _validate_profile_resolution(path: Path, report: dict[str, Any]) -> str:
    try:
        resolution = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"profile upgrade resolution is invalid JSON: {exc}") from exc
    if resolution.get("schema_version") != MIGRATION_SCHEMA_VERSION:
        raise LedgerError("unsupported profile upgrade resolution schema_version")
    if resolution.get("dry_run_report_hash") != report["dry_run_report_hash"]:
        raise LedgerError(
            "profile upgrade resolution dry_run_report_hash is stale or mismatched"
        )
    entries = resolution.get("entries")
    if not isinstance(entries, list):
        raise LedgerError("profile upgrade resolution entries must be a list")
    required = {
        str(item["finding_id"]): item for item in report["resolution_required"]
    }
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise LedgerError("profile upgrade resolution entry must be an object")
        finding_id = str(entry.get("finding_id") or "")
        if finding_id in seen:
            raise LedgerError(
                f"duplicate profile upgrade resolution finding: {finding_id}"
            )
        seen.add(finding_id)
        if finding_id not in required:
            raise LedgerError(
                f"profile upgrade resolution references unknown finding: {finding_id}"
            )
        if entry.get("resolution") != "retain-under-source-profile":
            raise LedgerError(
                "profile upgrade resolution must retain terminal history "
                "under its source profile"
            )
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise LedgerError("profile upgrade resolution reason must be non-empty")
    missing = sorted(set(required) - seen)
    if missing:
        raise LedgerError(
            f"profile upgrade resolution is incomplete; missing findings: {missing}"
        )
    return _sha256_file(path)


def upgrade_profile(project_dir: str | Path, ledger: HypothesisLedger, *,
                    resolution_path: str | Path, resolved_by: str) -> dict[str, Any]:
    """Append a completed v2.0 -> v2.1 transition after a no-write assessment.

    This deliberately never invents missing scientific facts.  Projects with
    nonterminal candidates fail closed instead of mixing topology within a
    candidate lifecycle.
    """
    if not resolved_by.strip():
        raise LedgerError("--resolved-by must be non-empty")
    project = Path(project_dir)
    report = dry_run_profile_upgrade(project, ledger)
    if report["source_profile_id"] != PROFILE_V20:
        raise LedgerError("profile upgrade source must be v2.0-legacy")
    if report["nonterminal"]:
        raise LedgerError("profile upgrade requires no nonterminal candidate")
    if report["blocking_findings"]:
        raise LedgerError("profile upgrade requires every source emission to be finalized")
    resolution = Path(resolution_path)
    if not resolution.is_file():
        raise LedgerError("profile upgrade resolution manifest is required")
    resolution_hash = _validate_profile_resolution(resolution, report)
    manifest = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "project_id": report["project_id"], "store_id": ledger.store_id,
        "source_profile_id": PROFILE_V20, "target_profile_id": PROFILE_V21,
        "dry_run_report_hash": report["dry_run_report_hash"],
        "resolution_sha256": resolution_hash, "resolved_by": resolved_by,
        "finding_ids": [
            item["finding_id"] for item in report["resolution_required"]
        ],
    }
    manifest_hash = content_hash(manifest)
    return ledger.record_profile_transition(
        project_dir=project, source_profile_id=PROFILE_V20,
        target_profile_id=PROFILE_V21,
        dry_run_report_hash=report["dry_run_report_hash"], resolution_hash=resolution_hash,
        manifest_hash=manifest_hash, resolved_by=resolved_by,
        candidate_state_hash=report["candidate_state_hash"],
        expected_source_ledger_state_hash=report["source_ledger_state_hash"],
        expected_through_commit_seq=report["source_through_commit_seq"],
    )


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
    # Keep the staged manifest at the staging root.  Repeating the final audit
    # path below the already nested staging directory exceeds Windows path
    # limits and is not needed for the final publish target.
    manifest_name = f"{migration_id.replace(':', '_')}_manifest.json"
    manifest_path = staging / manifest_name
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
    for source in sorted((path for path in staging.rglob("*")
                          if path.is_file() and path != manifest_path),
                         key=lambda path: len(path.parts)):
        _publish_exclusive(source, project / source.relative_to(staging))
    _publish_exclusive(manifest_path, audit / manifest_name)
    os.replace(clone, ledger.path)
    return manifest
