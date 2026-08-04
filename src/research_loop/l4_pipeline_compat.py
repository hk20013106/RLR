"""Compatibility bridge for the staged L4A discovery call.

Older tests and third-party ARS wrappers may return the historical full evidence
payload even when invoked for discovery. The bridge projects that response to
metadata-only L4A records and keeps the mature L4B schema at the historical
work-directory path.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from research_loop.l4_pipeline import L4A_DISCOVERY_SCHEMA_VERSION, _sha256_json


_PARSER_LOCK = threading.Lock()


def _legacy_evidence_to_discovery(payload: dict) -> dict:
    if payload.get("schema_version") == L4A_DISCOVERY_SCHEMA_VERSION:
        return payload
    papers = payload.get("papers")
    if not isinstance(papers, list):
        return payload

    query_values = payload.get("queries") or ["legacy L4 method review"]
    queries = []
    for index, value in enumerate(query_values, 1):
        if isinstance(value, dict):
            query = str(value.get("query") or value.get("text") or "legacy query")
            purpose = str(value.get("purpose") or "Discover method literature")
            status = str(value.get("status") or "completed")
            receipt = str(value.get("receipt") or "legacy evidence response")
        else:
            query = str(value)
            purpose = "Discover method literature"
            status = "completed"
            receipt = "legacy evidence response"
        queries.append({
            "query_id": f"Q{index}",
            "query": query,
            "purpose": purpose,
            "status": status if status in {"completed", "failed", "partial"} else "completed",
            "receipt": receipt,
        })

    assets = []
    for index, paper in enumerate(papers, 1):
        metadata = paper.get("metadata") or {}
        identifier = (
            paper.get("doi") or paper.get("pmid") or paper.get("url")
            or paper.get("title") or f"paper-{index}"
        )
        asset_id = f"LEGACY-{_sha256_json({'identifier': identifier, 'index': index})[:12]}"
        locations = [str(paper.get("url"))] if paper.get("url") else []
        has_payload = bool(str(paper.get("source_payload") or "").strip())
        open_access = bool(paper.get("open_access"))
        assets.append({
            "asset_id": asset_id,
            "doi": str(paper.get("doi") or ""),
            "pmid": str(paper.get("pmid") or ""),
            "url": str(paper.get("url") or ""),
            "title": str(paper.get("title") or identifier),
            "year": int(metadata.get("year") or 0),
            "journal": str(metadata.get("journal") or ""),
            "role": "unspecified",
            "abstract": "",
            "source_database": str(paper.get("source_database") or "legacy"),
            "source_metadata_response": paper.get("source_metadata_response"),
            "open_access_status": "open" if open_access else "unknown",
            "full_text_status": (
                "available_oa" if has_payload or open_access else "metadata_only"
            ),
            "full_text_locations": locations,
            "relevance_score": 10.0,
            "selection_status": "selected",
            "selection_reason": "Projected from a legacy L4 evidence response.",
            "hypothesis_ids": [],
            "method_component_hints": [],
            "diagnostic_requirements": [],
        })
    return {
        "schema_version": L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": queries,
        "assets": assets,
    }


def install(l4_pipeline_module, deep_research_module) -> None:
    if getattr(l4_pipeline_module, "_l4_pipeline_compat_installed", False):
        return
    original = l4_pipeline_module.run_l4a_discovery

    def run_l4a_discovery(
        project_dir, candidate_id, question, claim, spec, work_dir,
        skill_version="unknown", *, project_id="", round_id="", profile_id="",
    ):
        root = Path(work_dir)
        root.mkdir(parents=True, exist_ok=True)
        # Preserve the historical path and the exact provider-facing L4B schema
        # for diagnostics and callers that inspect a failed invocation. The
        # reader schema permits navigation-only anchor fields to be omitted,
        # whereas the provider schema must require every declared property.
        schema = deep_research_module._runtime_schema("L4")
        extract = schema["properties"]["papers"]["items"]["properties"][
            "extracts"
        ]["items"]
        extract["required"] = list(extract["properties"])
        (root / "deep_research_output.schema.json").write_text(
            json.dumps(schema, indent=2),
            encoding="utf-8",
        )
        discovery_work = root / "L4A"
        with _PARSER_LOCK:
            original_parser = deep_research_module._parse_cli_output

            def compatible_parser(stdout):
                return _legacy_evidence_to_discovery(original_parser(stdout))

            deep_research_module._parse_cli_output = compatible_parser
            try:
                return original(
                    project_dir, candidate_id, question, claim, spec,
                    discovery_work, skill_version, project_id=project_id,
                    round_id=round_id, profile_id=profile_id,
                )
            finally:
                deep_research_module._parse_cli_output = original_parser

    l4_pipeline_module._l4_pipeline_compat_original_run_l4a = original
    l4_pipeline_module.run_l4a_discovery = run_l4a_discovery
    l4_pipeline_module._l4_pipeline_compat_installed = True
