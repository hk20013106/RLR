"""Focused native v2.1 contracts for historical hypothesis reuse."""
from __future__ import annotations


def _string_array(*, min_items: int = 0) -> dict:
    return {
        "type": "array",
        "minItems": min_items,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }


def _forbid(*fields: str) -> dict:
    return {
        "not": {
            "anyOf": [{"required": [field]} for field in fields]
        }
    }


def install(contracts_module) -> None:
    """Install additive L1/L3 reactivation schemas after method contracts."""
    hc = contracts_module
    if getattr(hc, "_REACTIVATION_CONTRACTS_INSTALLED", False):
        return

    schemas = hc.SCHEMA_REGISTRY["2.1"]
    l1_item = schemas["L1"]["properties"]["hypotheses"]["items"]

    basis = hc._object(
        {
            "basis_type": {
                "enum": [
                    "NEW_EVIDENCE",
                    "NEW_DATA",
                    "NEW_METHOD",
                    "CHANGED_SCOPE",
                    "CHANGED_FEASIBILITY",
                    "USER_RECONSIDERATION",
                ]
            },
            "summary": hc._STR,
            "evidence_ids": _string_array(),
            "artifact_refs": {"type": "array", "items": hc._REF},
            "changed_conditions": _string_array(),
        },
        [
            "basis_type",
            "summary",
            "evidence_ids",
            "artifact_refs",
            "changed_conditions",
        ],
    )
    l1_item["properties"].update(
        {
            "origin": {
                "enum": ["NEW", "REACTIVATE", "REVISE", "DERIVE"]
            },
            "source_hypothesis_id": hc._ID,
            "source_occurrence_id": hc._ID,
            "parent_hypothesis_ids": _string_array(min_items=1),
            "change_summary": hc._STR,
            "reactivation_basis": basis,
        }
    )
    l1_rules = l1_item.setdefault("allOf", [])
    l1_rules.extend(
        [
            {
                "if": {
                    "anyOf": [
                        {"required": ["source_hypothesis_id"]},
                        {"required": ["source_occurrence_id"]},
                        {"required": ["parent_hypothesis_ids"]},
                        {"required": ["change_summary"]},
                        {"required": ["reactivation_basis"]},
                    ]
                },
                "then": {"required": ["origin"]},
            },
            {
                "if": {
                    "properties": {"origin": {"const": "NEW"}},
                    "required": ["origin"],
                },
                "then": _forbid(
                    "source_hypothesis_id",
                    "source_occurrence_id",
                    "parent_hypothesis_ids",
                    "change_summary",
                    "reactivation_basis",
                ),
            },
            {
                "if": {
                    "properties": {"origin": {"const": "REACTIVATE"}},
                    "required": ["origin"],
                },
                "then": {
                    "required": [
                        "source_hypothesis_id",
                        "source_occurrence_id",
                    ],
                    **_forbid("parent_hypothesis_ids", "change_summary"),
                },
            },
            {
                "if": {
                    "properties": {"origin": {"const": "REVISE"}},
                    "required": ["origin"],
                },
                "then": {
                    "required": ["source_hypothesis_id", "change_summary"],
                    **_forbid("parent_hypothesis_ids", "reactivation_basis"),
                },
            },
            {
                "if": {
                    "properties": {"origin": {"const": "DERIVE"}},
                    "required": ["origin"],
                },
                "then": {
                    "required": ["parent_hypothesis_ids", "change_summary"],
                    **_forbid(
                        "source_hypothesis_id",
                        "source_occurrence_id",
                        "reactivation_basis",
                    ),
                },
            },
        ]
    )

    l3_item = schemas["L3"]["properties"]["triage"]["items"]
    assessment = hc._object(
        {
            "source_hypothesis_id": hc._ID,
            "prior_blocking_event_ids": _string_array(),
            "basis_verdict": {
                "enum": [
                    "RESOLVED",
                    "PARTIALLY_RESOLVED",
                    "UNRESOLVED",
                    "NOT_APPLICABLE",
                ]
            },
            "reason": hc._STR,
            "remaining_risks": _string_array(),
        },
        [
            "source_hypothesis_id",
            "prior_blocking_event_ids",
            "basis_verdict",
            "reason",
            "remaining_risks",
        ],
    )
    obligation = hc._object(
        {
            "obligation_id": hc._ID,
            "type": {
                "enum": [
                    "QC",
                    "QC_CHECK",
                    "STOP_RULE",
                    "DATA_REQUIREMENT",
                ]
            },
            "description": hc._STR,
            "source_blocker_event_ids": _string_array(),
        },
        [
            "obligation_id",
            "type",
            "description",
            "source_blocker_event_ids",
        ],
    )
    l3_item["properties"].update(
        {
            "reactivation_assessment": assessment,
            "downstream_obligations": {
                "type": "array",
                "uniqueItems": True,
                "items": obligation,
            },
        }
    )
    l3_rules = l3_item.setdefault("allOf", [])
    l3_rules.extend(
        [
            {
                "not": {
                    "properties": {
                        "disposition": {"const": "SELECTED"},
                        "reactivation_assessment": {
                            "properties": {
                                "basis_verdict": {"const": "UNRESOLVED"}
                            },
                            "required": ["basis_verdict"],
                        },
                    },
                    "required": [
                        "disposition",
                        "reactivation_assessment",
                    ],
                }
            },
            {
                "if": {
                    "properties": {
                        "disposition": {"const": "SELECTED"},
                        "reactivation_assessment": {
                            "properties": {
                                "basis_verdict": {
                                    "const": "PARTIALLY_RESOLVED"
                                }
                            },
                            "required": ["basis_verdict"],
                        },
                    },
                    "required": [
                        "disposition",
                        "reactivation_assessment",
                    ],
                },
                "then": {
                    "required": ["downstream_obligations"],
                    "properties": {
                        "downstream_obligations": {"minItems": 1}
                    },
                },
            },
        ]
    )

    # method_contracts may already have rebuilt these schemas. Rebuild once more
    # after the reactivation extension. Persisted legacy v2.1 artifacts may omit
    # origin; new commits normalize it before persistence.
    hc.PERSISTED_SCHEMA_REGISTRY["2.1"] = {
        node: hc._persisted_schema(node, "2.1") for node in schemas
    }
    hc._REACTIVATION_CONTRACTS_INSTALLED = True
