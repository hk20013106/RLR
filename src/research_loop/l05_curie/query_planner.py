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
from itertools import combinations
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from research_loop import research_seed

from .contracts import (
    KEYWORD_QUERY_REQUEST_COUNT, QUERY_PLAN_SCHEMA_VERSION_V2,
    CurieContractError, validate_query_plan,
)

SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION = "L05ScientificQueryPlan/v1"
SCIENTIFIC_QUERY_PLANNER_VERSION = "scientific-query-planner/v1"
SCIENTIFIC_QUERY_PLAN_V2 = "L05ScientificQueryPlan/v2"
SCIENTIFIC_QUERY_PLANNER_V2 = "scientific-query-planner/v2"
_ANCHOR_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source_field": {"type": "string", "enum": ["scientific_question", "hypothesis_seed"]},
        "text_snippet": {"type": "string", "minLength": 1},
    },
    "required": ["source_field", "text_snippet"],
}
_PLAN_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "core_anchors": {"type": "array", "minItems": 1, "items": _ANCHOR_PROPOSAL_SCHEMA},
        "optional_anchors": {"type": "array", "items": _ANCHOR_PROPOSAL_SCHEMA},
        "intents": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "optional_anchor_indices": {
                        "type": "array", "uniqueItems": True,
                        "items": {"type": "integer", "minimum": 0},
                    },
                },
                "required": ["optional_anchor_indices"],
            },
        },
    },
    "required": ["core_anchors", "optional_anchors", "intents"],
}
_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["PLAN", "NO_ADMISSIBLE_REPLAN"]},
        "reason": {"type": "string", "minLength": 1},
        "plan": {"anyOf": [_PLAN_PROPOSAL_SCHEMA, {"type": "null"}]},
    },
    "required": ["status", "reason", "plan"],
}
_CANDIDATE_SELECTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["SELECT_CANDIDATE"]},
        "reason": {"type": "string", "minLength": 1},
        "candidate_id": {"type": "string", "minLength": 1},
    },
    "required": ["status", "reason", "candidate_id"],
}
MIN_QUERY_CANDIDATES = 3
MAX_QUERY_CANDIDATES = 6
MAX_REFORMULATION_INDEX = 1
MAX_QUERY_CHARS = 240
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+]*(?:[-/][A-Za-z0-9+]+)*")
_KEYWORD_DATE_RANGE = re.compile(r",\s*(\d{4})-(\d{4}|)$")
_KEYWORD_DATE_LIKE = re.compile(r",\s*\d+\s*-\s*\d*$|,\s*\d{4}$")
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


def materialize_keyword_question(
    seed: dict, *, scientific_plan: dict, feedback: dict | None
) -> str:
    """Freeze the original claim with its validated plan and current gaps."""
    if not isinstance(seed, dict):
        raise CurieContractError("ResearchSeed must be an object")
    question = seed.get("scientific_question")
    hypothesis = seed.get("hypothesis_seed")
    if not isinstance(question, str) or not question.strip():
        raise CurieContractError("ResearchSeed scientific_question must be non-empty text")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise CurieContractError("ResearchSeed hypothesis_seed must be non-empty text")
    planning = validate_scientific_query_plan(scientific_plan, seed=seed)
    if planning["schema_version"] != SCIENTIFIC_QUERY_PLAN_V2:
        raise CurieContractError("keyword query generation requires a validated scientific plan v2")
    if feedback is not None and not isinstance(feedback, dict):
        raise CurieContractError("keyword query feedback must be an object")
    gaps = [] if feedback is None else feedback.get("validated_coverage_gaps", [])
    if not isinstance(gaps, list):
        raise CurieContractError("validated_coverage_gaps must be a list")
    projection = {
        "core_anchors": planning["core_anchors"],
        "optional_concepts": planning["optional_concepts"],
        "intents": planning["intents"],
    }
    return "\n".join([
        "Scientific question:", question, "",
        "Hypothesis to evaluate:", hypothesis, "",
        "Validated scientific plan:", _canonical(projection).decode("utf-8"), "",
        "Validated coverage gaps:", _canonical(gaps).decode("utf-8"),
    ])


def validate_keyword_proposals(
    proposals: object, *, generation_year: int, prior_queries: list[dict | str]
) -> list[dict]:
    """Validate the complete native proposal batch without repairing or reordering it."""
    if (isinstance(generation_year, bool) or not isinstance(generation_year, int)
            or generation_year < 1):
        raise CurieContractError("generation_year must be a positive integer")
    if not isinstance(proposals, list) or not 1 <= len(proposals) <= KEYWORD_QUERY_REQUEST_COUNT:
        raise CurieContractError(
            "MODEL CONTRACT FAILURE: PaperQA2 must return 1 to 3 keyword proposals"
        )
    if not isinstance(prior_queries, list):
        raise CurieContractError("prior_queries must be a list")

    prior_keys: set[str] = set()
    for index, item in enumerate(prior_queries, 1):
        if isinstance(item, dict):
            item = item.get("query")
        if not isinstance(item, str) or not item.strip():
            raise CurieContractError(f"prior query {index} must contain non-empty query text")
        prior_keys.add(item.strip().casefold())

    validated: list[dict] = []
    seen = set(prior_keys)
    for index, proposal in enumerate(proposals, 1):
        if not isinstance(proposal, str) or not proposal.strip():
            raise CurieContractError(f"keyword proposal {index} must be non-empty text")
        value = proposal.strip()
        if any(unicodedata.category(char) == "Cc" for char in value) or len(value.splitlines()) != 1:
            raise CurieContractError(f"keyword proposal {index} must be a single line without controls")

        start_year = end_year = None
        match = _KEYWORD_DATE_RANGE.search(value)
        if match:
            start_year = int(match.group(1))
            end_year = int(match.group(2)) if match.group(2) else None
            if (start_year < 1 or start_year > generation_year
                    or end_year is not None and (end_year < start_year or end_year > generation_year)):
                raise CurieContractError(f"keyword proposal {index} has an invalid advisory year range")
            query = value[:match.start()].strip()
        else:
            if _KEYWORD_DATE_LIKE.search(value):
                raise CurieContractError(f"keyword proposal {index} has a malformed advisory year range")
            query = value

        if not query or len(query) > MAX_QUERY_CHARS:
            raise CurieContractError(f"keyword proposal {index} query is empty or exceeds {MAX_QUERY_CHARS} characters")
        if re.search(r"(?<!\w)(?:AND|OR|NOT)(?!\w)", query, flags=re.IGNORECASE):
            raise CurieContractError(f"keyword proposal {index} contains a Boolean operator")
        if re.search(r"\b[a-z][a-z0-9+.-]*://", query, flags=re.IGNORECASE):
            raise CurieContractError(f"keyword proposal {index} contains a URL scheme")
        if any(char in query for char in '(){}[]:\"=<>'):
            raise CurieContractError(f"keyword proposal {index} contains unsupported search syntax")
        key = query.strip().casefold()
        if key in seen:
            raise CurieContractError(f"keyword proposal {index} duplicates an executed query")
        seen.add(key)
        validated.append({
            "proposal": proposal,
            "query": query,
            "year_start": start_year,
            "year_end": end_year,
        })
    return validated


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


def _project_optional_intent(previous: dict, intent_index: int, kept_ids: tuple[str, ...]) -> dict:
    """Project one intent without changing any mandatory CORE anchor."""
    candidate = copy.deepcopy(previous)
    candidate.pop("plan_content_hash", None)
    candidate["intents"] = [candidate["intents"][intent_index]]
    candidate["intents"][0]["optional_concept_ids"] = list(kept_ids)
    return candidate


def _replan_candidates(previous: dict, seed: dict, feedback: dict, index: int):
    """Enumerate every authorized transformation class in one fixed order."""
    provenance = {
        "reformulation_index": index,
        "parent_plan_content_hash": previous["plan_content_hash"],
        "feedback_sha256": _sha(feedback),
        "feedback_gap_ids": sorted(gap["gap_id"] for gap in feedback["validated_coverage_gaps"]),
    }

    def prepared(source_intent_id: str | None, candidate: dict):
        candidate.pop("plan_content_hash", None)
        candidate.update(provenance)
        return source_intent_id, candidate

    optional_by_id = {item["concept_id"]: item for item in previous["optional_concepts"]}

    def optional_intents():
        for intent_index, intent in enumerate(previous["intents"]):
            ids = tuple(sorted(intent.get("optional_concept_ids", []), key=lambda key: (
                optional_by_id[key]["source_field"], optional_by_id[key]["start"],
                optional_by_id[key]["end"], _normalized_term(optional_by_id[key]["term"]), key,
            )))
            if ids:
                yield intent_index, intent, ids

    def removals():
        for intent_index, intent, ids in optional_intents():
            for removed in ids:
                yield prepared(intent["intent_id"], _project_optional_intent(
                    previous, intent_index, tuple(key for key in ids if key != removed)
                ))
            if len(ids) > 1:
                yield prepared(intent["intent_id"], _project_optional_intent(
                    previous, intent_index, ()
                ))

    def synonyms():
        for _operation, candidate in _seed_synonym_candidates(previous, seed):
            yield prepared(None, candidate)

    def gap_targets():
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
                yield prepared(intent["intent_id"], candidate)

    def splits():
        for intent_index, intent, ids in optional_intents():
            if len(ids) < 2:
                continue
            for size in range(1, len(ids)):
                for kept_ids in combinations(ids, size):
                    yield prepared(intent["intent_id"], _project_optional_intent(
                        previous, intent_index, kept_ids
                    ))

    operations = (
        ("optional removal", "no OPTIONAL term is used by a prior intent",
         "prior intent uses source-bound OPTIONAL terms", removals),
        ("grounded core synonym expansion", "no new authorized seed parenthetical mapping",
         "new parenthetical mapping is present in an authorized seed field", synonyms),
        ("non-essential design constraint removal", "no OPTIONAL constraint is used by a prior intent",
         "non-essential constraints are represented by OPTIONAL terms", removals),
        ("validated gap targeted intent", "no source-bound target applies to the validated gap",
         "validated gap names a source-bound seed span", gap_targets),
        ("composite intent split", "no prior intent has at least two OPTIONAL terms",
         "prior intent has multiple source-bound OPTIONAL terms", splits),
    )
    for kind, empty_reason, applicable_reason, generate in operations:
        yield kind, empty_reason, applicable_reason, generate()


def _intent_exhaustion_hashes(feedback: dict) -> tuple[bool, set[str]]:
    executed_plans = feedback.get("executed_plans", [])
    if not isinstance(executed_plans, list):
        raise CurieContractError("executed_plans must be a list")
    keyword_mode = any(
        isinstance(item, dict) and "intent_query_content_hashes" in item
        for item in executed_plans
    )
    if not keyword_mode:
        return False, set()
    hashes: set[str] = set()
    for index, item in enumerate(executed_plans, 1):
        if not isinstance(item, dict) or "intent_query_content_hashes" not in item:
            raise CurieContractError("keyword replan feedback mixes intent and legacy query fingerprints")
        values = item["intent_query_content_hashes"]
        if (not isinstance(values, list) or not values
                or not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                           for value in values)
                or len(values) != len(set(values))):
            raise CurieContractError(f"executed_plans[{index}].intent_query_content_hashes is invalid")
        hashes.update(values)
    return True, hashes


def _admissible_replan_candidates(previous: dict, seed: dict, feedback: dict, index: int):
    """Validate and deduplicate every class before proving exhaustion."""
    executed_queries = {item.get("query_content_hash") for item in feedback.get("executed_queries", [])}
    executed_plans = {item.get("plan_content_hash") for item in feedback.get("executed_plans", [])}
    keyword_mode, intent_query_hashes = _intent_exhaustion_hashes(feedback)
    exhausted_queries = intent_query_hashes if keyword_mode else executed_queries
    candidates: list[tuple[str, dict]] = []
    seen_plans: set[str] = set()
    seen_queries: set[str] = set()
    audit = {
        "parent_plan_content_hash": previous["plan_content_hash"],
        "feedback_sha256": _sha(feedback),
        "feedback_gap_ids": sorted(gap["gap_id"] for gap in feedback["validated_coverage_gaps"]),
        "attempt_outcome_type": (feedback.get("attempt_outcome") or {}).get("type"),
        "transformations": [],
    }
    for operation, empty_reason, applicable_reason, generated in _replan_candidates(
        previous, seed, feedback, index
    ):
        record = {"kind": operation, "applicable": False, "reason": empty_reason,
                  "candidates": []}
        for source_intent_id, candidate in generated:
            record["applicable"] = True
            record["reason"] = applicable_reason
            validated = validate_scientific_query_plan(candidate, seed=seed)
            compiled = compile_scientific_query_plan(validated, seed=seed)
            identity = validated["plan_content_hash"]
            query_hashes = [item["query_content_hash"] for item in compiled]
            if identity in seen_plans:
                outcome = "duplicate_candidate"
            elif identity in executed_plans:
                outcome = "executed_plan"
            elif any(value in exhausted_queries for value in query_hashes):
                outcome = "executed_query"
            elif any(value in seen_queries for value in query_hashes):
                outcome = "duplicate_candidate_query"
            else:
                outcome = "admissible"
                seen_queries.update(query_hashes)
                candidates.append((operation, validated))
            seen_plans.add(identity)
            record["candidates"].append({
                "source_intent_id": source_intent_id,
                "parent_plan_content_hash": previous["plan_content_hash"],
                "feedback_sha256": audit["feedback_sha256"],
                "feedback_gap_ids": audit["feedback_gap_ids"],
                "plan_content_hash": identity,
                "query_content_hashes": query_hashes,
                "outcome": outcome,
            })
        audit["transformations"].append(record)
    return candidates, audit


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


def _keyword_query_rows(
    scientific_plan: dict, proposals: list[dict], *, query_id_prefix: str
) -> list[dict]:
    concepts = [item["concept_id"] for item in
                scientific_plan["core_anchors"] + scientific_plan["optional_concepts"]]
    return [{
        "query_id": f"{query_id_prefix}{index:03d}",
        "intent": "paperqa2_keyword_batch",
        "query": proposal["query"],
        "concepts": concepts,
        "providers": ["europe-pmc"],
        "query_content_hash": _sha({"query": proposal["query"]}),
        "origin": "generated",
    } for index, proposal in enumerate(proposals, 1)]


def _keyword_query_plan_id(
    *, candidate_id: str, round_id: str, seed_sha256: str, round_index: int,
    scientific_plan_content_hash: str, invocation_sha256: str, queries: list[dict],
) -> str:
    return "QP_MULTI_" + _sha({
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": seed_sha256,
        "round_index": round_index,
        "scientific_plan_content_hash": scientific_plan_content_hash,
        "invocation_sha256": invocation_sha256,
        "queries": queries,
    })[:16]


def validate_keyword_query_plan(
    plan: dict, *, seed: dict, scientific_plan: dict, invocation: dict,
    prior_plans: list[dict],
) -> dict:
    """Verify a v2 plan's actual queries against its frozen scientific and runtime inputs."""
    if not isinstance(seed, dict) or not isinstance(invocation, dict):
        raise CurieContractError("keyword QueryPlan validation requires frozen seed and invocation objects")
    if not isinstance(prior_plans, list):
        raise CurieContractError("prior_plans must be a list")
    seed_sha256 = research_seed.seed_sha256(seed)
    validated_plan = validate_query_plan(plan, seed_sha256=seed_sha256)
    if validated_plan["schema_version"] != QUERY_PLAN_SCHEMA_VERSION_V2:
        raise CurieContractError("keyword QueryPlan validation requires L05QueryPlan/v2")

    planning = validate_scientific_query_plan(scientific_plan, seed=seed)
    if planning["schema_version"] != SCIENTIFIC_QUERY_PLAN_V2:
        raise CurieContractError("keyword QueryPlan requires a validated scientific plan v2")
    if validated_plan.get("planning") != planning:
        raise CurieContractError("keyword QueryPlan scientific plan association mismatch")
    if (validated_plan["candidate_id"] != seed.get("candidate_id")
            or validated_plan["round_id"] != seed.get("round_id")
            or validated_plan.get("reformulation_index") != planning["reformulation_index"]):
        raise CurieContractError("keyword QueryPlan identity differs from its frozen inputs")

    if (invocation.get("acquisition_run_id") is None
            or not isinstance(invocation.get("acquisition_run_id"), str)
            or not invocation["acquisition_run_id"].strip()
            or type(invocation.get("attempt_index")) is not int
            or invocation["attempt_index"] < 1
            or invocation.get("seed_sha256") != seed_sha256
            or invocation.get("scientific_plan_content_hash") != planning["plan_content_hash"]):
        raise CurieContractError("keyword invocation does not bind the current acquisition and scientific plan")
    try:
        invocation_sha256 = _sha(invocation)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CurieContractError("keyword invocation is not canonical JSON") from exc

    generation = validated_plan["planning_provenance"]["keyword_generation"]
    if generation["invocation_sha256"] != invocation_sha256:
        raise CurieContractError("keyword QueryPlan invocation hash mismatch")
    if generation["bridge_sha256"] != invocation.get("bridge_sha256"):
        raise CurieContractError("keyword QueryPlan bridge hash mismatch")
    if generation["settings_sha256"] != invocation.get("settings_sha256"):
        raise CurieContractError("keyword QueryPlan Settings hash mismatch")
    provenance = validated_plan["planning_provenance"]
    if invocation.get("planner_receipt_sha256") != _sha(provenance["receipt"]):
        raise CurieContractError("keyword QueryPlan host receipt hash mismatch")
    proposal_sha256 = provenance.get("proposal_sha256")
    if (not isinstance(proposal_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", proposal_sha256) is None
            or invocation.get("planner_proposal_sha256") != proposal_sha256):
        raise CurieContractError("keyword QueryPlan host proposal hash mismatch")
    if invocation.get("planner_feedback_sha256") != planning.get("feedback_sha256"):
        raise CurieContractError("keyword QueryPlan planner feedback hash mismatch")
    expected_runtime = invocation.get("expected_runtime")
    runtime_fields = {
        "package", "version", "upstream_tag", "upstream_commit",
        "module_path", "clean_checkout", "llm_model",
    }
    if (not isinstance(expected_runtime, dict) or set(expected_runtime) != runtime_fields
            or any(generation["runtime"].get(key) != value
                   for key, value in expected_runtime.items())):
        raise CurieContractError("keyword QueryPlan runtime differs from the frozen PaperQA2 binding")

    prior_queries = []
    for index, previous in enumerate(prior_plans, 1):
        previous = validate_query_plan(previous, seed_sha256=seed_sha256)
        prior_queries.extend(previous["queries"])
    actual_proposals = [item["proposal"] for item in generation["proposals"]]
    normalized = validate_keyword_proposals(
        actual_proposals,
        generation_year=generation["runtime"]["generation_year"],
        prior_queries=prior_queries,
    )
    if normalized != generation["proposals"]:
        raise CurieContractError("keyword QueryPlan proposal projection mismatch")
    first_query_id = validated_plan["queries"][0]["query_id"]
    if not first_query_id.endswith("001"):
        raise CurieContractError("keyword QueryPlan query IDs must be sequential")
    query_id_prefix = first_query_id[:-3]
    expected_queries = _keyword_query_rows(
        planning, normalized, query_id_prefix=query_id_prefix)
    if validated_plan["queries"] != expected_queries:
        raise CurieContractError("keyword QueryPlan queries differ from validated native proposals")

    expected_plan_id = _keyword_query_plan_id(
        candidate_id=validated_plan["candidate_id"],
        round_id=validated_plan["round_id"],
        seed_sha256=validated_plan["seed_sha256"],
        round_index=validated_plan["round_index"],
        scientific_plan_content_hash=planning["plan_content_hash"],
        invocation_sha256=invocation_sha256,
        queries=expected_queries,
    )
    if validated_plan["plan_id"] != expected_plan_id:
        raise CurieContractError("keyword QueryPlan identity hash mismatch")
    return validated_plan


def _scientific_intent(plan: dict) -> dict:
    """Project a formal plan into the scientific choices exposed to cognition."""
    optional_indices = {item["concept_id"]: index
                        for index, item in enumerate(plan["optional_concepts"])}
    return {
        "core_anchors": [{"source_field": item["source_field"],
                          "text_snippet": item["text_snippet"]}
                         for item in plan["core_anchors"]],
        "optional_anchors": [{"source_field": item["source_field"],
                              "text_snippet": item["text_snippet"]}
                             for item in plan["optional_concepts"]],
        "intents": [{"optional_anchor_indices": [optional_indices[key]
                     for key in intent.get("optional_concept_ids", [])]}
                    for intent in plan["intents"]],
    }


def _planner_prompt(seed: dict, *, reformulation_index: int,
                    feedback: dict | None) -> str:
    context = {
        "authorized_seed": {field: seed[field]
                            for field in ("scientific_question", "hypothesis_seed")},
        "reformulation_index": reformulation_index,
        "validated_feedback": None if feedback is None else {
            "previous_scientific_intent": _scientific_intent(feedback["previous_plan"]),
            "attempt_outcome": feedback.get("attempt_outcome"),
            "validated_coverage_gaps": feedback.get("validated_coverage_gaps", []),
            "semantic_rejections": feedback.get("semantic_rejections", []),
            "executed_queries": [item["query"] for item in feedback.get("executed_queries", [])],
        },
    }
    return (
        "Propose only scientific intent for Europe PMC. In plan choose core_anchors "
        "and optional_anchors using only source_field and text_snippet. Each snippet "
        "must be an exact, uniquely located span of the supplied seed field. Select "
        "optional_anchor_indices for each intent; every intent automatically includes "
        "all CORE anchors. Include a question CORE anchor. RLR materializes the formal "
        "plan and all machine fields. Do not invent synonyms or entity mappings, "
        "negative exclusions, evidence judgments or scientific results. Search must "
        "remain open to support, refutation and limitations. For replans use only "
        "validated feedback and preserve prior CORE spans. A proposal without a legal "
        "new query may use NO_ADMISSIBLE_REPLAN with plan null only after feedback. "
        "Return the schema object.\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True)
    )


def _planner_request_hash(request: dict) -> str:
    return _sha({key: value for key, value in request.items() if key != "request_sha256"})


def _check_planner_context(seed: dict, *, reformulation_index: int,
                           feedback: dict | None) -> None:
    if reformulation_index == 0:
        if feedback is not None:
            raise CurieContractError("initial scientific plan cannot use feedback")
    elif reformulation_index in (1, 2):
        if not isinstance(feedback, dict) or not feedback.get("previous_plan"):
            raise CurieContractError("scientific replan requires validated prior plan and feedback")
        previous = validate_scientific_query_plan(feedback["previous_plan"], seed=seed)
        if feedback["previous_plan"].get("plan_content_hash") != previous["plan_content_hash"]:
            raise CurieContractError("scientific planner prior plan hash is stale")
    else:
        raise CurieContractError("scientific planner index exceeds the P0 attempt budget")


def prepare_scientific_query_plan_request(
    seed: dict, *, reformulation_index: int, feedback: dict | None,
) -> dict:
    """Freeze the authorized seed, feedback, prompt, and schema for one proposal."""
    _check_planner_context(seed, reformulation_index=reformulation_index, feedback=feedback)
    seed_snapshot = json.loads(json.dumps(seed, ensure_ascii=False, sort_keys=True))
    feedback_snapshot = (
        json.loads(json.dumps(feedback, ensure_ascii=False, sort_keys=True))
        if feedback is not None else None
    )
    previous_hash = (
        feedback_snapshot["previous_plan"]["plan_content_hash"]
        if feedback_snapshot is not None else None
    )
    request = {
        "schema_version": "L05ScientificQueryPlanRequest/v1",
        "seed": seed_snapshot,
        "seed_sha256": research_seed.seed_sha256(seed_snapshot),
        "reformulation_index": reformulation_index,
        "feedback": feedback_snapshot,
        "feedback_sha256": _sha(feedback_snapshot) if feedback_snapshot is not None else None,
        "previous_plan_content_hash": previous_hash,
        "prompt": _planner_prompt(
            seed_snapshot, reformulation_index=reformulation_index,
            feedback=feedback_snapshot,
        ),
        "schema": copy.deepcopy(_PROPOSAL_SCHEMA),
    }
    request["request_sha256"] = _planner_request_hash(request)
    return request


def _check_planner_request(seed: dict, request: dict) -> tuple[dict, int, dict | None]:
    if not isinstance(request, dict) or request.get(
        "schema_version"
    ) not in {"L05ScientificQueryPlanRequest/v1", "L05ScientificQueryPlanSelectionRequest/v1"}:
        raise CurieContractError("scientific planner request schema is invalid")
    if not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise CurieContractError("scientific planner request prompt is missing")
    selection = request["schema_version"] == "L05ScientificQueryPlanSelectionRequest/v1"
    expected_schema = _CANDIDATE_SELECTION_SCHEMA if selection else _PROPOSAL_SCHEMA
    if request.get("schema") != expected_schema:
        raise CurieContractError("scientific planner request schema bytes are missing or changed")
    if request.get("seed") != seed or request.get("seed_sha256") != research_seed.seed_sha256(seed):
        raise CurieContractError("scientific planner request seed identity/hash is stale")
    feedback = request.get("feedback")
    if request.get("feedback_sha256") != (_sha(feedback) if feedback is not None else None):
        raise CurieContractError("scientific planner request feedback hash is stale")
    index = request.get("reformulation_index")
    _check_planner_context(seed, reformulation_index=index, feedback=feedback)
    previous_hash = feedback["previous_plan"]["plan_content_hash"] if feedback else None
    if request.get("previous_plan_content_hash") != previous_hash:
        raise CurieContractError("scientific planner request previous-plan hash is stale")
    if request.get("request_sha256") != _planner_request_hash(request):
        raise CurieContractError("scientific planner request hash does not match its bytes")
    if selection:
        if feedback is None:
            raise CurieContractError("candidate selection requires prior plan and feedback")
        candidates = _frozen_replan_candidates(seed, feedback, index)
        if (not candidates or request.get("candidates") != candidates
                or request.get("candidate_set_sha256") != _sha(candidates)):
            raise CurieContractError("candidate selection enumeration/hash binding changed")
    return seed, index, feedback


def _frozen_replan_candidates(seed: dict, feedback: dict, index: int) -> list[dict]:
    candidates, _audit = _admissible_replan_candidates(
        feedback["previous_plan"], seed, feedback, index,
    )
    return [{"candidate_id": "candidate-" + _sha(plan), "operation": operation,
             "candidate_sha256": _sha(plan), "plan": plan}
            for operation, plan in candidates]


def _candidate_selection_request(request: dict, candidates: list[dict]) -> dict:
    """Freeze exact enumerated plans; cognition selects an identity only."""
    next_request = copy.deepcopy(request)
    next_request["schema_version"] = "L05ScientificQueryPlanSelectionRequest/v1"
    next_request["schema"] = copy.deepcopy(_CANDIDATE_SELECTION_SCHEMA)
    next_request["candidates"] = copy.deepcopy(candidates)
    next_request["candidate_set_sha256"] = _sha(candidates)
    summaries = [{
        "candidate_id": item["candidate_id"], "candidate_sha256": item["candidate_sha256"],
        "plan_content_hash": item["plan"]["plan_content_hash"], "operation": item["operation"],
        "core_terms": [anchor["term"] for anchor in item["plan"]["core_anchors"]],
        "queries": compile_scientific_query_plan(item["plan"], seed=request["seed"]),
    } for item in candidates]
    next_request["prompt"] = (
        "Validated, unexecuted formal replan candidates exist. Choose exactly one "
        "authorized candidate_id using the scientific summaries below. Return only "
        "SELECT_CANDIDATE, reason and candidate_id. RLR retrieves the exact frozen "
        "plan. Do not recreate plans, anchors, spans, hashes, provenance or queries. "
        "NO_ADMISSIBLE_REPLAN is unavailable while these candidates remain.\n"
        + json.dumps({"scientific_question": request["seed"]["scientific_question"],
                      "hypothesis_seed": request["seed"]["hypothesis_seed"],
                      "attempt_outcome": request["feedback"].get("attempt_outcome"),
                      "validated_coverage_gaps": request["feedback"].get("validated_coverage_gaps", [])},
                     ensure_ascii=False, sort_keys=True)
        + "\n" + json.dumps(summaries, ensure_ascii=False, sort_keys=True)
    )
    next_request["request_sha256"] = _planner_request_hash(next_request)
    return next_request


def materialize_scientific_query_plan(seed: dict, *, request: dict, proposal: dict) -> dict:
    """Derive formal v2 bookkeeping solely from validated scientific choices."""
    _seed, index, feedback = _check_planner_request(seed, request)
    errors = list(Draft202012Validator(_PLAN_PROPOSAL_SCHEMA).iter_errors(proposal))
    if errors:
        raise CurieContractError(f"scientific intent schema invalid: {errors[0].message}")

    def anchor(choice: dict) -> dict:
        field, snippet = choice["source_field"], choice["text_snippet"]
        source = seed[field]
        start = source.find(snippet)
        if start < 0:
            raise CurieContractError("scientific intent requires an exact seed span")
        if source.find(snippet, start + 1) >= 0:
            raise CurieContractError("scientific intent requires a unique exact seed span")
        term = _normalized_term(snippet)
        return {
            "concept_id": "concept-" + term.replace(" ", "-") + "-" + _sha(
                {"field": field, "start": start, "end": start + len(snippet)}
            )[:16],
            "term": term,
            "source_type": "QUESTION" if field == "scientific_question" else "INITIAL_HYPOTHESIS",
            "source_field": field, "text_snippet": snippet,
            "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "start": start, "end": start + len(snippet), "synonyms": [],
        }

    core = [anchor(choice) for choice in proposal["core_anchors"]]
    optional = [anchor(choice) for choice in proposal["optional_anchors"]]
    intents = []
    for choice in proposal["intents"]:
        indices = choice["optional_anchor_indices"]
        if any(value >= len(optional) for value in indices):
            raise CurieContractError("scientific intent optional anchor index is out of range")
        core_ids = [item["concept_id"] for item in core]
        optional_ids = [optional[value]["concept_id"] for value in indices]
        intents.append({
            "intent_id": "intent-" + _sha({"core": sorted(core_ids), "optional": sorted(optional_ids)})[:16],
            "core_concept_ids": core_ids, "optional_concept_ids": optional_ids,
        })
    previous = feedback["previous_plan"] if feedback else None
    if previous is not None:
        # Preserve already-authorized equivalences in minimal intent replans.
        for item in core + optional:
            prior = next((old for old in previous["core_anchors"] + previous["optional_concepts"]
                          if (old["source_field"], old["start"], old["end"]) ==
                          (item["source_field"], item["start"], item["end"])), None)
            if prior is not None:
                item["synonyms"] = copy.deepcopy(prior.get("synonyms", []))
    plan = {
        "schema_version": SCIENTIFIC_QUERY_PLAN_V2, "planner": SCIENTIFIC_QUERY_PLANNER_V2,
        "seed_sha256": research_seed.seed_sha256(seed), "reformulation_index": index,
        "core_anchors": core, "optional_concepts": optional, "intents": intents,
        "unresolved_entities": copy.deepcopy(previous["unresolved_entities"]) if previous else [],
        "advisory_search_constraints": copy.deepcopy(previous["advisory_search_constraints"]) if previous else [],
        "target_question_sha256": hashlib.sha256(seed["scientific_question"].encode("utf-8")).hexdigest(),
        "parent_plan_content_hash": previous["plan_content_hash"] if previous else None,
        "feedback_sha256": _sha(feedback) if feedback else None,
        "feedback_gap_ids": sorted(item["gap_id"] for item in feedback["validated_coverage_gaps"]) if feedback else [],
    }
    return validate_scientific_query_plan(plan, seed=seed)


def _validated_plan_result(seed: dict, request: dict, proposal: dict,
                            proposal_sha256: str) -> dict:
    _seed, reformulation_index, feedback = _check_planner_request(seed, request)
    if not isinstance(proposal, dict):
        raise CurieContractError("scientific planner response must be an object")
    schema_errors = sorted(
        Draft202012Validator(request["schema"]).iter_errors(proposal),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        error = schema_errors[0]
        field = ".".join(str(item) for item in error.absolute_path) or "response"
        raise CurieContractError(
            f"scientific planner response schema invalid at {field}: {error.message}"
        )
    if request["schema_version"] == "L05ScientificQueryPlanSelectionRequest/v1":
        selected = next((item for item in request["candidates"]
                         if item["candidate_id"] == proposal["candidate_id"]), None)
        if selected is None:
            raise CurieContractError("candidate_id is not authorized by the current request")
        validated = validate_scientific_query_plan(copy.deepcopy(selected["plan"]), seed=seed)
        if _sha(validated) != selected["candidate_sha256"]:
            raise CurieContractError("selected candidate hash binding changed")
        return {"status": "PLAN", "plan": validated, "reason": proposal["reason"],
                "compiled_queries": compile_scientific_query_plan(validated, seed=seed),
                "proposal_sha256": proposal_sha256}
    if proposal["status"] == "NO_ADMISSIBLE_REPLAN":
        if reformulation_index == 0 or feedback is None or proposal["plan"] is not None:
            raise CurieContractError("initial or malformed no_admissible_replan proposal")
        previous = validate_scientific_query_plan(feedback["previous_plan"], seed=seed)
        candidates, enumeration = _admissible_replan_candidates(
            previous, seed, feedback, reformulation_index
        )
        if not candidates:
            gaps = feedback.get("validated_coverage_gaps", [])
            if ((feedback.get("attempt_outcome") or {}).get("type") == "COVERAGE_GAP"
                    and any(gap.get("search_directions") for gap in gaps)
                    and not any(_gap_seed_spans(seed, gaps))):
                raise CurieContractError(
                    "no_admissible_replan cannot prove applicable gap-targeted plans are exhausted"
                )
            return {
                "status": "NO_ADMISSIBLE_REPLAN", "plan": None,
                "reason": proposal["reason"],
                "replan_enumeration": enumeration,
                "proposal_sha256": proposal_sha256,
            }
        candidate_set = _frozen_replan_candidates(seed, feedback, reformulation_index)
        next_request = _candidate_selection_request(request, candidate_set)
        return {
            "status": "REPROPOSAL_REQUIRED",
            "plan": None,
            "reason": proposal["reason"],
            "candidates": candidate_set,
            "replan_enumeration": enumeration,
            "next_request": next_request,
            "proposal_sha256": proposal_sha256,
        }
    if proposal["status"] != "PLAN" or not isinstance(proposal["plan"], dict):
        raise CurieContractError("structured planner did not return a plan object")
    validated = materialize_scientific_query_plan(seed, request=request, proposal=proposal["plan"])
    if feedback is not None:
        executed_queries = {item.get("query_content_hash") for item in feedback.get("executed_queries", [])}
        executed_plans = {item.get("plan_content_hash") for item in feedback.get("executed_plans", [])}
        keyword_mode, intent_query_hashes = _intent_exhaustion_hashes(feedback)
        exhausted_queries = intent_query_hashes if keyword_mode else executed_queries
        if validated["plan_content_hash"] in executed_plans or any(
            item["query_content_hash"] in exhausted_queries
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
    return {
        "status": "PLAN", "plan": validated, "reason": proposal["reason"],
        "compiled_queries": compile_scientific_query_plan(validated, seed=seed),
        "proposal_sha256": proposal_sha256,
    }


def validate_scientific_query_plan_response(
    seed: dict, *, request: dict, raw_response: bytes,
) -> dict:
    """Validate raw host proposal bytes through the authoritative Curie owners."""
    from research_loop import deep_research

    _check_planner_request(seed, request)
    if not isinstance(raw_response, bytes) or not raw_response:
        raise CurieContractError("scientific planner raw response bytes are missing")
    try:
        raw_text = raw_response.decode("utf-8")
        proposal = deep_research._parse_cli_output(raw_text)
    except (UnicodeDecodeError, deep_research.DeepResearchError) as exc:
        raise CurieContractError(f"scientific planner raw proposal is invalid: {exc}") from exc
    proposal_sha256 = hashlib.sha256(raw_response).hexdigest()
    return _validated_plan_result(seed, request, proposal, proposal_sha256)


def propose_scientific_query_plan(
    seed: dict, *, spec: Any, work_dir: str | Path,
    reformulation_index: int, feedback: dict | None = None,
) -> dict:
    """Headless adapter over the shared pure request and response owners."""
    from research_loop import deep_research, structured_execution

    request = prepare_scientific_query_plan_request(
        seed, reformulation_index=reformulation_index, feedback=feedback
    )

    def checked_proposal(active_request: dict, directory: str | Path):
        result = structured_execution.run_structured_model(
            spec, prompt=active_request["prompt"], schema=active_request["schema"],
            work_dir=directory, purpose="l05_scientific_query_planning",
        )
        try:
            raw_proposal = deep_research._parse_cli_output(result["raw_output"])
        except deep_research.DeepResearchError as exc:
            raise CurieContractError(f"structured planner raw proposal is invalid: {exc}") from exc
        if raw_proposal != result["payload"]:
            raise CurieContractError("structured planner raw proposal differs from validated payload")
        raw_bytes = result["raw_output"].encode("utf-8")
        _check_planner_request(seed, active_request)
        decision = _validated_plan_result(
            seed, active_request, raw_proposal,
            hashlib.sha256(raw_bytes).hexdigest(),
        )
        return decision, result["receipt"]

    decision, receipt = checked_proposal(request, work_dir)
    if decision["status"] == "REPROPOSAL_REQUIRED":
        retry_request = decision["next_request"]
        second, second_receipt = checked_proposal(
            retry_request, Path(work_dir) / "reproposal"
        )
        if second["status"] != "PLAN":
            operation = second.get("candidates", [])[0].get("operation", "candidate")
            raise CurieContractError(
                f"no_admissible_replan ignores an {operation} candidate"
            )
        receipt = {
            **second_receipt,
            "prior_proposal_sha256": decision["proposal_sha256"],
            "prior_proposal_receipt": receipt,
            "replan_enumeration": decision["replan_enumeration"],
        }
        decision = second
    else:
        receipt = {**receipt, **({
            "replan_enumeration": decision["replan_enumeration"]
        } if "replan_enumeration" in decision else {})}
    decision["receipt"] = receipt
    return decision


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
