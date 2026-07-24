"""Versioned, append-only hypothesis lifecycle ledger.

The ledger is the single persistence seam for hypothesis lifecycle facts.  It
does not import the engine or providers: callers submit a node delta together
with already-authorized candidate metadata, and receive a normalized delta plus
an immutable commit receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_loop.hypothesis_contracts import (
    DELTA_SCHEMA_VERSION,
    EPISTEMIC_STATUSES,
    LOOP_TYPES,
    NODE_SCHEMAS,
    validate_persisted,
    validate_submission,
)


STORE_SCHEMA_VERSION = "2.0"
GRAPH_SCHEMA_VERSION = "1.0"
NAMESPACE = uuid.UUID("d879c2d5-e8e7-4835-bf91-17c6a7d8da99")

WORKFLOW_STATUSES = {
    "PROPOSED", "SELECTED", "REJECTED", "METHOD_DESIGNED",
    "METHOD_APPROVED", "EXECUTED", "AUDITED", "REVIEWED", "RETAINED",
    "REVISION_REQUIRED", "SUPERSEDED", "ARCHIVED",
}
WORKFLOW_TRANSITIONS = {
    "PROPOSED": {"SELECTED", "REJECTED", "ARCHIVED"},
    "SELECTED": {"METHOD_DESIGNED", "ARCHIVED"},
    "METHOD_DESIGNED": {"METHOD_APPROVED", "REJECTED", "ARCHIVED"},
    "METHOD_APPROVED": {"EXECUTED", "ARCHIVED"},
    "EXECUTED": {"AUDITED", "ARCHIVED"},
    "AUDITED": {"REVIEWED", "ARCHIVED"},
    "REVIEWED": {"RETAINED", "REVISION_REQUIRED", "ARCHIVED"},
    "RETAINED": {"ARCHIVED"},
    "REVISION_REQUIRED": {"SUPERSEDED", "ARCHIVED"},
}


class LedgerError(ValueError):
    """A fail-closed ledger contract or persistence error."""


@dataclass(frozen=True)
class CommitResult:
    normalized_delta: dict[str, Any]
    delta_hash: str
    commit_seq: int
    event_ids: tuple[str, ...]
    receipt: dict[str, Any]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_statement(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError("hypothesis statement must be a non-empty string")
    return " ".join(unicodedata.normalize("NFC", value).strip().split())


def _uuid(kind: str, *parts: str) -> str:
    return f"{kind}:{uuid.uuid5(NAMESPACE, '|'.join(parts))}"


def binding_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / "00_Preflight" / "hypothesis_store_binding.json"


class HypothesisLedger:
    """SQLite-backed immutable hypothesis facts with rebuildable projections."""

    def __init__(self, store_path: str | Path):
        self.path = Path(store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            if not self.path.is_file():
                raise LedgerError(f"hypothesis ledger store does not exist: {self.path}")
            con = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True,
                                  timeout=5, isolation_level=None)
        else:
            con = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        if not readonly:
            con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA busy_timeout = 5000")
        return con

    def _initialize(self) -> None:
        con = self._connect()
        try:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, store_id TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS families (family_id TEXT PRIMARY KEY, statement TEXT NOT NULL, statement_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS versions (hypothesis_id TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES families(family_id), statement TEXT NOT NULL, operationalization TEXT NOT NULL, falsification_criteria_json TEXT NOT NULL, definition_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, created_event_id TEXT);
                CREATE TABLE IF NOT EXISTS occurrences (occurrence_id TEXT PRIMARY KEY, hypothesis_id TEXT NOT NULL REFERENCES versions(hypothesis_id), project_id TEXT NOT NULL REFERENCES projects(project_id), candidate_id TEXT NOT NULL, round_id TEXT NOT NULL, UNIQUE(hypothesis_id, project_id, candidate_id, round_id));
                CREATE TABLE IF NOT EXISTS evidence_records (evidence_id TEXT PRIMARY KEY, source_kind TEXT NOT NULL, summary TEXT NOT NULL, artifact_refs_json TEXT NOT NULL, content_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS emissions (delta_hash TEXT PRIMARY KEY, project_id TEXT NOT NULL, candidate_id TEXT NOT NULL, round_id TEXT NOT NULL, node TEXT NOT NULL, persona TEXT NOT NULL, delta_path TEXT NOT NULL, committed_at TEXT NOT NULL, commit_seq INTEGER NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS committed_emissions (delta_hash TEXT PRIMARY KEY REFERENCES emissions(delta_hash), artifact_sha256 TEXT NOT NULL, receipt_sha256 TEXT NOT NULL, finalized_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, commit_seq INTEGER NOT NULL, event_type TEXT NOT NULL, hypothesis_id TEXT, occurrence_id TEXT, evidence_id TEXT, project_id TEXT NOT NULL, candidate_id TEXT NOT NULL, round_id TEXT NOT NULL, node TEXT NOT NULL, persona TEXT NOT NULL, outcome TEXT, reason TEXT, artifact_ref_json TEXT NOT NULL, supersedes_event_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS workflow_projection (occurrence_id TEXT PRIMARY KEY, workflow_status TEXT NOT NULL, event_id TEXT NOT NULL, commit_seq INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS epistemic_projection (hypothesis_id TEXT PRIMARY KEY, epistemic_status TEXT NOT NULL, event_id TEXT NOT NULL, commit_seq INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS authorizations (authorization_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, hypothesis_id TEXT NOT NULL, through_commit_seq INTEGER NOT NULL, snapshot_hash TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS migration_batches (migration_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, scan_hash TEXT NOT NULL, report_hash TEXT NOT NULL, resolved_by TEXT NOT NULL, manifest_hash TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_activations (project_id TEXT PRIMARY KEY REFERENCES projects(project_id), activation_mode TEXT NOT NULL CHECK(activation_mode IN ('NATIVE_V2','MIGRATED_V2')), migration_id TEXT REFERENCES migration_batches(migration_id), activated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS authorization_snapshots (authorization_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, candidate_id TEXT NOT NULL, round_id TEXT NOT NULL, node TEXT NOT NULL, through_commit_seq INTEGER NOT NULL, event_ids_json TEXT NOT NULL, projection_hash TEXT NOT NULL, artifact_hash TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS families_append_only BEFORE UPDATE ON families BEGIN SELECT RAISE(ABORT, 'families are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS families_no_delete BEFORE DELETE ON families BEGIN SELECT RAISE(ABORT, 'families are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS versions_append_only BEFORE UPDATE ON versions BEGIN SELECT RAISE(ABORT, 'versions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS versions_no_delete BEFORE DELETE ON versions BEGIN SELECT RAISE(ABORT, 'versions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS occurrences_append_only BEFORE UPDATE ON occurrences BEGIN SELECT RAISE(ABORT, 'occurrences are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS occurrences_no_delete BEFORE DELETE ON occurrences BEGIN SELECT RAISE(ABORT, 'occurrences are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS evidence_append_only BEFORE UPDATE ON evidence_records BEGIN SELECT RAISE(ABORT, 'evidence records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence_records BEGIN SELECT RAISE(ABORT, 'evidence records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS emissions_append_only BEFORE UPDATE ON emissions BEGIN SELECT RAISE(ABORT, 'emissions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS emissions_no_delete BEFORE DELETE ON emissions BEGIN SELECT RAISE(ABORT, 'emissions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS committed_emissions_append_only BEFORE UPDATE ON committed_emissions BEGIN SELECT RAISE(ABORT, 'committed emissions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS committed_emissions_no_delete BEFORE DELETE ON committed_emissions BEGIN SELECT RAISE(ABORT, 'committed emissions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_append_only BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS migrations_append_only BEFORE UPDATE ON migration_batches BEGIN SELECT RAISE(ABORT, 'migration batches are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS migrations_no_delete BEFORE DELETE ON migration_batches BEGIN SELECT RAISE(ABORT, 'migration batches are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS activations_append_only BEFORE UPDATE ON project_activations BEGIN SELECT RAISE(ABORT, 'project activations are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS activations_no_delete BEFORE DELETE ON project_activations BEGIN SELECT RAISE(ABORT, 'project activations are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS authorization_snapshots_append_only BEFORE UPDATE ON authorization_snapshots BEGIN SELECT RAISE(ABORT, 'authorization snapshots are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS authorization_snapshots_no_delete BEFORE DELETE ON authorization_snapshots BEGIN SELECT RAISE(ABORT, 'authorization snapshots are append-only'); END;
            """)
            con.execute("INSERT OR IGNORE INTO ledger_meta(key, value) VALUES (?, ?)", ("schema_version", STORE_SCHEMA_VERSION))
            con.execute("UPDATE ledger_meta SET value=? WHERE key='schema_version' AND value='1.0'", (STORE_SCHEMA_VERSION,))
            con.execute("INSERT OR IGNORE INTO ledger_meta(key, value) VALUES (?, ?)", ("store_id", _uuid("STORE", str(self.path.resolve()))))
        finally:
            con.close()

    @property
    def store_id(self) -> str:
        con = self._connect()
        try:
            return str(con.execute("SELECT value FROM ledger_meta WHERE key='store_id'").fetchone()[0])
        finally:
            con.close()

    def bind_project(self, project_dir: str | Path, project_id: str | None = None,
                     *, activate: bool = True,
                     activation_mode: str = "NATIVE_V2",
                     bound_at: str | None = None) -> dict[str, Any]:
        project_dir = Path(project_dir)
        project_id = project_id or _uuid("PROJECT", self.store_id, str(uuid.uuid4()))
        binding = {"schema_version": "1.0", "store_id": self.store_id,
                   "project_id": project_id, "bound_at": bound_at or _now()}
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT OR IGNORE INTO projects(project_id, store_id, created_at) VALUES (?, ?, ?)", (project_id, self.store_id, binding["bound_at"]))
            if activate:
                if activation_mode not in {"NATIVE_V2", "MIGRATED_V2"}:
                    raise LedgerError(f"invalid project activation mode: {activation_mode}")
                con.execute(
                    "INSERT OR IGNORE INTO project_activations(project_id,activation_mode,migration_id,activated_at) VALUES (?,?,NULL,?)",
                    (project_id, activation_mode, binding["bound_at"]),
                )
            con.commit()
        finally:
            con.close()
        target = binding_path(project_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing.get("store_id") != self.store_id or existing.get("project_id") != project_id:
                raise LedgerError(f"project binding mismatch: {target}")
            return existing
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(binding, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
        return binding

    def commit_migration(self, *, project_id: str, migration_id: str,
                         scan_hash: str, report_hash: str, resolved_by: str,
                         manifest_hash: str, activated_at: str) -> None:
        """Atomically record an immutable migration batch and activate its project."""
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            project = con.execute(
                "SELECT store_id FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
            if not project or project[0] != self.store_id:
                raise LedgerError("migration project is not bound to this store")
            con.execute(
                "INSERT OR IGNORE INTO migration_batches(migration_id,project_id,scan_hash,report_hash,resolved_by,manifest_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                (migration_id, project_id, scan_hash, report_hash, resolved_by,
                 manifest_hash, activated_at),
            )
            existing = con.execute(
                "SELECT project_id,scan_hash,report_hash,resolved_by,manifest_hash "
                "FROM migration_batches WHERE migration_id=?", (migration_id,)
            ).fetchone()
            expected = (project_id, scan_hash, report_hash, resolved_by, manifest_hash)
            if not existing or tuple(existing) != expected:
                raise LedgerError("migration retry does not match immutable batch metadata")
            con.execute(
                "INSERT OR IGNORE INTO project_activations(project_id,activation_mode,migration_id,activated_at) VALUES (?,'MIGRATED_V2',?,?)",
                (project_id, migration_id, activated_at),
            )
            activation = con.execute(
                "SELECT activation_mode,migration_id FROM project_activations WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if not activation or tuple(activation) != ("MIGRATED_V2", migration_id):
                raise LedgerError("project activation conflicts with migration batch")
            con.commit()
        except sqlite3.Error as exc:
            con.rollback()
            raise LedgerError(f"migration activation transaction failed: {exc}") from exc
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def create_continuation_occurrence(
        self, *, project_dir: str | Path, candidate_id: str, round_id: str,
        hypothesis_id: str, memory_path: str | Path, memory_hash: str,
    ) -> str:
        """Idempotently attach an L10b-created successor version to its child."""
        binding = self.require_activated_project(project_dir)
        project = Path(project_dir)
        memory = Path(memory_path)
        try:
            relative = memory.resolve().relative_to(project.resolve()).as_posix()
        except ValueError as exc:
            raise LedgerError("continuation memory must be inside the project") from exc
        actual_memory_hash = hashlib.sha256(memory.read_bytes()).hexdigest()
        if actual_memory_hash != memory_hash:
            raise LedgerError("continuation memory hash mismatch")
        try:
            memory_data = json.loads(memory.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError("continuation memory is not valid JSON") from exc
        snapshot = memory_data.get("hypothesis_ledger")
        if (memory_data.get("schema_version") != "2.0"
                or memory_data.get("next_round_hypothesis_id") != hypothesis_id
                or not isinstance(snapshot, dict)
                or snapshot.get("store_id") != self.store_id
                or snapshot.get("project_id") != binding["project_id"]):
            raise LedgerError("continuation memory ledger identity or successor mismatch")
        occurrence_id = _uuid(
            "HO", binding["project_id"], candidate_id, str(round_id), hypothesis_id
        )
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute(
                "SELECT 1 FROM versions WHERE hypothesis_id=?", (hypothesis_id,)
            ).fetchone():
                raise LedgerError("continuation references unknown successor hypothesis_id")
            lineage = con.execute(
                "SELECT payload_json FROM events WHERE hypothesis_id=? "
                "AND candidate_id=? AND event_type IN ('REVISED','DERIVED') "
                "ORDER BY commit_seq DESC LIMIT 1",
                (hypothesis_id, memory_data.get("source_candidate_id")),
            ).fetchone()
            if not lineage:
                raise LedgerError("continuation successor was not created by source L10b")
            lineage_payload = json.loads(lineage[0])
            if lineage_payload.get("loop_type") != memory_data.get("loop_type"):
                raise LedgerError("continuation loop_type does not match successor lineage")
            existing = con.execute(
                "SELECT occurrence_id FROM occurrences WHERE occurrence_id=?",
                (occurrence_id,),
            ).fetchone()
            if existing:
                con.commit()
                return occurrence_id
            seq = self._next_commit_seq(con)
            emission_hash = content_hash({
                "memory_hash": memory_hash, "hypothesis_id": hypothesis_id,
                "candidate_id": candidate_id, "round_id": str(round_id),
            })
            con.execute(
                "INSERT INTO occurrences(occurrence_id,hypothesis_id,project_id,candidate_id,round_id) VALUES (?,?,?,?,?)",
                (occurrence_id, hypothesis_id, binding["project_id"], candidate_id,
                 str(round_id)),
            )
            con.execute(
                "INSERT INTO emissions(delta_hash,project_id,candidate_id,round_id,node,persona,delta_path,committed_at,commit_seq) VALUES (?,?,?,?,?,?,?,?,?)",
                (emission_hash, binding["project_id"], candidate_id, str(round_id),
                 "L0", "Linnaeus", relative, _now(), seq),
            )
            event = self._event(
                commit_seq=seq, delta_hash=emission_hash, ordinal=1,
                event_type="PROPOSED", project_id=binding["project_id"],
                candidate_id=candidate_id, round_id=str(round_id), node="L0",
                persona="Linnaeus", hypothesis_id=hypothesis_id,
                occurrence_id=occurrence_id, outcome="PROPOSED",
                reason="continuation occurrence created from fixed loop-memory",
                artifact_ref={"project_id": binding["project_id"], "path": relative,
                              "sha256": memory_hash, "json_pointer": ""},
                payload={"memory_hash": memory_hash},
            )
            self._insert_event(con, event)
            self._set_workflow(con, occurrence_id, "PROPOSED", event)
            con.commit()
            return occurrence_id
        except sqlite3.Error as exc:
            con.rollback()
            raise LedgerError(f"continuation occurrence transaction failed: {exc}") from exc
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def require_binding(self, project_dir: str | Path) -> dict[str, Any]:
        target = binding_path(project_dir)
        if not target.exists():
            raise LedgerError("hypothesis ledger binding missing; configure --knowledge-store and migrate/bind project")
        try:
            binding = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(f"invalid hypothesis ledger binding: {target}") from exc
        if binding.get("store_id") != self.store_id or not binding.get("project_id"):
            raise LedgerError("hypothesis ledger binding does not match configured store")
        return binding

    def require_activated_project(self, project_dir: str | Path) -> dict[str, Any]:
        binding = self.require_binding(project_dir)
        con = self._connect()
        try:
            row = con.execute(
                "SELECT activation_mode,migration_id,activated_at FROM project_activations WHERE project_id=?",
                (binding["project_id"],),
            ).fetchone()
        finally:
            con.close()
        if not row:
            raise LedgerError(
                "hypothesis ledger project is not activated; run hypothesis-migrate or create a native-v2 project"
            )
        return {**binding, "activation_mode": row[0], "migration_id": row[1],
                "activated_at": row[2]}

    def _next_commit_seq(self, con: sqlite3.Connection) -> int:
        return int(con.execute("SELECT COALESCE(MAX(commit_seq), 0) + 1 FROM emissions").fetchone()[0])

    def _event(self, *, commit_seq: int, delta_hash: str, ordinal: int, event_type: str,
               project_id: str, candidate_id: str, round_id: str, node: str, persona: str,
               hypothesis_id: str | None = None, occurrence_id: str | None = None,
               evidence_id: str | None = None, outcome: str | None = None, reason: str | None = None,
               artifact_ref: dict[str, Any] | None = None, supersedes_event_id: str | None = None,
               payload: dict[str, Any] | None = None) -> dict[str, Any]:
        fingerprint_body = {"delta_hash": delta_hash, "ordinal": ordinal, "event_type": event_type,
                            "hypothesis_id": hypothesis_id, "occurrence_id": occurrence_id,
                            "evidence_id": evidence_id, "outcome": outcome, "reason": reason,
                            "payload": payload or {}}
        fingerprint = content_hash(fingerprint_body)
        return {"event_id": _uuid("HE", self.store_id, fingerprint), "commit_seq": commit_seq,
                "event_type": event_type, "hypothesis_id": hypothesis_id, "occurrence_id": occurrence_id,
                "evidence_id": evidence_id, "project_id": project_id, "candidate_id": candidate_id,
                "round_id": round_id, "node": node, "persona": persona, "outcome": outcome,
                "reason": reason or "", "artifact_ref": artifact_ref or {},
                "supersedes_event_id": supersedes_event_id, "payload": payload or {},
                "created_at": _now(), "fingerprint": fingerprint}

    def _insert_event(self, con: sqlite3.Connection, event: dict[str, Any]) -> None:
        con.execute("""INSERT OR IGNORE INTO events(event_id, commit_seq, event_type, hypothesis_id, occurrence_id, evidence_id, project_id, candidate_id, round_id, node, persona, outcome, reason, artifact_ref_json, supersedes_event_id, payload_json, created_at, fingerprint) VALUES (:event_id,:commit_seq,:event_type,:hypothesis_id,:occurrence_id,:evidence_id,:project_id,:candidate_id,:round_id,:node,:persona,:outcome,:reason,:artifact_ref_json,:supersedes_event_id,:payload_json,:created_at,:fingerprint)""",
                    {**event, "artifact_ref_json": canonical_json(event["artifact_ref"]), "payload_json": canonical_json(event["payload"])})

    def _existing_occurrences(self, con: sqlite3.Connection, project_id: str, candidate_id: str, round_id: str) -> dict[str, str]:
        rows = con.execute("SELECT hypothesis_id, occurrence_id FROM occurrences WHERE project_id=? AND candidate_id=? AND round_id=?", (project_id, candidate_id, round_id)).fetchall()
        return {str(row["hypothesis_id"]): str(row["occurrence_id"]) for row in rows}

    def _require_occurrences(self, con: sqlite3.Connection, project_id: str, candidate_id: str, round_id: str, ids: list[str]) -> dict[str, str]:
        known = self._existing_occurrences(con, project_id, candidate_id, round_id)
        if len(ids) != len(set(ids)):
            raise LedgerError("hypothesis reference contains duplicate IDs")
        missing = sorted(set(ids) - set(known))
        if missing:
            raise LedgerError(f"unknown or unauthorized hypothesis IDs for this candidate/round: {missing}")
        return known

    def _active_occurrences(self, con: sqlite3.Connection, occurrences: dict[str, str]) -> set[str]:
        active = set()
        for hypothesis_id, occurrence_id in occurrences.items():
            row = con.execute(
                "SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?",
                (occurrence_id,),
            ).fetchone()
            if row and row[0] not in {"REJECTED", "ARCHIVED", "SUPERSEDED"}:
                active.add(hypothesis_id)
        return active

    def _require_exhaustive(self, label: str, submitted: list[str], expected: set[str]) -> None:
        if len(submitted) != len(set(submitted)):
            raise LedgerError(f"{label} contains duplicate hypothesis_id")
        if set(submitted) != expected:
            raise LedgerError(f"{label} must assess every and only authorized hypothesis occurrence")

    def _strategy_ids(self, con: sqlite3.Connection, project_id: str,
                      candidate_id: str, round_id: str) -> set[str]:
        rows = con.execute(
            "SELECT payload_json FROM events WHERE project_id=? AND candidate_id=? "
            "AND round_id=? AND node='L4' AND event_type='METHOD_DESIGNED'",
            (project_id, candidate_id, round_id),
        ).fetchall()
        return {str(json.loads(row[0]).get("strategy_id")) for row in rows
                if json.loads(row[0]).get("strategy_id")}

    def _verified_evidence_ids(self, con: sqlite3.Connection, *, project_id: str,
                               candidate_id: str, round_id: str) -> set[str]:
        return {str(row[0]) for row in con.execute(
            "SELECT DISTINCT evidence_id FROM events WHERE event_type='EVIDENCE_VERIFIED' "
            "AND evidence_id IS NOT NULL AND project_id=? AND candidate_id=? AND round_id=?",
            (project_id, candidate_id, round_id),
        ).fetchall()}

    def _set_workflow(self, con: sqlite3.Connection, occurrence_id: str, status: str, event: dict[str, Any]) -> None:
        if status not in WORKFLOW_STATUSES:
            raise LedgerError(f"invalid workflow status: {status}")
        prior = con.execute("SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        if prior and status != prior["workflow_status"] and status not in WORKFLOW_TRANSITIONS.get(prior["workflow_status"], set()):
            raise LedgerError(f"illegal occurrence workflow transition: {prior['workflow_status']} -> {status}")
        con.execute("INSERT INTO workflow_projection(occurrence_id, workflow_status, event_id, commit_seq) VALUES (?, ?, ?, ?) ON CONFLICT(occurrence_id) DO UPDATE SET workflow_status=excluded.workflow_status,event_id=excluded.event_id,commit_seq=excluded.commit_seq", (occurrence_id, status, event["event_id"], event["commit_seq"]))

    def _set_epistemic(self, con: sqlite3.Connection, hypothesis_id: str, status: str, event: dict[str, Any]) -> None:
        if status not in EPISTEMIC_STATUSES:
            raise LedgerError(f"invalid epistemic status: {status}")
        con.execute("INSERT INTO epistemic_projection(hypothesis_id, epistemic_status, event_id, commit_seq) VALUES (?, ?, ?, ?) ON CONFLICT(hypothesis_id) DO UPDATE SET epistemic_status=excluded.epistemic_status,event_id=excluded.event_id,commit_seq=excluded.commit_seq", (hypothesis_id, status, event["event_id"], event["commit_seq"]))

    def commit_delta(self, *, project_dir: str | Path, candidate_id: str, round_id: str,
                     node: str, persona: str, delta: dict[str, Any], delta_path: str | Path,
                     _allow_unactivated_migration: bool = False) -> CommitResult:
        """Validate and record one v2 delta atomically with its lifecycle events.

        The caller writes the normalized returned object only after this method
        succeeds.  The emission records the expected hash/path; consumers must
        verify both before treating the artifact as authoritative.
        """
        binding = (self.require_binding(project_dir) if _allow_unactivated_migration
                   else self.require_activated_project(project_dir))
        project_id = str(binding["project_id"])
        if delta.get("candidate_id") not in (None, candidate_id):
            raise LedgerError("candidate_id mismatch in delta")
        normalized = json.loads(json.dumps(delta))
        normalized["candidate_id"] = candidate_id
        normalized["project_id"] = project_id
        normalized["schema_version"] = DELTA_SCHEMA_VERSION
        errors = validate_submission(node, normalized)
        if errors:
            raise LedgerError("delta v2 schema rejected: " + "; ".join(errors))
        delta_hash = content_hash(normalized)
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            prior = con.execute(
                "SELECT commit_seq FROM emissions WHERE delta_hash=? AND project_id=? "
                "AND candidate_id=? AND round_id=? AND node=?",
                (delta_hash, project_id, candidate_id, str(round_id), node),
            ).fetchone()
            if prior:
                rows = con.execute("SELECT event_id FROM events WHERE commit_seq=? ORDER BY rowid", (prior["commit_seq"],)).fetchall()
                receipt = self._receipt(project_id, candidate_id, round_id, node, persona, delta_hash, int(prior["commit_seq"]), [r[0] for r in rows])
                con.commit()
                return CommitResult(normalized, delta_hash, int(prior["commit_seq"]), tuple(r[0] for r in rows), receipt)
            seq = self._next_commit_seq(con)
            try:
                relative_delta_path = Path(delta_path).relative_to(project_dir)
            except ValueError as exc:
                raise LedgerError("delta artifact path must be below the project directory") from exc
            artifact_ref = {"project_id": project_id, "path": str(relative_delta_path).replace("\\", "/"), "sha256": delta_hash, "json_pointer": ""}
            events: list[dict[str, Any]] = []
            ordinal = 0
            def add(event_type: str, **kwargs: Any) -> dict[str, Any]:
                nonlocal ordinal
                ordinal += 1
                event_artifact_ref = kwargs.pop("artifact_ref", artifact_ref)
                event = self._event(commit_seq=seq, delta_hash=delta_hash, ordinal=ordinal, event_type=event_type,
                                    project_id=project_id, candidate_id=candidate_id, round_id=str(round_id), node=node, persona=persona, artifact_ref=event_artifact_ref, **kwargs)
                events.append(event)
                return event
            if node == "L1":
                keys: dict[str, str] = {}
                for item in normalized["hypotheses"]:
                    statement = normalize_statement(item["statement"])
                    statement_hash = content_hash(statement)
                    family_id = _uuid("HF", self.store_id, statement_hash)
                    definition = {"statement": statement, "operationalization": item["operationalization"].strip(), "falsification_criteria": item["falsification_criteria"]}
                    definition_hash = content_hash(definition)
                    hypothesis_id = _uuid("H", self.store_id, definition_hash)
                    item["hypothesis_family_id"] = family_id
                    item["hypothesis_id"] = hypothesis_id
                    keys[item["proposal_key"]] = hypothesis_id
                    con.execute("INSERT OR IGNORE INTO families(family_id,statement,statement_hash,created_at) VALUES (?,?,?,?)", (family_id, statement, statement_hash, _now()))
                    con.execute("INSERT OR IGNORE INTO versions(hypothesis_id,family_id,statement,operationalization,falsification_criteria_json,definition_hash,created_at) VALUES (?,?,?,?,?,?,?)", (hypothesis_id, family_id, statement, item["operationalization"].strip(), canonical_json(item["falsification_criteria"]), definition_hash, _now()))
                    occurrence_id = _uuid("HO", project_id, candidate_id, str(round_id), hypothesis_id)
                    con.execute("INSERT OR IGNORE INTO occurrences(occurrence_id,hypothesis_id,project_id,candidate_id,round_id) VALUES (?,?,?,?,?)", (occurrence_id, hypothesis_id, project_id, candidate_id, str(round_id)))
                    event = add("PROPOSED", hypothesis_id=hypothesis_id, occurrence_id=occurrence_id, outcome="PROPOSED", reason=item["rationale"], payload={"family_id": family_id, "proposal_key": item["proposal_key"], "primary": item["proposal_key"] == normalized["primary_proposal_key"]})
                    self._set_workflow(con, occurrence_id, "PROPOSED", event)
                if normalized["primary_proposal_key"] not in keys:
                    raise LedgerError("L1 primary_proposal_key does not identify a submitted hypothesis")
                normalized["primary_hypothesis_id"] = keys[normalized["primary_proposal_key"]]
            else:
                existing = self._existing_occurrences(con, project_id, candidate_id, str(round_id))
                if node == "L2":
                    verdict_ids = [item["hypothesis_id"] for item in normalized["verdicts"]]
                    self._require_exhaustive("L2 verdicts", verdict_ids, set(existing))
                    scopes = {
                        "attacks": "HYPOTHESIS_ATTACK",
                        "confounders": "CONFOUNDER",
                        "diagnostic_tests": "DIAGNOSTIC_TEST",
                    }
                    for group, scope in scopes.items():
                        for item in normalized[group]:
                            self._require_occurrences(con, project_id, candidate_id, str(round_id), [item["hypothesis_id"]])
                            add("ATTACKED", hypothesis_id=item["hypothesis_id"], occurrence_id=existing[item["hypothesis_id"]], outcome=item.get("severity", "PROPOSED"), reason=item["text"], payload={"scope": scope, **item})
                    for item in normalized["verdicts"]:
                        add("ATTACKED", hypothesis_id=item["hypothesis_id"], occurrence_id=existing[item["hypothesis_id"]], outcome=item["outcome"], reason=item["reason"], payload={"scope": "VERDICT", **item})
                elif node == "L3":
                    ids = [item["hypothesis_id"] for item in normalized["triage"]]
                    if len(ids) != len(set(ids)):
                        raise LedgerError("L3 triage contains duplicate hypothesis_id")
                    if set(ids) != set(existing):
                        raise LedgerError("L3 triage must dispose every and only current L1 hypothesis")
                    for item in normalized["triage"]:
                        event = add(item["disposition"], hypothesis_id=item["hypothesis_id"], occurrence_id=existing[item["hypothesis_id"]], outcome=item["reason_code"], reason=item["reason"])
                        self._set_workflow(con, existing[item["hypothesis_id"]], item["disposition"], event)
                elif node in {"L4", "L6"}:
                    collection = normalized["strategies"] if node == "L4" else normalized["analysis_plan"]
                    mapping = {"L4": "METHOD_DESIGNED", "L6": "METHOD_APPROVED"}
                    for item in collection:
                        ids = item.get("hypothesis_ids", [])
                        self._require_occurrences(con, project_id, candidate_id, str(round_id), ids)
                        for hid in ids:
                            event = add(mapping[node], hypothesis_id=hid, occurrence_id=existing[hid], reason=str(item.get("reason") or item.get("name") or node), payload=item)
                            if node == "L4": self._set_workflow(con, existing[hid], "METHOD_DESIGNED", event)
                            if node == "L6" and normalized["method_decision"] == "APPROVE": self._set_workflow(con, existing[hid], "METHOD_APPROVED", event)
                elif node == "L5":
                    strategy_ids = self._strategy_ids(con, project_id, candidate_id, str(round_id))
                    selected = {
                        hid for hid, occurrence_id in existing.items()
                        if (row := con.execute(
                            "SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?",
                            (occurrence_id,),
                        ).fetchone()) and row[0] == "METHOD_DESIGNED"
                    }
                    covered: set[str] = set()
                    groups = (
                        ("attacks", "METHOD"),
                        ("qc_checkpoints", "QC"),
                        ("failure_stop_rules", "STOP_RULE"),
                    )
                    for group, scope in groups:
                        for item in normalized[group]:
                            ids = item["hypothesis_ids"]
                            self._require_occurrences(con, project_id, candidate_id, str(round_id), ids)
                            if item["strategy_id"] not in strategy_ids:
                                raise LedgerError(f"L5 references unknown L4 strategy_id: {item['strategy_id']}")
                            covered.update(ids)
                            for hid in ids:
                                add("ATTACKED", hypothesis_id=hid, occurrence_id=existing[hid],
                                    outcome=item.get("severity", "REVIEWED"),
                                    reason=str(item.get("text") or item.get("criterion") or item.get("reason")),
                                    payload={"scope": scope, **item})
                    if covered != selected:
                        raise LedgerError("L5 must review every selected hypothesis")
                elif node == "L7":
                    for result in normalized["results"]:
                        self._require_occurrences(con, project_id, candidate_id, str(round_id), result["hypothesis_ids"])
                        evidence_body = {"source_kind": "L7_RESULT", "summary": result["summary"], "artifact_refs": result["artifact_refs"]}
                        evidence_id = _uuid("E", self.store_id, content_hash(evidence_body))
                        result["evidence_id"] = evidence_id
                        con.execute("INSERT OR IGNORE INTO evidence_records(evidence_id,source_kind,summary,artifact_refs_json,content_hash,created_at) VALUES (?,?,?,?,?,?)", (evidence_id, "L7_RESULT", result["summary"], canonical_json(result["artifact_refs"]), content_hash(evidence_body), _now()))
                        for hid in result["hypothesis_ids"]:
                            event = add("EXECUTED", hypothesis_id=hid, occurrence_id=existing[hid], evidence_id=evidence_id, outcome="PENDING", reason=result["summary"], payload={"result_key": result["result_key"]})
                            self._set_workflow(con, existing[hid], "EXECUTED", event)
                elif node == "L8":
                    pending = {r["evidence_id"] for r in con.execute("SELECT DISTINCT evidence_id FROM events WHERE project_id=? AND candidate_id=? AND round_id=? AND node='L7'", (project_id, candidate_id, str(round_id))).fetchall()}
                    submitted_ids = [item["evidence_id"] for item in normalized["evidence_assessments"]]
                    if len(submitted_ids) != len(set(submitted_ids)):
                        raise LedgerError("L8 contains duplicate evidence assessments")
                    submitted = set(submitted_ids)
                    if submitted != pending:
                        raise LedgerError("L8 must assess every and only L7 pending evidence record")
                    for item in normalized["evidence_assessments"]:
                        if item["verification"] == "REJECTED" and item["relations"]:
                            raise LedgerError("L8 rejected evidence cannot create hypothesis relations")
                        add(f"EVIDENCE_{item['verification']}", evidence_id=item["evidence_id"], outcome=item["verification"])
                        if item["verification"] == "VERIFIED":
                            for relation in item["relations"]:
                                self._require_occurrences(con, project_id, candidate_id, str(round_id), [relation["hypothesis_id"]])
                                event = add(f"EVIDENCE_{relation['outcome']}", hypothesis_id=relation["hypothesis_id"], occurrence_id=existing[relation["hypothesis_id"]], evidence_id=item["evidence_id"], outcome=relation["outcome"], reason=relation["reason"])
                                self._set_workflow(con, existing[relation["hypothesis_id"]], "AUDITED", event)
                elif node == "L8.5":
                    from research_loop import deep_research
                    try:
                        pack = deep_research.evidence_pack_details(
                            project_dir, candidate_id, "L8.5"
                        )
                    except deep_research.DeepResearchError as exc:
                        raise LedgerError(f"L8.5 deep-research evidence rejected: {exc}") from exc
                    if normalized["deep_research_run_id"] != pack["run_id"]:
                        raise LedgerError("L8.5 deep-research run ID mismatch")
                    if normalized["deep_research_receipt_hash"] != pack["receipt_hash"]:
                        raise LedgerError("L8.5 deep-research receipt hash mismatch")
                    assessment_ids = [item["hypothesis_id"] for item in normalized["assessments"]]
                    self._require_exhaustive(
                        "L8.5 assessments", assessment_ids,
                        self._active_occurrences(con, existing),
                    )
                    imported: set[str] = set()
                    for assessment in normalized["assessments"]:
                        hid = assessment["hypothesis_id"]
                        for evidence_id in assessment["evidence_ids"]:
                            record = pack["records"].get(evidence_id)
                            if record is None:
                                raise LedgerError(
                                    f"L8.5 references unknown deep-research evidence: {evidence_id}"
                                )
                            evidence_body = {
                                "source_kind": "DEEP_RESEARCH", "summary": record["summary"],
                                "artifact_refs": [record["artifact_ref"]],
                            }
                            con.execute(
                                "INSERT OR IGNORE INTO evidence_records(evidence_id,source_kind,summary,artifact_refs_json,content_hash,created_at) VALUES (?,?,?,?,?,?)",
                                (evidence_id, "DEEP_RESEARCH", record["summary"],
                                 canonical_json([record["artifact_ref"]]),
                                 content_hash(evidence_body), _now()),
                            )
                            if evidence_id not in imported:
                                add("EVIDENCE_VERIFIED", evidence_id=evidence_id,
                                    outcome="VERIFIED", reason="verified deep-research receipt",
                                    artifact_ref=record["artifact_ref"],
                                    payload={"run_id": pack["run_id"]})
                                imported.add(evidence_id)
                            add(f"EVIDENCE_{assessment['outcome']}", hypothesis_id=hid,
                                occurrence_id=existing[hid], evidence_id=evidence_id,
                                outcome=assessment["outcome"],
                                reason=assessment["comparison"],
                                artifact_ref=record["artifact_ref"])
                        self._set_workflow(
                            con, existing[hid], "AUDITED", events[-1]
                        )
                elif node == "L9b":
                    assessment_ids = [item["hypothesis_id"] for item in normalized["assessments"]]
                    self._require_exhaustive(
                        "L9b assessments", assessment_ids,
                        self._active_occurrences(con, existing),
                    )
                    verified = self._verified_evidence_ids(
                        con, project_id=project_id, candidate_id=candidate_id,
                        round_id=str(round_id),
                    )
                    for item in normalized["assessments"]:
                        unknown = set(item["evidence_ids"]) - verified
                        if unknown:
                            raise LedgerError(
                                f"L9b may reference only verified evidence: {sorted(unknown)}"
                            )
                        add("INTERPRETED", hypothesis_id=item["hypothesis_id"],
                            occurrence_id=existing[item["hypothesis_id"]],
                            reason=item["interpretation"], payload=item)
                elif node == "L10a":
                    assessment_ids = [item["hypothesis_id"] for item in normalized["assessments"]]
                    self._require_exhaustive(
                        "L10a assessments", assessment_ids,
                        self._active_occurrences(con, existing),
                    )
                    for item in normalized["assessments"]:
                        add("VALUE_ASSESSED", hypothesis_id=item["hypothesis_id"],
                            occurrence_id=existing[item["hypothesis_id"]],
                            reason=item["value_assessment"], payload=item)
                elif node == "L9a":
                    active = self._active_occurrences(con, existing)
                    ids = [item["hypothesis_id"] for item in normalized["assessments"]]
                    self._require_exhaustive("L9a assessments", ids, active)
                    for item in normalized["assessments"]:
                        status = item["epistemic_status"]
                        verified = self._verified_evidence_ids(
                            con, project_id=project_id, candidate_id=candidate_id,
                            round_id=str(round_id),
                        )
                        unknown_evidence = set(item["evidence_ids"]) - verified
                        if unknown_evidence:
                            raise LedgerError(f"L9a may reference only verified evidence: {sorted(unknown_evidence)}")
                        prior = con.execute("SELECT epistemic_status,event_id FROM epistemic_projection WHERE hypothesis_id=?", (item["hypothesis_id"],)).fetchone()
                        if status == "FALSIFIED" and not item.get("falsification_criterion"):
                            raise LedgerError("L9a FALSIFIED assessment requires falsification_criterion")
                        if status == "FALSIFIED":
                            criteria = json.loads(con.execute(
                                "SELECT falsification_criteria_json FROM versions WHERE hypothesis_id=?",
                                (item["hypothesis_id"],),
                            ).fetchone()[0])
                            if item["falsification_criterion"] not in criteria:
                                raise LedgerError(
                                    "L9a FALSIFIED must cite an exact predeclared falsification criterion"
                                )
                            contradicted = {str(row["evidence_id"]) for row in con.execute(
                                "SELECT evidence_id FROM events WHERE hypothesis_id=? "
                                "AND project_id=? AND candidate_id=? AND round_id=? "
                                "AND event_type='EVIDENCE_CONTRADICTS' AND evidence_id IS NOT NULL",
                                (item["hypothesis_id"], project_id, candidate_id,
                                 str(round_id)),
                            ).fetchall()}
                            if not set(item["evidence_ids"]) & contradicted:
                                raise LedgerError("L9a FALSIFIED requires verified contradictory evidence for that hypothesis")
                        if prior and prior["epistemic_status"] == "FALSIFIED" and status != "FALSIFIED":
                            if not item.get("supersedes_event_id") or item["supersedes_event_id"] != prior["event_id"]:
                                raise LedgerError("reopening FALSIFIED hypothesis must supersede the prior assessment event")
                            prior_seq = con.execute(
                                "SELECT commit_seq FROM events WHERE event_id=?",
                                (prior["event_id"],),
                            ).fetchone()[0]
                            new_evidence = con.execute(
                                "SELECT 1 FROM events WHERE hypothesis_id=? AND project_id=? "
                                "AND candidate_id=? AND round_id=? "
                                "AND event_type='EVIDENCE_CONTRADICTS' AND evidence_id IN ("
                                + ",".join("?" for _ in item["evidence_ids"]) +
                                ") AND commit_seq>? LIMIT 1",
                                (item["hypothesis_id"], project_id, candidate_id,
                                 str(round_id), *item["evidence_ids"], prior_seq),
                            ).fetchone() if item["evidence_ids"] else None
                            if not new_evidence:
                                raise LedgerError(
                                    "reopening FALSIFIED hypothesis requires newly committed verified contradictory evidence"
                                )
                            event_type = "REOPENED"
                        else:
                            event_type = "FALSIFIED" if status == "FALSIFIED" else "EPISTEMIC_ASSESSED"
                        event = add(event_type, hypothesis_id=item["hypothesis_id"], occurrence_id=existing[item["hypothesis_id"]], outcome=status, reason=item["reason"], supersedes_event_id=item.get("supersedes_event_id"), payload={"evidence_ids": item["evidence_ids"], "criterion": item.get("falsification_criterion", "")})
                        self._set_epistemic(con, item["hypothesis_id"], status, event)
                        self._set_workflow(con, existing[item["hypothesis_id"]], "REVIEWED", event)
                elif node == "L10b":
                    active = {hid for hid, oid in existing.items() if (row := con.execute("SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?", (oid,)).fetchone()) and row[0] not in {"REJECTED", "ARCHIVED", "SUPERSEDED"}}
                    ids = {item["hypothesis_id"] for item in normalized["hypothesis_decisions"]}
                    if ids != active:
                        raise LedgerError("L10b must dispose every and only active hypothesis occurrence")
                    for item in normalized["hypothesis_decisions"]:
                        status = {"RETAIN": "RETAINED", "REVISE": "REVISION_REQUIRED", "ARCHIVE": "ARCHIVED"}[item["disposition"]]
                        event = add(status, hypothesis_id=item["hypothesis_id"], occurrence_id=existing[item["hypothesis_id"]], outcome=item["disposition"], reason=item["reason"])
                        self._set_workflow(con, existing[item["hypothesis_id"]], status, event)
                    proposal = normalized.get("next_round_proposal")
                    if normalized["decision"] == "REVISE":
                        if not proposal or not normalized["next_steps"]:
                            raise LedgerError("L10b REVISE requires next_round_proposal and non-empty next_steps")
                        parents = proposal["parent_hypothesis_ids"]
                        self._require_occurrences(con, project_id, candidate_id, str(round_id), parents)
                        if proposal["relationship"] == "REVISION_OF" and len(parents) != 1:
                            raise LedgerError("REVISION_OF must have exactly one parent hypothesis")
                        statement = normalize_statement(proposal["statement"])
                        statement_hash = content_hash(statement)
                        family_id = _uuid("HF", self.store_id, statement_hash)
                        if proposal["relationship"] == "REVISION_OF":
                            family_id = con.execute("SELECT family_id FROM versions WHERE hypothesis_id=?", (parents[0],)).fetchone()[0]
                            parent_statement = con.execute("SELECT statement FROM versions WHERE hypothesis_id=?", (parents[0],)).fetchone()[0]
                            if statement != parent_statement:
                                raise LedgerError("REVISION_OF must preserve the parent hypothesis family statement")
                        definition = {"statement": statement, "operationalization": proposal["operationalization"].strip(), "falsification_criteria": proposal["falsification_criteria"]}
                        definition_hash = content_hash(definition)
                        hid = _uuid("H", self.store_id, definition_hash)
                        proposal["hypothesis_family_id"] = family_id
                        proposal["hypothesis_id"] = hid
                        con.execute("INSERT OR IGNORE INTO families(family_id,statement,statement_hash,created_at) VALUES (?,?,?,?)", (family_id, statement, statement_hash, _now()))
                        con.execute("INSERT OR IGNORE INTO versions(hypothesis_id,family_id,statement,operationalization,falsification_criteria_json,definition_hash,created_at) VALUES (?,?,?,?,?,?,?)", (hid, family_id, statement, proposal["operationalization"].strip(), canonical_json(proposal["falsification_criteria"]), definition_hash, _now()))
                        add("REVISED" if proposal["relationship"] == "REVISION_OF" else "DERIVED", hypothesis_id=hid, outcome=proposal["relationship"], reason=proposal["reason"], payload={"parents": parents, "loop_type": proposal["loop_type"]})
                    elif proposal is not None:
                        raise LedgerError("only L10b REVISE may create next_round_proposal")
            persisted_errors = validate_persisted(node, normalized)
            if persisted_errors:
                raise LedgerError(
                    "persisted delta v2 schema rejected: " + "; ".join(persisted_errors)
                )
            final_hash = content_hash(normalized)
            if final_hash != delta_hash:
                delta_hash = final_hash
                # IDs are sourced from immutable content, not this final envelope; event
                # fingerprints must bind the persisted artifact hash.
                for event in events:
                    event["artifact_ref"]["sha256"] = delta_hash
                    event["fingerprint"] = content_hash({"delta_hash": delta_hash, "event_id": event["event_id"]})
            # L1/L7/L10b normalization assigns engine-owned IDs, so the hash
            # visible on retry is not necessarily the submission hash checked
            # above. Roll back the speculative projection work and return the
            # prior immutable emission instead of creating a second commit.
            final_prior = con.execute(
                "SELECT commit_seq FROM emissions WHERE delta_hash=? AND project_id=? "
                "AND candidate_id=? AND round_id=? AND node=?",
                (delta_hash, project_id, candidate_id, str(round_id), node),
            ).fetchone()
            if final_prior:
                seq0 = int(final_prior["commit_seq"])
                rows = con.execute("SELECT event_id FROM events WHERE commit_seq=? ORDER BY rowid", (seq0,)).fetchall()
                con.rollback()
                receipt = self._receipt(project_id, candidate_id, str(round_id), node, persona,
                                        delta_hash, seq0, [row[0] for row in rows])
                return CommitResult(normalized, delta_hash, seq0, tuple(row[0] for row in rows), receipt)
            con.execute("INSERT INTO emissions(delta_hash,project_id,candidate_id,round_id,node,persona,delta_path,committed_at,commit_seq) VALUES (?,?,?,?,?,?,?,?,?)", (delta_hash, project_id, candidate_id, str(round_id), node, persona, str(relative_delta_path).replace("\\", "/"), _now(), seq))
            for event in events:
                self._insert_event(con, event)
            con.commit()
            receipt = self._receipt(project_id, candidate_id, str(round_id), node, persona, delta_hash, seq, [event["event_id"] for event in events])
            return CommitResult(normalized, delta_hash, seq, tuple(event["event_id"] for event in events), receipt)
        except sqlite3.Error as exc:
            con.rollback()
            raise LedgerError(f"hypothesis ledger transaction failed: {exc}") from exc
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def finalize_emission(self, delta_hash: str, *, artifact_sha256: str,
                          receipt_sha256: str) -> None:
        """Mark an emission consumable after its artifact and receipt exist."""
        if artifact_sha256 != delta_hash:
            raise LedgerError("emission artifact hash does not match delta hash")
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute(
                "SELECT 1 FROM emissions WHERE delta_hash=?", (delta_hash,)
            ).fetchone():
                raise LedgerError("cannot finalize an unknown ledger emission")
            con.execute(
                "INSERT OR IGNORE INTO committed_emissions"
                "(delta_hash,artifact_sha256,receipt_sha256,finalized_at) "
                "VALUES (?,?,?,?)",
                (delta_hash, artifact_sha256, receipt_sha256, _now()),
            )
            row = con.execute(
                "SELECT artifact_sha256,receipt_sha256 FROM committed_emissions "
                "WHERE delta_hash=?", (delta_hash,),
            ).fetchone()
            if not row or tuple(row) != (artifact_sha256, receipt_sha256):
                raise LedgerError("emission finalization conflicts with immutable marker")
            con.commit()
        except sqlite3.Error as exc:
            con.rollback()
            raise LedgerError(f"emission finalization failed: {exc}") from exc
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _receipt(self, project_id: str, candidate_id: str, round_id: str, node: str, persona: str, delta_hash: str, commit_seq: int, event_ids: list[str]) -> dict[str, Any]:
        return {"schema_version": "1.0", "store_id": self.store_id, "project_id": project_id,
                "candidate_id": candidate_id, "round_id": str(round_id), "node": node, "persona": persona,
                "delta_hash": delta_hash, "commit_seq": commit_seq, "event_ids": event_ids, "created_at": _now()}

    def graph(self, hypothesis_id: str, *, as_of: int | None = None) -> dict[str, Any]:
        con = self._connect(readonly=True)
        try:
            version = con.execute("SELECT * FROM versions WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()
            if not version:
                raise LedgerError(f"unknown hypothesis_id: {hypothesis_id}")
            limit = "" if as_of is None else " AND commit_seq <= ?"
            params: list[Any] = [hypothesis_id]
            if as_of is not None: params.append(int(as_of))
            events = [dict(row) for row in con.execute("SELECT * FROM events WHERE hypothesis_id=?" + limit + " ORDER BY commit_seq,event_id", params).fetchall()]
            occurrences = [dict(row) for row in con.execute(
                "SELECT DISTINCT o.* FROM occurrences o JOIN events e ON e.occurrence_id=o.occurrence_id "
                "WHERE o.hypothesis_id=?" + ("" if as_of is None else " AND e.commit_seq<=?"),
                ((hypothesis_id,) if as_of is None else (hypothesis_id, int(as_of))),
            ).fetchall()]
            current_event = next((event for event in reversed(events)
                                  if event["node"] == "L9a"
                                  and event.get("outcome") in EPISTEMIC_STATUSES), None)
            current_state = ({"epistemic_status": current_event["outcome"],
                              "event_id": current_event["event_id"],
                              "commit_seq": current_event["commit_seq"]}
                             if current_event else {"epistemic_status": "UNASSESSED"})
            node = {"kind": "hypothesis_version", **dict(version), "current_state": current_state}
            return {"schema_version": GRAPH_SCHEMA_VERSION, "nodes": [node], "edges": [], "events": events, "occurrences": occurrences}
        finally:
            con.close()

    def history(self, hypothesis_id: str, *, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise LedgerError("history limit must be between 1 and 1000")
        con = self._connect(readonly=True)
        try:
            rows = con.execute("SELECT * FROM events WHERE hypothesis_id=? AND commit_seq>? ORDER BY commit_seq,event_id LIMIT ?", (hypothesis_id, int(after), int(limit))).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()

    def search(self, text: str = "", limit: int = 50) -> list[dict[str, Any]]:
        con = self._connect(readonly=True)
        try:
            rows = con.execute("SELECT v.hypothesis_id,v.family_id,v.statement,v.operationalization,e.epistemic_status FROM versions v LEFT JOIN epistemic_projection e ON e.hypothesis_id=v.hypothesis_id WHERE v.statement LIKE ? ORDER BY v.statement LIMIT ?", (f"%{text}%", int(limit))).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()

    def ranking_inputs(self, candidate_ids: list[str], stage: str,
                       *, as_of: int | None = None,
                       project_id: str | None = None) -> dict[str, Any]:
        """Return immutable ledger DTOs for the pure advisory ranking algorithm."""
        if stage not in {"L3", "L10b"}:
            raise LedgerError("ranking stage must be L3 or L10b")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise LedgerError("ranking candidate IDs must be unique")
        con = self._connect(readonly=True)
        try:
            cursor = int(as_of) if as_of is not None else int(con.execute(
                "SELECT COALESCE(MAX(commit_seq),0) FROM events"
            ).fetchone()[0])
            candidates = []
            decisions = []
            for candidate_id in candidate_ids:
                params: list[Any] = [candidate_id, cursor]
                project_clause = ""
                if project_id:
                    project_clause = " AND e.project_id=?"
                    params.append(project_id)
                rows = con.execute(
                    "SELECT e.*,v.statement,m.delta_hash,m.delta_path "
                    "FROM events e JOIN versions v ON v.hypothesis_id=e.hypothesis_id "
                    "JOIN emissions m ON m.commit_seq=e.commit_seq "
                    "WHERE e.candidate_id=? AND e.event_type='PROPOSED' "
                    "AND e.commit_seq<=?" + project_clause +
                    " ORDER BY e.commit_seq,e.event_id", params,
                ).fetchall()
                if not rows:
                    raise LedgerError(f"ranking candidate has no ledger L1 occurrence: {candidate_id}")
                primary = next((row for row in rows
                                if json.loads(row["payload_json"]).get("primary")), rows[0])
                candidates.append({
                    "candidate_id": candidate_id,
                    "hypothesis_id": primary["hypothesis_id"],
                    "statement": primary["statement"],
                    "occurrence_id": primary["occurrence_id"],
                    "source_emission": {
                        "commit_seq": primary["commit_seq"],
                        "delta_hash": primary["delta_hash"],
                        "delta_path": primary["delta_path"],
                    },
                })
                decision_types = ({"SELECTED", "REJECTED"} if stage == "L3" else
                                  {"RETAINED", "REVISION_REQUIRED", "ARCHIVED"})
                placeholders = ",".join("?" for _ in decision_types)
                decision = con.execute(
                    f"SELECT event_type,outcome,commit_seq,event_id FROM events "
                    f"WHERE occurrence_id=? AND commit_seq<=? AND event_type IN ({placeholders}) "
                    "ORDER BY commit_seq DESC,event_id DESC LIMIT 1",
                    (primary["occurrence_id"], cursor, *sorted(decision_types)),
                ).fetchone()
                formal = "UNAVAILABLE"
                if decision:
                    formal = ({"RETAINED": "KEEP", "REVISION_REQUIRED": "REVISE",
                               "ARCHIVED": "DROP"}.get(decision["event_type"],
                              decision["event_type"]))
                decisions.append({
                    "candidate_id": candidate_id,
                    "hypothesis_id": primary["hypothesis_id"],
                    "formal_decision": formal,
                    "source_event_id": decision["event_id"] if decision else None,
                    "source_commit_seq": decision["commit_seq"] if decision else None,
                })
            return {"schema_version": "1.0", "as_of_commit_seq": cursor,
                    "candidates": candidates, "formal_decisions": decisions}
        finally:
            con.close()

    def verify(self, rebuild: bool = False) -> list[str]:
        con = self._connect(readonly=not rebuild)
        try:
            problems = []
            version = con.execute("SELECT value FROM ledger_meta WHERE key='schema_version'").fetchone()
            if not version or version[0] != STORE_SCHEMA_VERSION:
                problems.append("unsupported hypothesis ledger schema version")
            bad = con.execute("SELECT e.event_id FROM events e LEFT JOIN emissions m ON m.commit_seq=e.commit_seq WHERE m.commit_seq IS NULL").fetchall()
            problems.extend(f"event without emission: {row[0]}" for row in bad)
            if rebuild:
                before = content_hash({
                    "workflow": [dict(row) for row in con.execute(
                        "SELECT * FROM workflow_projection ORDER BY occurrence_id"
                    )],
                    "epistemic": [dict(row) for row in con.execute(
                        "SELECT * FROM epistemic_projection ORDER BY hypothesis_id"
                    )],
                })
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM workflow_projection")
                con.execute("DELETE FROM epistemic_projection")
                workflow_events = {
                    "PROPOSED": "PROPOSED", "SELECTED": "SELECTED",
                    "REJECTED": "REJECTED", "METHOD_DESIGNED": "METHOD_DESIGNED",
                    "METHOD_APPROVED": "METHOD_APPROVED", "EXECUTED": "EXECUTED",
                    "RETAINED": "RETAINED", "REVISION_REQUIRED": "REVISION_REQUIRED",
                    "ARCHIVED": "ARCHIVED", "SUPERSEDED": "SUPERSEDED",
                }
                for row in con.execute(
                    "SELECT * FROM events ORDER BY commit_seq,event_id"
                ).fetchall():
                    event = dict(row)
                    workflow = workflow_events.get(event["event_type"])
                    if event["node"] in {"L8", "L8.5"} and event["hypothesis_id"]:
                        workflow = "AUDITED"
                    if event["node"] == "L9a" and event["hypothesis_id"]:
                        workflow = "REVIEWED"
                    if workflow and event["occurrence_id"]:
                        con.execute(
                            "INSERT INTO workflow_projection VALUES (?,?,?,?) "
                            "ON CONFLICT(occurrence_id) DO UPDATE SET workflow_status=excluded.workflow_status,event_id=excluded.event_id,commit_seq=excluded.commit_seq",
                            (event["occurrence_id"], workflow, event["event_id"],
                             event["commit_seq"]),
                        )
                    if (event["node"] == "L9a"
                            and event["outcome"] in EPISTEMIC_STATUSES
                            and event["hypothesis_id"]):
                        con.execute(
                            "INSERT INTO epistemic_projection VALUES (?,?,?,?) "
                            "ON CONFLICT(hypothesis_id) DO UPDATE SET epistemic_status=excluded.epistemic_status,event_id=excluded.event_id,commit_seq=excluded.commit_seq",
                            (event["hypothesis_id"], event["outcome"],
                             event["event_id"], event["commit_seq"]),
                        )
                after = content_hash({
                    "workflow": [dict(row) for row in con.execute(
                        "SELECT * FROM workflow_projection ORDER BY occurrence_id"
                    )],
                    "epistemic": [dict(row) for row in con.execute(
                        "SELECT * FROM epistemic_projection ORDER BY hypothesis_id"
                    )],
                })
                if before != after:
                    con.rollback()
                    problems.append("projection rebuild differs from persisted projection")
                else:
                    con.commit()
            return problems
        finally:
            con.close()

    def snapshot_candidate(self, project_dir: str | Path, candidate_id: str,
                           round_id: str) -> dict[str, Any]:
        """Return a fixed, candidate-scoped event cursor for loop memory/context."""
        binding = self.require_binding(project_dir)
        con = self._connect(readonly=True)
        try:
            rows = con.execute(
                "SELECT event_id,commit_seq,hypothesis_id,occurrence_id,event_type,outcome "
                "FROM events WHERE project_id=? AND candidate_id=? AND round_id=? "
                "ORDER BY commit_seq,event_id",
                (binding["project_id"], candidate_id, str(round_id)),
            ).fetchall()
            event_refs = [dict(row) for row in rows]
            return {"store_id": self.store_id, "project_id": binding["project_id"],
                    "candidate_id": candidate_id, "round_id": str(round_id),
                    "as_of_commit_seq": max((int(row["commit_seq"]) for row in rows), default=0),
                    "authorized_events": event_refs,
                    "projection_hash": content_hash(event_refs)}
        finally:
            con.close()

    def authorize_context(self, project_dir: str | Path, hypothesis_id: str, through_commit_seq: int, reason: str) -> dict[str, Any]:
        binding = self.require_binding(project_dir)
        snapshot = self.graph(hypothesis_id, as_of=through_commit_seq)
        digest = content_hash(snapshot)
        authorization_id = _uuid("AUTH", binding["project_id"], hypothesis_id, str(through_commit_seq), digest)
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT OR IGNORE INTO authorizations(authorization_id,project_id,hypothesis_id,through_commit_seq,snapshot_hash,reason,created_at) VALUES (?,?,?,?,?,?,?)", (authorization_id, binding["project_id"], hypothesis_id, int(through_commit_seq), digest, reason, _now()))
            con.commit()
        finally:
            con.close()
        return {"authorization_id": authorization_id, "hypothesis_id": hypothesis_id, "through_commit_seq": int(through_commit_seq), "snapshot_hash": digest}

    def materialize_authorized_context(
        self, project_dir: str | Path, candidate_id: str, round_id: str,
        node: str, *, as_of: int | None = None,
    ) -> dict[str, Any]:
        """Persist a candidate/node-scoped immutable snapshot derived from the DAG."""
        from research_loop.topology import DAG_SEQUENCE, NODE_MAP

        if node not in NODE_MAP:
            raise LedgerError(f"unknown context authorization node: {node}")
        binding = self.require_activated_project(project_dir)
        raw_inputs = NODE_MAP[node].get("context_inputs", [])
        if "ALL" in raw_inputs:
            allowed_nodes = [item for item in DAG_SEQUENCE if item != "L9_parallel"]
        else:
            allowed_nodes = [item for item in raw_inputs if item in NODE_MAP]
        con = self._connect()
        try:
            latest = con.execute(
                "SELECT COALESCE(MAX(commit_seq),0) FROM events WHERE project_id=? "
                "AND candidate_id=? AND round_id=?",
                (binding["project_id"], candidate_id, str(round_id)),
            ).fetchone()[0]
            cursor = int(latest if as_of is None else as_of)
            if cursor < 0 or cursor > int(latest):
                raise LedgerError("authorization as-of cursor is outside candidate history")
            if allowed_nodes:
                placeholders = ",".join("?" for _ in allowed_nodes)
                rows = con.execute(
                    f"SELECT * FROM events WHERE project_id=? AND candidate_id=? "
                    f"AND round_id=? AND commit_seq<=? AND node IN ({placeholders}) "
                    "ORDER BY commit_seq,event_id",
                    (binding["project_id"], candidate_id, str(round_id), cursor,
                     *allowed_nodes),
                ).fetchall()
            else:
                rows = []
            events = []
            for row in rows:
                event = dict(row)
                event["artifact_ref"] = json.loads(event.pop("artifact_ref_json"))
                event["payload"] = json.loads(event.pop("payload_json"))
                events.append(event)
            occurrence_rows = con.execute(
                "SELECT o.occurrence_id,o.hypothesis_id,v.statement "
                "FROM occurrences o JOIN versions v ON v.hypothesis_id=o.hypothesis_id "
                "WHERE o.project_id=? AND o.candidate_id=? AND o.round_id=?",
                (binding["project_id"], candidate_id, str(round_id)),
            ).fetchall()
        finally:
            con.close()
        state = []
        for occurrence in occurrence_rows:
            relevant = [event for event in events
                        if event.get("occurrence_id") == occurrence["occurrence_id"]]
            if not relevant:
                continue
            epistemic = "UNASSESSED"
            for event in relevant:
                if event["node"] == "L9a" and event.get("outcome") in EPISTEMIC_STATUSES:
                    epistemic = event["outcome"]
            visible = {"occurrence_id": occurrence["occurrence_id"],
                       "hypothesis_id": occurrence["hypothesis_id"],
                       "epistemic_status": epistemic}
            if "L1" in allowed_nodes:
                visible["statement"] = occurrence["statement"]
            state.append(visible)
        projection = {"events": events, "current_state": state}
        projection_hash = content_hash(projection)
        event_ids = [event["event_id"] for event in events]
        authorization_id = _uuid(
            "AUTH", binding["project_id"], candidate_id, str(round_id), node,
            str(cursor), projection_hash,
        )
        snapshot = {
            "schema_version": "2.0", "authorization_id": authorization_id,
            "store_id": self.store_id, "project_id": binding["project_id"],
            "candidate_id": candidate_id, "round_id": str(round_id),
            "node": node, "as_of_commit_seq": cursor,
            "allowed_source_nodes": allowed_nodes, "event_ids": event_ids,
            "projection_hash": projection_hash, **projection,
        }
        artifact_hash = content_hash(snapshot)
        snapshot["artifact_hash"] = artifact_hash
        target = (Path(project_dir) / "08_Audit" / "hypothesis_context" /
                  f"{authorization_id.replace(':', '_')}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json(snapshot)
        if target.exists() and target.read_text(encoding="utf-8") != raw:
            raise LedgerError(f"authorization snapshot collision: {target}")
        if not target.exists():
            with target.open("x", encoding="utf-8") as handle:
                handle.write(raw)
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT OR IGNORE INTO authorization_snapshots(authorization_id,project_id,candidate_id,round_id,node,through_commit_seq,event_ids_json,projection_hash,artifact_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (authorization_id, binding["project_id"], candidate_id,
                 str(round_id), node, cursor, canonical_json(event_ids),
                 projection_hash, artifact_hash, _now()),
            )
            con.commit()
        finally:
            con.close()
        return {**snapshot, "artifact_path": str(target)}

    def load_authorized_context(self, project_dir: str | Path,
                                authorization_id: str) -> dict[str, Any]:
        binding = self.require_activated_project(project_dir)
        con = self._connect()
        try:
            row = con.execute(
                "SELECT * FROM authorization_snapshots WHERE authorization_id=? "
                "AND project_id=?", (authorization_id, binding["project_id"]),
            ).fetchone()
        finally:
            con.close()
        if not row:
            raise LedgerError("unknown or unauthorized hypothesis context snapshot")
        target = (Path(project_dir) / "08_Audit" / "hypothesis_context" /
                  f"{authorization_id.replace(':', '_')}.json")
        try:
            snapshot = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(f"authorization snapshot missing or invalid: {target}") from exc
        actual_hash = content_hash({key: value for key, value in snapshot.items()
                                    if key != "artifact_hash"})
        if actual_hash != row["artifact_hash"] or snapshot.get("artifact_hash") != actual_hash:
            raise LedgerError(f"authorization snapshot hash mismatch: {target}")
        if snapshot.get("projection_hash") != row["projection_hash"]:
            raise LedgerError(f"authorization projection hash mismatch: {target}")
        return snapshot
