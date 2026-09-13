"""Install one English-retrieval language invariant on existing runtime seams.

This module creates no query planner, retriever, evidence authority, identity,
or retry path. It only constrains existing query-plan/L4/PaperQA2/SPECTER2
consumers to English retrieval text and reuses already-authorized queries.
"""
from __future__ import annotations

from research_loop.l05_curie.contracts import CurieContractError
from research_loop.l05_curie.query_language import (
    validate_english_retrieval_query,
    validate_english_retrieval_queries,
)


def install(
    multisource_module,
    l4_inventory_module,
    l4_contextual_module,
    l4a_specter2_module,
    paperqa2_runtime_module,
    deep_research_module,
) -> None:
    if getattr(l4_inventory_module, "_english_retrieval_boundary_installed", False):
        return

    original_build_query_plan = multisource_module.build_multisource_query_plan

    def build_multisource_query_plan(*args, **kwargs):
        if kwargs.get("explicit_queries") is not None:
            kwargs = dict(kwargs)
            kwargs["explicit_queries"] = validate_english_retrieval_queries(
                kwargs["explicit_queries"],
                name="explicit English retrieval queries",
            )
        plan = original_build_query_plan(*args, **kwargs)
        for item in plan.get("queries") or []:
            if not isinstance(item, dict):
                continue
            validate_english_retrieval_query(
                item.get("query"),
                name=(
                    "canonical QueryPlan English retrieval query "
                    f"{str(item.get('query_id') or '<unknown>')}"
                ),
            )
        return plan

    original_build_prompt = l4_inventory_module.build_prompt

    def build_prompt(question, claim, known_sources=None):
        prompt = original_build_prompt(question, claim, known_sources)
        return prompt + """

Retrieval-language contract:
- The scientific question and claim above may be written in any language.
- Every method_inventory item's `name`, `purpose`, and `inventory_reason` MUST
  be written in English scientific terminology.
- Preserve the scientific meaning; do not merely transliterate non-English
  method descriptions.
- This language rule does not authorize literature retrieval in this offline
  inventory step.
"""

    original_validate_inventory = l4_inventory_module._validate_inventory_payload

    def validate_inventory_payload(l4p, dr, payload):
        canonical = original_validate_inventory(l4p, dr, payload)
        for method in canonical.get("method_inventory") or []:
            method_id = str(method.get("method_id") or "").strip() or "<unknown>"
            for field in ("name", "purpose", "inventory_reason"):
                try:
                    validate_english_retrieval_query(
                        method.get(field),
                        name=f"L4A method {method_id} {field}",
                    )
                except CurieContractError as exc:
                    raise dr.DeepResearchError(str(exc)) from exc
        return canonical

    def method_query(method: dict, planner_queries: list[dict]) -> str:
        method_id = str(method.get("method_id") or "").strip()
        planned = []
        seen = set()
        for item in planner_queries or []:
            if not isinstance(item, dict):
                continue
            method_ids = {str(value).strip() for value in item.get("method_ids") or []}
            if method_id not in method_ids:
                continue
            query = validate_english_retrieval_query(
                item.get("query"),
                name=f"L4A method {method_id} contextual English query",
            )
            key = query.casefold()
            if key not in seen:
                seen.add(key)
                planned.append(query)
        if planned:
            return ". ".join(planned)
        fallback = []
        for field in ("name", "purpose", "inventory_reason"):
            value = str(method.get(field) or "").strip()
            if value:
                fallback.append(
                    validate_english_retrieval_query(
                        value,
                        name=f"L4A method {method_id} {field}",
                    )
                )
        if not fallback:
            raise ValueError(
                f"L4A method {method_id or '<unknown>'} has no English retrieval text"
            )
        return ". ".join(fallback)

    original_rank_method_papers = l4a_specter2_module.rank_method_papers

    def rank_method_papers(method_query, canonical_records, *, ranker=None):
        query = validate_english_retrieval_query(
            method_query, name="SPECTER2 English retrieval query"
        )
        return original_rank_method_papers(query, canonical_records, ranker=ranker)

    original_paperqa_retrieve = (
        paperqa2_runtime_module.PaperQA2CurieRuntime.retrieve_and_verify
    )

    def retrieve_and_verify(self, *, paper, question, source_candidates, verify):
        query = validate_english_retrieval_query(
            question, name="PaperQA2 English retrieval query"
        )
        return original_paperqa_retrieve(
            self,
            paper=paper,
            question=query,
            source_candidates=source_candidates,
            verify=verify,
        )

    multisource_module.build_multisource_query_plan = build_multisource_query_plan
    l4_inventory_module.build_prompt = build_prompt
    l4_inventory_module._validate_inventory_payload = validate_inventory_payload
    l4_contextual_module._method_query = method_query
    l4a_specter2_module.rank_method_papers = rank_method_papers
    paperqa2_runtime_module.PaperQA2CurieRuntime.retrieve_and_verify = retrieve_and_verify
    l4_inventory_module._english_retrieval_boundary_installed = True
