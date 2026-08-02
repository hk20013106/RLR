"""Compatibility updates for consumers of explicit reactivation event types."""
from __future__ import annotations

import json
from typing import Any


def install(ledger_module, constraint_module) -> None:
    """Teach existing selectors, ranking, and rebuild logic about new events."""
    if getattr(ledger_module, "_REACTIVATION_CONSUMER_COMPAT_INSTALLED", False):
        return

    original_selected_ids = constraint_module._selected_ids

    def _selected_ids(
        con,
        *,
        project_id: str,
        candidate_id: str,
        round_id: str,
    ) -> set[str]:
        selected = original_selected_ids(
            con,
            project_id=project_id,
            candidate_id=candidate_id,
            round_id=round_id,
        )
        rows = con.execute(
            "SELECT e.hypothesis_id,e.payload_json FROM events e "
            "JOIN emissions m ON m.commit_seq=e.commit_seq "
            "JOIN committed_emissions c ON c.delta_hash=m.delta_hash "
            "WHERE e.project_id=? AND e.candidate_id=? AND e.round_id=? "
            "AND e.node='L3' AND e.event_type='REACTIVATION_REVIEWED' "
            "AND e.hypothesis_id IS NOT NULL",
            (project_id, candidate_id, round_id),
        ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"] or "{}")
            if payload.get("disposition") == "SELECTED":
                selected.add(str(row["hypothesis_id"]))
        return selected

    constraint_module._selected_ids = _selected_ids

    cls = ledger_module.HypothesisLedger
    original_ranking_inputs = cls.ranking_inputs
    original_verify = cls.verify

    def ranking_inputs(
        self,
        candidate_ids: list[str],
        stage: str,
        *,
        as_of: int | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        if stage not in {"L3", "L10b"}:
            return original_ranking_inputs(
                self,
                candidate_ids,
                stage,
                as_of=as_of,
                project_id=project_id,
            )
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ledger_module.LedgerError(
                "ranking candidate IDs must be unique"
            )
        con = self._connect(readonly=True)
        try:
            cursor = int(as_of) if as_of is not None else int(con.execute(
                "SELECT COALESCE(MAX(e.commit_seq),0) FROM events e "
                "JOIN emissions m ON m.commit_seq=e.commit_seq WHERE "
                + ledger_module._FINALIZED_EMISSION_PREDICATE
            ).fetchone()[0])
            candidates = []
            decisions = []
            l1_types = ("PROPOSED", "REPROPOSED", "REVISED", "DERIVED")
            l1_placeholders = ",".join("?" for _ in l1_types)
            for candidate_id in candidate_ids:
                params: list[Any] = [candidate_id, cursor, *l1_types]
                project_clause = ""
                if project_id:
                    project_clause = " AND e.project_id=?"
                    params.append(project_id)
                rows = con.execute(
                    "SELECT e.*,v.statement,m.delta_hash,m.delta_path "
                    "FROM events e JOIN versions v "
                    "ON v.hypothesis_id=e.hypothesis_id "
                    "JOIN emissions m ON m.commit_seq=e.commit_seq "
                    "WHERE e.candidate_id=? AND e.commit_seq<=? "
                    f"AND e.event_type IN ({l1_placeholders}) AND "
                    + ledger_module._FINALIZED_EMISSION_PREDICATE
                    + project_clause
                    + " ORDER BY e.commit_seq,e.event_id",
                    params,
                ).fetchall()
                if not rows:
                    raise ledger_module.LedgerError(
                        f"ranking candidate has no ledger L1 occurrence: {candidate_id}"
                    )
                primary = next(
                    (
                        row for row in rows
                        if json.loads(row["payload_json"] or "{}").get("primary")
                    ),
                    rows[0],
                )
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
                decision_types = (
                    {"SELECTED", "REJECTED", "REACTIVATION_REVIEWED"}
                    if stage == "L3"
                    else {"RETAINED", "REVISION_REQUIRED", "ARCHIVED"}
                )
                placeholders = ",".join("?" for _ in decision_types)
                decision = con.execute(
                    "SELECT e.event_type,e.outcome,e.payload_json,e.commit_seq,e.event_id "
                    "FROM events e JOIN emissions m ON m.commit_seq=e.commit_seq "
                    "WHERE e.occurrence_id=? AND e.commit_seq<=? "
                    f"AND e.event_type IN ({placeholders}) AND "
                    + ledger_module._FINALIZED_EMISSION_PREDICATE
                    + " ORDER BY e.commit_seq DESC,e.event_id DESC LIMIT 1",
                    (
                        primary["occurrence_id"],
                        cursor,
                        *sorted(decision_types),
                    ),
                ).fetchone()
                formal = "UNAVAILABLE"
                if decision:
                    if decision["event_type"] == "REACTIVATION_REVIEWED":
                        formal = str(
                            json.loads(decision["payload_json"] or "{}").get(
                                "disposition"
                            )
                            or "UNAVAILABLE"
                        )
                    else:
                        formal = {
                            "RETAINED": "KEEP",
                            "REVISION_REQUIRED": "REVISE",
                            "ARCHIVED": "DROP",
                        }.get(decision["event_type"], decision["event_type"])
                decisions.append({
                    "candidate_id": candidate_id,
                    "hypothesis_id": primary["hypothesis_id"],
                    "formal_decision": formal,
                    "source_event_id": decision["event_id"] if decision else None,
                    "source_commit_seq": (
                        decision["commit_seq"] if decision else None
                    ),
                })
            return {
                "schema_version": "1.0",
                "as_of_commit_seq": cursor,
                "candidates": candidates,
                "formal_decisions": decisions,
            }
        finally:
            con.close()

    def verify(self, rebuild: bool = False) -> list[str]:
        if not rebuild:
            return original_verify(self, rebuild=False)
        problems = original_verify(self, rebuild=False)
        if problems:
            return problems
        con = self._connect()
        try:
            before = ledger_module.content_hash({
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
                "PROPOSED": "PROPOSED",
                "REPROPOSED": "PROPOSED",
                "REVISED": "PROPOSED",
                "DERIVED": "PROPOSED",
                "SELECTED": "SELECTED",
                "REJECTED": "REJECTED",
                "METHOD_DESIGNED": "METHOD_DESIGNED",
                "METHOD_APPROVED": "METHOD_APPROVED",
                "EXECUTED": "EXECUTED",
                "RETAINED": "RETAINED",
                "REVISION_REQUIRED": "REVISION_REQUIRED",
                "ARCHIVED": "ARCHIVED",
                "SUPERSEDED": "SUPERSEDED",
            }
            for row in con.execute(
                "SELECT e.* FROM events e JOIN emissions m "
                "ON m.commit_seq=e.commit_seq WHERE "
                + ledger_module._FINALIZED_EMISSION_PREDICATE
                + " ORDER BY e.commit_seq,e.event_id"
            ).fetchall():
                event = dict(row)
                workflow = workflow_events.get(event["event_type"])
                if event["event_type"] == "REACTIVATION_REVIEWED":
                    disposition = json.loads(
                        event["payload_json"] or "{}"
                    ).get("disposition")
                    if disposition in {"SELECTED", "REJECTED"}:
                        workflow = disposition
                if (
                    event["node"] in {"L8", "L8.5"}
                    and event["hypothesis_id"]
                ):
                    workflow = "AUDITED"
                if event["node"] == "L9a" and event["hypothesis_id"]:
                    workflow = "REVIEWED"
                if workflow and event["occurrence_id"]:
                    con.execute(
                        "INSERT INTO workflow_projection VALUES (?,?,?,?) "
                        "ON CONFLICT(occurrence_id) DO UPDATE SET "
                        "workflow_status=excluded.workflow_status,"
                        "event_id=excluded.event_id,commit_seq=excluded.commit_seq",
                        (
                            event["occurrence_id"],
                            workflow,
                            event["event_id"],
                            event["commit_seq"],
                        ),
                    )
                if (
                    event["node"] == "L9a"
                    and event["outcome"] in ledger_module.EPISTEMIC_STATUSES
                    and event["hypothesis_id"]
                ):
                    con.execute(
                        "INSERT INTO epistemic_projection VALUES (?,?,?,?) "
                        "ON CONFLICT(hypothesis_id) DO UPDATE SET "
                        "epistemic_status=excluded.epistemic_status,"
                        "event_id=excluded.event_id,commit_seq=excluded.commit_seq",
                        (
                            event["hypothesis_id"],
                            event["outcome"],
                            event["event_id"],
                            event["commit_seq"],
                        ),
                    )
            after = ledger_module.content_hash({
                "workflow": [dict(row) for row in con.execute(
                    "SELECT * FROM workflow_projection ORDER BY occurrence_id"
                )],
                "epistemic": [dict(row) for row in con.execute(
                    "SELECT * FROM epistemic_projection ORDER BY hypothesis_id"
                )],
            })
            if before != after:
                con.rollback()
                problems.append(
                    "projection rebuild differs from persisted projection"
                )
            else:
                con.commit()
            return problems
        finally:
            con.close()

    cls.ranking_inputs = ranking_inputs
    cls.verify = verify
    ledger_module._REACTIVATION_CONSUMER_COMPAT_INSTALLED = True
