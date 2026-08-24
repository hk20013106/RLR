"""Fail-closed discovery-query provenance for Curie.

Discovery transports own raw provider receipts, while the multi-source
orchestrator owns the exact QueryPlan query that produced each batch. This
extension attaches that authoritative query lineage after discovery and before
Selector use. Provider payloads cannot invent or erase originating query IDs.
"""
from __future__ import annotations

import json

from .contracts import CurieContractError


def _copy(value):
    return json.loads(json.dumps(value))


def _record_matches(multisource_module, canonical: dict, observed: dict) -> bool:
    if str(canonical.get("paper_id") or "") == str(observed.get("paper_id") or ""):
        return True
    left = multisource_module._stable_ids(canonical)
    right = multisource_module._stable_ids(observed)
    return bool(left and right and left.intersection(right))


def _attach_originating_queries(multisource_module, result: dict) -> dict:
    if not isinstance(result, dict):
        raise CurieContractError("multi-source discovery result must be an object")
    batches = result.get("batches")
    records = result.get("records")
    if not isinstance(batches, list) or not isinstance(records, list):
        raise CurieContractError(
            "multi-source discovery result must contain batch and record lists"
        )

    query_ids_by_index: list[list[str]] = [[] for _ in records]
    for batch in batches:
        if not isinstance(batch, dict):
            raise CurieContractError("discovery batch provenance must be an object")
        query_id = str(batch.get("query_id") or "").strip()
        if not query_id:
            raise CurieContractError("discovery batch has no authoritative query_id")
        batch_records = batch.get("records")
        if not isinstance(batch_records, list):
            raise CurieContractError("discovery batch records must be a list")
        for observed in batch_records:
            matches = [
                index
                for index, canonical in enumerate(records)
                if _record_matches(multisource_module, canonical, observed)
            ]
            if len(matches) != 1:
                raise CurieContractError(
                    "discovery query provenance cannot resolve exactly one canonical paper"
                )
            lineage = query_ids_by_index[matches[0]]
            if query_id not in lineage:
                lineage.append(query_id)

    hardened = _copy(result)
    for index, record in enumerate(hardened["records"]):
        lineage = query_ids_by_index[index]
        if not lineage:
            raise CurieContractError(
                "canonical discovery paper has no originating query provenance"
            )
        provenance = record.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
            record["provenance"] = provenance
        provenance["originating_query_ids"] = lineage
    return hardened


def _strict_query_ids(record: dict) -> list[str]:
    provenance = record.get("provenance") if isinstance(record, dict) else None
    if not isinstance(provenance, dict):
        raise CurieContractError("selector record has no discovery provenance")
    values = provenance.get("originating_query_ids")
    if not isinstance(values, list) or not values:
        raise CurieContractError(
            "selector record has no originating query provenance"
        )
    query_ids: list[str] = []
    for value in values:
        query_id = str(value or "").strip()
        if not query_id:
            raise CurieContractError(
                "selector originating query provenance contains an empty query_id"
            )
        if query_id not in query_ids:
            query_ids.append(query_id)
    return query_ids


def install(multisource_module, selector_module) -> None:
    """Install query-lineage enforcement once on canonical Curie modules."""
    if getattr(multisource_module, "_query_provenance_hardened", False):
        return

    original_run = multisource_module.run_multisource_discovery

    def run_multisource_discovery(plan, transports, *, page_size=25,
                                  allow_partial=False):
        result = original_run(
            plan,
            transports,
            page_size=page_size,
            allow_partial=allow_partial,
        )
        return _attach_originating_queries(multisource_module, result)

    multisource_module.run_multisource_discovery = run_multisource_discovery
    selector_module._query_ids = _strict_query_ids
    multisource_module._query_provenance_hardened = True
    selector_module._query_provenance_hardened = True
