"""Native v2.1 contracts for evidence-backed method selection."""
from __future__ import annotations


def _string_array(*, min_items=0):
    return {
        "type": "array", "minItems": min_items, "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }


def install(contracts_module) -> None:
    """Extend only native schema 2.1; legacy 2.0 remains byte-compatible."""
    hc = contracts_module
    if getattr(hc, "_METHOD_CONTRACTS_INSTALLED", False):
        return
    schemas = hc.SCHEMA_REGISTRY["2.1"]

    component = hc._object({
        "component_id": hc._ID,
        "name": hc._STR,
        "required": {"type": "boolean"},
        "rationale": hc._STR,
    }, ["component_id", "name", "required", "rationale"])

    candidate = hc._object({
        "method_id": hc._ID,
        "component_id": hc._ID,
        "hypothesis_ids": hc._target_ids(),
        "name": hc._STR,
        "status": {"enum": ["eligible", "ineligible", "needs_user_source"]},
        "purpose": hc._STR,
        "applicable_to": _string_array(min_items=1),
        "implementation_steps": _string_array(min_items=1),
        "assumptions": _string_array(),
        "expected_outputs": _string_array(min_items=1),
        "strengths": _string_array(),
        "limitations": _string_array(),
        "alternatives": _string_array(),
        "method_anchor_ids": _string_array(),
        "rejection_reasons": _string_array(),
        "missing_source": {"type": "string"},
    }, [
        "method_id", "component_id", "hypothesis_ids", "name", "status",
        "purpose", "applicable_to", "implementation_steps", "assumptions",
        "expected_outputs", "strengths", "limitations", "alternatives",
        "method_anchor_ids", "rejection_reasons", "missing_source",
    ])
    candidate["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "eligible"}},
                   "required": ["status"]},
            "then": {"properties": {"method_anchor_ids": {"minItems": 1}}},
        },
        {
            "if": {"properties": {"status": {"const": "ineligible"}},
                   "required": ["status"]},
            "then": {"properties": {"rejection_reasons": {"minItems": 1}}},
        },
        {
            "if": {"properties": {"status": {"const": "needs_user_source"}},
                   "required": ["status"]},
            "then": {"properties": {"missing_source": {"minLength": 1}}},
        },
    ]

    l4 = schemas["L4"]
    l4["properties"].update({
        "deep_research_run_id": hc._ID,
        "method_components": {
            "type": "array", "minItems": 1, "items": component,
        },
        "method_candidates": {
            "type": "array", "minItems": 1, "items": candidate,
        },
    })
    for field in ("deep_research_run_id", "method_components", "method_candidates"):
        if field not in l4["required"]:
            l4["required"].append(field)

    critique = hc._object({
        "method_id": hc._ID,
        "component_id": hc._ID,
        "verdict": {"enum": ["ACCEPT", "MODIFY", "REJECT"]},
        "assumption_risks": _string_array(),
        "required_diagnostics": _string_array(),
        "failure_modes": _string_array(),
        "recommended_modifications": _string_array(),
    }, [
        "method_id", "component_id", "verdict", "assumption_risks",
        "required_diagnostics", "failure_modes", "recommended_modifications",
    ])
    l5 = schemas["L5"]
    l5["properties"]["method_critiques"] = {
        "type": "array", "minItems": 1, "items": critique,
    }
    if "method_critiques" not in l5["required"]:
        l5["required"].append("method_critiques")

    rejected = hc._object({
        "method_id": hc._ID,
        "reason": hc._STR,
    }, ["method_id", "reason"])
    selection = hc._object({
        "component_id": hc._ID,
        "selected_method_ids": _string_array(min_items=1),
        "decision_rationale": hc._STR,
        "rejected_alternatives": {"type": "array", "items": rejected},
        "parameters": {"type": "object"},
        "software_requirements": _string_array(),
        "scripts": _string_array(min_items=1),
        "method_anchor_ids": _string_array(min_items=1),
        "l5_qc_requirements": _string_array(),
    }, [
        "component_id", "selected_method_ids", "decision_rationale",
        "rejected_alternatives", "parameters", "software_requirements",
        "scripts", "method_anchor_ids", "l5_qc_requirements",
    ])
    l6 = schemas["L6"]
    l6["properties"]["selected_methods"] = {
        "type": "array", "minItems": 1, "items": selection,
    }
    if "selected_methods" not in l6["required"]:
        l6["required"].append("selected_methods")

    # Rebuild the persisted v2.1 contracts from the extended submission schemas.
    hc.PERSISTED_SCHEMA_REGISTRY["2.1"] = {
        node: hc._persisted_schema(node, "2.1") for node in schemas
    }
    hc._METHOD_CONTRACTS_INSTALLED = True
