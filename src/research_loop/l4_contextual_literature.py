"""Contextual L4A query planning over the canonical L0.5 discovery layer.

The first L4A provider invocation is the existing offline method-inventory
step.  Only methods that remain unresolved after frozen L0.5 matching and the
method registry get a second invocation.  That invocation is deliberately a
query planner: it returns method IDs and structured query terms, never paper
records.

The resulting structured query terms are deterministically rendered into
explicit queries and handed to the canonical L0.5 multisource
planner and discovery runner.  That layer remains the sole owner of provider
transports, canonical paper identity, cross-provider deduplication, and raw
provider receipts.  L4A only selects bounded candidate support and projects
the already-canonical records into its existing asset contract for the L4B
handoff; it does not create another paper identity or evidence verifier.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from research_loop import l4a_specter2
from research_loop import research_seed
from research_loop.l05_curie.contracts import (
    MAX_ACQUISITION_ROUNDS,
    validate_record_query_provenance,
)
from research_loop.l05_curie import europepmc, multisource, selector


CONTEXTUAL_QUERY_PLAN_SCHEMA_VERSION = "L4AContextualQueryPlan/v2"
METHOD_SUPPORT_SCHEMA_VERSION = "L4AMethodSupportAdjudication/v2"
METHOD_SUPPORT_CLASSIFICATIONS = (
    "DIRECT_METHOD_SUPPORT",
    "RELATED_BUT_NOT_METHOD_SUPPORT",
    "IRRELEVANT",
    "INSUFFICIENT_METADATA",
)
DEFAULT_TOP_K_PER_METHOD = 5
MAX_METHOD_TERMS = 8
MAX_CONTEXT_TERMS = 2
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _contextual_query_plan_schema() -> dict:
    query = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query_id": {"type": "string", "minLength": 1},
            "purpose": {"type": "string", "minLength": 1},
            "status": {"type": "string", "const": "planned"},
            "receipt": {"type": "string", "minLength": 1},
            "method_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "method_terms": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_METHOD_TERMS,
                "items": {"type": "string", "minLength": 1},
            },
            "context_terms": {
                "type": "array",
                "maxItems": MAX_CONTEXT_TERMS,
                "items": {"type": "string", "minLength": 1},
            },
        },
        # Codex structured outputs require every declared property to appear
        # in required, including these audit annotations.
        "required": [
            "query_id",
            "purpose",
            "status",
            "receipt",
            "method_ids",
            "method_terms",
            "context_terms",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "string",
                "const": CONTEXTUAL_QUERY_PLAN_SCHEMA_VERSION,
            },
            "queries": {"type": "array", "minItems": 1, "items": query},
        },
        "required": ["schema_version", "queries"],
    }


def _contextual_prompt(
    question: str, claim: str, methods: list[dict], backend: str
) -> str:
    """Ask the provider for query planning only, with no retrieval authority."""
    del backend  # retained in the private helper signature for compatibility
    compact = [
        {
            "method_id": str(method.get("method_id") or ""),
            "name": str(method.get("name") or ""),
            "purpose": str(method.get("purpose") or ""),
            "inventory_reason": str(method.get("inventory_reason") or ""),
        }
        for method in methods
    ]
    return f"""RLR stage: L4A Contextual Literature Query Planning
Scientific question: {question}
Selected hypothesis/claim: {claim}
All contextual literature search queries MUST be written in English using standard scientific terminology.
Unresolved candidate analysis actions:
{json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}

Produce a small, reproducible query plan for contextual literature discovery.
This is query planning only. Do not search literature, browse the web, call a
database, invoke a literature-search skill, read the project filesystem, or
retrieve any paper metadata. The controller will execute every query through
the canonical multisource discovery layer.

Use a METHOD-FIRST query contract. Prefer one unresolved method per query; do
not group different methods into one query. Each query must contain exactly
one method_id, a method_terms array, and a context_terms array. Do not return
a query field: the controller deterministically renders the final query from
the two term arrays. The method_terms array must contain the method name or
canonical label plus useful English synonyms, abbreviations, common
software/tool names, statistical or computational family terms, and
implementation or benchmark terms when they exist. Keep method_terms focused
on the method, not the scientific result.

The context_terms array may contain at most two short English phrases and may
only describe data modality or study design, such as RNA-seq,
cross-species, comparative study, bulk, single-cell, or long-read. Do not copy the scientific question, claim, hypothesis, phenotype, organism,
mechanism axis, pathway, gene, or disease into context_terms. Do not let
scientific context dominate the query. The controller will render the final
query as the exact whitespace-joined sequence of method_terms followed by
context_terms, with no extra words before, between, or after those terms. This
preserves method-first ordering for the canonical discovery layer.

Return only contextual queries. Each query must contain a unique query_id, the
concise purpose, status=planned, a short planning receipt, one exact unresolved
method_id, method_terms, and context_terms from the supplied list. Do not
return a final query string. Do not require a paper title to equal a method
label.

Do not return assets, papers, paper titles, citations, DOI, PMID, PMCID, stable
URLs, source databases, source metadata, abstracts, full-text extracts,
paper_id values, or any identity/hash/deduplication result. Do not invent a
method ID. If a method cannot be expressed responsibly, omit that method from
the query plan so it remains unresolved.

Return JSON only, conforming exactly to the supplied L4A contextual query-plan
schema. Do not include prose, Markdown, code fences, commentary, or text
outside the JSON object.
"""


def _contextual_command(command: list[str], spec, work_dir: Path) -> list[str]:
    """Run the planner in the same disposable, no-web boundary as L4A cognition."""
    result = list(command)
    if str(getattr(spec, "backend", "")) == "codex":
        result.extend([
            "--sandbox", "read-only",
            "-c", 'web_search="disabled"',
            "-C", str(Path(work_dir).resolve()),
            "--skip-git-repo-check",
        ])
    return result


def _validate_contextual_payload(
    l4p, dr, payload: dict, unresolved_ids: list[str]
) -> dict:
    """Validate wire terms and add the controller-owned query to a copy."""
    if not isinstance(payload, dict):
        raise dr.DeepResearchError(
            "L4A contextual literature query plan must be a JSON object"
        )
    if "assets" in payload:
        raise dr.DeepResearchError(
            "L4A contextual literature query planner must not return assets"
        )

    errors = sorted(
        Draft202012Validator(_contextual_query_plan_schema()).iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "payload"
        raise dr.DeepResearchError(
            f"L4A contextual literature query plan {path}: {error.message}"
        )

    allowed = {str(value).strip() for value in unresolved_ids}
    seen_query_ids: set[str] = set()
    for query in payload["queries"]:
        query_id = str(query["query_id"]).strip()
        if query_id in seen_query_ids:
            raise dr.DeepResearchError(
                f"L4A contextual literature query planner returned duplicate query_id {query_id}"
            )
        seen_query_ids.add(query_id)
        method_ids = [str(value).strip() for value in query["method_ids"]]
        if len(method_ids) != len(set(method_ids)):
            raise dr.DeepResearchError(
                f"L4A contextual literature query {query_id} repeats a method_id"
            )
        unknown = [value for value in method_ids if value not in allowed]
        if unknown:
            raise dr.DeepResearchError(
                "L4A contextual literature query references a method outside the "
                f"unresolved inventory: {unknown[0]}"
            )
        method_terms = [str(value).strip() for value in query["method_terms"]]
        context_terms = [str(value).strip() for value in query["context_terms"]]
        rendered_query = _method_first_query(method_terms, context_terms)
        if CJK_RE.search(rendered_query) or not re.search(r"[A-Za-z]", rendered_query):
            raise dr.DeepResearchError(
                f"L4A contextual literature query {query_id} must be an English "
                "scientific query"
            )
        method_word_count = len(_query_words(" ".join(method_terms)))
        context_word_count = len(_query_words(" ".join(context_terms)))
        if not method_word_count or context_word_count > method_word_count:
            raise dr.DeepResearchError(
                f"L4A contextual literature query {query_id} has context_terms "
                "that outweigh method_terms"
            )
    normalized = copy.deepcopy(payload)
    for query in normalized["queries"]:
        # The final query is an internal controller field, never provider input.
        query["query"] = _method_first_query(
            query["method_terms"], query["context_terms"]
        )
        query.setdefault(
            "purpose", "Contextual literature query for an unresolved analysis action."
        )
        query.setdefault("status", "planned")
        query.setdefault("receipt", "contextual query planner")
    return normalized


def _query_words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", str(value or ""))


def _method_first_query(method_terms: list[str], context_terms: list[str]) -> str:
    """Render the sole canonical query from validated structured terms."""
    terms = [
        " ".join(str(value).split())
        for value in [*method_terms, *context_terms]
    ]
    return " ".join(
        term
        for term in terms
        if term
    )


def _transport_timeout(spec) -> int:
    value = getattr(spec, "timeout", None)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return 20
    return value


def _contextual_transports(
    project_dir: str | Path,
    candidate_id: str,
    run_id: str,
    timeout: int,
) -> dict[str, object]:
    common = {
        "project_dir": project_dir,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "timeout": timeout,
    }
    return {
        "europe-pmc": europepmc.EuropePmcTransport(**common),
        "pubmed": multisource.PubMedTransport(**common),
        "openalex": multisource.OpenAlexTransport(**common),
        "crossref": multisource.CrossrefTransport(**common),
        "semantic-scholar": multisource.SemanticScholarTransport(**common),
    }


def _round_index(round_id: str) -> int:
    match = re.search(r"\d+", str(round_id or ""))
    value = int(match.group(0)) if match else 1
    return value if 1 <= value <= MAX_ACQUISITION_ROUNDS else 1


def _english_contextual_eligibility(record: dict) -> tuple[bool, str]:
    """Apply the L4A-only English contextual policy without mutating Curie data."""

    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    language = str(metadata.get("language") or "").strip().casefold()
    if language:
        english_values = {"en", "eng", "english"}
        if language not in english_values and not language.startswith("en-"):
            return False, "NON_ENGLISH_CONTEXTUAL_SOURCE"
        return True, "ENGLISH_CONTEXTUAL_SOURCE"

    title = str(record.get("title") or "")
    abstract = str(metadata.get("abstract") or "")
    if CJK_RE.search(title) or CJK_RE.search(abstract):
        return False, "NON_ENGLISH_CONTEXTUAL_SOURCE"
    return True, "ENGLISH_CONTEXTUAL_SOURCE"


def _contextual_candidate_eligibility(record: dict) -> tuple[bool, str]:
    english_allowed, english_reason = _english_contextual_eligibility(record)
    if not english_allowed:
        return False, english_reason
    return _l4b_retrievable(record)


def _method_query(method: dict, planner_queries: list[dict]) -> str:
    values = [
        str(method.get("name") or "").strip(),
        str(method.get("purpose") or "").strip(),
        str(method.get("inventory_reason") or "").strip(),
    ]
    method_id = str(method.get("method_id") or "").strip()
    values.extend(
        str(query.get("query") or "").strip()
        for query in planner_queries
        if method_id in [str(value).strip() for value in query.get("method_ids") or []]
    )
    return ". ".join(value for value in values if value)


def _record_query_ids(record: dict) -> list[str]:
    provenance = record.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    values = provenance.get("originating_query_ids") or []
    return [str(value).strip() for value in values if str(value).strip()]


def _safe_method_run_id(method_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(method_id or "")).strip("_.") or "method"


def _top_k_per_method(spec_or_value: object) -> int:
    value = (
        getattr(spec_or_value, "top_k_per_method")
        if hasattr(spec_or_value, "top_k_per_method")
        else spec_or_value
    )
    if value is None:
        return DEFAULT_TOP_K_PER_METHOD
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("top_k_per_method must be a positive integer")
    return value


def _selection_score(semantic_score: float) -> float:
    # Selector contracts use [0, 1], while cosine similarity is [-1, 1].
    # This is a monotonic representation for deterministic selector ordering,
    # not a support threshold and never promotes a paper to method support.
    return min(1.0, max(0.0, (float(semantic_score) + 1.0) / 2.0))


def _ranker_scores(
    method_id: str,
    candidate_records: list[dict],
    method_query: str,
    *,
    seed: dict,
    ranker: object | None,
) -> tuple[dict[str, dict], list[dict]]:
    ranked = l4a_specter2.rank_method_papers(
        method_query, candidate_records, ranker=ranker
    )
    candidate_ids = {
        str(record.get("paper_id") or "").strip() for record in candidate_records
    }
    if {str(item["paper_id"]) for item in ranked} != candidate_ids:
        missing = sorted(candidate_ids - {str(item["paper_id"]) for item in ranked})
        extra = sorted({str(item["paper_id"]) for item in ranked} - candidate_ids)
        raise ValueError(
            f"SPECTER2 ranker did not return the complete {method_id} candidate set; "
            f"missing={missing[:1]} extra={extra[:1]}"
        )
    by_paper = {str(item["paper_id"]): item for item in ranked}

    def score(record: dict, _seed: dict) -> dict:
        item = by_paper[str(record.get("paper_id") or "")]
        relevance = _selection_score(item["semantic_score"])
        return {
            "relevance": relevance,
            "directness": 0.0,
            "methodological_value": relevance,
            "contradiction_value": 0.0,
            "evidence_diversity": 0.0,
            "reason": (
                "SPECTER2 semantic pre-ranking for one L4A method; final method "
                "support requires metadata-only cognitive adjudication."
            ),
        }

    del seed  # scorer receives it through selector for the shared contract
    return by_paper, score


def _select_contextual_candidates(
    records: list[dict],
    methods: list[dict],
    planner_queries: list[dict],
    query_plan: dict,
    *,
    seed: dict,
    ranker: object | None = None,
    top_k_per_method: int = DEFAULT_TOP_K_PER_METHOD,
    project_dir: str | Path | None = None,
    candidate_id: str | None = None,
    discovery_run_id: str | None = None,
) -> tuple[dict, list[dict]]:
    """Run the existing selector once per method over SPECTER2-ranked pairs."""

    if not isinstance(records, list) or not isinstance(methods, list):
        raise ValueError("contextual records and methods must be lists")
    if len(query_plan.get("queries") or []) != len(planner_queries):
        raise ValueError("contextual planner and canonical QueryPlan lengths differ")
    top_k = _top_k_per_method(top_k_per_method)
    plan_queries = list(query_plan.get("queries") or [])
    full_query_ids = {
        str(item.get("query_id") or "").strip()
        for item in plan_queries
        if isinstance(item, dict) and str(item.get("query_id") or "").strip()
    }
    for record in records:
        # Validate against the complete canonical QueryPlan before any
        # method-specific provenance intersection can filter a record out.
        validate_record_query_provenance(
            record, authorized_query_ids=full_query_ids
        )
    if ranker is None and any(
        _contextual_candidate_eligibility(record)[0] for record in records
    ):
        # Load once for the whole contextual pass; the adapter itself batches
        # each method's paper set and remains process-scoped.
        ranker = l4a_specter2.get_specter2_ranker()
    method_selections: list[dict] = []
    pair_rows: list[dict] = []
    all_decisions: list[dict] = []
    selected_records: list[dict] = []
    selected_ids: set[str] = set()
    record_by_id = {
        str(record.get("paper_id") or "").strip(): record for record in records
    }

    for method in methods:
        method_id = str(method.get("method_id") or "").strip()
        if not method_id:
            raise ValueError("contextual method has no method_id")
        method_plan_queries = [
            plan_query
            for plan_query, planner_query in zip(plan_queries, planner_queries)
            if method_id in {
                str(value).strip() for value in planner_query.get("method_ids") or []
            }
        ]
        method_query_ids = {
            str(item.get("query_id") or "").strip()
            for item in method_plan_queries
            if str(item.get("query_id") or "").strip()
        }
        method_records = [
            record for record in records
            if set(_record_query_ids(record)) & method_query_ids
        ]
        if not method_query_ids:
            method_selector = {
                "schema_version": "L05SelectorRun/v1",
                "decisions": [],
                "included_paper_ids": [],
            }
            method_selections.append({
                "method_id": method_id,
                "query_ids": [],
                "query": _method_query(method, planner_queries),
                "selector": method_selector,
                "decisions": [],
            })
            continue
        eligible_records = [
            record for record in method_records
            if _contextual_candidate_eligibility(record)[0]
        ]
        semantic_by_paper, scorer = _ranker_scores(
            method_id,
            eligible_records,
            _method_query(method, planner_queries),
            seed=seed,
            ranker=ranker,
        ) if eligible_records else ({}, lambda _record, _seed: {
            "relevance": 0.0,
            "directness": 0.0,
            "methodological_value": 0.0,
            "contradiction_value": 0.0,
            "evidence_diversity": 0.0,
            "reason": "No eligible canonical contextual records.",
        })

        selector_run_id = (
            f"{discovery_run_id}_{_safe_method_run_id(method_id)}"
            if discovery_run_id else None
        )
        method_selector = selector.select_candidates_strict(
            method_records,
            seed=seed,
            scorer=scorer,
            eligibility=_contextual_candidate_eligibility,
            max_papers=top_k,
            project_dir=project_dir,
            candidate_id=candidate_id,
            run_id=selector_run_id,
            query_ids=full_query_ids,
        )
        method_rows = []
        for decision in method_selector.get("decisions") or []:
            row = copy.deepcopy(decision)
            paper_id = str(row.get("paper_id") or "")
            row["method_id"] = method_id
            semantic = semantic_by_paper.get(paper_id)
            if semantic is not None:
                row["semantic_score"] = float(semantic["semantic_score"])
                row["semantic_rank"] = int(semantic["semantic_rank"])
            method_rows.append(row)
            all_decisions.append(row)
        for paper_id in method_selector.get("included_paper_ids") or []:
            paper_id = str(paper_id)
            semantic = semantic_by_paper.get(paper_id)
            if semantic is None:
                raise ValueError(
                    f"selector included paper without SPECTER2 score: {paper_id}"
                )
            pair_rows.append({
                "paper_id": paper_id,
                "method_id": method_id,
                "semantic_score": float(semantic["semantic_score"]),
                "semantic_rank": int(semantic["semantic_rank"]),
                "selector_decision": "INCLUDE",
            })
            if paper_id not in selected_ids:
                selected_ids.add(paper_id)
                selected_records.append(record_by_id[paper_id])
        method_selections.append({
            "method_id": method_id,
            "query_ids": sorted(method_query_ids),
            "query": _method_query(method, planner_queries),
            "selector": method_selector,
            "decisions": method_rows,
        })

    result = {
        # Preserve the existing selector run marker for receipt consumers;
        # per-method selector artifacts remain owned by l05_curie.selector.
        "schema_version": "L05SelectorRun/v1",
        "top_k_per_method": top_k,
        "method_selections": method_selections,
        "decisions": all_decisions,
        "pairs": pair_rows,
        "included_paper_ids": [str(item["paper_id"]) for item in pair_rows
                               if str(item["paper_id"]) in selected_ids],
        "semantic_ranker": (
            l4a_specter2.ranker_receipt(ranker)
            if ranker is not None
            else {
                "implementation": "research_loop.l4a_specter2",
                "status": "not_loaded_no_eligible_records",
            }
        ),
    }
    # The list expression above can repeat a paper selected for multiple
    # methods; retain first-seen paper order for the existing asset projection.
    result["included_paper_ids"] = list(dict.fromkeys(result["included_paper_ids"]))
    return result, selected_records


def _method_support_schema() -> dict:
    decision = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "classification": {
                "type": "string",
                "enum": list(METHOD_SUPPORT_CLASSIFICATIONS),
            },
            "rationale": {"type": "string", "minLength": 1},
        },
        "required": ["classification", "rationale"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "string", "const": METHOD_SUPPORT_SCHEMA_VERSION
            },
            "decisions": {"type": "array", "items": decision},
        },
        "required": ["schema_version", "decisions"],
    }


def _validate_method_support_payload(
    dr, payload: dict, expected_count: int
) -> dict:
    if not isinstance(payload, dict):
        raise dr.DeepResearchError(
            "L4A method-support adjudication must be a JSON object"
        )
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count < 0
    ):
        raise dr.DeepResearchError(
            "L4A method-support adjudication expected decision count must be a "
            "non-negative integer"
        )
    errors = sorted(
        Draft202012Validator(_method_support_schema()).iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "payload"
        raise dr.DeepResearchError(
            f"L4A method-support adjudication {path}: {error.message}"
        )
    actual_count = len(payload["decisions"])
    if actual_count != expected_count:
        raise dr.DeepResearchError(
            "L4A method-support adjudication decision count mismatch; "
            f"expected={expected_count} actual={actual_count}"
        )
    return copy.deepcopy(payload)


def _method_support_prompt(payload: dict, backend: str) -> str:
    del backend
    return f"""RLR stage: L4A metadata-only method-support adjudication

You are adjudicating only one supplied L4A method against its ordered canonical
paper metadata candidates. Do not web search, browse, call a database, read the
filesystem, retrieve full text, or invent bibliographic identity.

Topic relevance is NOT method support.

A paper must NOT be labeled DIRECT_METHOD_SUPPORT merely because it studies the
same biological process, pathway, phenotype, organism, disease, or gene family.
DIRECT_METHOD_SUPPORT requires title/abstract evidence that the target
analytical, experimental, statistical, or computational method itself is used,
developed, evaluated, benchmarked, or explicitly explained. Ask whether the
exact paper's Methods section could reasonably be expected to contain
implementation information for THIS exact method. Do not infer method use from
topic overlap. When title/abstract metadata is insufficient, return
INSUFFICIENT_METADATA.

Candidates are supplied in a fixed order. Return exactly one decision for every
candidate, in exactly the same order. Use only these classifications:
DIRECT_METHOD_SUPPORT,
RELATED_BUT_NOT_METHOD_SUPPORT, IRRELEVANT, INSUFFICIENT_METADATA. Each
decision may contain only classification and a short rationale. Do not return
candidate number, paper_id, method_id, DOI, PMID, PMCID, title, URL, paper,
identity, score, confidence, or any other field. The controller owns all
candidate and method identity values and will restore them by ordered position.

Supplied one-method L4A metadata:
{json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}

Return JSON only, conforming exactly to the supplied method-support schema.
Do not include prose, Markdown, code fences, commentary, or text outside JSON.
"""


def _method_support_input(
    method: dict, candidate_records: list[dict]
) -> dict:
    if not isinstance(method, dict):
        raise ValueError("method-support method must be an object")
    if not isinstance(candidate_records, list):
        raise ValueError("method-support candidates must be a list")
    candidates = []
    for index, record in enumerate(candidate_records, 1):
        if not isinstance(record, dict):
            raise ValueError("method-support candidate must be an object")
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        candidates.append({
            "candidate_number": index,
            "title": str(record.get("title") or ""),
            "abstract": str(metadata.get("abstract") or ""),
            "journal": str(metadata.get("journal") or ""),
            "year": str(metadata.get("year") or ""),
        })
    return {
        # Method and paper identity stay in the deterministic caller. The
        # provider receives only the scientific method description and ordered
        # metadata, so it has no identity field to rewrite.
        "method": {
            "name": str(method.get("name") or ""),
            "purpose": str(method.get("purpose") or ""),
            "inventory_reason": str(method.get("inventory_reason") or ""),
        },
        "candidates": candidates,
    }


def _method_support_batches(
    methods: list[dict], selected_records: list[dict], pairs: list[dict]
) -> list[tuple[dict, list[dict], list[dict]]]:
    """Build ordered per-method inputs while retaining caller-owned identity."""

    if not isinstance(methods, list) or not isinstance(selected_records, list):
        raise ValueError("method-support methods and records must be lists")
    if not isinstance(pairs, list):
        raise ValueError("method-support selection pairs must be a list")

    method_by_id: dict[str, dict] = {}
    for method in methods:
        if not isinstance(method, dict):
            raise ValueError("method-support method must be an object")
        method_id = str(method.get("method_id") or "").strip()
        if not method_id:
            raise ValueError("method-support method has no method_id")
        if method_id in method_by_id:
            raise ValueError(f"duplicate method-support method_id {method_id}")
        method_by_id[method_id] = method

    record_by_id: dict[str, dict] = {}
    for record in selected_records:
        if not isinstance(record, dict):
            raise ValueError("shortlisted paper record must be an object")
        paper_id = str(record.get("paper_id") or "").strip()
        if not paper_id:
            raise ValueError("shortlisted paper record has no paper_id")
        if paper_id in record_by_id:
            raise ValueError(f"duplicate shortlisted paper_id {paper_id}")
        record_by_id[paper_id] = record

    grouped: dict[str, list[dict]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("method-support selection pair must be an object")
        paper_id = str(pair.get("paper_id") or "").strip()
        method_id = str(pair.get("method_id") or "").strip()
        if not paper_id or not method_id:
            raise ValueError("method-support selection pair has incomplete identity")
        identity = (paper_id, method_id)
        if identity in seen_pairs:
            raise ValueError(f"duplicate method-support selection pair {identity}")
        seen_pairs.add(identity)
        if method_id not in method_by_id:
            raise ValueError(f"selection contains unknown method {method_id}")
        if paper_id not in record_by_id:
            raise ValueError(f"shortlisted paper record is missing: {paper_id}")
        grouped.setdefault(method_id, []).append(pair)

    batches = []
    for method in methods:
        method_id = str(method["method_id"]).strip()
        method_pairs = grouped.pop(method_id, [])
        if not method_pairs:
            continue
        candidate_records = [
            record_by_id[str(pair["paper_id"]).strip()]
            for pair in method_pairs
        ]
        batches.append((method, method_pairs, candidate_records))
    if grouped:
        unknown = sorted(grouped)[0]
        raise ValueError(f"selection contains unknown method {unknown}")
    return batches


def _run_method_support_adjudication(
    l4p,
    dr,
    project_dir: str | Path,
    candidate_id: str,
    question: str,
    claim: str,
    spec,
    work_dir: str | Path,
    skill_version: str,
    methods: list[dict],
    selected_records: list[dict],
    selection: dict,
    *,
    inventory_module,
) -> dict:
    del project_dir, candidate_id, question, claim
    pairs = list(selection.get("pairs") or [])
    if not pairs:
        return {
            "schema_version": METHOD_SUPPORT_SCHEMA_VERSION,
            "status": "not_run_no_shortlisted_pairs",
            "decisions": [],
            "method_batches": [],
            "direct_count": 0,
            "shortlisted_pair_count": 0,
            "adjudication_call_count": 0,
            "skill_receipts": [],
        }

    batches = _method_support_batches(methods, selected_records, pairs)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    method_batches = []
    decisions = []
    receipts = []
    for batch_index, (method, method_pairs, candidate_records) in enumerate(
        batches, 1
    ):
        method_id = str(method["method_id"]).strip()
        method_work = work / (
            f"method_support_{batch_index:03d}_{_safe_method_run_id(method_id)}"
        )
        method_work.mkdir(parents=True, exist_ok=True)
        schema_path = method_work / "l4a_method_support_output.schema.json"
        schema_path.write_text(
            json.dumps(_method_support_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        command, _ = dr.build_invocation(
            spec,
            "L4",
            "L4A metadata-only method-support adjudication",
            "",
            method_work,
        )
        command = [
            str(schema_path)
            if value == str(method_work / "deep_research_output.schema.json")
            else value
            for value in command
        ]
        command = inventory_module._offline_provider_command(
            command, spec, method_work
        )
        prompt = _method_support_prompt(
            _method_support_input(method, candidate_records),
            str(getattr(spec, "backend", "")),
        )
        command[0] = dr.resolve_subprocess_executable(command[0])
        execution_command, invocation_kwargs = dr.subprocess_invocation(
            command, prompt
        )
        completed = dr.execute_provider_invocation(
            execution_command,
            invocation_kwargs,
            timeout=spec.timeout,
            label=f"L4A method-support adjudication CLI ({method_id})",
        )
        receipt = dr.skill_receipt(
            spec.backend,
            command,
            prompt,
            skill_version,
            exit_code=completed.returncode,
            stdout_hash=inventory_module._sha(completed.stdout),
            model=spec.model,
        )
        receipts.append(receipt)
        if completed.returncode != 0:
            raise dr.DeepResearchError(
                "L4A method-support adjudication CLI exited "
                f"{completed.returncode} for {method_id}: {completed.stderr.strip()}"
            )
        validated = _validate_method_support_payload(
            dr,
            dr._parse_cli_output(completed.stdout),
            len(candidate_records),
        )
        wire_decisions = list(validated["decisions"])
        bound_decisions = [
            {
                "paper_id": str(pair["paper_id"]).strip(),
                "method_id": method_id,
                "classification": decision["classification"],
                "rationale": decision["rationale"],
            }
            for pair, decision in zip(method_pairs, wire_decisions)
        ]
        method_batches.append({
            "method_id": method_id,
            "candidate_paper_ids": [
                str(pair["paper_id"]).strip() for pair in method_pairs
            ],
            "decisions": bound_decisions,
            "skill_receipt": receipt,
        })
        decisions.extend(bound_decisions)

    return {
        "schema_version": METHOD_SUPPORT_SCHEMA_VERSION,
        "status": "completed",
        "decisions": decisions,
        "method_batches": method_batches,
        "direct_count": sum(
            item["classification"] == "DIRECT_METHOD_SUPPORT" for item in decisions
        ),
        "shortlisted_pair_count": len(pairs),
        "adjudication_call_count": len(method_batches),
        "skill_receipts": receipts,
    }


def _l4b_retrievable(record: dict) -> tuple[bool, str]:
    """Require a locator that the native L4B source contract can consume."""

    identifiers = record.get("identifiers")
    if not isinstance(identifiers, dict):
        identifiers = {}

    if any(
        (
            multisource.normalize_doi(identifiers.get("doi")),
            multisource.normalize_pmid(identifiers.get("pmid")),
            multisource.normalize_pmcid(identifiers.get("pmcid")),
        )
    ):
        return True, "L4A_RETRIEVABLE_SOURCE"

    return False, "NO_L4B_RETRIEVAL_LOCATOR"


def _record_asset(l4_inventory_module, record: dict, method_ids: list[str]) -> dict:
    identifiers = record.get("identifiers")
    identifiers = identifiers if isinstance(identifiers, dict) else {}
    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    paper_id = str(record.get("paper_id") or "").strip()
    if not paper_id:
        raise ValueError("canonical multisource record has no paper_id")

    doi = multisource.normalize_doi(identifiers.get("doi"))
    pmid = multisource.normalize_pmid(identifiers.get("pmid"))
    pmcid = multisource.normalize_pmcid(identifiers.get("pmcid"))
    url = l4_inventory_module._catalog_source_url({
        "doi": doi, "pmid": pmid, "pmcid": pmcid,
    })
    year_text = str(metadata.get("year") or "").strip()
    year = int(year_text) if year_text.isdigit() else 0
    is_open_access = bool(pmcid or metadata.get("is_open_access"))
    locations = [url] if url else []
    return {
        # The canonical multisource paper_id is the L4A asset identity.  No
        # L4A-specific hash or provider-created asset ID is introduced here.
        "asset_id": paper_id,
        "doi": doi,
        "pmid": pmid,
        "url": url,
        "title": str(record.get("title") or "").strip(),
        "year": year,
        "role": "method",
        "journal": str(metadata.get("journal") or "").strip(),
        "abstract": str(metadata.get("abstract") or "").strip(),
        "source_database": "l05_curie_multisource",
        "source_metadata_response": l4_inventory_module._canonical_json(record),
        "open_access_status": "open" if is_open_access else "unknown",
        "full_text_status": "available_oa" if is_open_access else "metadata_only",
        "full_text_locations": locations,
        "relevance_score": 0.0,
        "selection_status": "selected",
        "selection_reason": (
            "Canonical multisource metadata candidate selected for contextual "
            "method support; not final evidence verification."
        ),
        "hypothesis_ids": [],
        "method_component_hints": list(method_ids),
        "diagnostic_requirements": [],
    }


def _local_asset_by_record(known_sources: dict, record: dict) -> str:
    identifiers = record.get("identifiers")
    identifiers = identifiers if isinstance(identifiers, dict) else {}
    record_paper_id = str(record.get("paper_id") or "").strip()
    record_ids = {
        "doi": multisource.normalize_doi(identifiers.get("doi")),
        "pmid": multisource.normalize_pmid(identifiers.get("pmid")),
        "pmcid": multisource.normalize_pmcid(identifiers.get("pmcid")),
    }
    for source in known_sources.get("sources") or []:
        if not isinstance(source, dict):
            continue
        if record_paper_id and str(source.get("paper_id") or "").strip() == record_paper_id:
            return str(source.get("asset_id") or "").strip()
        for key, value in record_ids.items():
            if not value:
                continue
            if key == "doi":
                source_value = multisource.normalize_doi(source.get(key))
            elif key == "pmid":
                source_value = multisource.normalize_pmid(source.get(key))
            else:
                source_value = multisource.normalize_pmcid(source.get(key))
            if value == source_value:
                return str(source.get("asset_id") or "").strip()
    return ""


def _manifest_contextual_queries(plan: dict, discovery: dict) -> list[dict]:
    failures = discovery.get("failures") or []
    batches = discovery.get("batches") or []
    result = []
    for query in plan.get("queries") or []:
        query_id = str(query["query_id"])
        query_failures = [
            item for item in failures
            if str(item.get("query_id") or "") == query_id
        ]
        batch_count = sum(
            1 for batch in batches
            if str(batch.get("query_id") or "") == query_id
        )
        status = (
            "completed" if not query_failures
            else "partial" if batch_count
            else "failed"
        )
        receipt = {
            "query_plan_id": str(discovery.get("query_plan_id") or plan.get("plan_id") or ""),
            "query_id": query_id,
            "provider_batch_count": batch_count,
            "provider_failure_count": len(query_failures),
        }
        result.append({
            "query_id": query_id,
            "query": str(query.get("query") or ""),
            "purpose": "Canonical multisource contextual method-literature discovery.",
            "status": status,
            "receipt": json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        })
    return result


def _bind_selected_records(
    controller_inventory: list[dict],
    selected_records: list[dict],
    selection: dict,
    adjudication: dict,
    known_sources: dict,
    l4_inventory_module,
) -> tuple[list[dict], list[dict], list[str]]:
    """Project shortlisted metadata records using only DIRECT pair decisions."""

    inventory = copy.deepcopy(controller_inventory)
    by_method = {
        str(method.get("method_id") or ""): method for method in inventory
    }
    pairs = list(selection.get("pairs") or [])
    expected_pairs = {
        (str(item.get("paper_id") or "").strip(),
         str(item.get("method_id") or "").strip())
        for item in pairs
        if isinstance(item, dict)
    }
    if len(expected_pairs) != len(pairs):
        raise ValueError("selection contains duplicate or invalid paper/method pairs")
    decisions = {}
    for item in adjudication.get("decisions") or []:
        if not isinstance(item, dict):
            raise ValueError("method-support adjudication decision must be an object")
        pair = (
            str(item.get("paper_id") or "").strip(),
            str(item.get("method_id") or "").strip(),
        )
        if pair in decisions:
            raise ValueError(f"duplicate method-support decision for pair {pair}")
        if str(item.get("classification") or "") not in METHOD_SUPPORT_CLASSIFICATIONS:
            raise ValueError(
                f"invalid method-support classification for pair {pair}"
            )
        if not str(item.get("rationale") or "").strip():
            raise ValueError(f"method-support rationale is empty for pair {pair}")
        decisions[pair] = item
    if set(decisions) != expected_pairs:
        missing = sorted(expected_pairs - set(decisions))
        unknown = sorted(set(decisions) - expected_pairs)
        raise ValueError(
            "method-support decisions do not match shortlisted pairs; "
            f"missing={missing[:1]} unknown={unknown[:1]}"
        )
    direct_by_paper: dict[str, list[str]] = {}
    semantic_by_pair = {
        (
            str(item.get("paper_id") or "").strip(),
            str(item.get("method_id") or "").strip(),
        ): item
        for item in pairs
        if isinstance(item, dict)
    }
    for pair, decision in decisions.items():
        if decision.get("classification") != "DIRECT_METHOD_SUPPORT":
            continue
        paper_id, method_id = pair
        if method_id not in by_method:
            raise ValueError(f"method-support decision references unknown method {method_id}")
        direct_by_paper.setdefault(paper_id, []).append(method_id)

    assets: list[dict] = []
    selected_asset_ids: list[str] = []
    record_by_id = {
        str(record.get("paper_id") or "").strip(): record
        for record in selected_records
    }
    pair_paper_ids = {
        str(item.get("paper_id") or "").strip()
        for item in pairs
        if isinstance(item, dict)
    }
    pair_method_ids = {
        str(item.get("method_id") or "").strip()
        for item in pairs
        if isinstance(item, dict)
    }
    unknown_methods = sorted(pair_method_ids - set(by_method))
    if unknown_methods:
        raise ValueError(
            f"selection contains unknown method {unknown_methods[0]}"
        )
    if set(record_by_id) != pair_paper_ids:
        missing = sorted(
            {
                str(item.get("paper_id") or "").strip() for item in pairs
                if isinstance(item, dict)
            } - set(record_by_id)
        )
        if missing:
            raise ValueError(f"shortlisted paper record is missing: {missing[0]}")

    for record in selected_records:
        paper_id = str(record.get("paper_id") or "").strip()
        if paper_id not in record_by_id:
            continue
        method_ids = [
            method_id for method_id in direct_by_paper.get(paper_id, [])
            if method_id in by_method
        ]
        local_asset_id = _local_asset_by_record(known_sources, record)
        asset_id = local_asset_id
        if not asset_id:
            asset = _record_asset(l4_inventory_module, record, method_ids)
            semantic_scores = [
                float(semantic_by_pair[pair].get("semantic_score"))
                for pair in semantic_by_pair
                if pair[0] == paper_id
            ]
            asset["relevance_score"] = min(
                10.0,
                max(0.0, 10.0 * _selection_score(max(semantic_scores, default=-1.0))),
            )
            if method_ids:
                asset["selection_reason"] = (
                    "SPECTER2-shortlisted canonical metadata candidate with one or "
                    "more DIRECT_METHOD_SUPPORT pair decisions."
                )
            else:
                asset["selection_reason"] = (
                    "SPECTER2-shortlisted canonical metadata candidate retained for "
                    "audit; no DIRECT_METHOD_SUPPORT pair decision."
                )
            assets.append(asset)
            asset_id = str(asset["asset_id"])
        if asset_id not in selected_asset_ids:
            selected_asset_ids.append(asset_id)
        for method_id in method_ids:
            method = by_method[method_id]
            if asset_id not in method["source_asset_ids"]:
                method["source_asset_ids"].append(asset_id)
    return inventory, assets, selected_asset_ids


def install(l4_inventory_module, deep_research_module) -> None:
    """Install native-v2.1 contextual planning without changing old profiles."""
    if getattr(l4_inventory_module, "_contextual_literature_installed", False):
        return

    original_run_discovery = l4_inventory_module.run_discovery
    original_persist_discovery = l4_inventory_module.persist_discovery
    original_manifest_base = l4_inventory_module._manifest_base

    def manifest_base(*args, **kwargs):
        assets = list(kwargs.get("assets") or [])
        selected_ids = [
            str(asset.get("asset_id") or "")
            for asset in assets
            if asset.get("selection_status") == "selected"
        ]
        receipt = kwargs.get("runtime_receipt") or {}
        if selected_ids or "contextual_literature_search" not in receipt:
            return original_manifest_base(*args, **kwargs)
        # A completed contextual pass with zero trustworthy canonical records is
        # a valid persisted L4A blocked state. L4B remains fail-closed because
        # it requires a non-empty selected corpus.
        l4p = args[0] if args else kwargs["l4p"]
        return {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
            "pipeline_stage": "L4A",
            "project_id": kwargs["project_id"],
            "round_id": str(kwargs["round_id"]),
            "candidate_id": kwargs["candidate_id"],
            "profile_id": kwargs["profile_id"],
            "question": kwargs["question"],
            "claim": kwargs["claim"],
            "question_sha256": l4_inventory_module._sha(kwargs["question"]),
            "claim_sha256": l4_inventory_module._sha(kwargs["claim"]),
            "queries": kwargs["queries"],
            "assets": assets,
            "duplicates": kwargs["duplicates"],
            "selected_asset_ids": [],
            "runtime_receipt": receipt,
            "inventory_schema": l4_inventory_module.INVENTORY_SCHEMA_VERSION,
            "method_inventory": kwargs["inventory"],
        }

    def run_discovery(
        l4p,
        dr,
        project_dir,
        candidate_id,
        question,
        claim,
        spec,
        work_dir,
        skill_version="unknown",
        *,
        project_id="",
        round_id="",
        profile_id="",
    ):
        known_sources, registry_snapshot = l4_inventory_module._native_known_source_catalog(
            project_dir, candidate_id, profile_id, dr
        )
        if known_sources is None:
            return original_run_discovery(
                l4p, dr, project_dir, candidate_id, question, claim, spec, work_dir,
                skill_version,
                project_id=project_id,
                round_id=round_id,
                profile_id=profile_id,
            )

        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)
        legacy_schema_path = work / "deep_research_output.schema.json"
        inventory_schema_path = work / "l4a_method_inventory_output.schema.json"
        contextual_schema_path = work / "l4a_contextual_query_plan_output.schema.json"
        legacy_schema_path.write_text(
            json.dumps(dr._runtime_schema("L4"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        inventory_schema_path.write_text(
            json.dumps(l4_inventory_module.discovery_schema(l4p), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        contextual_schema_path.write_text(
            json.dumps(_contextual_query_plan_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        command, _ = dr.build_invocation(spec, "L4", question, claim, work)
        command = [
            str(inventory_schema_path) if value == str(legacy_schema_path) else value
            for value in command
        ]
        command = l4_inventory_module._offline_provider_command(command, spec, work)
        prompt = l4_inventory_module.build_prompt(question, claim, known_sources)
        command[0] = dr.resolve_subprocess_executable(command[0])
        execution_command, invocation_kwargs = dr.subprocess_invocation(command, prompt)
        completed = dr.execute_provider_invocation(
            execution_command,
            invocation_kwargs,
            timeout=spec.timeout,
            label="L4A method-inventory CLI",
        )
        receipt = dr.skill_receipt(
            spec.backend,
            command,
            prompt,
            skill_version,
            exit_code=completed.returncode,
            stdout_hash=l4_inventory_module._sha(completed.stdout),
            model=spec.model,
        )
        pack = known_sources["evidence_pack"]
        receipt["known_source_catalog"] = {
            "catalog_sha256": l4_inventory_module._sha(
                l4_inventory_module._canonical_json(known_sources)
            ),
            "evidence_pack_id": str(pack.get("pack_id") or ""),
            "evidence_pack_content_sha256": str(pack.get("content_sha256") or ""),
            "evidence_pack_artifact_sha256": str(pack.get("artifact_sha256") or ""),
            "selected_paper_count": len(known_sources["sources"]),
        }
        if completed.returncode != 0:
            raise dr.DeepResearchError(
                f"L4A method-inventory CLI exited {completed.returncode}: "
                f"{completed.stderr.strip()}"
            )

        offline_payload = dr._parse_cli_output(completed.stdout)
        canonical = l4_inventory_module._validate_inventory_payload(l4p, dr, offline_payload)
        controller_inventory = l4_inventory_module._validate_controller_boundary(
            canonical, known_sources, dr
        )
        try:
            registry_inventory, _ = l4_inventory_module.l4_method_registry.apply_registry(
                project_dir,
                controller_inventory,
                loaded_registry=registry_snapshot,
            )
        except l4_inventory_module.l4_method_registry.MethodRegistryError as exc:
            raise dr.DeepResearchError(f"L4 method-source registry failed: {exc}") from exc

        unresolved = [
            method for method in registry_inventory
            if not method.get("source_asset_ids") and not method.get("source_hints")
        ]
        unresolved_ids = [str(method["method_id"]) for method in unresolved]
        contextual_assets: list[dict] = []
        enriched_inventory = copy.deepcopy(registry_inventory)
        contextual_queries: list[dict] = []
        if unresolved:
            search_command, _ = dr.build_invocation(spec, "L4", question, claim, work)
            search_command = [
                str(contextual_schema_path) if value == str(legacy_schema_path) else value
                for value in search_command
            ]
            search_command = l4_inventory_module._offline_provider_command(
                search_command, spec, work
            )
            search_prompt = _contextual_prompt(
                question, claim, unresolved, str(getattr(spec, "backend", ""))
            )
            search_command[0] = dr.resolve_subprocess_executable(search_command[0])
            execution_command, invocation_kwargs = dr.subprocess_invocation(
                search_command, search_prompt
            )
            search_completed = dr.execute_provider_invocation(
                execution_command,
                invocation_kwargs,
                timeout=spec.timeout,
                label="L4A contextual query-planner CLI",
            )
            search_receipt = dr.skill_receipt(
                spec.backend,
                search_command,
                search_prompt,
                skill_version,
                exit_code=search_completed.returncode,
                stdout_hash=l4_inventory_module._sha(search_completed.stdout),
                model=spec.model,
            )
            if search_completed.returncode != 0:
                raise dr.DeepResearchError(
                    "L4A contextual query-planner CLI exited "
                    f"{search_completed.returncode}: {search_completed.stderr.strip()}"
                )
            contextual = _validate_contextual_payload(
                l4p,
                dr,
                dr._parse_cli_output(search_completed.stdout),
                unresolved_ids,
            )
            planner_queries = list(contextual["queries"])
            seed = research_seed.load_l1_research_seed(project_dir, candidate_id)
            seed_hash = research_seed.seed_sha256(seed)
            explicit_queries = [str(item["query"]) for item in planner_queries]
            try:
                query_plan = multisource.build_multisource_query_plan(
                    seed,
                    seed_sha256=seed_hash,
                    round_index=_round_index(seed.get("round_id") or round_id),
                    explicit_queries=explicit_queries,
                    providers=list(multisource._PROVIDERS),
                )
            except multisource.CurieContractError as exc:
                raise dr.DeepResearchError(
                    f"L4A contextual multisource query planning failed: {exc}"
                ) from exc

            discovery_run_id = "L4A_" + l4_inventory_module._sha(
                l4_inventory_module._canonical_json(query_plan)
            )[:20]
            try:
                transports = _contextual_transports(
                    project_dir,
                    candidate_id,
                    discovery_run_id,
                    _transport_timeout(spec),
                )
                discovery = multisource.run_multisource_discovery_strict(
                    query_plan,
                    transports,
                    seed_sha256=seed_hash,
                    page_size=25,
                    allow_partial=True,
                )
            except multisource.CurieContractError as exc:
                raise dr.DeepResearchError(
                    f"L4A contextual multisource discovery failed: {exc}"
                ) from exc

            try:
                selection, selected_records = _select_contextual_candidates(
                    list(discovery.get("records") or []),
                    unresolved,
                    planner_queries,
                    query_plan,
                    seed=seed,
                    top_k_per_method=_top_k_per_method(spec),
                    project_dir=project_dir,
                    candidate_id=candidate_id,
                    discovery_run_id=discovery_run_id,
                )
            except (multisource.CurieContractError, ValueError, TypeError,
                    l4a_specter2.Specter2Error) as exc:
                raise dr.DeepResearchError(
                    f"L4A contextual SPECTER2 candidate selection failed: {exc}"
                ) from exc
            try:
                adjudication = _run_method_support_adjudication(
                    l4p,
                    dr,
                    project_dir,
                    candidate_id,
                    question,
                    claim,
                    spec,
                    work,
                    skill_version,
                    unresolved,
                    selected_records,
                    selection,
                    inventory_module=l4_inventory_module,
                )
            except (ValueError, TypeError, OSError) as exc:
                raise dr.DeepResearchError(
                    f"L4A method-support adjudication failed closed: {exc}"
                ) from exc
            enriched_inventory, contextual_assets, selected_asset_ids = _bind_selected_records(
                registry_inventory,
                selected_records,
                selection,
                adjudication,
                known_sources,
                l4_inventory_module,
            )
            contextual_queries = _manifest_contextual_queries(query_plan, discovery)
            contextual_receipt = {
                "method_ids": unresolved_ids,
                "planner_query_ids": [
                    str(item["query_id"]) for item in planner_queries
                ],
                "query_plan": query_plan,
                "planner_to_canonical_query_ids": {
                    str(planner_query["query_id"]): str(plan_query["query_id"])
                    for plan_query, planner_query in zip(
                        query_plan["queries"], planner_queries
                    )
                },
                "discovery": discovery,
                "selection": selection,
                "method_support_adjudication": adjudication,
                "selected_asset_ids": selected_asset_ids,
                "planner_skill_receipt": search_receipt,
                # Keep the historical key for receipt readers; its contents are
                # now explicitly a query-planner invocation, never paper output.
                "skill_receipt": search_receipt,
            }
            receipt["contextual_literature_search"] = contextual_receipt

        local_assets = l4_inventory_module._catalog_assets(known_sources)
        enriched_payload = {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "queries": list(canonical["queries"]) + contextual_queries,
            "assets": local_assets + contextual_assets,
            "method_inventory": enriched_inventory,
        }
        # The native controller boundary is already enforced above.  Pass the
        # payload through the existing registry/projection persistence owner,
        # but do not invoke its retired title resolver and do not let L4A run a
        # second identity/deduplication pass over canonical multisource assets.
        return original_persist_discovery(
            l4p,
            dr,
            project_dir,
            candidate_id,
            enriched_payload,
            receipt,
            question=question,
            claim=claim,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            registry_snapshot=registry_snapshot,
            known_sources=None,
            deduplicate_assets=False,
        )

    l4_inventory_module._manifest_base = manifest_base
    l4_inventory_module.run_discovery = run_discovery
    l4_inventory_module._contextual_literature_original_run_discovery = original_run_discovery
    l4_inventory_module._contextual_literature_original_manifest_base = original_manifest_base
    l4_inventory_module._contextual_literature_installed = True
