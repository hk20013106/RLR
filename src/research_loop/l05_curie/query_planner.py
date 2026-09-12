"""Bounded, provider-neutral query planning for Curie acquisition.

This module owns only scientific-query planning.  It never selects records,
retrieves source bytes, verifies evidence, or creates an EvidencePack.
"""
from __future__ import annotations

import re
import unicodedata

from .contracts import CurieContractError


SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION = "L05ScientificQueryPlan/v1"
SCIENTIFIC_QUERY_PLANNER_VERSION = "scientific-query-planner/v1"
MIN_QUERY_CANDIDATES = 3
MAX_QUERY_CANDIDATES = 6
MAX_REFORMULATION_INDEX = 1
MAX_QUERY_CHARS = 240
_CJK = re.compile(r"[\u3400-\u9fff]")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+]*(?:[-/][A-Za-z0-9+]+)*")
_STOPWORDS = frozenset({"a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for", "from", "how", "in", "is", "of", "on", "or", "that", "the", "to", "what", "which", "with"})
_LEXICON = (
    ("高心率", "high heart rate", "phenomenon"),
    ("病理性重塑", "pathological remodeling", "outcome"),
    ("肾上腺素能", "adrenergic regulation", "mechanism"),
    ("钙离子处理", "calcium handling", "mechanism"),
    ("Ca2+", "calcium handling", "mechanism"),
    ("兴奋-收缩", "excitation-contraction coupling", "mechanism"),
    ("心脏", "cardiac", "system"),
    ("鼩鼱", "shrews", "organism"),
    ("哺乳动物", "mammals", "organism"),
)
_ROLES = {
    "heart": ("heart", "system"), "cardiac": ("cardiac", "system"),
    "calcium": ("calcium handling", "mechanism"),
    "ca2+": ("calcium handling", "mechanism"),
    "adrenergic": ("adrenergic regulation", "mechanism"),
    "remodeling": ("remodeling", "outcome"), "injury": ("injury", "outcome"),
    "adaptation": ("adaptation", "outcome"), "mechanism": ("mechanism", "mechanism"),
    "shrew": ("shrews", "organism"), "shrews": ("shrews", "organism"),
    "mammal": ("mammals", "organism"), "mammals": ("mammals", "organism"),
}


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurieContractError(f"{name} must be a non-empty string")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        value = re.sub(r"\s+", " ", value).strip().lower()
        if value and value not in result:
            result.append(value)
    return result


def _concepts(seed: dict) -> list[dict]:
    question = _text(seed.get("scientific_question"), "ResearchSeed scientific_question")
    hypothesis = _text(seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed")
    source = f"{question} {hypothesis}"
    concepts: list[dict] = []
    seen: set[str] = set()

    def add(term: str, role: str, origin: str) -> None:
        term = term.strip().lower()
        if term and term not in seen:
            concepts.append({"term": term, "role": role, "source": origin})
            seen.add(term)

    for needle, term, role in _LEXICON:
        if needle.casefold() in source.casefold():
            add(term, role, f"lexicon:{needle}")
    for token in _TOKEN.findall(source):
        normalized = token.casefold()
        if normalized in _STOPWORDS:
            continue
        term, role = _ROLES.get(normalized, (normalized, "mechanism" if normalized.endswith(("ing", "tion", "ity")) else "phenomenon"))
        add(term, role, "seed")
    if not concepts:
        raise CurieContractError("scientific query planner could not derive searchable concepts from the ResearchSeed")
    return concepts


def _bounded(values: list[str]) -> str:
    terms = _unique(values)
    while terms and len(" ".join(terms)) > MAX_QUERY_CHARS:
        terms.pop()
    if not terms:
        raise CurieContractError("scientific query planner produced an empty query")
    return " ".join(terms)


def validate_scientific_query_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("schema_version") != SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION:
        raise CurieContractError("scientific query plan schema_version is invalid")
    if plan.get("planner") != SCIENTIFIC_QUERY_PLANNER_VERSION:
        raise CurieContractError("scientific query plan planner is invalid")
    index = plan.get("reformulation_index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= MAX_REFORMULATION_INDEX:
        raise CurieContractError("scientific query plan reformulation_index is invalid")
    if set(plan).intersection({"papers", "evidence", "evidence_pack", "verification", "status"}):
        raise CurieContractError("scientific query plan must not contain evidence authority fields")
    concepts = plan.get("concepts")
    queries = plan.get("queries")
    if not isinstance(concepts, list) or not concepts or not isinstance(queries, list) or not MIN_QUERY_CANDIDATES <= len(queries) <= MAX_QUERY_CANDIDATES:
        raise CurieContractError("scientific query plan must contain bounded concepts and queries")
    seen: set[str] = set()
    for query in queries:
        if not isinstance(query, dict) or not str(query.get("intent") or "").strip() or not str(query.get("query") or "").strip() or not isinstance(query.get("concepts"), list) or not query["concepts"]:
            raise CurieContractError("scientific query plan query is invalid")
        if _CJK.search(query["query"]):
            raise CurieContractError("scientific query plan query must be normalized to retrieval language")
        key = query["query"].casefold()
        if key in seen:
            raise CurieContractError("scientific query plan queries must be distinct")
        seen.add(key)
    return plan


def build_scientific_query_plan(seed: dict, *, reformulation_index: int = 0) -> dict:
    if isinstance(reformulation_index, bool) or not isinstance(reformulation_index, int) or not 0 <= reformulation_index <= MAX_REFORMULATION_INDEX:
        raise CurieContractError(f"reformulation_index must be between 0 and {MAX_REFORMULATION_INDEX}")
    concepts = _concepts(seed)
    by_role = lambda role: [item["term"] for item in concepts if item["role"] == role]
    core = _unique(by_role("phenomenon") + by_role("organism") + by_role("system") + by_role("outcome") + by_role("mechanism"))
    if reformulation_index:
        templates = [
            ("broad_biological_context", by_role("organism") + by_role("system") + by_role("phenomenon")),
            ("mechanism_axis", by_role("system") + by_role("mechanism")[:3] + ["primary evidence"]),
            ("outcome_or_adaptation", by_role("outcome") + by_role("mechanism")[-3:] + ["adaptation"]),
        ]
    else:
        templates = [
            ("broad_biological_context", core[:5]),
            ("mechanism_axis", by_role("system") + by_role("phenomenon") + by_role("mechanism")[:4]),
            ("outcome_or_adaptation", by_role("phenomenon") + by_role("outcome") + by_role("mechanism")[-3:]),
        ]
    queries = []
    for intent, terms in templates:
        rendered = _bounded(terms or core)
        if rendered not in [item["query"] for item in queries]:
            queries.append({"intent": intent, "query": rendered, "concepts": _unique(terms or core)})
    for suffix in ("mechanistic evidence", "comparative evidence", "primary research"):
        if len(queries) >= MIN_QUERY_CANDIDATES:
            break
        rendered = _bounded(core + [suffix])
        if rendered not in [item["query"] for item in queries]:
            queries.append({"intent": "complementary_scientific_evidence", "query": rendered, "concepts": _unique(core + [suffix])})
    plan = {"schema_version": SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION, "planner": SCIENTIFIC_QUERY_PLANNER_VERSION, "language": "mixed" if _CJK.search(str(seed)) and _TOKEN.search(str(seed)) else ("zh" if _CJK.search(str(seed)) else "en"), "reformulation_index": reformulation_index, "concepts": concepts, "queries": queries[:MAX_QUERY_CANDIDATES]}
    return validate_scientific_query_plan(plan)


def reformulate_scientific_query_plan(seed: dict, previous_plan: dict) -> dict:
    previous = validate_scientific_query_plan(previous_plan)
    return build_scientific_query_plan(seed, reformulation_index=previous["reformulation_index"] + 1)
