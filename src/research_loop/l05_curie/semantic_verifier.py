"""Semantic verification after deterministic source fidelity.

The assessor may judge entailment, scope, context, and qualification preservation.
It cannot rewrite evidence identity, source fidelity, or the policy verdict.
Ambiguous evidence remains representable but is not reasoning-authorized.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from .contracts import CurieContractError, validate_evidence_extract

SEMANTIC_VERIFICATION_SCHEMA_VERSION = "L05SemanticVerification/v1"
_ENTAILMENT = {"SUPPORTED", "CONTRADICTED", "AMBIGUOUS", "UNRELATED"}
_VERDICTS = {"PASS", "AMBIGUOUS", "FAIL"}
_FORBIDDEN_ASSESSOR_KEYS = {
    "evidence_id", "paper_id", "source_fidelity", "verdict",
    "verification_status", "role", "text", "locator",
}


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    return text


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise CurieContractError(f"{name} must be boolean")
    return value


def validate_semantic_verification(result: dict) -> dict:
    if not isinstance(result, dict):
        raise CurieContractError("semantic verification must be an object")
    if result.get("schema_version") != SEMANTIC_VERIFICATION_SCHEMA_VERSION:
        raise CurieContractError("semantic verification schema_version is invalid")
    _text(result.get("evidence_id"), "semantic verification evidence_id")
    _text(result.get("paper_id"), "semantic verification paper_id")
    if result.get("source_fidelity") != "PASS":
        raise CurieContractError(
            "semantic verification source_fidelity must be PASS after deterministic verification"
        )
    entailment = _text(result.get("entailment"), "semantic verification entailment").upper()
    if entailment not in _ENTAILMENT:
        raise CurieContractError(
            f"semantic verification entailment must be one of {sorted(_ENTAILMENT)}"
        )
    for field in ("scope_match", "context_preserved", "qualification_preserved"):
        _bool(result.get(field), f"semantic verification {field}")
    verdict = _text(result.get("verdict"), "semantic verification verdict").upper()
    if verdict not in _VERDICTS:
        raise CurieContractError(
            f"semantic verification verdict must be one of {sorted(_VERDICTS)}"
        )
    _text(result.get("reason"), "semantic verification reason")
    _text(result.get("claim_sha256"), "semantic verification claim_sha256")
    return json.loads(json.dumps(result))


def _policy_verdict(assessment: dict) -> str:
    if not all(
        assessment[field]
        for field in ("scope_match", "context_preserved", "qualification_preserved")
    ):
        return "FAIL"
    entailment = assessment["entailment"]
    if entailment in {"SUPPORTED", "CONTRADICTED"}:
        return "PASS"
    if entailment == "AMBIGUOUS":
        return "AMBIGUOUS"
    return "FAIL"


class SemanticEvidenceVerifier:
    """Apply a semantic assessor under a fixed, non-delegable admission policy."""

    def __init__(self, *, assessor: Callable, assessor_id: str = "semantic-assessor/v1") -> None:
        if not callable(assessor):
            raise CurieContractError("semantic assessor must be callable")
        self.assessor = assessor
        self.assessor_id = _text(assessor_id, "semantic assessor_id")

    def verify(self, extract: dict, *, claim: str) -> dict:
        if not isinstance(extract, dict) or extract.get("verification_status") != "LOCATED":
            raise CurieContractError(
                "semantic verification requires LOCATED deterministic source fidelity"
            )
        validate_evidence_extract(extract)
        claim = _text(claim, "semantic verification claim")
        try:
            raw = self.assessor(extract=json.loads(json.dumps(extract)), claim=claim)
        except Exception as exc:
            raise CurieContractError(f"semantic assessor failed: {exc}") from exc
        if not isinstance(raw, dict):
            raise CurieContractError("semantic assessor must return an object")
        forbidden = sorted(_FORBIDDEN_ASSESSOR_KEYS.intersection(raw))
        if forbidden:
            raise CurieContractError(
                "semantic assessor authority violation; forbidden fields: " + ", ".join(forbidden)
            )
        entailment = _text(raw.get("entailment"), "semantic assessor entailment").upper()
        if entailment not in _ENTAILMENT:
            raise CurieContractError(
                f"semantic assessor entailment must be one of {sorted(_ENTAILMENT)}"
            )
        assessment = {
            "entailment": entailment,
            "scope_match": _bool(raw.get("scope_match"), "semantic assessor scope_match"),
            "context_preserved": _bool(
                raw.get("context_preserved"), "semantic assessor context_preserved"
            ),
            "qualification_preserved": _bool(
                raw.get("qualification_preserved"),
                "semantic assessor qualification_preserved",
            ),
            "reason": _text(raw.get("reason"), "semantic assessor reason"),
        }
        result = {
            "schema_version": SEMANTIC_VERIFICATION_SCHEMA_VERSION,
            "evidence_id": str(extract["evidence_id"]),
            "paper_id": str(extract["paper_id"]),
            "source_fidelity": "PASS",
            **assessment,
            "verdict": _policy_verdict(assessment),
            "reason": assessment["reason"],
            "claim_sha256": hashlib.sha256(claim.encode("utf-8")).hexdigest(),
            "assessor_id": self.assessor_id,
        }
        return validate_semantic_verification(result)


def reasoning_authorized(result: dict) -> bool:
    validated = validate_semantic_verification(result)
    return (
        validated["source_fidelity"] == "PASS"
        and validated["verdict"] == "PASS"
        and validated["entailment"] in {"SUPPORTED", "CONTRADICTED"}
    )


def admit_reasoning_evidence(extracts: list[dict], semantic_results: list[dict]) -> list[dict]:
    """Return only extracts explicitly authorized by one matching semantic result.

    Semantic results themselves remain separate audit artifacts; this function
    controls which source-located extracts may enter a reasoning-authorized pack.
    """
    if not isinstance(extracts, list) or not isinstance(semantic_results, list):
        raise CurieContractError("reasoning admission requires evidence and semantic lists")
    semantic_by_id = {}
    for result in semantic_results:
        validated = validate_semantic_verification(result)
        evidence_id = validated["evidence_id"]
        if evidence_id in semantic_by_id:
            raise CurieContractError(
                f"duplicate semantic verification for evidence_id {evidence_id}"
            )
        semantic_by_id[evidence_id] = validated
    admitted = []
    for extract in extracts:
        validated_extract = validate_evidence_extract(extract)
        evidence_id = validated_extract["evidence_id"]
        semantic = semantic_by_id.get(evidence_id)
        if semantic is None:
            raise CurieContractError(
                f"located evidence {evidence_id} has no semantic verification"
            )
        if semantic["paper_id"] != validated_extract["paper_id"]:
            raise CurieContractError(
                f"semantic verification paper identity mismatch for {evidence_id}"
            )
        if reasoning_authorized(semantic):
            admitted.append(validated_extract)
    return admitted
