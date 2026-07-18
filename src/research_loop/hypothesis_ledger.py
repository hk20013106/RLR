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

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover - installation contract
    raise RuntimeError("jsonschema is required for hypothesis delta v2") from exc


STORE_SCHEMA_VERSION = "1.0"
DELTA_SCHEMA_VERSION = "2.0"
GRAPH_SCHEMA_VERSION = "1.0"
NAMESPACE = uuid.UUID("d879c2d5-e8e7-4835-bf91-17c6a7d8da99")

WORKFLOW_STATUSES = {
    "PROPOSED", "SELECTED", "REJECTED", "METHOD_DESIGNED",
    "METHOD_APPROVED", "EXECUTED", "AUDITED", "REVIEWED", "RETAINED",
    "REVISION_REQUIRED", "SUPERSEDED", "ARCHIVED",
}
EPISTEMIC_STATUSES = {
    "UNASSESSED", "INSUFFICIENT_EVIDENCE", "PROVISIONALLY_SUPPORTED",
    "CONTRADICTED", "FALSIFIED",
}
LOOP_TYPES = {"correction", "divergent", "data-acquisition"}
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


def _required(properties: dict[str, Any], required: list[str], *, extra=True):
    result = {"type": "object", "properties": properties, "required": required}
    if not extra:
        result["additionalProperties"] = False
    return result


_ID = {"type": "string", "minLength": 1}
_STR = {"type": "string", "minLength": 1}
_STR_LIST = {"type": "array", "items": _STR}
_REF = _required({
    "path": _STR, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "json_pointer": {"type": "string"},
}, ["path", "sha256"], extra=False)
_HYPOTHESIS = _required({
    "proposal_key": _STR, "statement": _STR, "operationalization": _STR,
    "falsification_criteria": {"type": "array", "minItems": 1, "items": _STR},
    "rationale": _STR,
}, ["proposal_key", "statement", "operationalization", "falsification_criteria", "rationale"])
_TRIAGE = _required({
    "hypothesis_id": _ID, "disposition": {"enum": ["SELECTED", "REJECTED"]},
    "reason_code": _STR, "reason": _STR,
}, ["hypothesis_id", "disposition", "reason_code", "reason"], extra=False)
_ATTACK = _required({
    "hypothesis_id": _ID, "severity": _STR, "text": _STR,
}, ["hypothesis_id", "severity", "text"])
_TARGETED = _required({
    "hypothesis_ids": {"type": "array", "minItems": 1, "items": _ID},
}, ["hypothesis_ids"])


def _node_schema(node: str) -> dict[str, Any]:
    """Return a Draft 2020-12 submission schema for one node."""
    base = {
        "schema_version": {"const": DELTA_SCHEMA_VERSION},
        "candidate_id": _ID,
    }
    if node == "L1":
        base.update({"hypotheses": {"type": "array", "minItems": 1, "items": _HYPOTHESIS},
                     "primary_proposal_key": _STR, "key_uncertainty": _STR})
        required = ["schema_version", "hypotheses", "primary_proposal_key", "key_uncertainty"]
    elif node == "L2":
        base.update({"attacks": {"type": "array", "items": _ATTACK},
                     "confounders": {"type": "array", "items": _ATTACK},
                     "diagnostic_tests": {"type": "array", "items": _ATTACK}, "verdict": _STR})
        required = ["schema_version", "attacks", "confounders", "diagnostic_tests", "verdict"]
    elif node == "L3":
        base.update({"triage": {"type": "array", "minItems": 1, "items": _TRIAGE}, "route_to": _STR})
        required = ["schema_version", "triage", "route_to"]
    elif node in {"L4", "L5", "L6"}:
        key = "strategies" if node == "L4" else ("attacks" if node == "L5" else "analysis_plan")
        base[key] = {"type": "array", "minItems": 1,
                     "items": {"allOf": [_TARGETED, {"type": "object"}]}}
        if node == "L6":
            base["method_decision"] = {"enum": ["APPROVE", "REJECT"]}
            base["reason"] = _STR
            required = ["schema_version", key, "method_decision", "reason"]
        else:
            required = ["schema_version", key]
    elif node == "L7":
        result = _required({"result_key": _STR, "hypothesis_ids": {"type": "array", "minItems": 1, "items": _ID},
                            "summary": _STR, "artifact_refs": {"type": "array", "minItems": 1, "items": _REF}},
                           ["result_key", "hypothesis_ids", "summary", "artifact_refs"])
        base.update({"results": {"type": "array", "minItems": 1, "items": result},
                     "scripts_run": {"type": "array"}, "warnings": {"type": "array"}, "failures": {"type": "array"}})
        required = ["schema_version", "results", "scripts_run", "warnings", "failures"]
    elif node == "L8":
        assessment = _required({
            "evidence_id": _ID, "verification": {"enum": ["VERIFIED", "REJECTED"]},
            "relations": {"type": "array", "items": _required({"hypothesis_id": _ID,
                "outcome": {"enum": ["SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"]}, "reason": _STR},
                ["hypothesis_id", "outcome", "reason"], extra=False)},
        }, ["evidence_id", "verification", "relations"], extra=False)
        base["evidence_assessments"] = {"type": "array", "items": assessment}
        required = ["schema_version", "evidence_assessments"]
    elif node == "L8.5":
        paper = _required({"evidence_id": _ID, "hypothesis_ids": {"type": "array", "minItems": 1, "items": _ID},
                           "outcome": {"enum": ["SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"]}, "comparison": _STR},
                          ["evidence_id", "hypothesis_ids", "outcome", "comparison"])
        base.update({"papers": {"type": "array", "items": paper}, "summary": _STR})
        required = ["schema_version", "papers", "summary"]
    elif node == "L9a":
        assessment = _required({
            "hypothesis_id": _ID, "epistemic_status": {"enum": sorted(EPISTEMIC_STATUSES)},
            "reason": _STR, "evidence_ids": {"type": "array", "items": _ID},
            "falsification_criterion": {"type": "string"}, "supersedes_event_id": {"type": "string"},
        }, ["hypothesis_id", "epistemic_status", "reason", "evidence_ids"])
        base["assessments"] = {"type": "array", "minItems": 1, "items": assessment}
        required = ["schema_version", "assessments"]
    elif node in {"L9b", "L10a"}:
        base["assessments"] = {"type": "array", "minItems": 1,
                               "items": {"allOf": [_TARGETED, {"type": "object"}]}}
        required = ["schema_version", "assessments"]
    elif node == "L10b":
        disposition = _required({"hypothesis_id": _ID,
                                 "disposition": {"enum": ["RETAIN", "REVISE", "ARCHIVE"]},
                                 "reason": _STR}, ["hypothesis_id", "disposition", "reason"], extra=False)
        proposal = _required({
            "proposal_key": _STR, "statement": _STR, "operationalization": _STR,
            "falsification_criteria": {"type": "array", "minItems": 1, "items": _STR},
            "relationship": {"enum": ["REVISION_OF", "DERIVED_FROM"]},
            "parent_hypothesis_ids": {"type": "array", "minItems": 1, "items": _ID},
            "loop_type": {"enum": sorted(LOOP_TYPES)}, "reason": _STR,
        }, ["proposal_key", "statement", "operationalization", "falsification_criteria", "relationship", "parent_hypothesis_ids", "loop_type", "reason"], extra=False)
        base.update({"decision": {"enum": ["KEEP", "REVISE", "DOWNGRADE", "DROP"]},
                     "reason": _STR, "next_steps": {"type": "array", "items": _STR},
                     "hypothesis_decisions": {"type": "array", "items": disposition},
                     "next_round_proposal": proposal})
        required = ["schema_version", "decision", "reason", "next_steps", "hypothesis_decisions"]
    else:
        # L0 is versioned for ownership/provenance but keeps its existing payload.
        return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                "properties": base, "required": ["schema_version"], "additionalProperties": True}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "properties": base, "required": required, "additionalProperties": True}


NODE_SCHEMAS = {node: _node_schema(node) for node in
                ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L8.5", "L9a", "L9b", "L10a", "L10b")}


def validate_submission(node: str, delta: dict[str, Any]) -> list[str]:
    if node not in NODE_SCHEMAS:
        return [f"unknown ledger node: {node}"]
    errors = sorted(jsonschema.Draft202012Validator(NODE_SCHEMAS[node]).iter_errors(delta),
                    key=lambda error: list(error.absolute_path))
    rendered = []
    for error in errors:
        where = "/".join(str(part) for part in error.absolute_path) or "<root>"
        rendered.append(f"{where}: {error.message}")
    return rendered


def binding_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / "00_Preflight" / "hypothesis_store_binding.json"


class HypothesisLedger:
    """SQLite-backed immutable hypothesis facts with rebuildable projections."""

    def __init__(self, store_path: str | Path):
        self.path = Path(store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, commit_seq INTEGER NOT NULL, event_type TEXT NOT NULL, hypothesis_id TEXT, occurrence_id TEXT, evidence_id TEXT, project_id TEXT NOT NULL, candidate_id TEXT NOT NULL, round_id TEXT NOT NULL, node TEXT NOT NULL, persona TEXT NOT NULL, outcome TEXT, reason TEXT, artifact_ref_json TEXT NOT NULL, supersedes_event_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS workflow_projection (occurrence_id TEXT PRIMARY KEY, workflow_status TEXT NOT NULL, event_id TEXT NOT NULL, commit_seq INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS epistemic_projection (hypothesis_id TEXT PRIMARY KEY, epistemic_status TEXT NOT NULL, event_id TEXT NOT NULL, commit_seq INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS authorizations (authorization_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, hypothesis_id TEXT NOT NULL, through_commit_seq INTEGER NOT NULL, snapshot_hash TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
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
                CREATE TRIGGER IF NOT EXISTS events_append_only BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            """)
            con.execute("INSERT OR IGNORE INTO ledger_meta(key, value) VALUES (?, ?)", ("schema_version", STORE_SCHEMA_VERSION))
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

    def bind_project(self, project_dir: str | Path, project_id: str | None = None) -> dict[str, Any]:
        project_dir = Path(project_dir)
        project_id = project_id or _uuid("PROJECT", self.store_id, str(uuid.uuid4()))
        binding = {"schema_version": "1.0", "store_id": self.store_id, "project_id": project_id, "bound_at": _now()}
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT OR IGNORE INTO projects(project_id, store_id, created_at) VALUES (?, ?, ?)", (project_id, self.store_id, binding["bound_at"]))
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
        missing = sorted(set(ids) - set(known))
        if missing:
            raise LedgerError(f"unknown or unauthorized hypothesis IDs for this candidate/round: {missing}")
        return known

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
                     node: str, persona: str, delta: dict[str, Any], delta_path: str | Path) -> CommitResult:
        """Validate and record one v2 delta atomically with its lifecycle events.

        The caller writes the normalized returned object only after this method
        succeeds.  The emission records the expected hash/path; consumers must
        verify both before treating the artifact as authoritative.
        """
        binding = self.require_binding(project_dir)
        project_id = str(binding["project_id"])
        if delta.get("candidate_id") not in (None, candidate_id):
            raise LedgerError("candidate_id mismatch in delta")
        normalized = json.loads(json.dumps(delta))
        normalized["candidate_id"] = candidate_id
        normalized["schema_version"] = DELTA_SCHEMA_VERSION
        errors = validate_submission(node, normalized)
        if errors:
            raise LedgerError("delta v2 schema rejected: " + "; ".join(errors))
        delta_hash = content_hash(normalized)
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            prior = con.execute("SELECT commit_seq FROM emissions WHERE delta_hash=?", (delta_hash,)).fetchone()
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
                event = self._event(commit_seq=seq, delta_hash=delta_hash, ordinal=ordinal, event_type=event_type,
                                    project_id=project_id, candidate_id=candidate_id, round_id=str(round_id), node=node, persona=persona, artifact_ref=artifact_ref, **kwargs)
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
                    event = add("PROPOSED", hypothesis_id=hypothesis_id, occurrence_id=occurrence_id, outcome="PROPOSED", reason=item["rationale"], payload={"family_id": family_id, "proposal_key": item["proposal_key"]})
                    self._set_workflow(con, occurrence_id, "PROPOSED", event)
                if normalized["primary_proposal_key"] not in keys:
                    raise LedgerError("L1 primary_proposal_key does not identify a submitted hypothesis")
                normalized["primary_hypothesis_id"] = keys[normalized.pop("primary_proposal_key")]
            else:
                existing = self._existing_occurrences(con, project_id, candidate_id, str(round_id))
                if node == "L2":
                    for group in ("attacks", "confounders", "diagnostic_tests"):
                        for item in normalized[group]:
                            self._require_occurrences(con, project_id, candidate_id, str(round_id), [item["hypothesis_id"]])
                            add("ATTACKED", hypothesis_id=item["hypothesis_id"], occurrence_id=existing[item["hypothesis_id"]], outcome=item["severity"], reason=item["text"])
                elif node == "L3":
                    ids = [item["hypothesis_id"] for item in normalized["triage"]]
                    if len(ids) != len(set(ids)):
                        raise LedgerError("L3 triage contains duplicate hypothesis_id")
                    if set(ids) != set(existing):
                        raise LedgerError("L3 triage must dispose every and only current L1 hypothesis")
                    for item in normalized["triage"]:
                        event = add(item["disposition"], hypothesis_id=item["hypothesis_id"], occurrence_id=existing[item["hypothesis_id"]], outcome=item["reason_code"], reason=item["reason"])
                        self._set_workflow(con, existing[item["hypothesis_id"]], item["disposition"], event)
                elif node in {"L4", "L5", "L6", "L9b", "L10a"}:
                    collection = normalized["strategies"] if node == "L4" else (normalized["attacks"] if node == "L5" else normalized["analysis_plan"] if node == "L6" else normalized["assessments"])
                    mapping = {"L4": "METHOD_DESIGNED", "L5": "ATTACKED", "L6": "METHOD_APPROVED", "L9b": "INTERPRETED", "L10a": "VALUE_ASSESSED"}
                    for item in collection:
                        ids = item.get("hypothesis_ids", [])
                        self._require_occurrences(con, project_id, candidate_id, str(round_id), ids)
                        for hid in ids:
                            event = add(mapping[node], hypothesis_id=hid, occurrence_id=existing[hid], reason=str(item.get("reason") or item.get("name") or node), payload=item)
                            if node == "L4": self._set_workflow(con, existing[hid], "METHOD_DESIGNED", event)
                            if node == "L6" and normalized["method_decision"] == "APPROVE": self._set_workflow(con, existing[hid], "METHOD_APPROVED", event)
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
                    submitted = {item["evidence_id"] for item in normalized["evidence_assessments"]}
                    if submitted != pending:
                        raise LedgerError("L8 must assess every and only L7 pending evidence record")
                    for item in normalized["evidence_assessments"]:
                        add(f"EVIDENCE_{item['verification']}", evidence_id=item["evidence_id"], outcome=item["verification"])
                        if item["verification"] == "VERIFIED":
                            for relation in item["relations"]:
                                self._require_occurrences(con, project_id, candidate_id, str(round_id), [relation["hypothesis_id"]])
                                event = add(f"EVIDENCE_{relation['outcome']}", hypothesis_id=relation["hypothesis_id"], occurrence_id=existing[relation["hypothesis_id"]], evidence_id=item["evidence_id"], outcome=relation["outcome"], reason=relation["reason"])
                                self._set_workflow(con, existing[relation["hypothesis_id"]], "AUDITED", event)
                elif node == "L8.5":
                    for paper in normalized["papers"]:
                        self._require_occurrences(con, project_id, candidate_id, str(round_id), paper["hypothesis_ids"])
                        for hid in paper["hypothesis_ids"]:
                            event = add(f"EVIDENCE_{paper['outcome']}", hypothesis_id=hid, occurrence_id=existing[hid], evidence_id=paper["evidence_id"], outcome=paper["outcome"], reason=paper["comparison"])
                            self._set_workflow(con, existing[hid], "AUDITED", event)
                elif node == "L9a":
                    active = {hid for hid, oid in existing.items() if (row := con.execute("SELECT workflow_status FROM workflow_projection WHERE occurrence_id=?", (oid,)).fetchone()) and row[0] not in {"REJECTED", "ARCHIVED", "SUPERSEDED"}}
                    ids = {item["hypothesis_id"] for item in normalized["assessments"]}
                    if ids != active:
                        raise LedgerError("L9a must assess every and only active hypothesis occurrence")
                    for item in normalized["assessments"]:
                        status = item["epistemic_status"]
                        verified = {str(row["evidence_id"]) for row in con.execute(
                            "SELECT DISTINCT evidence_id FROM events WHERE event_type='EVIDENCE_VERIFIED' AND evidence_id IS NOT NULL"
                        ).fetchall()}
                        unknown_evidence = set(item["evidence_ids"]) - verified
                        if unknown_evidence:
                            raise LedgerError(f"L9a may reference only verified evidence: {sorted(unknown_evidence)}")
                        prior = con.execute("SELECT epistemic_status,event_id FROM epistemic_projection WHERE hypothesis_id=?", (item["hypothesis_id"],)).fetchone()
                        if status == "FALSIFIED" and not item.get("falsification_criterion"):
                            raise LedgerError("L9a FALSIFIED assessment requires falsification_criterion")
                        if status == "FALSIFIED":
                            contradicted = {str(row["evidence_id"]) for row in con.execute(
                                "SELECT evidence_id FROM events WHERE hypothesis_id=? AND event_type='EVIDENCE_CONTRADICTS' AND evidence_id IS NOT NULL",
                                (item["hypothesis_id"],),
                            ).fetchall()}
                            if not set(item["evidence_ids"]) & contradicted:
                                raise LedgerError("L9a FALSIFIED requires verified contradictory evidence for that hypothesis")
                        if prior and prior["epistemic_status"] == "FALSIFIED" and status != "FALSIFIED":
                            if not item.get("supersedes_event_id") or item["supersedes_event_id"] != prior["event_id"]:
                                raise LedgerError("reopening FALSIFIED hypothesis must supersede the prior assessment event")
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
            final_prior = con.execute("SELECT commit_seq FROM emissions WHERE delta_hash=?", (delta_hash,)).fetchone()
            if final_prior:
                seq0 = int(final_prior["commit_seq"])
                rows = con.execute("SELECT event_id FROM events WHERE commit_seq=? ORDER BY rowid", (seq0,)).fetchall()
                con.rollback()
                receipt = self._receipt(project_id, candidate_id, str(round_id), node, persona,
                                        delta_hash, seq0, [row[0] for row in rows])
                return CommitResult(normalized, delta_hash, seq0, tuple(row[0] for row in rows), receipt)
            con.execute("INSERT INTO emissions(delta_hash,project_id,candidate_id,round_id,node,persona,delta_path,committed_at,commit_seq) VALUES (?,?,?,?,?,?,?,?,?)", (delta_hash, project_id, candidate_id, str(round_id), node, persona, str(delta_path), _now(), seq))
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

    def _receipt(self, project_id: str, candidate_id: str, round_id: str, node: str, persona: str, delta_hash: str, commit_seq: int, event_ids: list[str]) -> dict[str, Any]:
        return {"schema_version": "1.0", "store_id": self.store_id, "project_id": project_id,
                "candidate_id": candidate_id, "round_id": str(round_id), "node": node, "persona": persona,
                "delta_hash": delta_hash, "commit_seq": commit_seq, "event_ids": event_ids, "created_at": _now()}

    def graph(self, hypothesis_id: str, *, as_of: int | None = None) -> dict[str, Any]:
        con = self._connect()
        try:
            version = con.execute("SELECT * FROM versions WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()
            if not version:
                raise LedgerError(f"unknown hypothesis_id: {hypothesis_id}")
            limit = "" if as_of is None else " AND commit_seq <= ?"
            params: list[Any] = [hypothesis_id]
            if as_of is not None: params.append(int(as_of))
            events = [dict(row) for row in con.execute("SELECT * FROM events WHERE hypothesis_id=?" + limit + " ORDER BY commit_seq,event_id", params).fetchall()]
            occurrences = [dict(row) for row in con.execute("SELECT * FROM occurrences WHERE hypothesis_id=?", (hypothesis_id,)).fetchall()]
            current = con.execute("SELECT * FROM epistemic_projection WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()
            node = {"kind": "hypothesis_version", **dict(version), "current_state": dict(current) if current else {"epistemic_status": "UNASSESSED"}}
            return {"schema_version": GRAPH_SCHEMA_VERSION, "nodes": [node], "edges": [], "events": events, "occurrences": occurrences}
        finally:
            con.close()

    def history(self, hypothesis_id: str, *, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise LedgerError("history limit must be between 1 and 1000")
        con = self._connect()
        try:
            rows = con.execute("SELECT * FROM events WHERE hypothesis_id=? AND commit_seq>? ORDER BY commit_seq,event_id LIMIT ?", (hypothesis_id, int(after), int(limit))).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()

    def search(self, text: str = "", limit: int = 50) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute("SELECT v.hypothesis_id,v.family_id,v.statement,v.operationalization,e.epistemic_status FROM versions v LEFT JOIN epistemic_projection e ON e.hypothesis_id=v.hypothesis_id WHERE v.statement LIKE ? ORDER BY v.statement LIMIT ?", (f"%{text}%", int(limit))).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()

    def verify(self) -> list[str]:
        con = self._connect()
        try:
            problems = []
            version = con.execute("SELECT value FROM ledger_meta WHERE key='schema_version'").fetchone()
            if not version or version[0] != STORE_SCHEMA_VERSION:
                problems.append("unsupported hypothesis ledger schema version")
            bad = con.execute("SELECT e.event_id FROM events e LEFT JOIN emissions m ON m.commit_seq=e.commit_seq WHERE m.commit_seq IS NULL").fetchall()
            problems.extend(f"event without emission: {row[0]}" for row in bad)
            return problems
        finally:
            con.close()

    def snapshot_candidate(self, project_dir: str | Path, candidate_id: str,
                           round_id: str) -> dict[str, Any]:
        """Return a fixed, candidate-scoped event cursor for loop memory/context."""
        binding = self.require_binding(project_dir)
        con = self._connect()
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
