"""Deterministic, rebuildable projection of finalized hypothesis-ledger facts."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from research_loop.hypothesis_contracts import EPISTEMIC_STATUSES
from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError, content_hash


POOL_SCHEMA_VERSION = "HypothesisPool/v1"
_ELIGIBILITY = {
    "ELIGIBLE",
    "ELIGIBLE_WITH_BASIS",
    "REQUIRES_EXPLICIT_OVERRIDE",
    "BLOCKED_FALSIFIED",
}
_WORKFLOW_EVENTS = {
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


def _decode_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _latest_finalized_commit_seq(ledger: HypothesisLedger) -> int:
    con = ledger._connect(readonly=True)
    try:
        row = con.execute(
            "SELECT COALESCE(MAX(m.commit_seq),0) "
            "FROM emissions m JOIN committed_emissions c "
            "ON c.delta_hash=m.delta_hash"
        ).fetchone()
        return int(row[0])
    finally:
        con.close()


def _eligibility(
    epistemic_status: str,
    latest_workflow_status: str,
    rejection_count: int,
    unresolved_blockers: list[str],
) -> tuple[str, list[str]]:
    if epistemic_status == "FALSIFIED":
        return "BLOCKED_FALSIFIED", ["formal reopening is required"]
    if latest_workflow_status == "ARCHIVED" or epistemic_status == "CONTRADICTED":
        return (
            "REQUIRES_EXPLICIT_OVERRIDE",
            ["explicit reviewed basis is required"],
        )
    if (
        rejection_count
        or unresolved_blockers
        or epistemic_status == "INSUFFICIENT_EVIDENCE"
    ):
        return (
            "ELIGIBLE_WITH_BASIS",
            ["new evidence or changed conditions are required"],
        )
    return "ELIGIBLE", []


def _workflow_status(event: dict[str, Any]) -> str | None:
    status = _WORKFLOW_EVENTS.get(str(event["event_type"]))
    if status:
        return status
    if event.get("event_type") == "REACTIVATION_REVIEWED":
        disposition = str(event.get("payload", {}).get("disposition") or "")
        if disposition in {"SELECTED", "REJECTED"}:
            return disposition
    if event.get("hypothesis_id") and event.get("node") in {"L8", "L8.5"}:
        return "AUDITED"
    if event.get("hypothesis_id") and event.get("node") == "L9a":
        return "REVIEWED"
    return None


def build_pool(
    ledger: HypothesisLedger,
    *,
    as_of: int | None = None,
) -> dict[str, Any]:
    """Build one deterministic pool record per finalized hypothesis version."""
    latest = _latest_finalized_commit_seq(ledger)
    cursor = latest if as_of is None else int(as_of)
    if cursor < 0 or cursor > latest:
        raise LedgerError("hypothesis-pool cursor is outside finalized ledger history")

    con = ledger._connect(readonly=True)
    try:
        version_rows = con.execute(
            "SELECT DISTINCT v.* FROM versions v "
            "JOIN events e ON e.hypothesis_id=v.hypothesis_id "
            "JOIN emissions m ON m.commit_seq=e.commit_seq "
            "JOIN committed_emissions c ON c.delta_hash=m.delta_hash "
            "WHERE e.commit_seq<=? ORDER BY v.hypothesis_id",
            (cursor,),
        ).fetchall()
        event_rows = con.execute(
            "SELECT e.* FROM events e "
            "JOIN emissions m ON m.commit_seq=e.commit_seq "
            "JOIN committed_emissions c ON c.delta_hash=m.delta_hash "
            "WHERE e.hypothesis_id IS NOT NULL AND e.commit_seq<=? "
            "ORDER BY e.commit_seq,e.event_id",
            (cursor,),
        ).fetchall()
    finally:
        con.close()

    events_by_hypothesis: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        event = dict(row)
        event["payload"] = _decode_json(event.pop("payload_json", "{}"), {})
        event["artifact_ref"] = _decode_json(
            event.pop("artifact_ref_json", "{}"), {}
        )
        events_by_hypothesis[str(event["hypothesis_id"])].append(event)

    records: list[dict[str, Any]] = []
    family_members: dict[str, list[str]] = defaultdict(list)
    for row in version_rows:
        version = dict(row)
        hypothesis_id = str(version["hypothesis_id"])
        family_id = str(version["family_id"])
        family_members[family_id].append(hypothesis_id)
        events = events_by_hypothesis[hypothesis_id]

        occurrences: dict[str, dict[str, Any]] = {}
        for event in events:
            occurrence_id = event.get("occurrence_id")
            if not occurrence_id:
                continue
            occurrence = occurrences.setdefault(
                str(occurrence_id),
                {
                    "occurrence_id": str(occurrence_id),
                    "project_id": str(event["project_id"]),
                    "candidate_id": str(event["candidate_id"]),
                    "round_id": str(event["round_id"]),
                    "workflow_status": "PROPOSED",
                    "first_commit_seq": int(event["commit_seq"]),
                    "last_commit_seq": int(event["commit_seq"]),
                },
            )
            occurrence["last_commit_seq"] = int(event["commit_seq"])
            status = _workflow_status(event)
            if status:
                occurrence["workflow_status"] = status

        occurrence_history = sorted(
            occurrences.values(),
            key=lambda item: (
                int(item["first_commit_seq"]),
                str(item["occurrence_id"]),
            ),
        )
        latest_occurrence = (
            max(
                occurrence_history,
                key=lambda item: (
                    int(item["last_commit_seq"]),
                    str(item["occurrence_id"]),
                ),
            )
            if occurrence_history
            else None
        )
        latest_workflow_status = (
            str(latest_occurrence["workflow_status"])
            if latest_occurrence
            else "PROPOSED"
        )

        attacks = [event for event in events if event["event_type"] == "ATTACKED"]
        rejections = [
            event
            for event in events
            if event["event_type"] == "REJECTED"
            or (
                event["event_type"] == "REACTIVATION_REVIEWED"
                and event.get("payload", {}).get("disposition") == "REJECTED"
            )
        ]
        last_rejection_event = rejections[-1] if rejections else None
        last_rejection = None
        if last_rejection_event:
            payload = last_rejection_event.get("payload", {})
            last_rejection = {
                "event_id": str(last_rejection_event["event_id"]),
                "project_id": str(last_rejection_event["project_id"]),
                "candidate_id": str(last_rejection_event["candidate_id"]),
                "round_id": str(last_rejection_event["round_id"]),
                "reason_code": str(
                    payload.get("reason_code")
                    or last_rejection_event.get("outcome")
                    or ""
                ),
                "reason": str(last_rejection_event.get("reason") or ""),
                "commit_seq": int(last_rejection_event["commit_seq"]),
            }

        epistemic_status = "UNASSESSED"
        for event in events:
            if (
                event.get("node") == "L9a"
                and event.get("outcome") in EPISTEMIC_STATUSES
            ):
                epistemic_status = str(event["outcome"])

        attack_scopes = sorted(
            {
                str(event["payload"].get("scope") or "ATTACK")
                for event in attacks
            }
        )
        unresolved_blockers = {str(event["event_id"]) for event in attacks}
        for event in events:
            if event["event_type"] != "REACTIVATION_REVIEWED":
                continue
            assessment = event.get("payload", {}).get(
                "reactivation_assessment"
            ) or {}
            if assessment.get("basis_verdict") == "RESOLVED":
                unresolved_blockers.difference_update(
                    str(value)
                    for value in assessment.get("prior_blocking_event_ids") or []
                )
        unresolved_blocker_ids = sorted(unresolved_blockers)
        eligibility, requirements = _eligibility(
            epistemic_status,
            latest_workflow_status,
            len(rejections),
            unresolved_blocker_ids,
        )
        if eligibility not in _ELIGIBILITY:
            raise LedgerError(f"invalid reactivation eligibility: {eligibility}")

        records.append(
            {
                "hypothesis_id": hypothesis_id,
                "hypothesis_family_id": family_id,
                "statement": str(version["statement"]),
                "operationalization": str(version["operationalization"]),
                "falsification_criteria": _decode_json(
                    version["falsification_criteria_json"], []
                ),
                "definition_hash": str(version["definition_hash"]),
                "epistemic_status": epistemic_status,
                "occurrence_count": len(occurrence_history),
                "occurrences": occurrence_history,
                "attack_count": len(attacks),
                "attack_scopes": attack_scopes,
                "rejection_count": len(rejections),
                "last_rejection": last_rejection,
                "latest_occurrence": latest_occurrence,
                "latest_workflow_status": latest_workflow_status,
                "unresolved_blocker_event_ids": unresolved_blocker_ids,
                "reactivation_eligibility": eligibility,
                "reactivation_requirements": requirements,
                "first_seen_at": str(events[0]["created_at"]) if events else None,
                "last_seen_at": str(events[-1]["created_at"]) if events else None,
                "related_version_ids": [],
            }
        )

    for record in records:
        record["related_version_ids"] = sorted(
            item
            for item in family_members[record["hypothesis_family_id"]]
            if item != record["hypothesis_id"]
        )

    body = {
        "schema_version": POOL_SCHEMA_VERSION,
        "store_id": ledger.store_id,
        "as_of_commit_seq": cursor,
        "records": sorted(records, key=lambda item: item["hypothesis_id"]),
    }
    return {**body, "projection_hash": content_hash(body)}


def search_pool(
    ledger: HypothesisLedger,
    *,
    text: str = "",
    as_of: int | None = None,
    eligibility: set[str] | None = None,
    epistemic_status: set[str] | None = None,
    workflow_status: set[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Filter the deterministic pool without changing source ordering."""
    if limit < 1 or limit > 200:
        raise LedgerError("hypothesis-pool limit must be between 1 and 200")
    unknown = set(eligibility or ()) - _ELIGIBILITY
    if unknown:
        raise LedgerError(f"unknown reactivation eligibility: {sorted(unknown)}")
    needle = " ".join(str(text).casefold().split())
    pool = build_pool(ledger, as_of=as_of)
    records = []
    for record in pool["records"]:
        haystack = " ".join(
            [record["statement"], record["operationalization"]]
        ).casefold()
        if needle and needle not in haystack:
            continue
        if eligibility and record["reactivation_eligibility"] not in eligibility:
            continue
        if epistemic_status and record["epistemic_status"] not in epistemic_status:
            continue
        if workflow_status and record["latest_workflow_status"] not in workflow_status:
            continue
        records.append(record)
        if len(records) >= limit:
            break
    body = {
        "schema_version": POOL_SCHEMA_VERSION,
        "store_id": pool["store_id"],
        "as_of_commit_seq": pool["as_of_commit_seq"],
        "query": {
            "text": text,
            "eligibility": sorted(eligibility or ()),
            "epistemic_status": sorted(epistemic_status or ()),
            "workflow_status": sorted(workflow_status or ()),
            "limit": limit,
        },
        "records": records,
    }
    return {**body, "projection_hash": content_hash(body)}
