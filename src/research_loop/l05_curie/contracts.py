"""Pure contracts for the L0.5 Curie evidence-acquisition phase."""
from __future__ import annotations

import copy
import hashlib
import json
import re

QUERY_PLAN_SCHEMA_VERSION = "L05QueryPlan/v1"
QUERY_PLAN_SCHEMA_VERSION_V2 = "L05QueryPlan/v2"
KEYWORD_QUERY_REQUEST_COUNT = 3
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
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


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


def _require_exact_keys(value: object, keys: set[str], name: str) -> dict:
    value = _require_dict(value, name)
    if set(value) != keys:
        raise CurieContractError(f"{name} fields must be exactly {sorted(keys)}")
    return value


def _require_int(value: object, name: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise CurieContractError(f"{name} must be an integer in the permitted range")
    return value


def _validate_gap(gap: object, *, strict: bool = False) -> dict:
    gap = _require_dict(gap, "gap")
    if strict:
        _require_exact_keys(gap, {"gap_id", "topic", "reason", "search_directions"}, "gap")
    _require_text(gap.get("gap_id"), "gap.gap_id")
    _require_text(gap.get("topic"), "gap.topic")
    _require_text(gap.get("reason"), "gap.reason")
    _require_string_list(gap.get("search_directions"), "gap.search_directions")
    return copy.deepcopy(gap)


def validate_scientific_coverage_assessment(
    assessment: dict, *, request_sha256: str, admitted_evidence_ids: list[str],
) -> dict:
    """Validate a host proposal; scientific judgment and persistence remain with their owners."""
    assessment = _require_exact_keys(
        assessment, {"schema_version", "request_sha256", "dimensions", "gaps"}, "scientific coverage")
    try:
        _canonical_json(assessment).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise CurieContractError("scientific coverage must be strict UTF-8 JSON") from exc
    if assessment["schema_version"] != "L05ScientificCoverageAssessment/v1":
        raise CurieContractError("scientific coverage schema_version is invalid")
    if _require_sha256(assessment["request_sha256"], "coverage request_sha256") != _require_sha256(request_sha256, "request_sha256"):
        raise CurieContractError("scientific coverage request_sha256 mismatch")
    admitted = _require_string_list(admitted_evidence_ids, "admitted_evidence_ids", allow_empty=True)
    if len(admitted) != len(set(admitted)):
        raise CurieContractError("admitted_evidence_ids must be unique")
    required = {"SCIENTIFIC_QUESTION", "HYPOTHESIS_EVALUABILITY"}
    dimensions = assessment["dimensions"]
    if not isinstance(dimensions, list) or len(dimensions) != 2:
        raise CurieContractError("scientific coverage requires exactly two dimensions")
    sufficient = {}
    for dimension in dimensions:
        _require_exact_keys(dimension, {"dimension_id", "sufficient", "reason", "admitted_evidence_ids"}, "coverage dimension")
        name = _require_text(dimension["dimension_id"], "dimension_id")
        if name not in required or name in sufficient:
            raise CurieContractError("invalid or duplicate scientific coverage dimension")
        if type(dimension["sufficient"]) is not bool:
            raise CurieContractError("dimension sufficient must be boolean")
        _require_text(dimension["reason"], "dimension reason")
        refs = _require_string_list(dimension["admitted_evidence_ids"], "dimension admitted_evidence_ids", allow_empty=True)
        if len(refs) != len(set(refs)) or not set(refs) <= set(admitted):
            raise CurieContractError("dimension references must be unique admitted evidence")
        if dimension["sufficient"] and not refs:
            raise CurieContractError("sufficient dimension requires admitted evidence")
        sufficient[name] = dimension["sufficient"]
    gaps = assessment["gaps"]
    if not isinstance(gaps, list):
        raise CurieContractError("scientific coverage gaps must be a list")
    seen = set()
    topics = set()
    for gap in gaps:
        _validate_gap(gap, strict=True)
        if gap["gap_id"] in seen or gap["topic"] not in required or sufficient[gap["topic"]]:
            raise CurieContractError("coverage gap must be unique and identify an insufficient dimension")
        seen.add(gap["gap_id"])
        topics.add(gap["topic"])
    if topics != {name for name, value in sufficient.items() if not value}:
        raise CurieContractError("each insufficient dimension requires a gap")
    return copy.deepcopy(assessment)


def _validate_keyword_generation(generation: object, *, query_count: int) -> dict:
    generation = _require_exact_keys(
        generation,
        {"mode", "invocation_sha256", "bridge_sha256", "settings_sha256",
         "requested_count", "proposals", "runtime", "completion"},
        "query plan keyword_generation",
    )
    if generation["mode"] != "paperqa2-keyword-proposals-v1":
        raise CurieContractError("query plan keyword_generation mode is invalid")
    for name in ("invocation_sha256", "bridge_sha256", "settings_sha256"):
        _require_sha256(generation[name], f"keyword_generation.{name}")
    if (_require_int(generation["requested_count"], "keyword_generation.requested_count")
            != KEYWORD_QUERY_REQUEST_COUNT):
        raise CurieContractError(
            f"keyword_generation.requested_count must be {KEYWORD_QUERY_REQUEST_COUNT}"
        )

    proposals = generation["proposals"]
    if (not isinstance(proposals, list)
            or not 1 <= len(proposals) <= KEYWORD_QUERY_REQUEST_COUNT):
        raise CurieContractError(
            f"keyword_generation.proposals must contain 1 to {KEYWORD_QUERY_REQUEST_COUNT} proposals"
        )
    if len(proposals) != query_count:
        raise CurieContractError("keyword_generation proposal count does not match QueryPlan queries")
    for index, proposal in enumerate(proposals, 1):
        proposal = _require_exact_keys(
            proposal, {"proposal", "query", "year_start", "year_end"},
            f"keyword_generation.proposals[{index}]",
        )
        _require_text(proposal["proposal"], f"keyword proposal {index}")
        _require_text(proposal["query"], f"keyword query {index}")
        start, end = proposal["year_start"], proposal["year_end"]
        if start is not None:
            _require_int(start, f"keyword proposal {index} year_start")
        if end is not None:
            _require_int(end, f"keyword proposal {index} year_end")
        if start is None and end is not None:
            raise CurieContractError(f"keyword proposal {index} year range is invalid")

    runtime = _require_exact_keys(
        generation["runtime"],
        {"package", "version", "upstream_tag", "upstream_commit", "module_path",
         "clean_checkout", "generation_year", "llm_model"},
        "keyword_generation.runtime",
    )
    for name in ("package", "version", "upstream_tag", "upstream_commit", "module_path", "llm_model"):
        _require_text(runtime[name], f"keyword_generation.runtime.{name}")
    if runtime["clean_checkout"] is not True:
        raise CurieContractError("keyword_generation runtime checkout must be clean")
    _require_int(runtime["generation_year"], "keyword_generation.runtime.generation_year")

    completion = _require_exact_keys(
        generation["completion"],
        {"terminal_state", "returncode", "stdout_truncated", "stderr_truncated",
         "process_tree_cleanup"},
        "keyword_generation.completion",
    )
    if completion["terminal_state"] != "completed" or type(completion["returncode"]) is not int or completion["returncode"] != 0:
        raise CurieContractError("keyword generation process did not complete successfully")
    if completion["stdout_truncated"] is not False or completion["stderr_truncated"] is not False:
        raise CurieContractError("keyword generation process output must not be truncated")
    cleanup = _require_dict(completion["process_tree_cleanup"], "keyword_generation.process_tree_cleanup")
    if cleanup.get("alive_after_cleanup") is not False or cleanup.get("errors") != []:
        raise CurieContractError("keyword generation process-tree cleanup is unresolved")
    return copy.deepcopy(generation)


def validate_query_plan(plan: dict, *, seed_sha256: str) -> dict:
    """Validate an auditable search plan derived from the canonical L0 seed."""
    plan = _require_dict(plan, "query plan")
    schema_version = plan.get("schema_version")
    if schema_version not in (QUERY_PLAN_SCHEMA_VERSION, QUERY_PLAN_SCHEMA_VERSION_V2):
        raise CurieContractError("query plan schema_version is invalid")
    _require_text(plan.get("candidate_id"), "query plan candidate_id")
    _require_text(plan.get("round_id"), "query plan round_id")
    expected_seed = _require_sha256(seed_sha256, "seed_sha256")
    actual_seed = _require_sha256(plan.get("seed_sha256"), "query plan seed_sha256")
    if actual_seed != expected_seed:
        raise CurieContractError("query plan seed_sha256 does not match canonical ResearchSeed")
    _require_text(plan.get("plan_id"), "query plan plan_id")
    if "reformulation_index" in plan and (
        isinstance(plan["reformulation_index"], bool)
        or not isinstance(plan["reformulation_index"], int)
        or plan["reformulation_index"] < 0
    ):
        raise CurieContractError("query plan reformulation_index must be a non-negative integer")
    round_index = plan.get("round_index")
    if not isinstance(round_index, int) or isinstance(round_index, bool) or not (1 <= round_index <= MAX_ACQUISITION_ROUNDS):
        raise CurieContractError(
            f"query plan round_index must be an integer from 1 to {MAX_ACQUISITION_ROUNDS}"
        )
    queries = plan.get("queries")
    if not isinstance(queries, list) or not queries:
        raise CurieContractError("query plan queries must be a non-empty list")
    provenance = plan.get("planning_provenance")
    if schema_version == QUERY_PLAN_SCHEMA_VERSION:
        if isinstance(provenance, dict) and "keyword_generation" in provenance:
            raise CurieContractError("QueryPlan/v1 cannot carry keyword_generation")
    else:
        if (plan.get("planner") != "paperqa2-keyword-proposals-v1"
                or not isinstance(plan.get("planning"), dict)
                or plan["planning"].get("schema_version") != "L05ScientificQueryPlan/v2"
                or not isinstance(provenance, dict)
                or not isinstance(provenance.get("receipt"), dict)):
            raise CurieContractError("QueryPlan/v2 requires validated scientific planning and host receipt provenance")
        _validate_keyword_generation(
            provenance.get("keyword_generation"), query_count=len(queries))
    seen: set[str] = set()
    for query in queries:
        query = _require_dict(query, "query")
        query_id = _require_text(query.get("query_id"), "query.query_id")
        if query_id in seen:
            raise CurieContractError(f"duplicate query_id: {query_id}")
        seen.add(query_id)
        _require_text(query.get("intent"), f"query {query_id} intent")
        _require_text(query.get("query"), f"query {query_id} query")
        if "concepts" in query:
            _require_string_list(query["concepts"], f"query {query_id} concepts")
        _require_string_list(query.get("providers"), f"query {query_id} providers")
        if schema_version == QUERY_PLAN_SCHEMA_VERSION_V2:
            _require_sha256(query.get("query_content_hash"), f"query {query_id} query_content_hash")
            if (query.get("intent") != "paperqa2_keyword_batch"
                    or query.get("providers") != ["europe-pmc"]
                    or query.get("origin") != "generated"):
                raise CurieContractError(f"query {query_id} does not follow the keyword proposal contract")
    return copy.deepcopy(plan)


def validate_record_query_provenance(
    record: dict, *, authorized_query_ids: set[str] | None = None
) -> list[str]:
    """Validate and return a canonical record's QueryPlan lineage.

    The full QueryPlan owns provenance authorization.  Callers may perform a
    separate method-level intersection after this validation, but that subset
    must never be used as the authorization set for the record itself.
    """
    record = _require_dict(record, "discovery record")
    provenance = _require_dict(
        record.get("provenance"), "discovery record provenance"
    )
    values = _require_string_list(
        provenance.get("originating_query_ids"),
        "discovery record provenance originating_query_ids",
    )
    if authorized_query_ids is not None and (
        not isinstance(authorized_query_ids, set)
        or not authorized_query_ids
        or not all(
            isinstance(item, str) and item.strip()
            for item in authorized_query_ids
        )
    ):
        raise CurieContractError(
            "authorized_query_ids must be a non-empty set of strings"
        )
    normalized: list[str] = []
    for value in values:
        query_id = value.strip()
        if query_id not in normalized:
            normalized.append(query_id)
        if (
            authorized_query_ids is not None
            and query_id not in authorized_query_ids
        ):
            raise CurieContractError(
                f"record query provenance {query_id!r} is not authorized by the QueryPlan"
            )
    return normalized


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


def judge_coverage(coverage: dict, *, round_index: int, max_rounds: int = MAX_ACQUISITION_ROUNDS,
                   acquisition_state: dict | None = None) -> dict:
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
    terminal = False
    if acquisition_state is not None:
        facts = _require_exact_keys(acquisition_state, {"attempt_index", "max_attempts", "corpus_count", "corpus_limit", "terminal_reason"}, "acquisition_state")
        attempt = _require_int(facts["attempt_index"], "attempt_index", maximum=3)
        maximum = _require_int(facts["max_attempts"], "max_attempts", maximum=3)
        count = _require_int(facts["corpus_count"], "corpus_count", minimum=0, maximum=90)
        limit = _require_int(facts["corpus_limit"], "corpus_limit", maximum=90)
        reason = facts["terminal_reason"]
        if attempt > maximum or count > limit:
            raise CurieContractError("acquisition state exceeds frozen budget")
        if reason not in (None, "no_admissible_replan", "no_new_sources", "attempt_budget_exhausted", "corpus_budget_exhausted"):
            raise CurieContractError("invalid acquisition terminal_reason")
        if ((reason == "attempt_budget_exhausted" and attempt != maximum)
                or (reason == "corpus_budget_exhausted" and count != limit)):
            raise CurieContractError("acquisition terminal reason conflicts with budget facts")
        terminal = reason is not None or attempt == maximum or count == limit
    if not validated_gaps:
        verdict = "PASS"
    elif acquisition_state is not None:
        verdict = "INSUFFICIENT_STOP" if terminal else "INSUFFICIENT_RETRY"
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
