"""Install the English-internal invariant on literature-facing runtime seams.

User-language normalization occurs once upstream at the L0 -> ResearchSeed
boundary. This module never translates. It only fails closed if later internal
scientific state or retrieval text is not already English, and preserves the
existing retrieval/ranking/evidence authorities.
"""
from __future__ import annotations

from research_loop.l0_language import L0LanguageError, validate_internal_english
from research_loop.l05_curie.contracts import CurieContractError


def _english(value, *, name: str) -> str:
    try:
        return validate_internal_english(value, name=name)
    except L0LanguageError as exc:
        raise CurieContractError(str(exc)) from exc


def _english_queries(values, *, name: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise CurieContractError(f"{name} must be a non-empty list")
    result = []
    seen = set()
    for index, value in enumerate(values, 1):
        query = _english(value, name=f"{name} item {index}")
        key = query.casefold()
        if key in seen:
            raise CurieContractError(f"{name} must not contain duplicate queries")
        seen.add(key)
        result.append(query)
    return result


def install(
    multisource_module,
    europepmc_runtime_module,
    l4_inventory_module,
    l4_contextual_module,
    l4a_specter2_module,
    paperqa2_runtime_module,
) -> None:
    if getattr(l4_inventory_module, "_english_retrieval_boundary_installed", False):
        return

    original_build_query_plan = multisource_module.build_multisource_query_plan

    def build_multisource_query_plan(*args, **kwargs):
        if kwargs.get("explicit_queries") is not None:
            kwargs = dict(kwargs)
            kwargs["explicit_queries"] = _english_queries(
                kwargs["explicit_queries"],
                name="explicit English retrieval queries",
            )
        plan = original_build_query_plan(*args, **kwargs)
        for item in plan.get("queries") or []:
            if not isinstance(item, dict):
                continue
            _english(
                item.get("query"),
                name=(
                    "canonical QueryPlan English retrieval query "
                    f"{str(item.get('query_id') or '<unknown>')}"
                ),
            )
        return plan

    original_build_prompt = l4_inventory_module.build_prompt

    def build_prompt(question, claim, known_sources=None):
        _english(question, name="L4 scientific question")
        _english(claim, name="L4 claim")
        prompt = original_build_prompt(question, claim, known_sources)
        return prompt + """

Internal-language contract:
- All RLR internal scientific semantics are already English.
- Every method_inventory item's `name`, `purpose`, and `inventory_reason` MUST
  be written in standard English scientific terminology.
- Do not translate, localize, or reproduce user-language text in these fields.
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
                    _english(
                        method.get(field),
                        name=f"L4A method {method_id} {field}",
                    )
                except CurieContractError as exc:
                    raise dr.DeepResearchError(str(exc)) from exc
        return canonical

    original_rank_method_papers = l4a_specter2_module.rank_method_papers

    def rank_method_papers(method_query, canonical_records, *, ranker=None):
        query = _english(method_query, name="SPECTER2 English retrieval query")
        return original_rank_method_papers(query, canonical_records, ranker=ranker)

    original_paperqa_retrieve = (
        paperqa2_runtime_module.PaperQA2CurieRuntime.retrieve_and_verify
    )

    def retrieve_and_verify(self, *, paper, question, source_candidates, verify):
        query = _english(question, name="PaperQA2 English retrieval query")
        return original_paperqa_retrieve(
            self,
            paper=paper,
            question=query,
            source_candidates=source_candidates,
            verify=verify,
        )

    multisource_module.build_multisource_query_plan = build_multisource_query_plan
    europepmc_runtime_module.build_multisource_query_plan = build_multisource_query_plan
    l4_inventory_module.build_prompt = build_prompt
    l4_inventory_module._validate_inventory_payload = validate_inventory_payload
    l4a_specter2_module.rank_method_papers = rank_method_papers
    paperqa2_runtime_module.PaperQA2CurieRuntime.retrieve_and_verify = retrieve_and_verify
    l4_inventory_module._english_retrieval_boundary_installed = True
