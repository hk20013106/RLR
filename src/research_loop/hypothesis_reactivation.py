"""Focused lifecycle extension for recalled historical hypotheses."""
from __future__ import annotations

import contextvars
import json
from pathlib import Path
from typing import Any

from research_loop.hypothesis_recall import load_recall, validate_recall


_EVENT_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("rlr_hypothesis_reactivation", default=None)
)
_ORIGINS = {"NEW", "REACTIVATE", "REVISE", "DERIVE"}


def _definition(ledger_module, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "statement": ledger_module.normalize_statement(item["statement"]),
        "operationalization": str(item["operationalization"]).strip(),
        "falsification_criteria": list(item["falsification_criteria"]),
    }


def _source_definition(ledger_module, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "statement": ledger_module.normalize_statement(result["statement"]),
        "operationalization": str(result["operationalization"]).strip(),
        "falsification_criteria": list(result["falsification_criteria"]),
    }


def _recall_for_l1(
    ledger_module,
    ledger,
    project_dir,
    candidate_id: str,
    round_id: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    artifact = load_recall(project_dir, candidate_id, round_id)
    validate_recall(
        ledger,
        project_dir,
        artifact,
        expected_candidate_id=candidate_id,
        expected_round_id=round_id,
    )
    return artifact, {
        str(item["hypothesis_id"]): item
        for item in artifact.get("results") or []
    }


def _require_recalled(
    ledger_module,
    recalled: dict[str, dict[str, Any]],
    hypothesis_id: str,
) -> dict[str, Any]:
    result = recalled.get(str(hypothesis_id))
    if result is None:
        raise ledger_module.LedgerError(
            f"historical hypothesis {hypothesis_id} is absent from the bound recall"
        )
    return result


def _prepare_l1(
    ledger_module,
    ledger,
    project_dir,
    candidate_id: str,
    round_id: str,
    delta: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    normalized = json.loads(json.dumps(delta))
    items = normalized.get("hypotheses")
    if not isinstance(items, list):
        return normalized, {}

    artifact = None
    recalled: dict[str, dict[str, Any]] = {}
    if any(str(item.get("origin") or "NEW") != "NEW" for item in items):
        artifact, recalled = _recall_for_l1(
            ledger_module,
            ledger,
            project_dir,
            candidate_id,
            round_id,
        )

    event_context: dict[str, dict[str, Any]] = {}
    definition_hashes: set[str] = set()
    reused_sources: set[str] = set()

    for item in items:
        origin = str(item.get("origin") or "NEW")
        if origin not in _ORIGINS:
            raise ledger_module.LedgerError(
                f"unknown hypothesis origin: {origin}"
            )
        item["origin"] = origin
        definition = _definition(ledger_module, item)
        definition_hash = ledger_module.content_hash(definition)
        if definition_hash in definition_hashes:
            raise ledger_module.LedgerError(
                "L1 contains duplicate target hypothesis definitions"
            )
        definition_hashes.add(definition_hash)

        metadata: dict[str, Any] = {
            "origin": origin,
            "recall_artifact_hash": (
                artifact.get("artifact_hash") if artifact else None
            ),
            "recall_as_of_commit_seq": (
                artifact.get("as_of_commit_seq") if artifact else None
            ),
        }
        if origin == "NEW":
            event_context[str(item["proposal_key"])] = metadata
            continue

        if origin in {"REACTIVATE", "REVISE"}:
            source_id = str(item["source_hypothesis_id"])
            if source_id in reused_sources:
                raise ledger_module.LedgerError(
                    f"historical source is reused more than once in this L1 delta: {source_id}"
                )
            reused_sources.add(source_id)
            source = _require_recalled(ledger_module, recalled, source_id)
            source_definition = _source_definition(ledger_module, source)
            source_occurrence = str(
                item.get("source_occurrence_id")
                or source.get("source_occurrence_id")
                or ""
            )
            if item.get("source_occurrence_id") and source_occurrence != str(
                source.get("source_occurrence_id") or ""
            ):
                raise ledger_module.LedgerError(
                    "source occurrence is absent from the bound recall"
                )
            if source.get("reactivation_eligibility") == "BLOCKED_FALSIFIED":
                raise ledger_module.LedgerError(
                    "FALSIFIED hypothesis requires formal reopening before L1 reuse"
                )
            if origin == "REACTIVATE":
                if definition != source_definition:
                    raise ledger_module.LedgerError(
                        "REACTIVATE requires the exact historical definition"
                    )
                if (
                    source.get("reactivation_eligibility") != "ELIGIBLE"
                    and not item.get("reactivation_basis")
                ):
                    raise ledger_module.LedgerError(
                        "REACTIVATE requires a basis for this historical status"
                    )
            else:
                if definition["statement"] != source_definition["statement"]:
                    raise ledger_module.LedgerError(
                        "REVISE must preserve the historical family statement"
                    )
                if definition == source_definition:
                    raise ledger_module.LedgerError(
                        "REVISE must change operationalization or falsification criteria"
                    )
            metadata.update(
                {
                    "source_hypothesis_id": source_id,
                    "source_occurrence_id": source_occurrence,
                    "prior_blocking_event_ids": list(
                        source.get("unresolved_blocker_event_ids") or []
                    ),
                    "reactivation_basis": item.get("reactivation_basis"),
                    "change_summary": item.get("change_summary"),
                }
            )
        else:
            parent_ids = [str(value) for value in item["parent_hypothesis_ids"]]
            parent_records = [
                _require_recalled(ledger_module, recalled, parent_id)
                for parent_id in parent_ids
            ]
            if any(parent_id in reused_sources for parent_id in parent_ids):
                raise ledger_module.LedgerError(
                    "historical source is reused more than once in this L1 delta"
                )
            reused_sources.update(parent_ids)
            if any(
                parent.get("reactivation_eligibility") == "BLOCKED_FALSIFIED"
                for parent in parent_records
            ):
                raise ledger_module.LedgerError(
                    "FALSIFIED parent requires formal reopening before derivation"
                )
            if any(
                definition["statement"]
                == _source_definition(ledger_module, parent)["statement"]
                for parent in parent_records
            ):
                raise ledger_module.LedgerError(
                    "DERIVE must change the normalized statement"
                )
            metadata.update(
                {
                    "parent_hypothesis_ids": parent_ids,
                    "prior_blocking_event_ids": sorted(
                        {
                            event_id
                            for parent in parent_records
                            for event_id in (
                                parent.get("unresolved_blocker_event_ids") or []
                            )
                        }
                    ),
                    "change_summary": item.get("change_summary"),
                }
            )
        event_context[str(item["proposal_key"])] = metadata

    return normalized, event_context


def _current_l1_origins(
    ledger_module,
    ledger,
    project_dir,
    candidate_id: str,
    round_id: str,
) -> dict[str, dict[str, Any]]:
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
    result = {}
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        result[str(row["hypothesis_id"])] = payload
    return result


def _prepare_l3(
    ledger_module,
    ledger,
    project_dir,
    candidate_id: str,
    round_id: str,
    delta: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    origins = _current_l1_origins(
        ledger_module,
        ledger,
        project_dir,
        candidate_id,
        round_id,
    )
    context: dict[str, dict[str, Any]] = {}
    for item in delta.get("triage") or []:
        hypothesis_id = str(item.get("hypothesis_id") or "")
        source = origins.get(hypothesis_id) or {}
        origin = str(source.get("origin") or "NEW")
        assessment = item.get("reactivation_assessment")
        obligations = item.get("downstream_obligations") or []
        if origin == "NEW":
            if assessment is not None:
                raise ledger_module.LedgerError(
                    "NEW hypothesis must not carry reactivation assessment"
                )
            continue
        if not isinstance(assessment, dict):
            raise ledger_module.LedgerError(
                f"L3 requires reactivation assessment for {hypothesis_id}"
            )
        expected_blockers = set(
            source.get("prior_blocking_event_ids") or []
        )
        submitted_blockers = set(
            assessment.get("prior_blocking_event_ids") or []
        )
        if submitted_blockers != expected_blockers:
            raise ledger_module.LedgerError(
                f"L3 blocker assessment is not exhaustive for {hypothesis_id}"
            )
        verdict = str(assessment.get("basis_verdict") or "")
        if item.get("disposition") == "SELECTED" and verdict == "UNRESOLVED":
            raise ledger_module.LedgerError(
                "L3 cannot select an unresolved reactivation"
            )
        if (
            item.get("disposition") == "SELECTED"
            and verdict == "PARTIALLY_RESOLVED"
            and not obligations
        ):
            raise ledger_module.LedgerError(
                "partially resolved reactivation requires downstream obligations"
            )
        blocker_ids = expected_blockers
        for obligation in obligations:
            unknown = set(
                obligation.get("source_blocker_event_ids") or []
            ) - blocker_ids
            if unknown:
                raise ledger_module.LedgerError(
                    f"reactivation obligation references unknown blockers: {sorted(unknown)}"
                )
        context[hypothesis_id] = {
            "origin": origin,
            "reactivation_assessment": assessment,
            "downstream_obligations": obligations,
        }
    return context


def install(ledger_module) -> None:
    """Install a narrow wrapper around L1/L3 while retaining base transactions."""
    if getattr(ledger_module, "_REACTIVATION_LIFECYCLE_INSTALLED", False):
        return

    cls = ledger_module.HypothesisLedger
    original_commit = cls.commit_delta
    original_event = cls._event

    def commit_delta(self, *args, **kwargs):
        node = str(kwargs.get("node") or "")
        delta = kwargs.get("delta")
        schema_version = (
            str(delta.get("schema_version") or "")
            if isinstance(delta, dict)
            else ""
        )
        if schema_version != "2.1" or node not in {"L1", "L3"}:
            return original_commit(self, *args, **kwargs)

        project_dir = kwargs["project_dir"]
        candidate_id = str(kwargs["candidate_id"])
        round_id = str(kwargs["round_id"])
        if node == "L1":
            normalized, event_context = _prepare_l1(
                ledger_module,
                self,
                project_dir,
                candidate_id,
                round_id,
                delta,
            )
            kwargs["delta"] = normalized
            context = {"node": "L1", "items": event_context}
        else:
            event_context = _prepare_l3(
                ledger_module,
                self,
                project_dir,
                candidate_id,
                round_id,
                delta,
            )
            context = {"node": "L3", "items": event_context}

        token = _EVENT_CONTEXT.set(context)
        try:
            return original_commit(self, *args, **kwargs)
        finally:
            _EVENT_CONTEXT.reset(token)

    def _event(self, *args, **kwargs):
        context = _EVENT_CONTEXT.get()
        if context and context.get("node") == "L1":
            payload = dict(kwargs.get("payload") or {})
            proposal_key = str(payload.get("proposal_key") or "")
            metadata = (context.get("items") or {}).get(proposal_key)
            if metadata and kwargs.get("event_type") == "PROPOSED":
                origin = metadata["origin"]
                kwargs["event_type"] = {
                    "NEW": "PROPOSED",
                    "REACTIVATE": "REPROPOSED",
                    "REVISE": "REVISED",
                    "DERIVE": "DERIVED",
                }[origin]
                kwargs["payload"] = {
                    **payload,
                    **{
                        key: value
                        for key, value in metadata.items()
                        if value is not None
                    },
                }
        elif context and context.get("node") == "L3":
            hypothesis_id = str(kwargs.get("hypothesis_id") or "")
            metadata = (context.get("items") or {}).get(hypothesis_id)
            if metadata and kwargs.get("event_type") in {"SELECTED", "REJECTED"}:
                disposition = str(kwargs["event_type"])
                reason_code = kwargs.get("outcome")
                kwargs["event_type"] = "REACTIVATION_REVIEWED"
                kwargs["outcome"] = disposition
                kwargs["payload"] = {
                    "origin": metadata["origin"],
                    "disposition": disposition,
                    "reason_code": reason_code,
                    "reactivation_assessment": metadata[
                        "reactivation_assessment"
                    ],
                    "downstream_obligations": metadata[
                        "downstream_obligations"
                    ],
                }
        return original_event(self, *args, **kwargs)

    cls.commit_delta = commit_delta
    cls._event = _event
    ledger_module._REACTIVATION_LIFECYCLE_INSTALLED = True
