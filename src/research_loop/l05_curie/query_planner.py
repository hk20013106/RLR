"""Bounded, provider-neutral query planning for Curie acquisition.

This module owns only deterministic scientific-query planning for already
English ResearchSeed text. Chinese semantic translation/planning belongs to
the configured provider boundary and is passed back through the existing
explicit-query path. Other input languages are intentionally unsupported.
This module never selects records, retrieves source bytes, verifies evidence,
or creates an EvidencePack.
"""
from __future__ import annotations

import re
import unicodedata

from .contracts import CurieContractError
from .query_language import (
    classify_supported_input_language,
    validate_english_retrieval_query,
)

SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION = "L05ScientificQueryPlan/v1"
SCIENTIFIC_QUERY_PLANNER_VERSION = "scientific-query-planner/v1"
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


def requires_provider_planning(seed: dict) -> bool:
    if not isinstance(seed, dict):
        raise CurieContractError("ResearchSeed must be an object")
    question = _text(
        seed.get("scientific_question"), "ResearchSeed scientific_question"
    )
    hypothesis = _text(
        seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed"
    )
    languages = {
        classify_supported_input_language(
            question, name="ResearchSeed scientific_question"
        ),
        classify_supported_input_language(
            hypothesis, name="ResearchSeed hypothesis_seed"
        ),
    }
    return "zh" in languages


def _english_seed(seed: dict) -> tuple[str, str, list[str], list[str]]:
    if not isinstance(seed, dict):
        raise CurieContractError("ResearchSeed must be an object")
    question = _text(
        seed.get("scientific_question"), "ResearchSeed scientific_question"
    )
    hypothesis = _text(
        seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed"
    )
    for label, value in (
        ("ResearchSeed scientific_question", question),
        ("ResearchSeed hypothesis_seed", hypothesis),
    ):
        language = classify_supported_input_language(value, name=label)
        if language != "en":
            raise CurieContractError(
                "Chinese ResearchSeed requires provider-planned English retrieval queries"
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
    return validate_english_retrieval_query(
        " ".join(terms), name="English retrieval query"
    )


def validate_scientific_query_plan(plan: dict) -> dict:
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
        rendered = validate_english_retrieval_query(
            query["query"], name="English retrieval query"
        )
        key = rendered.casefold()
        if key in seen:
            raise CurieContractError(
                "scientific query plan queries must be distinct"
            )
        seen.add(key)
    return plan


def _append_query(
    queries: list[dict], intent: str, terms: list[str]
) -> None:
    rendered = _bounded(terms)
    if rendered.casefold() in {
        str(item["query"]).casefold() for item in queries
    }:
        return
    queries.append({
        "intent": intent,
        "query": rendered,
        "concepts": _unique(terms),
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
    question, hypothesis, question_tokens, hypothesis_tokens = _english_seed(seed)
    concepts = _concepts(question_tokens, hypothesis_tokens)
    core = _unique(question_tokens + hypothesis_tokens)

    queries: list[dict] = []
    if reformulation_index == 0:
        _append_query(queries, "scientific_question", question_tokens)
        _append_query(queries, "hypothesis_seed", hypothesis_tokens)
        _append_query(
            queries,
            "combined_scientific_context",
            core + ["primary research"],
        )
    else:
        _append_query(
            queries,
            "question_primary_evidence",
            question_tokens + ["primary evidence"],
        )
        _append_query(
            queries,
            "hypothesis_experimental_evidence",
            hypothesis_tokens + ["experimental evidence"],
        )
        _append_query(
            queries,
            "combined_comparative_evidence",
            core + ["comparative evidence"],
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
            core + [suffix],
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
