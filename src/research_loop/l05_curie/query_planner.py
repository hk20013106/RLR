"""Bounded, provider-neutral query planning for Curie acquisition.

Language normalization is complete before canonical L0 is frozen. This module
only plans deterministic scientific queries from that canonical semantic state.
"""
from __future__ import annotations

import re
import unicodedata
import hashlib
import json
import copy
from pathlib import Path
from typing import Any

from research_loop import research_seed

from .contracts import CurieContractError

SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION = "L05ScientificQueryPlan/v1"
SCIENTIFIC_QUERY_PLANNER_VERSION = "scientific-query-planner/v1"
SCIENTIFIC_QUERY_PLAN_V2 = "L05ScientificQueryPlan/v2"
SCIENTIFIC_QUERY_PLANNER_V2 = "scientific-query-planner/v2"
_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["PLAN", "NO_ADMISSIBLE_REPLAN"]},
        "reason": {"type": "string", "minLength": 1},
        "plan": {"type": ["object", "null"]},
    },
    "required": ["status", "reason", "plan"],
}
MIN_QUERY_CANDIDATES = 3
MAX_QUERY_CANDIDATES = 6
MAX_REFORMULATION_INDEX = 1
MAX_QUERY_CHARS = 240
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+]*(?:[-/][A-Za-z0-9+]+)*")
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for",
    "from", "how", "in", "is", "of", "on", "or", "that", "the", "to",
    "what", "which", "with",
})


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurieContractError(f"{name} must be a non-empty string")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _english_tokens(value: str) -> list[str]:
    return _unique([
        token
        for token in _TOKEN.findall(value)
        if token.casefold() not in _STOPWORDS
    ])


def _seed_terms(seed: dict) -> tuple[str, str, list[str], list[str]]:
    if not isinstance(seed, dict):
        raise CurieContractError("ResearchSeed must be an object")
    question = _text(
        seed.get("scientific_question"), "ResearchSeed scientific_question"
    )
    hypothesis = _text(
        seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed"
    )
    question_tokens = _english_tokens(question)
    hypothesis_tokens = _english_tokens(hypothesis)
    if not question_tokens and not hypothesis_tokens:
        raise CurieContractError(
            "scientific query planner could not derive searchable concepts from the ResearchSeed"
        )
    return question, hypothesis, question_tokens, hypothesis_tokens


def _concepts(question_tokens: list[str], hypothesis_tokens: list[str]) -> list[dict]:
    concepts: list[dict] = []
    seen: set[str] = set()
    for source, values in (
        ("scientific_question", question_tokens),
        ("hypothesis_seed", hypothesis_tokens),
    ):
        for term in values:
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            concepts.append({"term": term, "role": "concept", "source": source})
    return concepts


def _bounded(values: list[str]) -> str:
    terms = _unique(values)
    while terms and len(" ".join(terms)) > MAX_QUERY_CHARS:
        terms.pop()
    if not terms:
        raise CurieContractError("scientific query planner produced an empty query")
    return " ".join(terms)


def _bounded_with_suffix(values: list[str], suffix: list[str]) -> str:
    """Bound a query while retaining its intent-specific suffix."""
    terms = _unique(values)
    suffix_terms = _unique(suffix)
    suffix_keys = {term.casefold() for term in suffix_terms}
    terms = [term for term in terms if term.casefold() not in suffix_keys]
    while terms and len(" ".join(terms + suffix_terms)) > MAX_QUERY_CHARS:
        terms.pop()
    rendered = " ".join(terms + suffix_terms)
    if not rendered or len(rendered) > MAX_QUERY_CHARS:
        raise CurieContractError("scientific query planner produced an empty query")
    return rendered


def _validate_v1_scientific_query_plan(plan: dict) -> dict:
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION
    ):
        raise CurieContractError("scientific query plan schema_version is invalid")
    if plan.get("planner") != SCIENTIFIC_QUERY_PLANNER_VERSION:
        raise CurieContractError("scientific query plan planner is invalid")
    index = plan.get("reformulation_index")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index <= MAX_REFORMULATION_INDEX
    ):
        raise CurieContractError(
            "scientific query plan reformulation_index is invalid"
        )
    if set(plan).intersection({
        "papers", "evidence", "evidence_pack", "verification", "status"
    }):
        raise CurieContractError(
            "scientific query plan must not contain evidence authority fields"
        )
    concepts = plan.get("concepts")
    queries = plan.get("queries")
    if (
        not isinstance(concepts, list)
        or not concepts
        or not isinstance(queries, list)
        or not MIN_QUERY_CANDIDATES <= len(queries) <= MAX_QUERY_CANDIDATES
    ):
        raise CurieContractError(
            "scientific query plan must contain bounded concepts and queries"
        )
    seen: set[str] = set()
    for query in queries:
        if (
            not isinstance(query, dict)
            or not str(query.get("intent") or "").strip()
            or not str(query.get("query") or "").strip()
            or not isinstance(query.get("concepts"), list)
            or not query["concepts"]
        ):
            raise CurieContractError("scientific query plan query is invalid")
        rendered = _text(query["query"], "retrieval query")
        key = rendered.casefold()
        if key in seen:
            raise CurieContractError(
                "scientific query plan queries must be distinct"
            )
        seen.add(key)
    return plan


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _normalized_term(value: object) -> str:
    term = _text(value, "scientific query term").casefold()
    if not re.fullmatch(r"[^\W_]+(?:[ -][^\W_]+)*", term, flags=re.UNICODE):
        raise CurieContractError("scientific query term contains unsupported Boolean or provider syntax")
    if any(part in {"and", "or", "not"} for part in term.split()):
        raise CurieContractError("scientific query term contains a reserved Boolean operator")
    return term


def _validated_synonym(synonym: dict, anchor: dict, seed: dict) -> None:
    if not isinstance(synonym, dict) or set(synonym) != {
        "term", "source_type", "source_field", "text_snippet", "source_hash",
        "start", "end", "mapping_source", "mapping_version", "mapping_evidence",
        "mapping_evidence_start", "mapping_key",
    }:
        raise CurieContractError("synonym mapping fields are invalid")
    alternative = _source_bound_term(synonym, seed)
    primary = _normalized_term(anchor["term"])
    if alternative == primary:
        raise CurieContractError("synonym repeats its CORE term")
    field = synonym["source_field"]
    if field != anchor["source_field"]:
        raise CurieContractError("synonym mapping must be explicit in the same authorized seed field")
    if synonym.get("mapping_source") != "authorized_seed_parenthetical" or synonym.get("mapping_version") != "v1":
        raise CurieContractError("synonym mapping has no authorized versioned source")
    source = seed[field]
    evidence_start = synonym.get("mapping_evidence_start")
    evidence = synonym.get("mapping_evidence")
    if (isinstance(evidence_start, bool) or not isinstance(evidence_start, int)
            or not isinstance(evidence, str) or evidence_start < 0
            or source[evidence_start:evidence_start + len(evidence)] != evidence):
        raise CurieContractError("synonym mapping evidence is not an authorized text span")
    primary_span = (anchor["start"], anchor["end"])
    alternative_span = (synonym["start"], synonym["end"])
    paired = (
        f"{anchor['text_snippet']} ({synonym['text_snippet']})",
        f"{synonym['text_snippet']} ({anchor['text_snippet']})",
    )
    if (evidence not in paired or
            not all(evidence_start <= start < end <= evidence_start + len(evidence)
                    for start, end in (primary_span, alternative_span))):
        raise CurieContractError("synonym equivalence is not explicitly stated by the seed")
    expected_key = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    if synonym.get("mapping_key") != expected_key:
        raise CurieContractError("synonym mapping evidence hash mismatch")


def _plan_content_identity(plan: dict) -> dict:
    concepts = {item["concept_id"]: item for item in plan["core_anchors"] + plan["optional_concepts"]}

    def group(item: dict) -> tuple:
        return (
            item["source_field"], item["start"], item["end"],
            tuple(sorted({_normalized_term(item["term"])} |
                         {_normalized_term(value["term"]) for value in item.get("synonyms", [])})),
        )

    return {
        "seed_sha256": plan["seed_sha256"],
        "core": sorted(group(item) for item in plan["core_anchors"]),
        "intents": sorted(
            (tuple(sorted(group(concepts[key]) for key in intent["core_concept_ids"])),
             tuple(sorted(group(concepts[key]) for key in intent.get("optional_concept_ids", []))))
            for intent in plan["intents"]
        ),
    }


def _intent_groups(plan: dict, intent: dict) -> dict[tuple, set[str]]:
    concepts = {item["concept_id"]: item for item in plan["core_anchors"] + plan["optional_concepts"]}
    groups = {}
    for concept_id in intent["core_concept_ids"] + intent.get("optional_concept_ids", []):
        item = concepts[concept_id]
        key = (item["source_field"], item["start"], item["end"], _normalized_term(item["term"]))
        groups[key] = {_normalized_term(item["term"])} | {
            _normalized_term(synonym["term"]) for synonym in item.get("synonyms", [])
        }
    return groups


def _boolean_query_broadens(new_groups: dict, old_groups: dict) -> bool:
    return all(key in old_groups and old_groups[key] <= terms
               for key, terms in new_groups.items())


def _seed_synonym_candidates(previous: dict, seed: dict):
    """Enumerate only the parenthetical equivalences authorized by v2."""
    for anchor_index, anchor in enumerate(previous["core_anchors"]):
        source = seed[anchor["source_field"]]
        primary = anchor["text_snippet"]
        patterns = (
            re.escape(primary) + r" \((?P<alternative>[^()]{1,80})\)",
            r"(?P<alternative>[^()]{1,80}) \(" + re.escape(primary) + r"\)",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, source):
                alternative = match.group("alternative")
                try:
                    normalized = _normalized_term(alternative)
                except CurieContractError:
                    continue
                if normalized in {
                    _normalized_term(anchor["term"]),
                    *(_normalized_term(item["term"]) for item in anchor.get("synonyms", [])),
                }:
                    continue
                evidence = match.group(0)
                start, end = match.span("alternative")
                synonym = {
                    "term": alternative,
                    "source_type": anchor["source_type"],
                    "source_field": anchor["source_field"],
                    "text_snippet": alternative,
                    "source_hash": anchor["source_hash"],
                    "start": start, "end": end,
                    "mapping_source": "authorized_seed_parenthetical",
                    "mapping_version": "v1",
                    "mapping_evidence": evidence,
                    "mapping_evidence_start": match.start(),
                    "mapping_key": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
                }
                candidate = copy.deepcopy(previous)
                candidate.pop("plan_content_hash", None)
                candidate["core_anchors"][anchor_index].setdefault("synonyms", []).append(synonym)
                yield "authorized seed synonym", candidate


def _gap_seed_spans(seed: dict, gaps: list[dict]):
    """Use exact seed spans also named in validated gap topics/directions."""
    directions = [str(value) for gap in gaps for value in (
        [gap.get("topic", "")] + gap.get("search_directions", [])
    ) if isinstance(value, str)]
    matches: list[tuple[str, int, int, str]] = []
    seen: set[tuple[str, int, int]] = set()
    for field in ("scientific_question", "hypothesis_seed"):
        source = seed[field]
        tokens = list(_TOKEN.finditer(source))
        for start_index, first in enumerate(tokens):
            for width in range(1, min(4, len(tokens) - start_index) + 1):
                last = tokens[start_index + width - 1]
                span = source[first.start():last.end()]
                try:
                    term = _normalized_term(span)
                except CurieContractError:
                    continue
                if all(part in _STOPWORDS for part in term.split()):
                    continue
                if not any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)",
                                     unicodedata.normalize("NFKC", direction).casefold())
                           for direction in directions):
                    continue
                key = (field, first.start(), last.end())
                if key not in seen:
                    seen.add(key)
                    matches.append((field, first.start(), last.end(), span))
    for match in matches:
        term = _normalized_term(match[3])
        if any(len(other[3]) > len(match[3]) and re.search(
            r"(?<!\w)" + re.escape(term) + r"(?!\w)", _normalized_term(other[3])
        ) for other in matches):
            continue
        yield match


def _replan_candidates(previous: dict, seed: dict, feedback: dict, index: int):
    """Finite, source-bound operations that can disprove a no-plan proposal."""
    provenance = {
        "reformulation_index": index,
        "parent_plan_content_hash": previous["plan_content_hash"],
        "feedback_sha256": _sha(feedback),
        "feedback_gap_ids": sorted(gap["gap_id"] for gap in feedback["validated_coverage_gaps"]),
    }

    def prepared(candidate: dict) -> dict:
        candidate.pop("plan_content_hash", None)
        candidate.update(provenance)
        return candidate

    for intent_index, intent in enumerate(previous["intents"]):
        for optional_id in intent.get("optional_concept_ids", []):
            candidate = copy.deepcopy(previous)
            candidate["intents"][intent_index]["optional_concept_ids"].remove(optional_id)
            candidate["intents"] = [candidate["intents"][intent_index]]
            yield "optional/design constraint removal", prepared(candidate)
    for operation, candidate in _seed_synonym_candidates(previous, seed):
        yield operation, prepared(candidate)

    if (feedback.get("attempt_outcome") or {}).get("type") != "COVERAGE_GAP":
        return
    core_terms = {
        _normalized_term(value["term"])
        for anchor in previous["core_anchors"]
        for value in [anchor, *anchor.get("synonyms", [])]
    }
    for field, start, end, span in _gap_seed_spans(
        seed, feedback.get("validated_coverage_gaps", [])
    ):
        if _normalized_term(span) in core_terms:
            continue
        existing = next((item for item in previous["optional_concepts"]
                         if item["source_field"] == field and item["start"] == start
                         and item["end"] == end), None)
        optional_id = (existing or {}).get("concept_id") or "gap-" + _sha(
            {"field": field, "start": start, "end": end}
        )[:16]
        for intent in previous["intents"]:
            if optional_id in intent.get("optional_concept_ids", []):
                continue
            candidate = copy.deepcopy(previous)
            if existing is None:
                candidate["optional_concepts"].append({
                    "concept_id": optional_id, "term": span,
                    "source_type": "QUESTION" if field == "scientific_question" else "INITIAL_HYPOTHESIS",
                    "source_field": field, "text_snippet": span,
                    "source_hash": hashlib.sha256(seed[field].encode("utf-8")).hexdigest(),
                    "start": start, "end": end,
                })
            narrowed = copy.deepcopy(intent)
            narrowed["optional_concept_ids"].append(optional_id)
            candidate["intents"] = [narrowed]
            yield "validated gap targeted intent", prepared(candidate)


def _admissible_replan_candidates(previous: dict, seed: dict, feedback: dict, index: int) -> list[tuple[str, dict]]:
    executed_queries = {item.get("query_content_hash") for item in feedback.get("executed_queries", [])}
    executed_plans = {item.get("plan_content_hash") for item in feedback.get("executed_plans", [])}
    candidates: list[tuple[str, dict]] = []
    seen_plans: set[str] = set()
    for operation, candidate in _replan_candidates(previous, seed, feedback, index):
        try:
            validated = validate_scientific_query_plan(candidate, seed=seed)
            compiled = compile_scientific_query_plan(validated, seed=seed)
        except CurieContractError:
            continue
        identity = validated["plan_content_hash"]
        if (identity in seen_plans or identity in executed_plans
                or any(item["query_content_hash"] in executed_queries for item in compiled)):
            continue
        seen_plans.add(identity)
        candidates.append((operation, validated))
    return candidates


def _source_bound_term(item: dict, seed: dict, *, expected_role: str | None = None) -> str:
    if not isinstance(item, dict):
        raise CurieContractError("scientific query anchor must be an object")
    field = item.get("source_field")
    role = {"scientific_question": "QUESTION", "hypothesis_seed": "INITIAL_HYPOTHESIS"}.get(field)
    if role is None or item.get("source_type") != role or (expected_role and role != expected_role):
        raise CurieContractError("scientific query anchor source is not authorized")
    source = seed.get(field)
    if not isinstance(source, str) or not source.strip():
        raise CurieContractError("scientific query anchor source field is absent")
    if item.get("source_hash") != hashlib.sha256(source.encode("utf-8")).hexdigest():
        raise CurieContractError("scientific query anchor source hash mismatch")
    start, end = item.get("start"), item.get("end")
    snippet = item.get("text_snippet")
    if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
            or not isinstance(end, int) or not isinstance(snippet, str)
            or start < 0 or end <= start or source[start:end] != snippet):
        raise CurieContractError("scientific query anchor does not match the authorized text span")
    term = _normalized_term(item.get("term"))
    if term != _normalized_term(snippet):
        raise CurieContractError("scientific query term must match its authorized text span")
    return term


def _validated_v2(plan: dict, seed: dict) -> dict:
    allowed = {"schema_version", "planner", "seed_sha256", "reformulation_index",
               "core_anchors", "optional_concepts", "unresolved_entities",
               "advisory_search_constraints", "intents", "plan_content_hash",
               "target_question_sha256", "parent_plan_content_hash",
               "feedback_sha256", "feedback_gap_ids"}
    if set(plan) - allowed:
        raise CurieContractError("scientific query plan contains unsupported fields")
    if plan.get("planner") != SCIENTIFIC_QUERY_PLANNER_V2:
        raise CurieContractError("scientific query plan v2 planner is invalid")
    if seed.get("schema_version") != research_seed.SCHEMA_VERSION:
        raise CurieContractError("scientific query plan v2 requires a validated L1ResearchSeed/v1")
    if plan.get("seed_sha256") != research_seed.seed_sha256(seed):
        raise CurieContractError("scientific query plan seed identity mismatch")
    question_hash = hashlib.sha256(seed["scientific_question"].encode("utf-8")).hexdigest()
    if plan.get("target_question_sha256") != question_hash:
        raise CurieContractError("scientific query target does not match the authorized question")
    index = plan.get("reformulation_index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 2:
        raise CurieContractError("scientific query plan reformulation_index is invalid")
    if index == 0:
        if (plan.get("parent_plan_content_hash") is not None
                or plan.get("feedback_sha256") is not None
                or plan.get("feedback_gap_ids") != []):
            raise CurieContractError("initial scientific plan cannot cite prior feedback")
    elif (not isinstance(plan.get("parent_plan_content_hash"), str)
          or not re.fullmatch(r"[0-9a-f]{64}", plan["parent_plan_content_hash"])
          or not isinstance(plan.get("feedback_sha256"), str)
          or not re.fullmatch(r"[0-9a-f]{64}", plan["feedback_sha256"])
          or not isinstance(plan.get("feedback_gap_ids"), list)
          or not all(isinstance(key, str) and key.strip() for key in plan["feedback_gap_ids"])):
        raise CurieContractError("scientific replan lacks parent/feedback provenance")
    if set(plan).intersection({"papers", "evidence", "evidence_pack", "verification", "status", "raw_query"}):
        raise CurieContractError("scientific query plan contains unauthorized evidence or raw query authority")
    anchors = plan.get("core_anchors")
    if not isinstance(anchors, list) or not anchors:
        raise CurieContractError("scientific query plan requires authorized CORE anchors")
    concept_ids: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict) or set(anchor) - {
            "concept_id", "term", "source_type", "source_field", "text_snippet",
            "source_hash", "start", "end", "synonyms",
        }:
            raise CurieContractError("CORE anchor fields are invalid")
        _source_bound_term(anchor, seed)
        concept_id = _text(anchor.get("concept_id"), "CORE concept_id")
        if concept_id in concept_ids:
            raise CurieContractError("duplicate CORE concept_id")
        concept_ids.add(concept_id)
        synonyms = anchor.get("synonyms", [])
        if not isinstance(synonyms, list):
            raise CurieContractError("CORE synonyms must be a list")
        for synonym in synonyms:
            _validated_synonym(synonym, anchor, seed)
    if not any(anchor["source_type"] == "QUESTION" for anchor in anchors):
        raise CurieContractError("CORE must include the scientific question")
    optional = plan.get("optional_concepts", [])
    if not isinstance(optional, list):
        raise CurieContractError("optional_concepts must be a list")
    optional_ids: set[str] = set()
    for item in optional:
        if not isinstance(item, dict) or set(item) - {
            "concept_id", "term", "source_type", "source_field", "text_snippet",
            "source_hash", "start", "end", "synonyms",
        }:
            raise CurieContractError("optional concept fields are invalid")
        _source_bound_term(item, seed)
        concept_id = _text(item.get("concept_id"), "optional concept_id")
        if concept_id in concept_ids or concept_id in optional_ids:
            raise CurieContractError("duplicate optional concept_id")
        optional_ids.add(concept_id)
        synonyms = item.get("synonyms", [])
        if not isinstance(synonyms, list):
            raise CurieContractError("optional synonyms must be a list")
        for synonym in synonyms:
            _validated_synonym(synonym, item, seed)
    unresolved = plan.get("unresolved_entities", [])
    advisory = plan.get("advisory_search_constraints", [])
    if not isinstance(unresolved, list) or not all(isinstance(x, str) for x in unresolved):
        raise CurieContractError("unresolved_entities must be text items")
    normalized_unresolved = {_normalized_term(value) for value in unresolved}
    mandatory_terms = {
        _normalized_term(value["term"])
        for anchor in anchors for value in [anchor, *anchor.get("synonyms", [])]
    }
    if normalized_unresolved & mandatory_terms:
        raise CurieContractError("unresolved entity cannot enter a mandatory CORE expression")
    if not isinstance(advisory, list) or not all(isinstance(x, dict) for x in advisory):
        raise CurieContractError("advisory_search_constraints must be audit objects")
    for constraint in advisory:
        if set(constraint) - {"text", "source_attempt", "evidence_ids"}:
            raise CurieContractError("advisory search constraint fields are invalid")
        _text(constraint.get("text"), "advisory search constraint text")
        source_attempt = constraint.get("source_attempt")
        if (isinstance(source_attempt, bool) or not isinstance(source_attempt, int)
                or source_attempt < 1 or source_attempt > index):
            raise CurieContractError("advisory search constraint has no prior attempt")
        evidence_ids = constraint.get("evidence_ids")
        if (not isinstance(evidence_ids, list) or not evidence_ids
                or not all(isinstance(value, str) and value.strip() for value in evidence_ids)):
            raise CurieContractError("advisory search constraint lacks evidence provenance")
    intents = plan.get("intents")
    if not isinstance(intents, list) or not intents:
        raise CurieContractError("scientific query plan requires search intents")
    seen_intents: set[str] = set()
    for intent in intents:
        if not isinstance(intent, dict) or set(intent) - {
            "intent_id", "core_concept_ids", "optional_concept_ids",
        }:
            raise CurieContractError("search intent fields are invalid")
        intent_id = _text(intent.get("intent_id"), "intent_id")
        if intent_id in seen_intents:
            raise CurieContractError("duplicate search intent identity")
        seen_intents.add(intent_id)
        core_ids = intent.get("core_concept_ids")
        optional_refs = intent.get("optional_concept_ids", [])
        if (not isinstance(core_ids, list) or not all(isinstance(key, str) for key in core_ids)
                or set(core_ids) != concept_ids
                or len(core_ids) != len(concept_ids) or not isinstance(optional_refs, list)
                or not all(isinstance(key, str) for key in optional_refs)
                or len(optional_refs) != len(set(optional_refs))
                or not set(optional_refs) <= optional_ids):
            raise CurieContractError("search intent must preserve all CORE and reference authorized optional concepts")
    supplied_hash = plan.get("plan_content_hash")
    content = {key: value for key, value in plan.items() if key != "plan_content_hash"}
    content_hash = _sha(_plan_content_identity(content))
    if supplied_hash is not None and supplied_hash != content_hash:
        raise CurieContractError("scientific query plan content hash mismatch")
    validated = json.loads(json.dumps(content))
    validated["plan_content_hash"] = content_hash
    return validated


def validate_scientific_query_plan(plan: dict, *, seed: dict | None = None) -> dict:
    if not isinstance(plan, dict):
        raise CurieContractError("scientific query plan must be an object")
    if plan.get("schema_version") == SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION:
        return _validate_v1_scientific_query_plan(plan)
    if plan.get("schema_version") != SCIENTIFIC_QUERY_PLAN_V2:
        raise CurieContractError("scientific query plan schema_version is invalid")
    if not isinstance(seed, dict):
        raise CurieContractError("scientific query plan v2 requires the canonical ResearchSeed")
    return _validated_v2(plan, seed)


def _quoted(term: str) -> str:
    return f'"{term}"' if " " in term else term


def compile_scientific_query_plan(plan: dict, *, seed: dict) -> list[dict]:
    validated = validate_scientific_query_plan(plan, seed=seed)
    if validated["schema_version"] != SCIENTIFIC_QUERY_PLAN_V2:
        raise CurieContractError("only validated v2 plans can use the Boolean compiler")
    concepts = {item["concept_id"]: item for item in validated["core_anchors"]}
    concepts.update({item["concept_id"]: item for item in validated["optional_concepts"]})
    unresolved = {_normalized_term(value) for value in validated["unresolved_entities"]}
    result: list[dict] = []
    seen: set[str] = set()
    for intent in validated["intents"]:
        groups: list[str] = []
        ids = sorted(set(intent["core_concept_ids"] + intent.get("optional_concept_ids", [])))
        for concept_id in ids:
            concept = concepts[concept_id]
            terms = {_normalized_term(concept["term"])}
            for synonym in concept.get("synonyms", []):
                terms.add(_normalized_term(synonym["term"]))
            if concept_id in intent["core_concept_ids"] and terms & unresolved:
                raise CurieContractError("unresolved entity cannot enter a mandatory CORE expression")
            groups.append("(" + " OR ".join(_quoted(term) for term in sorted(terms)) + ")")
        query = " AND ".join(groups)
        if len(query) > MAX_QUERY_CHARS:
            raise CurieContractError("scientific query exceeds Europe PMC length bound; CORE cannot be truncated")
        if query in seen:
            raise CurieContractError("search intents compile to duplicate query content")
        seen.add(query)
        result.append({"intent": intent["intent_id"], "query": query,
                       "concepts": ids, "query_content_hash": _sha({"query": query})})
    return result


def propose_scientific_query_plan(
    seed: dict, *, spec: Any, work_dir: str | Path,
    reformulation_index: int, feedback: dict | None = None,
) -> dict:
    """Request schema-checked proposals; the Curie validator remains authoritative."""
    from research_loop import deep_research, structured_execution

    if reformulation_index == 0:
        if feedback is not None:
            raise CurieContractError("initial scientific plan cannot use feedback")
    elif reformulation_index in (1, 2):
        if not isinstance(feedback, dict) or not feedback.get("previous_plan"):
            raise CurieContractError("scientific replan requires validated prior plan and feedback")
    else:
        raise CurieContractError("scientific planner index exceeds the P0 attempt budget")
    authorized = {
        "candidate_id": seed.get("candidate_id"),
        "round_id": seed.get("round_id"),
        "scientific_question": seed.get("scientific_question"),
        "hypothesis_seed": seed.get("hypothesis_seed"),
        "seed_sha256": research_seed.seed_sha256(seed),
        "question_sha256": hashlib.sha256(str(seed.get("scientific_question") or "").encode("utf-8")).hexdigest(),
        "hypothesis_sha256": hashlib.sha256(str(seed.get("hypothesis_seed") or "").encode("utf-8")).hexdigest(),
    }
    context = {
        "authorized_seed": authorized,
        "reformulation_index": reformulation_index,
        "validated_feedback": feedback,
    }
    prompt = (
        "Propose only a L05ScientificQueryPlan/v2 for Europe PMC. Use CORE terms "
        "only as exact spans of the supplied question or initial hypothesis; mark "
        "source field, source type, snippet, source hash and span. Do not invent "
        "synonyms or entity mappings. Keep unknown abbreviations unresolved. "
        "Do not generate NOT, negative exclusions, evidence judgments or claimed "
        "scientific results. Search must remain open to support, refutation and "
        "limitations. For replans use only validated feedback; preserve all prior "
        "CORE anchors. A proposal without a legal new query may use "
        "NO_ADMISSIBLE_REPLAN only after feedback. Return the schema object.\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True)
    )
    def checked_proposal(model_prompt: str, directory: str | Path) -> tuple[dict, dict, str]:
        result = structured_execution.run_structured_model(
            spec, prompt=model_prompt, schema=_PROPOSAL_SCHEMA,
            work_dir=directory, purpose="l05_scientific_query_planning",
        )
        proposal = result["payload"]
        try:
            raw_proposal = deep_research._parse_cli_output(result["raw_output"])
        except deep_research.DeepResearchError as exc:
            raise CurieContractError(f"structured planner raw proposal is invalid: {exc}") from exc
        if raw_proposal != proposal:
            raise CurieContractError("structured planner raw proposal differs from validated payload")
        proposal_hash = hashlib.sha256(result["raw_output"].encode("utf-8")).hexdigest()
        return proposal, result["receipt"], proposal_hash

    proposal, receipt, proposal_hash = checked_proposal(prompt, work_dir)
    if proposal["status"] == "NO_ADMISSIBLE_REPLAN":
        if reformulation_index == 0 or feedback is None or proposal["plan"] is not None:
            raise CurieContractError("initial or malformed no_admissible_replan proposal")
        previous = validate_scientific_query_plan(feedback["previous_plan"], seed=seed)
        candidates = _admissible_replan_candidates(previous, seed, feedback, reformulation_index)
        if not candidates:
            gaps = feedback.get("validated_coverage_gaps", [])
            if ((feedback.get("attempt_outcome") or {}).get("type") == "COVERAGE_GAP"
                    and any(gap.get("search_directions") for gap in gaps)
                    and not any(_gap_seed_spans(seed, gaps))):
                raise CurieContractError(
                    "no_admissible_replan cannot prove applicable gap-targeted plans are exhausted"
                )
            return {"status": "NO_ADMISSIBLE_REPLAN", "plan": None,
                    "reason": proposal["reason"], "receipt": receipt,
                    "proposal_sha256": proposal_hash}
        first_hash, first_receipt = proposal_hash, receipt
        retry_prompt = prompt + "\nThe no-plan proposal is invalid: the following validated, " \
            "unexecuted candidates exist. Return one admissible PLAN with the same CORE " \
            "and feedback provenance. Do not return NO_ADMISSIBLE_REPLAN.\n" + json.dumps(
                [{"operation": operation, "plan": candidate} for operation, candidate in candidates],
                ensure_ascii=False, sort_keys=True,
            )
        proposal, receipt, proposal_hash = checked_proposal(
            retry_prompt, Path(work_dir) / "reproposal"
        )
        receipt = {**receipt, "prior_proposal_sha256": first_hash,
                   "prior_proposal_receipt": first_receipt}
        if proposal["status"] == "NO_ADMISSIBLE_REPLAN":
            raise CurieContractError(
                f"no_admissible_replan ignores an {candidates[0][0]} candidate"
            )
    if proposal["status"] != "PLAN" or not isinstance(proposal["plan"], dict):
        raise CurieContractError("structured planner did not return a plan object")
    proposed_plan = copy.deepcopy(proposal["plan"])
    expected_provenance = {
        "target_question_sha256": authorized["question_sha256"],
        "parent_plan_content_hash": feedback["previous_plan"]["plan_content_hash"] if feedback else None,
        "feedback_sha256": _sha(feedback) if feedback else None,
        "feedback_gap_ids": sorted(item["gap_id"] for item in feedback["validated_coverage_gaps"]) if feedback else [],
    }
    for key, value in expected_provenance.items():
        if key in proposed_plan and proposed_plan[key] != value:
            raise CurieContractError(f"structured planner supplied false {key}")
        proposed_plan[key] = value
    validated = validate_scientific_query_plan(proposed_plan, seed=seed)
    if validated["reformulation_index"] != reformulation_index:
        raise CurieContractError("structured planner reformulation index mismatch")
    if feedback is not None:
        executed_queries = {item.get("query_content_hash") for item in feedback.get("executed_queries", [])}
        executed_plans = {item.get("plan_content_hash") for item in feedback.get("executed_plans", [])}
        if validated["plan_content_hash"] in executed_plans or any(
            item["query_content_hash"] in executed_queries
            for item in compile_scientific_query_plan(validated, seed=seed)
        ):
            raise CurieContractError("scientific replan repeats executed plan or query content")
        rejected_ids = {item["evidence_id"] for item in feedback.get("semantic_rejections", [])}
        for constraint in validated["advisory_search_constraints"]:
            if not set(constraint["evidence_ids"]) <= rejected_ids:
                raise CurieContractError("advisory search constraint cites unverified rejection")
        previous = validate_scientific_query_plan(feedback["previous_plan"], seed=seed)
        prior_anchors = {
            (item["source_field"], item["start"], item["end"], _normalized_term(item["term"]))
            for item in previous["core_anchors"]
        }
        new_anchors = {
            (item["source_field"], item["start"], item["end"], _normalized_term(item["term"]))
            for item in validated["core_anchors"]
        }
        if prior_anchors != new_anchors:
            raise CurieContractError("scientific replan changed an authorized CORE anchor")
        old_cores = {item["concept_id"]: item for item in previous["core_anchors"]}
        new_cores = {item["concept_id"]: item for item in validated["core_anchors"]}
        for old in old_cores.values():
            key = (old["source_field"], old["start"], old["end"], _normalized_term(old["term"]))
            current = next(item for item in new_cores.values() if (
                item["source_field"], item["start"], item["end"], _normalized_term(item["term"])
            ) == key)
            if not {_normalized_term(value["term"]) for value in old.get("synonyms", [])} <= {
                _normalized_term(value["term"]) for value in current.get("synonyms", [])
            }:
                raise CurieContractError("scientific replan removed an authorized CORE synonym")
        outcome = (feedback.get("attempt_outcome") or {}).get("type")
        if outcome in {"ZERO_DISCOVERY", "NO_SOURCE_QUALIFIED_FULLTEXT", "NO_LOCATED_EVIDENCE"}:
            old_groups = [_intent_groups(previous, intent) for intent in previous["intents"]]
            for intent in validated["intents"]:
                groups = _intent_groups(validated, intent)
                if not any(_boolean_query_broadens(groups, prior) for prior in old_groups):
                    raise CurieContractError("scientific replan must broaden a zero-yield Boolean query")
    elif validated["advisory_search_constraints"]:
        raise CurieContractError("initial plan cannot invent negative search feedback")
    return {"status": "PLAN", "plan": validated, "reason": proposal["reason"],
            "receipt": receipt, "proposal_sha256": proposal_hash}


def _append_query(
    queries: list[dict], intent: str, terms: list[str], *, suffix: list[str] | None = None
) -> None:
    rendered = _bounded_with_suffix(terms, suffix) if suffix else _bounded(terms)
    if rendered.casefold() in {
        str(item["query"]).casefold() for item in queries
    }:
        return
    queries.append({
        "intent": intent,
        "query": rendered,
        "concepts": _unique(terms + (suffix or [])),
    })


def build_scientific_query_plan(
    seed: dict, *, reformulation_index: int = 0
) -> dict:
    if (
        isinstance(reformulation_index, bool)
        or not isinstance(reformulation_index, int)
        or not 0 <= reformulation_index <= MAX_REFORMULATION_INDEX
    ):
        raise CurieContractError(
            f"reformulation_index must be between 0 and {MAX_REFORMULATION_INDEX}"
        )
    _question, _hypothesis, question_tokens, hypothesis_tokens = _seed_terms(seed)
    concepts = _concepts(question_tokens, hypothesis_tokens)
    core = _unique(question_tokens + hypothesis_tokens)

    queries: list[dict] = []
    if reformulation_index == 0:
        _append_query(queries, "scientific_question", question_tokens)
        _append_query(queries, "hypothesis_seed", hypothesis_tokens)
        _append_query(
            queries,
            "combined_scientific_context",
            core,
            suffix=["primary", "research"],
        )
    else:
        _append_query(
            queries,
            "question_primary_evidence",
            question_tokens,
            suffix=["primary", "evidence"],
        )
        _append_query(
            queries,
            "hypothesis_experimental_evidence",
            hypothesis_tokens,
            suffix=["experimental", "evidence"],
        )
        _append_query(
            queries,
            "combined_comparative_evidence",
            core,
            suffix=["comparative", "evidence"],
        )

    for suffix in (
        "mechanistic evidence",
        "experimental evidence",
        "comparative evidence",
        "primary research",
    ):
        if len(queries) >= MIN_QUERY_CANDIDATES:
            break
        _append_query(
            queries,
            "complementary_scientific_evidence",
            core,
            suffix=suffix.split(),
        )

    plan = {
        "schema_version": SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION,
        "planner": SCIENTIFIC_QUERY_PLANNER_VERSION,
        "language": "en",
        "reformulation_index": reformulation_index,
        "concepts": concepts,
        "queries": queries[:MAX_QUERY_CANDIDATES],
    }
    return validate_scientific_query_plan(plan)


def reformulate_scientific_query_plan(seed: dict, previous_plan: dict) -> dict:
    previous = validate_scientific_query_plan(previous_plan)
    return build_scientific_query_plan(
        seed,
        reformulation_index=previous["reformulation_index"] + 1,
    )
