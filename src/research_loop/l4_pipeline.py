"""Contracts for the staged L4 method-planning pipeline.

The module starts with the transport-neutral L4A discovery contract and the
ordered stage identities. Runtime orchestration is added incrementally behind
these contracts; mature L4 evidence validation remains in the existing focused
extensions.
"""
from __future__ import annotations


PIPELINE_SCHEMA_VERSION = "L4MethodPlanningPipeline/v1"
L4A_DISCOVERY_SCHEMA_VERSION = "L4ADiscoveryManifest/v1"
L45_COMMIT_SCHEMA_VERSION = "L45MethodCommit/v1"


L4_PIPELINE_STAGES = (
    {
        "stage_id": "L4A",
        "responsibility": "literature_discovery",
        "cognitive": True,
        "storage_key": "L4A_discovery",
    },
    {
        "stage_id": "L4B",
        "responsibility": "evidence_construction",
        "cognitive": True,
        "storage_key": "L4B_evidence",
    },
    {
        "stage_id": "L4C",
        "responsibility": "fisher_method_design",
        "cognitive": True,
        "storage_key": "L4_fisher",
    },
    {
        "stage_id": "L4.5",
        "responsibility": "deterministic_commit",
        "cognitive": False,
        "storage_key": "L45_method_commit",
    },
)


def _string_array_schema() -> dict:
    return {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
    }


def l4a_discovery_schema() -> dict:
    """Return the strict metadata-only provider contract for L4A.

    The schema intentionally has no full-text or method-evidence fields. L4A
    locates and selects assets; the existing L4B evidence stack owns source
    retrieval, verbatim anchors, and method-candidate construction.
    """
    query = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query_id": {"type": "string", "minLength": 1},
            "query": {"type": "string", "minLength": 1},
            "purpose": {"type": "string", "minLength": 1},
            "status": {"enum": ["completed", "failed", "partial"]},
            "receipt": {"type": "string"},
        },
        "required": ["query_id", "query", "purpose", "status", "receipt"],
    }
    asset = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "asset_id": {"type": "string", "minLength": 1},
            "doi": {"type": "string"},
            "pmid": {"type": "string"},
            "url": {"type": "string"},
            "title": {"type": "string", "minLength": 1},
            "year": {"type": "integer"},
            "journal": {"type": "string"},
            "abstract": {"type": "string"},
            "source_database": {"type": "string", "minLength": 1},
            "source_metadata_response": {
                "type": "object",
                "additionalProperties": True,
            },
            "open_access_status": {
                "enum": ["open", "closed", "unknown"]
            },
            "full_text_status": {
                "enum": [
                    "available_local",
                    "available_oa",
                    "metadata_only",
                    "manual_required",
                ]
            },
            "full_text_locations": _string_array_schema(),
            "relevance_score": {
                "type": "number",
                "minimum": 0,
                "maximum": 10,
            },
            "selection_status": {
                "enum": ["selected", "reserve", "rejected", "manual_review"]
            },
            "selection_reason": {"type": "string", "minLength": 1},
            "hypothesis_ids": _string_array_schema(),
            "method_component_hints": _string_array_schema(),
            "diagnostic_requirements": _string_array_schema(),
        },
        "required": [
            "asset_id",
            "doi",
            "pmid",
            "url",
            "title",
            "year",
            "journal",
            "abstract",
            "source_database",
            "source_metadata_response",
            "open_access_status",
            "full_text_status",
            "full_text_locations",
            "relevance_score",
            "selection_status",
            "selection_reason",
            "hypothesis_ids",
            "method_component_hints",
            "diagnostic_requirements",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "string",
                "const": L4A_DISCOVERY_SCHEMA_VERSION,
            },
            "queries": {
                "type": "array",
                "minItems": 1,
                "items": query,
            },
            "assets": {
                "type": "array",
                "items": asset,
            },
        },
        "required": ["schema_version", "queries", "assets"],
    }
