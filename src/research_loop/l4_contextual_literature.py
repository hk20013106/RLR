"""Contextual L4A query planning over the canonical L0.5 discovery layer.

The first L4A provider invocation is the existing offline method-inventory
step.  Only methods that remain unresolved after frozen L0.5 matching and the
method registry get a second invocation.  That invocation is deliberately a
query planner: it returns query text and method IDs, never paper records.

The resulting explicit queries are handed to the canonical L0.5 multisource
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

from research_loop import research_seed
from research_loop.l05_curie.contracts import MAX_ACQUISITION_ROUNDS
from research_loop.l05_curie import europepmc, multisource, selector


CONTEXTUAL_QUERY_PLAN_SCHEMA_VERSION = "L4AContextualQueryPlan/v1"
_CONTEXTUAL_MAX_PAPERS = 5


def _contextual_query_plan_schema() -> dict:
    query = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query_id": {"type": "string", "minLength": 1},
            "query": {"type": "string", "minLength": 1},
            "purpose": {"type": "string", "minLength": 1},
            "status": {"type": "string", "const": "planned"},
            "receipt": {"type": "string", "minLength": 1},
            "method_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
        # Codex structured outputs require every declared property to appear
        # in required, including these audit annotations.
        "required": [
            "query_id",
            "query",
            "purpose",
            "status",
            "receipt",
            "method_ids",
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
Unresolved candidate analysis actions:
{json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}

Produce a small, reproducible query plan for contextual literature discovery.
This is query planning only. Do not search literature, browse the web, call a
database, invoke a literature-search skill, read the project filesystem, or
retrieve any paper metadata. The controller will execute every query through
the canonical multisource discovery layer.

Return only contextual queries. Each query must contain a unique query_id, the
query text, a concise purpose, status=planned, a short planning receipt, and
one or more exact unresolved method_id values from the supplied list. Build
queries from the scientific question, study design, data type, biological
context, and method purpose; do not require a paper title to equal a method
label. A query may cover more than one method when the context genuinely
supports that relationship.

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
    """Validate the provider's planner-only wire payload."""
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
    normalized = copy.deepcopy(payload)
    for query in normalized["queries"]:
        query.setdefault(
            "purpose", "Contextual literature query for an unresolved analysis action."
        )
        query.setdefault("status", "planned")
        query.setdefault("receipt", "contextual query planner")
    return normalized


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


def _method_context(methods: list[dict], planner_queries: list[dict]) -> str:
    fields = []
    for method in methods:
        fields.extend([
            str(method.get("name") or ""),
            str(method.get("purpose") or ""),
            str(method.get("inventory_reason") or ""),
        ])
    fields.extend(str(item.get("query") or "") for item in planner_queries)
    return " ".join(fields)


def _tokens(value: object) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", str(value or ""))
    }


def _build_selector_scorer(methods: list[dict], planner_queries: list[dict]):
    context = _tokens(_method_context(methods, planner_queries))
    method_tokens = _tokens(_method_context(methods, []))

    def score(record: dict, seed: dict) -> dict:
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        text = " ".join([
            str(record.get("title") or ""),
            str(metadata.get("abstract") or ""),
            str(metadata.get("authors") or ""),
            str(metadata.get("journal") or ""),
            str(seed.get("scientific_question") or ""),
            str(seed.get("hypothesis_seed") or ""),
        ])
        record_tokens = _tokens(text)
        overlap = len(context & record_tokens) / max(1, len(context))
        method_overlap = len(method_tokens & record_tokens) / max(1, len(method_tokens))
        provenance = record.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        source_records = provenance.get("source_records") or []
        diversity = min(1.0, len(source_records) / 2.0) if source_records else 0.5
        relevance = min(1.0, 0.5 * overlap + 0.5 * method_overlap)
        return {
            "relevance": relevance,
            "directness": 1.0 if provenance.get("originating_query_ids") else 0.0,
            "methodological_value": method_overlap,
            "contradiction_value": 0.0,
            "evidence_diversity": diversity,
            "reason": (
                "Canonical multisource metadata candidate selected as bounded "
                "contextual method support; this is candidate support only."
            ),
        }

    return score


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
    planner_to_methods: dict[str, list[str]],
    known_sources: dict,
    l4_inventory_module,
) -> tuple[list[dict], list[dict], list[str]]:
    inventory = copy.deepcopy(controller_inventory)
    by_method = {
        str(method.get("method_id") or ""): method for method in inventory
    }
    assets = []
    selected_asset_ids = []
    decisions = {
        str(item.get("paper_id") or ""): item
        for item in selection.get("decisions") or []
        if isinstance(item, dict)
    }
    for record in selected_records:
        provenance = record.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        method_ids = []
        for query_id in provenance.get("originating_query_ids") or []:
            for method_id in planner_to_methods.get(str(query_id), []):
                if method_id in by_method and method_id not in method_ids:
                    method_ids.append(method_id)
        if not method_ids:
            continue
        local_asset_id = _local_asset_by_record(known_sources, record)
        asset_id = local_asset_id
        if not asset_id:
            asset = _record_asset(l4_inventory_module, record, method_ids)
            decision = decisions.get(str(record.get("paper_id") or ""), {})
            asset["relevance_score"] = min(
                10.0, max(0.0, 10.0 * float(decision.get("relevance") or 0.0))
            )
            if decision.get("reason"):
                asset["selection_reason"] = str(decision["reason"])
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

            planner_to_methods = {
                str(plan_query["query_id"]): list(planner_query["method_ids"])
                for plan_query, planner_query in zip(
                    query_plan["queries"], planner_queries
                )
            }
            try:
                selection = selector.select_candidates_strict(
                    list(discovery.get("records") or []),
                    seed=seed,
                    scorer=_build_selector_scorer(unresolved, planner_queries),
                    eligibility=lambda record: (True, "L4A_CONTEXTUAL_METADATA"),
                    max_papers=_CONTEXTUAL_MAX_PAPERS,
                    project_dir=project_dir,
                    candidate_id=candidate_id,
                    run_id=discovery_run_id,
                    query_ids={
                        str(item["query_id"]) for item in query_plan["queries"]
                    },
                )
            except (multisource.CurieContractError, ValueError) as exc:
                raise dr.DeepResearchError(
                    f"L4A contextual multisource candidate selection failed: {exc}"
                ) from exc
            included_ids = set(selection.get("included_paper_ids") or [])
            selected_records = [
                record for record in discovery.get("records") or []
                if str(record.get("paper_id") or "") in included_ids
            ]
            enriched_inventory, contextual_assets, selected_asset_ids = _bind_selected_records(
                registry_inventory,
                selected_records,
                selection,
                planner_to_methods,
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
