"""Pure contracts for the L0.5 Curie evidence-acquisition phase."""
from __future__ import annotations

import copy
import hashlib
import json
import re

QUERY_PLAN_SCHEMA_VERSION = "L05QueryPlan/v1"
DISCOVERY_TRANSPORT_SCHEMA_VERSION = "DiscoveryTransport/v1"
DISCOVERY_BATCH_SCHEMA_VERSION = "L05DiscoveryBatch/v1"
EVIDENCE_EXTRACT_SCHEMA_VERSION = "L05EvidenceExtract/v1"
COVERAGE_DECISION_SCHEMA_VERSION = "L05CoverageDecision/v1"
GAP_REQUEST_SCHEMA_VERSION = "L05EvidenceGapRequest/v1"
EVIDENCE_PACK_SCHEMA_VERSION = "L05EvidencePack/v1"
EVIDENCE_PACK_MANIFEST_SCHEMA_VERSION = "L05EvidencePackManifest/v1"
MAX_ACQUISITION_ROUNDS = 3

_ROLES = {"SUPPORTING", "CONTRADICTORY", "CONTEXT", "METHOD"}
_COVERAGE_VERDICTS = {"PASS", "INSUFFICIENT_RETRY", "INSUFFICIENT_STOP"}
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class CurieContractError(ValueError):
    """Raised when an L0.5 contract violates an authority or provenance invariant."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_dict(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise CurieContractError(f"{name} must be an object")
    return value


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurieContractError(f"{name} must be a non-empty string")
    return value


def _require_sha256(value: object, name: str) -> str:
    value = _require_text(value, name)
    if not _HEX64.fullmatch(value):
        raise CurieContractError(f"{name} must be a 64-character SHA-256 hex digest")
    return value.lower()


def _require_string_list(value: object, name: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise CurieContractError(f"{name} must be {qualifier} of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise CurieContractError(f"{name} must contain only non-empty strings")
    return value


def _validate_gap(gap: object) -> dict:
    gap = _require_dict(gap, "gap")
    _require_text(gap.get("gap_id"), "gap.gap_id")
    _require_text(gap.get("topic"), "gap.topic")
    _require_text(gap.get("reason"), "gap.reason")
    _require_string_list(gap.get("search_directions"), "gap.search_directions")
    return copy.deepcopy(gap)


def validate_query_plan(plan: dict, *, seed_sha256: str) -> dict:
    """Validate an auditable search plan derived from the canonical L0 seed."""
    plan = _require_dict(plan, "query plan")
    if plan.get("schema_version") != QUERY_PLAN_SCHEMA_VERSION:
        raise CurieContractError("query plan schema_version is invalid")
    _require_text(plan.get("candidate_id"), "query plan candidate_id")
    _require_text(plan.get("round_id"), "query plan round_id")
    expected_seed = _require_sha256(seed_sha256, "seed_sha256")
    actual_seed = _require_sha256(plan.get("seed_sha256"), "query plan seed_sha256")
    if actual_seed != expected_seed:
        raise CurieContractError("query plan seed_sha256 does not match canonical ResearchSeed")
    _require_text(plan.get("plan_id"), "query plan plan_id")
    round_index = plan.get("round_index")
    if not isinstance(round_index, int) or isinstance(round_index, bool) or not (1 <= round_index <= MAX_ACQUISITION_ROUNDS):
        raise CurieContractError(
            f"query plan round_index must be an integer from 1 to {MAX_ACQUISITION_ROUNDS}"
        )
    queries = plan.get("queries")
    if not isinstance(queries, list) or not queries:
        raise CurieContractError("query plan queries must be a non-empty list")
    seen: set[str] = set()
    for query in queries:
        query = _require_dict(query, "query")
        query_id = _require_text(query.get("query_id"), "query.query_id")
        if query_id in seen:
            raise CurieContractError(f"duplicate query_id: {query_id}")
        seen.add(query_id)
        _require_text(query.get("intent"), f"query {query_id} intent")
        _require_text(query.get("query"), f"query {query_id} query")
        _require_string_list(query.get("providers"), f"query {query_id} providers")
    return copy.deepcopy(plan)


def validate_transport_handshake(handshake: dict) -> dict:
    """Validate the capability handshake for one deterministic discovery adapter."""
    handshake = _require_dict(handshake, "transport handshake")
    if handshake.get("schema_version") != DISCOVERY_TRANSPORT_SCHEMA_VERSION:
        raise CurieContractError("transport handshake schema_version must be DiscoveryTransport/v1")
    _require_text(handshake.get("provider"), "transport handshake provider")
    _require_string_list(handshake.get("capabilities"), "transport handshake capabilities")
    return copy.deepcopy(handshake)


def validate_discovery_batch(
    batch: dict,
    *,
    query_ids: set[str],
    expected_query_id: str | None = None,
    expected_provider: str | None = None,
    expected_providers_by_query: dict[str, set[str]] | None = None,
    require_source_identity: bool = False,
) -> dict:
    """Validate normalized discovery metadata and bind it to an executed query."""
    batch = _require_dict(batch, "discovery batch")
    if batch.get("schema_version") != DISCOVERY_BATCH_SCHEMA_VERSION:
        raise CurieContractError("discovery batch schema_version is invalid")
    provider = _require_text(batch.get("provider"), "discovery batch provider")
    query_id = _require_text(batch.get("query_id"), "discovery batch query_id")
    if query_id not in query_ids:
        raise CurieContractError(f"discovery batch query_id {query_id!r} is not in the QueryPlan")
    if expected_query_id is not None and query_id != _require_text(
        expected_query_id, "expected discovery query_id"
    ):
        raise CurieContractError(
            f"discovery batch query_id {query_id!r} does not match executed query {expected_query_id!r}"
        )
    if expected_provider is not None and provider != _require_text(
        expected_provider, "expected discovery provider"
    ):
        raise CurieContractError(
            f"discovery batch provider {provider!r} does not match executed provider {expected_provider!r}"
        )
    if expected_providers_by_query is not None and provider not in expected_providers_by_query.get(
        query_id, set()
    ):
        raise CurieContractError(
            f"discovery batch provider {provider!r} is not declared for query {query_id!r}"
        )
    receipt = _require_dict(batch.get("receipt"), "discovery batch receipt")
    _require_sha256(receipt.get("request_sha256"), "discovery receipt request_sha256")
    _require_sha256(receipt.get("response_sha256"), "discovery receipt response_sha256")
    records = batch.get("records")
    if not isinstance(records, list):
        raise CurieContractError("discovery batch records must be a list")
    for record in records:
        record = _require_dict(record, "discovery record")
        _require_text(record.get("paper_id"), "discovery record paper_id")
        _require_text(record.get("title"), "discovery record title")
        if not isinstance(record.get("identifiers"), dict):
            raise CurieContractError("discovery record identifiers must be an object")
        if require_source_identity:
            provenance = _require_dict(
                record.get("provenance"), "discovery record provenance"
            )
            record_provider = _require_text(
                provenance.get("provider"), "discovery record provenance provider"
            )
            if record_provider != provider:
                raise CurieContractError(
                    "discovery record provenance provider must match discovery batch provider"
                )
            _require_sha256(
                provenance.get("raw_record_sha256"),
                "discovery record provenance raw_record_sha256",
            )
    return copy.deepcopy(batch)


def validate_evidence_extract(extract: dict) -> dict:
    """Accept only source-located evidence; semantic interpretation remains downstream."""
    extract = _require_dict(extract, "evidence extract")
    if extract.get("schema_version") != EVIDENCE_EXTRACT_SCHEMA_VERSION:
        raise CurieContractError("evidence extract schema_version is invalid")
    for field in ("evidence_id", "paper_id", "section", "text", "locator"):
        _require_text(extract.get(field), f"evidence extract {field}")
    role = _require_text(extract.get("role"), "evidence extract role")
    if role not in _ROLES:
        raise CurieContractError(f"evidence extract role must be one of {sorted(_ROLES)}")
    if extract.get("verification_status") != "LOCATED":
        raise CurieContractError("evidence extract verification_status must be LOCATED")
    retrieval = _require_dict(extract.get("retrieval"), "evidence extract retrieval")
    _require_text(retrieval.get("engine"), "evidence extract retrieval engine")
    _require_sha256(retrieval.get("source_sha256"), "evidence extract retrieval source_sha256")
    return copy.deepcopy(extract)


def validate_coverage_decision(decision: dict) -> dict:
    decision = _require_dict(decision, "coverage decision")
    if decision.get("schema_version") != COVERAGE_DECISION_SCHEMA_VERSION:
        raise CurieContractError("coverage decision schema_version is invalid")
    verdict = _require_text(decision.get("verdict"), "coverage decision verdict")
    if verdict not in _COVERAGE_VERDICTS:
        raise CurieContractError(f"coverage decision verdict must be one of {sorted(_COVERAGE_VERDICTS)}")
    round_index = decision.get("round_index")
    max_rounds = decision.get("max_rounds")
    if not isinstance(round_index, int) or isinstance(round_index, bool) or round_index < 1:
        raise CurieContractError("coverage decision round_index must be a positive integer")
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or not (1 <= max_rounds <= MAX_ACQUISITION_ROUNDS):
        raise CurieContractError(
            f"coverage decision max_rounds exceeds the hard maximum of {MAX_ACQUISITION_ROUNDS}"
        )
    if round_index > max_rounds:
        raise CurieContractError("coverage decision round_index cannot exceed max_rounds")
    covered = decision.get("covered")
    if not isinstance(covered, list):
        raise CurieContractError("coverage decision covered must be a list")
    gaps = decision.get("gaps")
    if not isinstance(gaps, list):
        raise CurieContractError("coverage decision gaps must be a list")
    validated_gaps = [_validate_gap(gap) for gap in gaps]
    if verdict == "PASS" and validated_gaps:
        raise CurieContractError("coverage PASS cannot contain unresolved gaps")
    if verdict != "PASS" and not validated_gaps:
        raise CurieContractError("insufficient coverage must identify at least one gap")
    return copy.deepcopy(decision)


def judge_coverage(coverage: dict, *, round_index: int, max_rounds: int = MAX_ACQUISITION_ROUNDS) -> dict:
    """Convert a coverage assessment into a bounded, fail-closed routing decision."""
    coverage = _require_dict(coverage, "coverage")
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or not (1 <= max_rounds <= MAX_ACQUISITION_ROUNDS):
        raise CurieContractError(
            f"max_rounds must be between 1 and the hard maximum of {MAX_ACQUISITION_ROUNDS}"
        )
    if not isinstance(round_index, int) or isinstance(round_index, bool) or not (1 <= round_index <= max_rounds):
        raise CurieContractError("round_index must be between 1 and max_rounds")
    covered = coverage.get("covered")
    if not isinstance(covered, list):
        raise CurieContractError("coverage covered must be a list")
    gaps = coverage.get("gaps")
    if not isinstance(gaps, list):
        raise CurieContractError("coverage gaps must be a list")
    validated_gaps = [_validate_gap(gap) for gap in gaps]
    if not validated_gaps:
        verdict = "PASS"
    elif round_index < max_rounds:
        verdict = "INSUFFICIENT_RETRY"
    else:
        verdict = "INSUFFICIENT_STOP"
    return {
        "schema_version": COVERAGE_DECISION_SCHEMA_VERSION,
        "round_index": round_index,
        "max_rounds": max_rounds,
        "verdict": verdict,
        "covered": copy.deepcopy(covered),
        "gaps": validated_gaps,
    }


def build_gap_request(*, candidate_id: str, round_id: str, seed_sha256: str,
                      pack_sha256: str, gaps: list[dict]) -> dict:
    """Create the only authorized downstream request for a new evidence version."""
    candidate_id = _require_text(candidate_id, "gap request candidate_id")
    round_id = _require_text(round_id, "gap request round_id")
    seed_sha256 = _require_sha256(seed_sha256, "gap request seed_sha256")
    pack_sha256 = _require_sha256(pack_sha256, "gap request pack_sha256")
    if not isinstance(gaps, list) or not gaps:
        raise CurieContractError("gap request gaps must be a non-empty list")
    validated_gaps = [_validate_gap(gap) for gap in gaps]
    identity = {
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": seed_sha256,
        "pack_sha256": pack_sha256,
        "gaps": validated_gaps,
    }
    return {
        "schema_version": GAP_REQUEST_SCHEMA_VERSION,
        "request_id": f"EGR_{_sha(identity)[:16]}",
        **identity,
        "status": "OPEN",
    }


def validate_gap_request(request: dict) -> dict:
    request = _require_dict(request, "gap request")
    if request.get("schema_version") != GAP_REQUEST_SCHEMA_VERSION:
        raise CurieContractError("gap request schema_version is invalid")
    _require_text(request.get("request_id"), "gap request request_id")
    _require_text(request.get("candidate_id"), "gap request candidate_id")
    _require_text(request.get("round_id"), "gap request round_id")
    _require_sha256(request.get("seed_sha256"), "gap request seed_sha256")
    _require_sha256(request.get("pack_sha256"), "gap request pack_sha256")
    if request.get("status") != "OPEN":
        raise CurieContractError("gap request status must be OPEN")
    gaps = request.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        raise CurieContractError("gap request gaps must be a non-empty list")
    [_validate_gap(gap) for gap in gaps]
    return copy.deepcopy(request)
