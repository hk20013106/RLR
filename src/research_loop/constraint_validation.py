"""Pure, profile-aware cross-artifact constraints for ledger submissions.

This module deliberately owns no persistence.  The ledger supplies one open
SQLite transaction, so every upstream lookup sees the exact snapshot that the
subsequent commit will extend.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from research_loop.compatibility import CompatibilityProfile


class ConstraintViolation(ValueError):
    """A versioned cross-delta invariant was not satisfied."""


_FINALIZED = "EXISTS (SELECT 1 FROM committed_emissions c WHERE c.delta_hash=m.delta_hash)"


def _payloads(con: sqlite3.Connection, *, project_id: str, candidate_id: str,
              round_id: str, node: str) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT e.payload_json FROM events e JOIN emissions m ON m.commit_seq=e.commit_seq "
        "WHERE e.project_id=? AND e.candidate_id=? AND e.round_id=? AND e.node=? AND " + _FINALIZED,
        (project_id, candidate_id, round_id, node),
    ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _selected_ids(con: sqlite3.Connection, *, project_id: str, candidate_id: str,
                  round_id: str) -> set[str]:
    rows = con.execute(
        "SELECT DISTINCT e.hypothesis_id FROM events e "
        "JOIN emissions m ON m.commit_seq=e.commit_seq "
        "JOIN committed_emissions c ON c.delta_hash=m.delta_hash "
        "WHERE e.project_id=? AND e.candidate_id=? AND e.round_id=? "
        "AND e.node='L3' AND e.event_type='SELECTED' "
        "AND e.hypothesis_id IS NOT NULL",
        (project_id, candidate_id, round_id),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _finalized_hypothesis_ids(
    con: sqlite3.Connection, *, project_id: str, candidate_id: str,
    round_id: str, node: str,
) -> set[str]:
    rows = con.execute(
        "SELECT DISTINCT e.hypothesis_id FROM events e "
        "JOIN emissions m ON m.commit_seq=e.commit_seq "
        "JOIN committed_emissions c ON c.delta_hash=m.delta_hash "
        "WHERE e.project_id=? AND e.candidate_id=? AND e.round_id=? "
        "AND e.node=? AND e.hypothesis_id IS NOT NULL",
        (project_id, candidate_id, round_id, node),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _has_finalized_payload(con: sqlite3.Connection, *, project_id: str,
                           candidate_id: str, round_id: str, node: str) -> bool:
    return bool(_payloads(
        con, project_id=project_id, candidate_id=candidate_id,
        round_id=round_id, node=node,
    ))


def _strategies(con: sqlite3.Connection, *, project_id: str, candidate_id: str,
                round_id: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for payload in _payloads(con, project_id=project_id, candidate_id=candidate_id,
                             round_id=round_id, node="L4"):
        strategy_id = payload.get("strategy_id")
        ids = payload.get("hypothesis_ids")
        if isinstance(strategy_id, str) and isinstance(ids, list):
            result[strategy_id] = set(map(str, ids))
    return result


def validate_finalized_upstream(*, con: sqlite3.Connection,
                                profile: CompatibilityProfile, node: str,
                                delta: dict[str, Any], project_id: str,
                                candidate_id: str, round_id: str) -> None:
    """Validate v2.1 rules using only finalized upstream emissions."""
    if profile.delta_schema_version != "2.1":
        return

    if node == "L9b":
        l9a = _payloads(con, project_id=project_id, candidate_id=candidate_id,
                         round_id=round_id, node="L9a")
        if not l9a:
            raise ConstraintViolation("L9b requires a finalized L9a emission under v2.1 serial topology")
    elif node == "L10a":
        missing = [upstream for upstream in ("L9a", "L9b") if not _payloads(
            con, project_id=project_id, candidate_id=candidate_id,
            round_id=round_id, node=upstream,
        )]
        if missing:
            raise ConstraintViolation(
                f"L10a requires finalized serial L9 results: {missing}"
            )
    elif node == "L2":
        verdicts = delta["verdicts"]
        finalized_l1 = _finalized_hypothesis_ids(
            con, project_id=project_id, candidate_id=candidate_id,
            round_id=round_id, node="L1",
        )
        submitted = {str(item["hypothesis_id"]) for item in verdicts}
        if not finalized_l1 or submitted != finalized_l1:
            raise ConstraintViolation(
                "L2 verdicts must cover every and only finalized L1 hypothesis"
            )
        rejects = sum(item["outcome"] == "REJECT" for item in verdicts)
        allowed_na = sum(
            item["outcome"] == "NOT_APPLICABLE"
            and bool(item.get("not_applicable_reason"))
            and bool(item.get("not_applicable_evidence"))
            for item in verdicts
        )
        required_rejects = (len(verdicts) + 1) // 2
        if rejects + allowed_na < required_rejects:
            raise ConstraintViolation(
                "L2 requires at least ceil(L1_count/2) REJECT verdicts; "
                "only evidence-backed NOT_APPLICABLE records may substitute"
            )
        invalid_na = [
            str(item["hypothesis_id"]) for item in verdicts
            if item["outcome"] == "NOT_APPLICABLE"
            and (not item.get("not_applicable_reason")
                 or not item.get("not_applicable_evidence"))
        ]
        if invalid_na:
            raise ConstraintViolation(
                "L2 NOT_APPLICABLE requires reason and evidence for hypotheses: "
                f"{invalid_na}"
            )
    elif node == "L3":
        if not _has_finalized_payload(
            con, project_id=project_id, candidate_id=candidate_id,
            round_id=round_id, node="L2",
        ):
            raise ConstraintViolation("L3 requires a finalized L2 emission")
        finalized_l1 = _finalized_hypothesis_ids(
            con, project_id=project_id, candidate_id=candidate_id,
            round_id=round_id, node="L1",
        )
        submitted = [str(item["hypothesis_id"]) for item in delta["triage"]]
        if (not finalized_l1 or len(submitted) != len(set(submitted))
                or set(submitted) != finalized_l1):
            raise ConstraintViolation(
                "L3 triage must cover every finalized L1 hypothesis exactly once"
            )
        selected = [item for item in delta["triage"] if item["disposition"] == "SELECTED"]
        if len(selected) > 4:
            raise ConstraintViolation("L3 permits at most four SELECTED hypotheses")
    elif node == "L4":
        selected = _selected_ids(con, project_id=project_id, candidate_id=candidate_id,
                                 round_id=round_id)
        if not selected:
            raise ConstraintViolation("L4 requires finalized L3 SELECTED hypotheses")
        seen: set[str] = set()
        for strategy in delta["strategies"]:
            strategy_id = strategy["strategy_id"]
            if strategy_id in seen:
                raise ConstraintViolation(f"L4 contains duplicate strategy_id: {strategy_id}")
            seen.add(strategy_id)
            invalid = set(strategy["hypothesis_ids"]) - selected
            if invalid:
                raise ConstraintViolation(
                    f"L4 strategy {strategy_id} references non-selected hypotheses: {sorted(invalid)}"
                )
    elif node == "L5":
        strategies = _strategies(con, project_id=project_id, candidate_id=candidate_id,
                                 round_id=round_id)
        if not strategies:
            raise ConstraintViolation("L5 requires at least one finalized L4 strategy")
        coverage = {name: set() for name in ("attacks", "qc_checkpoints", "failure_stop_rules")}
        attack_ids = {
            str(payload["attack_id"])
            for payload in _payloads(
                con, project_id=project_id, candidate_id=candidate_id,
                round_id=round_id, node="L5",
            )
            if payload.get("scope") == "METHOD" and payload.get("attack_id")
        }
        for group, ids in coverage.items():
            for item in delta[group]:
                sid = item["strategy_id"]
                if sid not in strategies:
                    raise ConstraintViolation(f"L5 references unknown L4 strategy_id: {sid}")
                if set(item["hypothesis_ids"]) != strategies[sid]:
                    raise ConstraintViolation(
                        f"L5 {group} for strategy {sid} must have the identical L4 hypothesis IDs"
                    )
                if group == "attacks":
                    attack_id = str(item["attack_id"])
                    if attack_id in attack_ids:
                        raise ConstraintViolation(f"L5 contains duplicate attack_id: {attack_id}")
                    attack_ids.add(attack_id)
                ids.add(sid)
        for group, ids in coverage.items():
            missing = set(strategies) - ids
            if missing:
                raise ConstraintViolation(
                    f"L5 lacks {group} for L4 strategy IDs: {sorted(missing)}"
                )
    elif node == "L6":
        strategies = _strategies(con, project_id=project_id, candidate_id=candidate_id,
                                 round_id=round_id)
        if not _has_finalized_payload(
            con, project_id=project_id, candidate_id=candidate_id,
            round_id=round_id, node="L5",
        ):
            raise ConstraintViolation("L6 requires a finalized L5 emission")
        plan_ids = set()
        for plan in delta["analysis_plan"]:
            sid = plan["strategy_id"]
            plan_ids.add(sid)
            if sid not in strategies:
                raise ConstraintViolation(f"L6 references unknown L4 strategy_id: {sid}")
            if set(plan["hypothesis_ids"]) != strategies[sid]:
                raise ConstraintViolation(
                    f"L6 plan {sid} must have the identical L4 hypothesis IDs"
                )
        attacks: dict[str, str] = {}
        for payload in _payloads(
            con, project_id=project_id, candidate_id=candidate_id,
            round_id=round_id, node="L5",
        ):
            if payload.get("scope") != "METHOD":
                continue
            attack_id = payload.get("attack_id")
            if not attack_id:
                raise ConstraintViolation("finalized L5 attack lacks attack_id")
            attacks[str(attack_id)] = str(payload.get("severity") or "")
        resolutions: dict[str, str] = {}
        for plan in delta["analysis_plan"]:
            for resolution in plan.get("attack_resolutions", []):
                attack_id = str(resolution["attack_id"])
                if attack_id in resolutions:
                    raise ConstraintViolation(
                        f"L6 contains duplicate attack resolution: {attack_id}"
                    )
                if attack_id not in attacks:
                    raise ConstraintViolation(
                        f"L6 references unknown L5 attack_id: {attack_id}"
                    )
                resolutions[attack_id] = str(resolution["verdict"])
        if delta["method_decision"] == "APPROVE":
            high = {
                attack_id for attack_id, severity in attacks.items()
                if severity == "HIGH"
            }
            resolved = {
                attack_id for attack_id, verdict in resolutions.items()
                if verdict == "RESOLVED"
            }
            unresolved = high - resolved
            if unresolved:
                raise ConstraintViolation(
                    f"L6 APPROVE leaves HIGH L5 attacks unresolved: {sorted(unresolved)}"
                )
