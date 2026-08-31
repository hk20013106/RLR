"""Native L4A contextual literature search extension.

The staged L4A inventory remains an offline cognition step.  This extension
reuses the existing Academic Research Skills provider boundary for one bounded,
context-aware literature search only when frozen L0.5 sources and the existing
method registry leave inventory items unresolved.

It does not canonicalize method names, invent citations, or own literature
identity.  Returned papers must carry exact identifiers and explicitly name the
unresolved method IDs they support; the existing L4A persistence/dedup/registry
owners remain authoritative.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def _contextual_prompt(question: str, claim: str, methods: list[dict], backend: str) -> str:
    invocation = "$academic-research-suite" if backend == "codex" else "/ars-lit-review"
    compact = [
        {
            "method_id": str(method.get("method_id") or ""),
            "name": str(method.get("name") or ""),
            "purpose": str(method.get("purpose") or ""),
            "inventory_reason": str(method.get("inventory_reason") or ""),
        }
        for method in methods
    ]
    return f"""RLR stage: L4A Contextual Method Literature Search
Scientific question: {question}
Selected hypothesis/claim: {claim}
Unresolved candidate analysis actions:
{json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}

Use {invocation} to search academic literature for similar studies that actually
used, evaluated, benchmarked, or discussed the analysis approaches above.
Search in the scientific context of the question and claim, not by requiring a
paper title to equal a method label.  Derive contextual literature queries from
the study design, data type, biological question, and the method purposes.

This is one bounded contextual literature-search pass.  Prefer primary studies,
method papers, protocols, or benchmarking papers that show how comparable work
was performed.  A single paper may support more than one candidate analysis
action when its methods genuinely do so.

Return metadata only in the supplied L4A discovery schema.  For every selected
paper:
- provide DOI, PMID, or a stable URL actually returned by the search;
- keep the real source_database and source_metadata_response;
- put one or more exact unresolved method_id values in method_component_hints;
- do not invent a citation, identifier, paper, or method-to-paper relationship.

Do not access or modify the project filesystem or literature database.  Do not
return full-text extracts or quotations.  If the search finds no trustworthy
source for an action, leave it unresolved rather than guessing.

Return JSON only.  Do not include prose, Markdown, code fences, commentary, or
text outside the JSON object.
"""


def _contextual_command(command: list[str], spec, work_dir: Path) -> list[str]:
    """Keep the contextual search disposable/read-only without disabling web search."""
    result = list(command)
    if str(getattr(spec, "backend", "")) == "codex":
        result.extend([
            "--sandbox", "read-only",
            "-C", str(work_dir.resolve()),
            "--skip-git-repo-check",
        ])
    return result


def _validate_contextual_payload(l4p, dr, payload: dict, unresolved_ids: list[str]) -> dict:
    canonical = dict(l4p._canonicalize_l4a_provider_payload(payload))
    errors = sorted(
        Draft202012Validator(l4p.l4a_discovery_schema()).iter_errors(canonical),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "payload"
        raise dr.DeepResearchError(
            f"L4A contextual literature payload {path}: {error.message}"
        )

    allowed = set(unresolved_ids)
    asset_ids = []
    for asset in canonical.get("assets") or []:
        asset_id = str(asset.get("asset_id") or "").strip()
        if asset_id in asset_ids:
            raise dr.DeepResearchError(
                f"L4A contextual literature search returned duplicate asset_id {asset_id}"
            )
        asset_ids.append(asset_id)
        hints = [str(value).strip() for value in asset.get("method_component_hints") or []]
        unknown = [value for value in hints if value not in allowed]
        if unknown:
            raise dr.DeepResearchError(
                "L4A contextual literature asset references a method outside the "
                f"unresolved inventory: {unknown[0]}"
            )
        if asset.get("selection_status") == "selected":
            if not hints:
                raise dr.DeepResearchError(
                    f"L4A contextual literature asset {asset_id} has no unresolved method_id"
                )
            if not any(str(asset.get(key) or "").strip() for key in ("doi", "pmid", "url")):
                raise dr.DeepResearchError(
                    f"L4A contextual literature asset {asset_id} has no exact identifier"
                )
    return canonical


def _bind_contextual_assets(
    controller_inventory: list[dict],
    contextual: dict,
    unresolved_ids: list[str],
) -> list[dict]:
    result = copy.deepcopy(controller_inventory)
    by_id = {str(method.get("method_id") or ""): method for method in result}
    allowed = set(unresolved_ids)
    for asset in contextual.get("assets") or []:
        if asset.get("selection_status") != "selected":
            continue
        asset_id = str(asset.get("asset_id") or "").strip()
        for raw_method_id in asset.get("method_component_hints") or []:
            method_id = str(raw_method_id).strip()
            if method_id not in allowed:
                continue
            method = by_id[method_id]
            if asset_id not in method["source_asset_ids"]:
                method["source_asset_ids"].append(asset_id)
    return result


def install(l4_inventory_module, deep_research_module) -> None:
    """Install native-v2.1 contextual search without changing historical profiles."""
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
        # A completed contextual search with zero trustworthy papers is a valid
        # L4A blocked state.  Persist it; the existing L4B boundary still fails
        # closed because it requires a non-empty selected corpus.
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
        contextual_schema_path = work / "l4a_contextual_literature_output.schema.json"
        legacy_schema_path.write_text(
            json.dumps(dr._runtime_schema("L4"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        inventory_schema_path.write_text(
            json.dumps(l4_inventory_module.discovery_schema(l4p), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        contextual_schema_path.write_text(
            json.dumps(l4p.l4a_discovery_schema(), ensure_ascii=False, indent=2),
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
        contextual = None
        if unresolved:
            search_command, _ = dr.build_invocation(spec, "L4", question, claim, work)
            search_command = [
                str(contextual_schema_path) if value == str(legacy_schema_path) else value
                for value in search_command
            ]
            search_command = _contextual_command(search_command, spec, work)
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
                label="L4A contextual method-literature CLI",
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
                    f"L4A contextual method-literature CLI exited "
                    f"{search_completed.returncode}: {search_completed.stderr.strip()}"
                )
            contextual = _validate_contextual_payload(
                l4p,
                dr,
                dr._parse_cli_output(search_completed.stdout),
                unresolved_ids,
            )
            receipt["contextual_literature_search"] = {
                "method_ids": unresolved_ids,
                "query_ids": [
                    str(item.get("query_id") or "")
                    for item in contextual.get("queries") or []
                ],
                "selected_asset_ids": [
                    str(asset.get("asset_id") or "")
                    for asset in contextual.get("assets") or []
                    if asset.get("selection_status") == "selected"
                ],
                "skill_receipt": search_receipt,
            }

        enriched_inventory = copy.deepcopy(controller_inventory)
        contextual_assets = []
        contextual_queries = []
        if contextual is not None:
            enriched_inventory = _bind_contextual_assets(
                enriched_inventory, contextual, unresolved_ids
            )
            contextual_assets = list(contextual.get("assets") or [])
            contextual_queries = list(contextual.get("queries") or [])

        local_assets = l4_inventory_module._catalog_assets(known_sources)
        local_ids = {str(asset.get("asset_id") or "") for asset in local_assets}
        collision = next(
            (
                str(asset.get("asset_id") or "")
                for asset in contextual_assets
                if str(asset.get("asset_id") or "") in local_ids
            ),
            "",
        )
        if collision:
            raise dr.DeepResearchError(
                f"L4A contextual literature asset_id collides with frozen source: {collision}"
            )

        enriched_payload = {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "queries": list(canonical["queries"]) + contextual_queries,
            "assets": local_assets + contextual_assets,
            "method_inventory": enriched_inventory,
        }
        # The wrapper has already enforced the native controller boundary.  Pass
        # the enriched, controller-authorized payload through the existing
        # persistence/dedup/registry owner with known_sources=None so the retired
        # TITLE:\"MethodName\" resolver is not entered.
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
        )

    l4_inventory_module._manifest_base = manifest_base
    l4_inventory_module.run_discovery = run_discovery
    l4_inventory_module._contextual_literature_original_run_discovery = original_run_discovery
    l4_inventory_module._contextual_literature_original_manifest_base = original_manifest_base
    l4_inventory_module._contextual_literature_installed = True
