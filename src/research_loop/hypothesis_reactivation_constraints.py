"""Narrow lineage checks for L3 historical-hypothesis review."""
from __future__ import annotations

import json


def _lineage_by_hypothesis(ledger, project_dir, candidate_id: str, round_id: str):
    binding = ledger.require_activated_project(project_dir)
    con = ledger._connect(readonly=True)
    try:
        rows = con.execute(
            "SELECT e.hypothesis_id,e.payload_json FROM events e "
            "JOIN emissions m ON m.commit_seq=e.commit_seq "
            "JOIN committed_emissions c ON c.delta_hash=m.delta_hash "
            "WHERE e.project_id=? AND e.candidate_id=? AND e.round_id=? "
            "AND e.node='L1' AND e.occurrence_id IS NOT NULL "
            "ORDER BY e.commit_seq,e.event_id",
            (str(binding["project_id"]), candidate_id, round_id),
        ).fetchall()
    finally:
        con.close()
    return {
        str(row["hypothesis_id"]): json.loads(row["payload_json"] or "{}")
        for row in rows
    }


def install(ledger_module) -> None:
    """Require each L3 assessment to name an actual L1 historical source."""
    if getattr(ledger_module, "_REACTIVATION_CONSTRAINTS_INSTALLED", False):
        return

    cls = ledger_module.HypothesisLedger
    original_commit = cls.commit_delta

    def commit_delta(self, *args, **kwargs):
        delta = kwargs.get("delta")
        if (
            str(kwargs.get("node") or "") == "L3"
            and isinstance(delta, dict)
            and str(delta.get("schema_version") or "") == "2.1"
        ):
            candidate_id = str(kwargs["candidate_id"])
            round_id = str(kwargs["round_id"])
            lineage = _lineage_by_hypothesis(
                self,
                kwargs["project_dir"],
                candidate_id,
                round_id,
            )
            for item in delta.get("triage") or []:
                hypothesis_id = str(item.get("hypothesis_id") or "")
                payload = lineage.get(hypothesis_id) or {}
                origin = str(payload.get("origin") or "NEW")
                assessment = item.get("reactivation_assessment")
                if origin == "NEW" or not isinstance(assessment, dict):
                    continue
                submitted_source = str(
                    assessment.get("source_hypothesis_id") or ""
                )
                if origin in {"REACTIVATE", "REVISE"}:
                    allowed = {str(payload.get("source_hypothesis_id") or "")}
                else:
                    allowed = {
                        str(value)
                        for value in payload.get("parent_hypothesis_ids") or []
                    }
                allowed.discard("")
                if submitted_source not in allowed:
                    raise ledger_module.LedgerError(
                        "L3 reactivation source does not match L1 lineage"
                    )
        return original_commit(self, *args, **kwargs)

    cls.commit_delta = commit_delta
    ledger_module._REACTIVATION_CONSTRAINTS_INSTALLED = True
