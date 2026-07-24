"""Versioned JSON Schemas for hypothesis-ledger delta submissions."""
from __future__ import annotations

import copy
from typing import Any

import jsonschema


DELTA_SCHEMA_VERSION = "2.0"
EPISTEMIC_STATUSES = {
    "UNASSESSED", "INSUFFICIENT_EVIDENCE", "PROVISIONALLY_SUPPORTED",
    "CONTRADICTED", "FALSIFIED",
}
LOOP_TYPES = {"correction", "divergent", "data-acquisition"}

_ID = {"type": "string", "minLength": 1}
_STR = {"type": "string", "minLength": 1}
_REF = {
    "type": "object",
    "properties": {
        "path": _STR,
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "json_pointer": {"type": "string"},
    },
    "required": ["path", "sha256"],
    "additionalProperties": False,
}


def _object(properties: dict[str, Any], required: list[str], *, extra=False):
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": extra}


def _target_ids():
    return {"type": "array", "minItems": 1, "uniqueItems": True, "items": _ID}


def _base():
    return {"schema_version": {"const": DELTA_SCHEMA_VERSION},
            "candidate_id": _ID}


def _node_schema(node: str) -> dict[str, Any]:
    props = _base()
    required = ["schema_version"]
    if node == "L1":
        hypothesis = _object({
            "proposal_key": _STR, "statement": _STR,
            "operationalization": _STR,
            "falsification_criteria": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": _STR,
            },
            "rationale": _STR,
        }, ["proposal_key", "statement", "operationalization",
            "falsification_criteria", "rationale"])
        props.update({
            "hypotheses": {"type": "array", "minItems": 1, "items": hypothesis},
            "primary_proposal_key": _STR,
            "key_uncertainty": _STR,
        })
        required += ["hypotheses", "primary_proposal_key", "key_uncertainty"]
    elif node == "L2":
        attack = _object({"hypothesis_id": _ID, "severity": _STR, "text": _STR},
                         ["hypothesis_id", "severity", "text"])
        confounder = _object({"hypothesis_id": _ID, "name": _STR,
                              "severity": _STR, "text": _STR},
                             ["hypothesis_id", "name", "severity", "text"])
        diagnostic = _object({"hypothesis_id": _ID, "name": _STR, "text": _STR},
                             ["hypothesis_id", "name", "text"])
        verdict = _object({"hypothesis_id": _ID,
                           "outcome": {"enum": ["SURVIVES", "REVISE", "REJECT"]},
                           "reason": _STR},
                          ["hypothesis_id", "outcome", "reason"])
        props.update({"attacks": {"type": "array", "items": attack},
                      "confounders": {"type": "array", "items": confounder},
                      "diagnostic_tests": {"type": "array", "items": diagnostic},
                      "verdicts": {"type": "array", "minItems": 1, "items": verdict}})
        required += ["attacks", "confounders", "diagnostic_tests", "verdicts"]
    elif node == "L3":
        item = _object({"hypothesis_id": _ID,
                        "disposition": {"enum": ["SELECTED", "REJECTED"]},
                        "reason_code": _STR, "reason": _STR},
                       ["hypothesis_id", "disposition", "reason_code", "reason"])
        props.update({"triage": {"type": "array", "minItems": 1, "items": item},
                      "route_to": _STR})
        required += ["triage", "route_to"]
    elif node == "L4":
        strategy = _object({"strategy_id": _ID, "hypothesis_ids": _target_ids(),
                            "name": _STR, "steps": {"type": "array", "items": _STR}},
                           ["strategy_id", "hypothesis_ids", "name", "steps"], extra=True)
        props["strategies"] = {"type": "array", "minItems": 1, "items": strategy}
        required += ["strategies"]
    elif node == "L5":
        attack = _object({"hypothesis_ids": _target_ids(), "strategy_id": _ID,
                          "severity": _STR, "text": _STR},
                         ["hypothesis_ids", "strategy_id", "severity", "text"])
        checkpoint = _object({"hypothesis_ids": _target_ids(), "strategy_id": _ID,
                              "name": _STR, "criterion": _STR},
                             ["hypothesis_ids", "strategy_id", "name", "criterion"])
        stop_rule = _object({"hypothesis_ids": _target_ids(), "strategy_id": _ID,
                             "name": _STR, "condition": _STR, "reason": _STR},
                            ["hypothesis_ids", "strategy_id", "name", "condition", "reason"])
        props.update({"attacks": {"type": "array", "items": attack},
                      "qc_checkpoints": {"type": "array", "items": checkpoint},
                      "failure_stop_rules": {"type": "array", "items": stop_rule}})
        required += ["attacks", "qc_checkpoints", "failure_stop_rules"]
    elif node == "L6":
        plan = _object({"hypothesis_ids": _target_ids(), "strategy_id": _ID,
                        "scripts": {"type": "array"}, "parameters": {"type": "object"},
                        "outputs": {"type": "array"}},
                       ["hypothesis_ids", "strategy_id", "scripts", "parameters", "outputs"],
                       extra=True)
        props.update({"analysis_plan": {"type": "array", "minItems": 1, "items": plan},
                      "method_decision": {"enum": ["APPROVE", "REJECT"]},
                      "reason": _STR})
        required += ["analysis_plan", "method_decision", "reason"]
    elif node == "L7":
        result = _object({"result_key": _STR, "hypothesis_ids": _target_ids(),
                          "summary": _STR,
                          "artifact_refs": {"type": "array", "minItems": 1,
                                            "items": _REF}},
                         ["result_key", "hypothesis_ids", "summary", "artifact_refs"])
        props.update({"results": {"type": "array", "minItems": 1, "items": result},
                      "scripts_run": {"type": "array"}, "warnings": {"type": "array"},
                      "failures": {"type": "array"}})
        required += ["results", "scripts_run", "warnings", "failures"]
    elif node == "L8":
        relation = _object({"hypothesis_id": _ID,
                            "outcome": {"enum": ["SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"]},
                            "reason": _STR}, ["hypothesis_id", "outcome", "reason"])
        assessment = _object({"evidence_id": _ID,
                              "verification": {"enum": ["VERIFIED", "REJECTED"]},
                              "relations": {"type": "array", "items": relation}},
                             ["evidence_id", "verification", "relations"])
        props["evidence_assessments"] = {"type": "array", "items": assessment}
        required += ["evidence_assessments"]
    elif node == "L8.5":
        assessment = _object({"hypothesis_id": _ID,
                              "outcome": {"enum": ["SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"]},
                              "comparison": _STR,
                              "evidence_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                                               "items": _ID}},
                             ["hypothesis_id", "outcome", "comparison", "evidence_ids"])
        props.update({"deep_research_run_id": _ID, "deep_research_receipt_hash": {
                          "type": "string", "pattern": "^[0-9a-f]{64}$"},
                      "assessments": {"type": "array", "minItems": 1,
                                      "items": assessment}, "summary": _STR})
        required += ["deep_research_run_id", "deep_research_receipt_hash",
                     "assessments", "summary"]
    elif node == "L9a":
        assessment = _object({"hypothesis_id": _ID,
                              "epistemic_status": {"enum": sorted(EPISTEMIC_STATUSES)},
                              "reason": _STR,
                              "evidence_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                                               "items": _ID},
                              "falsification_criterion": {"type": "string"},
                              "supersedes_event_id": {"type": "string"}},
                             ["hypothesis_id", "epistemic_status", "reason", "evidence_ids"],
                             extra=True)
        props["assessments"] = {"type": "array", "minItems": 1, "items": assessment}
        required += ["assessments"]
    elif node == "L9b":
        assessment = _object({"hypothesis_id": _ID, "interpretation": _STR,
                              "evidence_ids": {"type": "array", "uniqueItems": True,
                                               "items": _ID},
                              "limitations": {"type": "array", "items": _STR},
                              "convergent_evolution": _STR},
                             ["hypothesis_id", "interpretation", "evidence_ids",
                              "limitations", "convergent_evolution"])
        props["assessments"] = {"type": "array", "minItems": 1, "items": assessment}
        required += ["assessments"]
    elif node == "L10a":
        assessment = _object({"hypothesis_id": _ID, "value_assessment": _STR,
                              "headline": _STR,
                              "publishable_now": {"type": "array", "items": _STR},
                              "needs_more_work": {"type": "array", "items": _STR},
                              "manuscript_framing": _STR},
                             ["hypothesis_id", "value_assessment", "headline",
                              "publishable_now", "needs_more_work", "manuscript_framing"])
        props["assessments"] = {"type": "array", "minItems": 1, "items": assessment}
        required += ["assessments"]
    elif node == "L10b":
        disposition = _object({"hypothesis_id": _ID,
                               "disposition": {"enum": ["RETAIN", "REVISE", "ARCHIVE"]},
                               "reason": _STR},
                              ["hypothesis_id", "disposition", "reason"])
        proposal = _object({"proposal_key": _STR, "statement": _STR,
                            "operationalization": _STR,
                            "falsification_criteria": {"type": "array", "minItems": 1,
                                                       "items": _STR},
                            "relationship": {"enum": ["REVISION_OF", "DERIVED_FROM"]},
                            "parent_hypothesis_ids": _target_ids(),
                            "loop_type": {"enum": sorted(LOOP_TYPES)}, "reason": _STR},
                           ["proposal_key", "statement", "operationalization",
                            "falsification_criteria", "relationship",
                            "parent_hypothesis_ids", "loop_type", "reason"])
        props.update({"decision": {"enum": ["KEEP", "REVISE", "DOWNGRADE", "DROP"]},
                      "reason": _STR,
                      "next_steps": {"type": "array", "items": _STR},
                      "hypothesis_decisions": {"type": "array", "items": disposition},
                      "next_round_proposal": proposal})
        required += ["decision", "reason", "next_steps", "hypothesis_decisions"]
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object", "properties": props, "required": required,
            "additionalProperties": True}


NODE_SCHEMAS = {node: _node_schema(node) for node in (
    "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L8.5",
    "L9a", "L9b", "L10a", "L10b",
)}


def _persisted_schema(node: str) -> dict[str, Any]:
    """Return the engine-normalized artifact contract for a node.

    Submission contracts deliberately omit ledger-owned identity fields.  The
    persisted contract retains all submission fields and permits only the
    explicit identities assigned during normalization.
    """
    schema = copy.deepcopy(NODE_SCHEMAS[node])
    schema["properties"]["project_id"] = _ID
    schema["required"].extend(["candidate_id", "project_id"])
    if node == "L1":
        item = schema["properties"]["hypotheses"]["items"]
        item["properties"].update({"hypothesis_id": _ID,
                                   "hypothesis_family_id": _ID})
        item["required"].extend(["hypothesis_id", "hypothesis_family_id"])
        schema["properties"]["primary_hypothesis_id"] = _ID
        schema["required"].append("primary_hypothesis_id")
    elif node == "L7":
        item = schema["properties"]["results"]["items"]
        item["properties"]["evidence_id"] = _ID
        item["required"].append("evidence_id")
    elif node == "L10b":
        proposal = schema["properties"]["next_round_proposal"]
        proposal["properties"].update({"hypothesis_id": _ID,
                                       "hypothesis_family_id": _ID})
    return schema


PERSISTED_NODE_SCHEMAS = {node: _persisted_schema(node) for node in NODE_SCHEMAS}


def validate_submission(node: str, delta: dict[str, Any]) -> list[str]:
    if node not in NODE_SCHEMAS:
        return [f"unknown ledger node: {node}"]
    errors = sorted(jsonschema.Draft202012Validator(NODE_SCHEMAS[node]).iter_errors(delta),
                    key=lambda error: list(error.absolute_path))
    rendered = []
    for error in errors:
        where = "/".join(str(part) for part in error.absolute_path) or "<root>"
        rendered.append(f"{where}: {error.message}")
    return rendered


def validate_persisted(node: str, delta: dict[str, Any]) -> list[str]:
    if node not in PERSISTED_NODE_SCHEMAS:
        return [f"unknown ledger node: {node}"]
    errors = sorted(
        jsonschema.Draft202012Validator(PERSISTED_NODE_SCHEMAS[node]).iter_errors(delta),
        key=lambda error: list(error.absolute_path),
    )
    rendered = []
    for error in errors:
        where = "/".join(str(part) for part in error.absolute_path) or "<root>"
        rendered.append(f"{where}: {error.message}")
    return rendered
