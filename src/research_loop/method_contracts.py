"""Native v2.1 contracts for evidence-backed method selection."""
from __future__ import annotations

import copy


_L4C_REFERENCE_FIELDS = {
    "evidence_card_ids": "evidence_card_handles",
    "evidence_gap_ids": "evidence_gap_handles",
    "method_anchor_ids": "method_anchor_handles",
}


def _rename_schema_fields(value, mapping):
    """Rename contract field references in properties and conditional rules."""
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            for old, new in mapping.items():
                if old in properties:
                    properties[new] = properties.pop(old)
        required = value.get("required")
        if isinstance(required, list):
            value["required"] = [mapping.get(item, item) for item in required]
        dependent = value.get("dependentRequired")
        if isinstance(dependent, dict):
            value["dependentRequired"] = {
                mapping.get(key, key): [mapping.get(item, item) for item in values]
                for key, values in dependent.items()
            }
        for child in value.values():
            _rename_schema_fields(child, mapping)
    elif isinstance(value, list):
        for child in value:
            _rename_schema_fields(child, mapping)


def _string_array(*, min_items=0):
    return {
        "type": "array", "minItems": min_items, "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }


def validate_input_requirements(candidate: dict) -> None:
    """Keep executable inputs, optional diagnostics, and source gaps separate."""
    required = {
        str(value).strip().casefold()
        for value in candidate.get("required_inputs", [])
        if str(value).strip()
    }
    optional = {
        str(value).strip().casefold()
        for value in candidate.get("optional_diagnostics", [])
        if str(value).strip()
    }
    overlap = sorted(required & optional)
    if overlap:
        raise ValueError(
            "L4C required_inputs and optional_diagnostics overlap: "
            + ", ".join(overlap)
        )
    status = str(candidate.get("status") or "")
    if status == "needs_user_source" and candidate.get("missing_inputs"):
        raise ValueError(
            "L4C needs_user_source cannot carry missing_inputs; use needs_user_data"
        )
    if status == "needs_user_data" and str(candidate.get("missing_source") or "").strip():
        raise ValueError(
            "L4C needs_user_data cannot carry missing_source; reserve it for evidence"
        )


def install(contracts_module) -> None:
    """Add an atomic optional extension to v2.1; legacy deltas remain readable."""
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
        "status": {"enum": [
            "eligible", "ineligible", "needs_user_source", "needs_user_data",
        ]},
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
        "required_inputs": _string_array(min_items=1),
        "optional_diagnostics": _string_array(),
        "missing_inputs": _string_array(),
        # Staged L4 v2 fields. They are additive so historical native-v2.1
        # deltas remain readable. Once one appears, all three are required.
        "execution_required": {"type": "boolean"},
        "evidence_card_ids": _string_array(),
        "evidence_gap_ids": _string_array(),
    }, [
        "method_id", "component_id", "hypothesis_ids", "name", "status",
        "purpose", "applicable_to", "implementation_steps", "assumptions",
        "expected_outputs", "strengths", "limitations", "alternatives",
        "method_anchor_ids", "rejection_reasons", "missing_source",
    ])
    staged_fields = (
        "execution_required", "evidence_card_ids", "evidence_gap_ids"
    )
    candidate["dependentRequired"] = {
        field: [other for other in staged_fields if other != field]
        for field in staged_fields
    }
    candidate["allOf"] = [
        {
            # Historical eligible candidates predate evidence cards and keep
            # their original method-anchor requirement.
            "if": {
                "allOf": [
                    {
                        "properties": {"status": {"const": "eligible"}},
                        "required": ["status"],
                    },
                    {"not": {"required": ["execution_required"]}},
                ]
            },
            "then": {"properties": {"method_anchor_ids": {"minItems": 1}}},
        },
        {
            # New staged runs require strong evidence only for Fisher-declared
            # implementation paths. Optional alternatives may carry gaps.
            "if": {
                "properties": {
                    "status": {"const": "eligible"},
                    "execution_required": {"const": True},
                },
                "required": ["status", "execution_required"],
            },
            "then": {"properties": {"evidence_card_ids": {"minItems": 1}}},
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
        {
            "if": {"properties": {"status": {"const": "needs_user_data"}},
                   "required": ["status"]},
            "then": {"properties": {"missing_inputs": {"minItems": 1}}},
        },
    ]

    l4 = schemas["L4"]
    method_fields = (
        "deep_research_run_id", "method_components", "method_candidates"
    )
    l4["properties"].update({
        "deep_research_run_id": hc._ID,
        "method_components": {
            "type": "array", "minItems": 1, "items": component,
        },
        "method_candidates": {
            "type": "array", "minItems": 1, "items": candidate,
        },
    })
    # Compatibility cutover: an old v2.1 L4 delta may omit the extension.
    # Once any extension field is present, all three become mandatory.
    dependencies = l4.setdefault("dependentRequired", {})
    for field in method_fields:
        dependencies[field] = [other for other in method_fields if other != field]

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
    schemas["L5"]["properties"]["method_critiques"] = {
        "type": "array", "minItems": 1, "items": critique,
    }

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
        "evidence_card_ids": _string_array(),
        "l5_qc_requirements": _string_array(),
    }, [
        "component_id", "selected_method_ids", "decision_rationale",
        "rejected_alternatives", "parameters", "software_requirements",
        "scripts", "method_anchor_ids", "l5_qc_requirements",
    ])
    schemas["L6"]["properties"]["selected_methods"] = {
        "type": "array", "minItems": 1, "items": selection,
    }

    # Rebuild the persisted v2.1 contracts from the extended submission schemas.
    hc.PERSISTED_SCHEMA_REGISTRY["2.1"] = {
        node: hc._persisted_schema(node, "2.1") for node in schemas
    }

    # Native catalog providers receive local handles.  The historical v2.1
    # registry remains the canonical-ID wire contract for the legacy profile;
    # the profile-specific projection prevents those two paths from sharing a
    # semantically ambiguous schema.
    provider_l4 = copy.deepcopy(l4)
    _rename_schema_fields(provider_l4, _L4C_REFERENCE_FIELDS)
    provider_candidate = provider_l4["properties"]["method_candidates"]["items"]
    provider_candidate["required"].extend([
        "required_inputs", "optional_diagnostics", "missing_inputs",
    ])
    hc.PROVIDER_SCHEMA_REGISTRY["v2.1-catalog-1"] = {
        "2.1": {"L4": provider_l4}
    }
    hc._METHOD_CONTRACTS_INSTALLED = True
