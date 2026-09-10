"""Provider-neutral scientific query planning for L0.5 Curie.

The planner turns the canonical ResearchSeed into a small, auditable set of
retrieval candidates.  It may normalize language and decompose scientific
concepts, but it does not select papers, verify sources, assign evidence roles,
or freeze an EvidencePack.  Provider adapters remain responsible for syntax
and transport.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .contracts import CurieContractError


SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION = "L05ScientificQueryPlan/v1"
SCIENTIFIC_QUERY_PLANNER_VERSION = "scientific-query-planner/v1"
MIN_QUERY_CANDIDATES = 3
MAX_QUERY_CANDIDATES = 6
MAX_REFORMULATION_INDEX = 1
MAX_QUERY_CHARS = 240

_CJK = re.compile(r"[\u3400-\u9fff]")
_ENGLISH_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+]*(?:[-/][A-Za-z0-9+]+)*")
_STOPWORDS = frozenset({
    "a", "about", "an", "and", "are", "as", "at", "be", "being", "can",
    "could", "does", "for", "from", "how", "if", "in", "into", "is", "it",
    "may", "of", "on", "or", "our", "that", "the", "their", "these", "this",
    "to", "under", "was", "what", "whether", "which", "with", "would", "why",
    "current", "question", "hypothesis", "related", "study", "studies", "research",
})
_GENERIC_TERMS = frozenset({
    "activity", "approach", "axis", "biological", "characteristic", "concept",
    "condition", "effect", "factor", "feature", "finding", "function", "mechanism",
    "pathway", "process", "response", "role", "system", "target", "term", "use",
})


# This is a general scientific vocabulary, not a paper or project catalog.
# Longer phrases are matched before their component words so that the output
# retains domain meaning instead of becoming a word-for-word translation.
_CN_LEXICON = (
    ("高心率", "high heart rate", "phenomenon"),
    ("高频心脏活动", "high-frequency cardiac activity", "phenomenon"),
    ("长期维持", "sustained", "phenomenon"),
    ("病理性重塑", "pathological remodeling", "outcome"),
    ("功能损伤", "functional damage", "outcome"),
    ("能量与营养供给", "energy and nutrient supply", "mechanism"),
    ("营养供给", "nutrient supply", "mechanism"),
    ("肾上腺素能调控", "adrenergic regulation", "mechanism"),
    ("兴奋-收缩耦联", "excitation-contraction coupling", "mechanism"),
    ("兴奋收缩耦联", "excitation-contraction coupling", "mechanism"),
    ("心肌收缩轴", "myocardial contraction", "mechanism"),
    ("心肌收缩", "myocardial contraction", "mechanism"),
    ("Ca2+调控", "calcium regulation", "mechanism"),
    ("Ca2+处理", "calcium handling", "mechanism"),
    ("钙离子处理", "calcium handling", "mechanism"),
    ("心脏结构", "cardiac structure", "system"),
    ("力学性质", "cardiac mechanics", "system"),
    ("协同重塑", "coordinated remodeling", "outcome"),
    ("肌丝反应", "myofilament response", "mechanism"),
    ("心脏活动", "cardiac activity", "system"),
    ("心脏功能", "cardiac function", "system"),
    ("心肌", "cardiac", "system"),
    ("心脏", "cardiac", "system"),
    ("鼩鼱类", "shrews", "organism"),
    ("鼩鼱", "shrews", "organism"),
    ("高心率哺乳动物", "high-heart-rate mammals", "organism"),
    ("哺乳动物", "mammals", "organism"),
    ("鸟类", "birds", "organism"),
    ("鱼类", "fish", "organism"),
    ("昆虫", "insects", "organism"),
    ("植物", "plants", "organism"),
    ("小鼠", "mice", "organism"),
    ("大鼠", "rats", "organism"),
    ("人类", "humans", "organism"),
    ("斑马鱼", "zebrafish", "organism"),
    ("果蝇", "Drosophila", "organism"),
    ("线虫", "nematodes", "organism"),
    ("跨物种", "cross-species", "comparison"),
    ("物种比较", "species comparison", "comparison"),
    ("比较", "comparative", "comparison"),
    ("进化", "evolution", "comparison"),
    ("演化", "evolution", "comparison"),
    ("适应性", "adaptive", "outcome"),
    ("适应", "adaptation", "outcome"),
    ("稳态", "homeostasis", "outcome"),
    ("调控", "regulation", "mechanism"),
    ("调节", "regulation", "mechanism"),
    ("信号通路", "signaling pathway", "mechanism"),
    ("信号", "signaling", "mechanism"),
    ("基因表达", "gene expression", "mechanism"),
    ("表达", "expression", "mechanism"),
    ("转录", "transcription", "mechanism"),
    ("翻译", "translation", "mechanism"),
    ("磷酸化", "phosphorylation", "mechanism"),
    ("甲基化", "methylation", "mechanism"),
    ("突变", "mutation", "mechanism"),
    ("变异", "variant", "mechanism"),
    ("相互作用", "interaction", "mechanism"),
    ("网络", "network", "mechanism"),
    ("代谢", "metabolism", "mechanism"),
    ("能量", "energy metabolism", "mechanism"),
    ("营养", "nutrient availability", "mechanism"),
    ("转运", "transport", "mechanism"),
    ("通透性", "permeability", "mechanism"),
    ("离子", "ion handling", "mechanism"),
    ("钙", "calcium", "mechanism"),
    ("收缩", "contraction", "mechanism"),
    ("舒张", "relaxation", "mechanism"),
    ("传导", "conduction", "mechanism"),
    ("结构", "structure", "system"),
    ("力学", "mechanics", "system"),
    ("炎症", "inflammation", "mechanism"),
    ("氧化应激", "oxidative stress", "mechanism"),
    ("凋亡", "apoptosis", "mechanism"),
    ("增殖", "proliferation", "mechanism"),
    ("迁移", "migration", "mechanism"),
    ("侵袭", "invasion", "mechanism"),
    ("肿瘤", "tumor", "system"),
    ("癌", "cancer", "system"),
    ("神经", "neural", "system"),
    ("大脑", "brain", "system"),
    ("免疫", "immune", "system"),
    ("肺", "lung", "system"),
    ("肝", "liver", "system"),
    ("肾", "kidney", "system"),
    ("肌肉", "muscle", "system"),
    ("骨", "bone", "system"),
    ("血管", "vascular", "system"),
    ("细胞", "cell", "system"),
    ("组织", "tissue", "system"),
    ("微生物", "microbiome", "organism"),
    ("肠道", "gut", "system"),
    ("皮肤", "skin", "system"),
    ("胚胎", "embryonic", "system"),
    ("发育", "development", "outcome"),
    ("病理", "pathology", "outcome"),
    ("疾病", "disease", "outcome"),
    ("损伤", "injury", "outcome"),
    ("表型", "phenotype", "outcome"),
    ("存活", "survival", "outcome"),
    ("风险", "risk", "outcome"),
    ("进展", "progression", "outcome"),
    ("治疗", "treatment", "outcome"),
    ("耐药", "drug resistance", "outcome"),
    ("敏感性", "sensitivity", "outcome"),
    ("差异", "difference", "comparison"),
    ("对照", "control comparison", "comparison"),
    ("保守", "conserved", "comparison"),
)

_ENGLISH_PHRASES = (
    (r"\bhigh[- ]heart[- ]rate(?:s)?\b", "high heart rate", "phenomenon"),
    (r"\bhigh[- ]hr\b", "high heart rate", "phenomenon"),
    (r"\bheart[- ]rate(?:s)?\b", "heart rate", "phenomenon"),
    (r"\bpathological remodeling\b", "pathological remodeling", "outcome"),
    (r"\bfunctional (?:damage|injury|impairment)\b", "functional damage", "outcome"),
    (r"\benergy (?:and|/) nutrient supply\b", "energy and nutrient supply", "mechanism"),
    (r"\bnutrient supply\b", "nutrient supply", "mechanism"),
    (r"\badrenergic regulation\b", "adrenergic regulation", "mechanism"),
    (r"\bca2\+ (?:handling|regulation)\b", "calcium handling", "mechanism"),
    (r"\bcalcium (?:handling|regulation)\b", "calcium handling", "mechanism"),
    (r"\bexcitation[- ]contraction coupling\b", "excitation-contraction coupling", "mechanism"),
    (r"\bmyofilament response\b", "myofilament response", "mechanism"),
    (r"\bcardiac (?:structure|mechanics|physiology|function)\b", "cardiac", "system"),
    (r"\bhigh[- ]frequency cardiac activity\b", "high-frequency cardiac activity", "phenomenon"),
    (r"\bcross[- ]species\b", "cross-species", "comparison"),
    (r"\bspecies comparison\b", "species comparison", "comparison"),
)

_ENGLISH_ROLE_TERMS = {
    "adrenergic": ("adrenergic regulation", "mechanism"),
    "adaptation": ("adaptation", "outcome"),
    "adaptive": ("adaptive", "outcome"),
    "calcium": ("calcium", "mechanism"),
    "ca2+": ("calcium", "mechanism"),
    "cardiac": ("cardiac", "system"),
    "contraction": ("contraction", "mechanism"),
    "coupling": ("coupling", "mechanism"),
    "development": ("development", "outcome"),
    "energy": ("energy metabolism", "mechanism"),
    "expression": ("expression", "mechanism"),
    "heart": ("heart", "system"),
    "high-heart-rate": ("high heart rate", "phenomenon"),
    "high-hr": ("high heart rate", "phenomenon"),
    "homeostasis": ("homeostasis", "outcome"),
    "immune": ("immune", "system"),
    "injury": ("injury", "outcome"),
    "mechanics": ("mechanics", "system"),
    "metabolism": ("metabolism", "mechanism"),
    "molecular": ("molecular", "mechanism"),
    "myofilament": ("myofilament", "mechanism"),
    "nutrient": ("nutrient availability", "mechanism"),
    "pathological": ("pathological", "outcome"),
    "physiology": ("physiology", "system"),
    "remodeling": ("remodeling", "outcome"),
    "regulation": ("regulation", "mechanism"),
    "response": ("response", "mechanism"),
    "signaling": ("signaling", "mechanism"),
    "structure": ("structure", "system"),
    "survival": ("survival", "outcome"),
    "supply": ("nutrient supply", "mechanism"),
    "tissue": ("tissue", "system"),
}
_KNOWN_ORGANISMS = frozenset({
    "bat", "bats", "bird", "birds", "fish", "fishes", "human", "humans",
    "mammal", "mammals", "mouse", "mice", "rat", "rats", "shrew", "shrews",
    "zebrafish", "drosophila", "nematode", "nematodes", "plant", "plants",
    "yeast", "bacteria", "virus", "viruses",
})


def _normalise_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurieContractError(f"{name} must be a non-empty string")
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", " ", value).strip()


def _language(text: str) -> str:
    has_cjk = bool(_CJK.search(text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    return "en"


def _compact(text: str) -> str:
    chars = []
    for char in text.casefold():
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if category.startswith("P") and char != "+":
            continue
        chars.append(char)
    return "".join(chars)


def _add_concept(concepts: list[dict], seen: dict[str, dict], term: object,
                 role: str, *, source: str) -> None:
    term = re.sub(r"\s+", " ", str(term or "")).strip().lower()
    if not term or term in _STOPWORDS or term in _GENERIC_TERMS:
        return
    if term in seen:
        return
    concept = {"term": term, "role": role, "source": source}
    concepts.append(concept)
    seen[term] = concept


def _extract_seed_concepts(question: str, hypothesis: str, seed: dict) -> list[dict]:
    concepts: list[dict] = []
    seen: dict[str, dict] = {}
    text = f"{question} {hypothesis}"
    compact = _compact(text)
    occupied: list[tuple[int, int]] = []
    for phrase, term, role in sorted(
        _CN_LEXICON, key=lambda item: len(_compact(item[0])), reverse=True
    ):
        needle = _compact(phrase)
        if not needle:
            continue
        start = compact.find(needle)
        while start >= 0:
            end = start + len(needle)
            if not any(start < right and end > left for left, right in occupied):
                occupied.append((start, end))
                _add_concept(concepts, seen, term, role, source=f"lexicon:{phrase}")
                break
            start = compact.find(needle, start + 1)

    english = text.casefold().replace("–", "-").replace("—", "-")
    for pattern, term, role in _ENGLISH_PHRASES:
        if re.search(pattern, english, flags=re.IGNORECASE):
            _add_concept(concepts, seen, term, role, source="english_phrase")

    for token in _ENGLISH_TOKEN.findall(text):
        normalized = token.casefold().replace("_", "")
        if normalized in _STOPWORDS or normalized in _GENERIC_TERMS:
            continue
        if normalized in _ENGLISH_ROLE_TERMS:
            term, role = _ENGLISH_ROLE_TERMS[normalized]
            _add_concept(concepts, seen, term, role, source="english_term")
        elif normalized in _KNOWN_ORGANISMS:
            _add_concept(concepts, seen, normalized, "organism", source="english_taxon")
        elif len(normalized) >= 4:
            role = "mechanism" if normalized.endswith(
                ("ing", "tion", "ance", "ence", "ism", "ity")
            ) else "phenomenon"
            _add_concept(concepts, seen, normalized, role, source="english_term")

    structured_roles = {
        "organisms": "organism",
        "taxa": "organism",
        "biological_system": "system",
        "mechanistic_concepts": "mechanism",
        "comparison": "comparison",
    }
    for field, role in structured_roles.items():
        value = seed.get(field)
        values: Iterable[object]
        if isinstance(value, (list, tuple, set)):
            values = value
        elif value not in (None, ""):
            values = (value,)
        else:
            values = ()
        for item in values:
            item_text = str(item or "").strip()
            if item_text:
                _add_concept(concepts, seen, item_text, role, source=f"seed:{field}")

    if not concepts:
        raise CurieContractError(
            "scientific query planner could not derive searchable concepts from the ResearchSeed"
        )
    return concepts


def _terms(concepts: list[dict], *roles: str) -> list[str]:
    allowed = set(roles)
    return [item["term"] for item in concepts if item["role"] in allowed]


def _unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = re.sub(r"\s+", " ", str(value or "")).strip().lower()
        if term and term not in seen:
            seen.add(term)
            result.append(term)
    return result


def _bounded_query(values: Iterable[object]) -> str:
    terms = _unique(values)
    while terms and len(" ".join(terms)) > MAX_QUERY_CHARS:
        terms.pop()
    if not terms:
        raise CurieContractError("scientific query planner produced an empty query")
    return " ".join(terms)


def _query_items(concepts: list[dict], reformulation_index: int) -> list[dict]:
    organisms = _terms(concepts, "organism")
    systems = _terms(concepts, "system")
    phenomena = _terms(concepts, "phenomenon")
    mechanisms = _terms(concepts, "mechanism")
    outcomes = _terms(concepts, "outcome")
    comparisons = _terms(concepts, "comparison")
    core = _unique(phenomena + organisms + systems + outcomes + comparisons)
    if not core:
        core = _unique(mechanisms)
    anchor = _unique(phenomena[:1] + organisms[:1] + systems[:2] + outcomes[:1])
    if not anchor:
        anchor = core[:4]

    if reformulation_index == 0:
        templates = (
            ("broad_biological_context", anchor + mechanisms[:2]),
            ("mechanism_axis", _unique(anchor[:3] + mechanisms[:4])),
            ("mechanism_axis", _unique(
                systems[:1] + phenomena[:1] + mechanisms[5:8] + mechanisms[:1]
            )),
            ("comparative_or_organism_evidence", _unique(organisms + comparisons + phenomena[:3] + systems[:1])),
            ("outcome_or_adaptation", _unique(phenomena[-2:] + outcomes[:2] + systems[:1] + mechanisms[-4:])),
        )
    else:
        # A reformulation changes search strategy while retaining the same
        # extracted concepts.  It intentionally removes dense conjunctions
        # and searches complementary axes instead of changing the question.
        templates = (
            ("broad_biological_context", _unique(organisms + systems + phenomena)),
            ("mechanism_axis", _unique(systems[:2] + mechanisms[:3] + ["primary evidence"])),
            ("mechanism_axis", _unique(phenomena[:2] + mechanisms[3:7] + ["mechanistic evidence"])),
            ("comparative_or_organism_evidence", _unique(organisms + comparisons + ["comparative evidence"])),
            ("outcome_or_adaptation", _unique(outcomes + phenomena + mechanisms[-3:] + ["adaptation"])),
        )

    items: list[dict] = []
    seen_queries: set[str] = set()
    for intent, values in templates:
        query = _bounded_query(values or core)
        if query in seen_queries:
            continue
        seen_queries.add(query)
        items.append({
            "intent": intent,
            "query": query,
            "concepts": _unique(values or core),
        })

    fallback_suffixes = ("mechanistic evidence", "comparative evidence", "primary research")
    for suffix in fallback_suffixes:
        if len(items) >= MIN_QUERY_CANDIDATES:
            break
        query = _bounded_query(core + [suffix])
        if query in seen_queries:
            continue
        seen_queries.add(query)
        items.append({
            "intent": "complementary_scientific_evidence",
            "query": query,
            "concepts": _unique(core + [suffix]),
        })
    if len(items) < MIN_QUERY_CANDIDATES:
        raise CurieContractError(
            f"scientific query planner produced fewer than {MIN_QUERY_CANDIDATES} distinct queries"
        )
    return items[:MAX_QUERY_CANDIDATES]


def validate_scientific_query_plan(plan: dict) -> dict:
    """Validate the cognitive planner output without granting evidence authority."""
    if not isinstance(plan, dict):
        raise CurieContractError("scientific query plan must be an object")
    if plan.get("schema_version") != SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION:
        raise CurieContractError("scientific query plan schema_version is invalid")
    if plan.get("planner") != SCIENTIFIC_QUERY_PLANNER_VERSION:
        raise CurieContractError("scientific query plan planner is invalid")
    index = plan.get("reformulation_index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= MAX_REFORMULATION_INDEX:
        raise CurieContractError("scientific query plan reformulation_index is invalid")
    concepts = plan.get("concepts")
    if not isinstance(concepts, list) or not concepts:
        raise CurieContractError("scientific query plan concepts must be a non-empty list")
    for concept in concepts:
        if not isinstance(concept, dict) or not str(concept.get("term") or "").strip():
            raise CurieContractError("scientific query plan concepts must contain terms")
        if concept.get("role") not in {
            "organism", "system", "phenomenon", "mechanism", "outcome", "comparison"
        }:
            raise CurieContractError("scientific query plan concept role is invalid")
    queries = plan.get("queries")
    if not isinstance(queries, list) or not MIN_QUERY_CANDIDATES <= len(queries) <= MAX_QUERY_CANDIDATES:
        raise CurieContractError(
            f"scientific query plan queries must contain {MIN_QUERY_CANDIDATES}-{MAX_QUERY_CANDIDATES} items"
        )
    seen: set[str] = set()
    for item in queries:
        if not isinstance(item, dict):
            raise CurieContractError("scientific query plan query must be an object")
        intent = str(item.get("intent") or "").strip()
        query = str(item.get("query") or "").strip()
        if not intent or not query:
            raise CurieContractError("scientific query plan queries require intent and query")
        if _CJK.search(query):
            raise CurieContractError("scientific query plan query must be normalized to retrieval language")
        if query.casefold() in seen:
            raise CurieContractError("scientific query plan queries must be distinct")
        seen.add(query.casefold())
        query_concepts = item.get("concepts")
        if not isinstance(query_concepts, list) or not query_concepts:
            raise CurieContractError("scientific query plan query concepts must be non-empty")
    # A planner payload is deliberately not allowed to smuggle in any object
    # that downstream code could mistake for formal evidence authority.
    forbidden = {"papers", "evidence", "evidence_pack", "verification", "role", "status"}
    if forbidden.intersection(plan):
        raise CurieContractError("scientific query plan must not contain evidence authority fields")
    return {
        "schema_version": plan["schema_version"],
        "planner": plan["planner"],
        "language": str(plan.get("language") or "en"),
        "reformulation_index": index,
        "concepts": [dict(item) for item in concepts],
        "queries": [dict(item) for item in queries],
    }


def build_scientific_query_plan(seed: dict, *, reformulation_index: int = 0) -> dict:
    """Derive a bounded provider-neutral plan from one canonical semantic seed."""
    if not isinstance(seed, dict):
        raise CurieContractError("ResearchSeed must be an object")
    if isinstance(reformulation_index, bool) or not isinstance(reformulation_index, int):
        raise CurieContractError("reformulation_index must be an integer")
    if not 0 <= reformulation_index <= MAX_REFORMULATION_INDEX:
        raise CurieContractError(
            f"reformulation_index must be between 0 and {MAX_REFORMULATION_INDEX}"
        )
    question = _normalise_text(seed.get("scientific_question"), "ResearchSeed scientific_question")
    hypothesis = _normalise_text(seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed")
    concepts = _extract_seed_concepts(question, hypothesis, seed)
    plan = {
        "schema_version": SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION,
        "planner": SCIENTIFIC_QUERY_PLANNER_VERSION,
        "language": _language(f"{question} {hypothesis}"),
        "reformulation_index": reformulation_index,
        "concepts": concepts,
        "queries": _query_items(concepts, reformulation_index),
    }
    return validate_scientific_query_plan(plan)


def reformulate_scientific_query_plan(seed: dict, previous_plan: dict) -> dict:
    """Build the one permitted alternative strategy from the same seed concepts."""
    previous = validate_scientific_query_plan(previous_plan)
    next_index = int(previous["reformulation_index"]) + 1
    if next_index > MAX_REFORMULATION_INDEX:
        raise CurieContractError("scientific query planner reformulation bound exhausted")
    return build_scientific_query_plan(seed, reformulation_index=next_index)


__all__ = [
    "MAX_QUERY_CANDIDATES",
    "MAX_REFORMULATION_INDEX",
    "MIN_QUERY_CANDIDATES",
    "SCIENTIFIC_QUERY_PLAN_SCHEMA_VERSION",
    "SCIENTIFIC_QUERY_PLANNER_VERSION",
    "build_scientific_query_plan",
    "reformulate_scientific_query_plan",
    "validate_scientific_query_plan",
]
