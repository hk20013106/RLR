"""Cognitive Selector contracts for Curie.

Hard eligibility is deterministic and authoritative. Cognitive scores may rank
only eligible papers; they cannot rescue an ineligible source. Contradiction is
an evidence-value dimension rather than a penalty.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .contracts import CurieContractError

SELECTOR_DECISION_SCHEMA_VERSION = "L05SelectorDecision/v1"
_SELECTOR_RUN_SCHEMA_VERSION = "L05SelectorRun/v1"
_DECISIONS = {"INCLUDE", "EXCLUDE", "RESERVE"}
_SCORE_FIELDS = (
    "relevance",
    "directness",
    "methodological_value",
    "contradiction_value",
    "evidence_diversity",
)
_ROOT = Path("08_Audit") / "l05_selector"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8") + b"\n"
    )


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    return text


def _score(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CurieContractError(f"{name} must be a number between 0 and 1")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise CurieContractError(f"{name} must be between 0 and 1")
    return number


def build_selector_decision(
    *, paper_id: str, decision: str, relevance: float, directness: float,
    methodological_value: float, contradiction_value: float,
    evidence_diversity: float, originating_query_ids: list[str], reason: str,
    reason_code: str | None = None,
) -> dict:
    payload = {
        "schema_version": SELECTOR_DECISION_SCHEMA_VERSION,
        "paper_id": _text(paper_id, "selector paper_id"),
        "decision": str(decision or "").strip().upper(),
        "relevance": relevance,
        "directness": directness,
        "methodological_value": methodological_value,
        "contradiction_value": contradiction_value,
        "evidence_diversity": evidence_diversity,
        "originating_query_ids": list(originating_query_ids or []),
        "reason": _text(reason, "selector reason"),
    }
    if reason_code:
        payload["reason_code"] = str(reason_code)
    return validate_selector_decision(payload)


def validate_selector_decision(decision: dict) -> dict:
    if not isinstance(decision, dict):
        raise CurieContractError("selector decision must be an object")
    if decision.get("schema_version") != SELECTOR_DECISION_SCHEMA_VERSION:
        raise CurieContractError("selector decision schema_version is invalid")
    _text(decision.get("paper_id"), "selector paper_id")
    verdict = _text(decision.get("decision"), "selector decision").upper()
    if verdict not in _DECISIONS:
        raise CurieContractError(
            f"selector decision must be one of {sorted(_DECISIONS)}"
        )
    for field in _SCORE_FIELDS:
        _score(decision.get(field), f"selector {field}")
    query_ids = decision.get("originating_query_ids")
    if not isinstance(query_ids, list) or not query_ids or not all(
        isinstance(item, str) and item.strip() for item in query_ids
    ):
        raise CurieContractError(
            "selector originating_query_ids must be a non-empty list of strings"
        )
    _text(decision.get("reason"), "selector reason")
    return json.loads(json.dumps(decision))


def _query_ids(record: dict) -> list[str]:
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        raise CurieContractError("selector record has no discovery provenance")
    values = provenance.get("originating_query_ids") or []
    if not isinstance(values, list) or not values:
        raise CurieContractError("selector record has no originating query provenance")
    query_ids: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise CurieContractError(
                "selector originating query provenance must contain only strings"
            )
        query_id = value.strip()
        if not query_id:
            raise CurieContractError(
                "selector originating query provenance contains an empty query_id"
            )
        if query_id not in query_ids:
            query_ids.append(query_id)
    return query_ids


def _ranking(decision: dict) -> tuple[float, float, float, float, float]:
    # Contradictory evidence is deliberately valuable. This lexicographic key
    # gives relevance/directness priority while letting strong contradiction
    # break otherwise comparable ties instead of suppressing dissenting papers.
    return (
        decision["relevance"] + decision["directness"],
        decision["contradiction_value"],
        decision["methodological_value"],
        decision["evidence_diversity"],
        decision["relevance"],
    )


def select_candidates(
    records: list[dict], *, seed: dict,
    scorer: Callable[[dict, dict], dict],
    eligibility: Callable[[dict], tuple[bool, str]],
    max_papers: int = 3,
    project_dir: str | Path | None = None,
    candidate_id: str | None = None,
    run_id: str | None = None,
) -> dict:
    if not isinstance(records, list):
        raise CurieContractError("selector records must be a list")
    if not isinstance(max_papers, int) or isinstance(max_papers, bool) or max_papers < 1:
        raise CurieContractError("selector max_papers must be a positive integer")

    decisions: list[dict] = []
    eligible: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise CurieContractError("selector record must be an object")
        paper_id = _text(record.get("paper_id"), "selector record paper_id")
        if paper_id in seen:
            raise CurieContractError(f"selector received duplicate paper_id: {paper_id}")
        seen.add(paper_id)
        gate = eligibility(record)
        if not isinstance(gate, tuple) or len(gate) != 2 or not isinstance(gate[0], bool):
            raise CurieContractError("selector eligibility must return (bool, reason_code)")
        allowed, reason_code = gate
        if not allowed:
            decision = build_selector_decision(
                paper_id=paper_id,
                decision="EXCLUDE",
                relevance=0.0,
                directness=0.0,
                methodological_value=0.0,
                contradiction_value=0.0,
                evidence_diversity=0.0,
                originating_query_ids=_query_ids(record),
                reason=f"Deterministic hard eligibility exclusion: {_text(reason_code, 'eligibility reason_code')}",
                reason_code=str(reason_code),
            )
            decisions.append(decision)
            continue
        raw_score = scorer(record, seed)
        if not isinstance(raw_score, dict):
            raise CurieContractError("selector scorer must return an object")
        decision = build_selector_decision(
            paper_id=paper_id,
            decision="RESERVE",
            originating_query_ids=_query_ids(record),
            relevance=raw_score.get("relevance"),
            directness=raw_score.get("directness"),
            methodological_value=raw_score.get("methodological_value"),
            contradiction_value=raw_score.get("contradiction_value"),
            evidence_diversity=raw_score.get("evidence_diversity"),
            reason=raw_score.get("reason"),
        )
        decisions.append(decision)
        eligible.append((index, decision))

    ranked = sorted(eligible, key=lambda item: (_ranking(item[1]), -item[0]), reverse=True)
    include_ids = {item[1]["paper_id"] for item in ranked[:max_papers]}
    for decision in decisions:
        if decision["decision"] == "RESERVE" and decision["paper_id"] in include_ids:
            decision["decision"] = "INCLUDE"
            validate_selector_decision(decision)

    result = {
        "schema_version": _SELECTOR_RUN_SCHEMA_VERSION,
        "decisions": decisions,
        "included_paper_ids": [
            item[1]["paper_id"] for item in ranked[:max_papers]
        ],
    }
    if project_dir is not None:
        if not candidate_id or not run_id:
            raise CurieContractError(
                "selector persistence requires candidate_id and run_id"
            )
        relative = _ROOT / str(candidate_id) / str(run_id) / "selector_decisions.json"
        path = Path(project_dir) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical_bytes(result)
        if path.exists() and path.read_bytes() != raw:
            raise CurieContractError(
                "selector decision artifact already exists with different content"
            )
        if not path.exists():
            path.write_bytes(raw)
        result["artifact_path"] = relative.as_posix()
        result["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
