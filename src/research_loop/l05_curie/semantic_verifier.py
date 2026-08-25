"""Semantic verification after deterministic source fidelity.

The assessor may judge entailment, scope, context, and qualification preservation.
It cannot rewrite evidence identity, source fidelity, policy provenance, or the
policy verdict. Ambiguous evidence remains representable but is not
reasoning-authorized.
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
    "schema_version", "evidence_id", "paper_id", "source_fidelity", "verdict",
    "verification_status", "role", "text", "locator", "claim_sha256",
    "extract_sha256", "assessor_id", "contract_sha256", "verification_id",
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


_SEMANTIC_CONTRACT = {
    "schema_version": SEMANTIC_VERIFICATION_SCHEMA_VERSION,
    "source_fidelity_precondition": "LOCATED",
    "assessor_inputs": ["extract", "claim"],
    "assessor_outputs": [
        "entailment", "scope_match", "context_preserved",
        "qualification_preserved", "reason",
    ],
    "bound_provenance": [
        "extract_sha256", "claim_sha256", "assessor_id", "contract_sha256"
    ],
    "entailment_values": sorted(_ENTAILMENT),
    "policy": {
        "PASS": ["SUPPORTED", "CONTRADICTED"],
        "AMBIGUOUS": ["AMBIGUOUS"],
        "FAIL": ["UNRELATED", "scope_or_context_or_qualification_mismatch"],
    },
}
SEMANTIC_CONTRACT_SHA256 = hashlib.sha256(
    _canonical_bytes(_SEMANTIC_CONTRACT)
).hexdigest()


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    return text


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise CurieContractError(f"{name} must be boolean")
    return value


def _sha256_text(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CurieContractError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def evidence_extract_sha256(extract: dict) -> str:
    """Content address the exact validated EvidenceExtract seen by the assessor."""
    validated = validate_evidence_extract(extract)
    return hashlib.sha256(_canonical_bytes(validated)).hexdigest()


def _verification_identity(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "schema_version",
            "evidence_id",
            "paper_id",
            "source_fidelity",
            "entailment",
            "scope_match",
            "context_preserved",
            "qualification_preserved",
            "verdict",
            "reason",
            "extract_sha256",
            "claim_sha256",
            "assessor_id",
            "contract_sha256",
        )
    }


def _verification_id(result: dict) -> str:
    return "SV_" + hashlib.sha256(
        _canonical_bytes(_verification_identity(result))
    ).hexdigest()[:20]


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
    scope_match = _bool(
        result.get("scope_match"), "semantic verification scope_match"
    )
    context_preserved = _bool(
        result.get("context_preserved"), "semantic verification context_preserved"
    )
    qualification_preserved = _bool(
        result.get("qualification_preserved"),
        "semantic verification qualification_preserved",
    )
    verdict = _text(result.get("verdict"), "semantic verification verdict").upper()
    if verdict not in _VERDICTS:
        raise CurieContractError(
            f"semantic verification verdict must be one of {sorted(_VERDICTS)}"
        )
    expected_verdict = _policy_verdict({
        "entailment": entailment,
        "scope_match": scope_match,
        "context_preserved": context_preserved,
        "qualification_preserved": qualification_preserved,
    })
    if verdict != expected_verdict:
        raise CurieContractError(
            "semantic verification verdict violates the non-delegable policy"
        )
    _text(result.get("reason"), "semantic verification reason")
    _sha256_text(result.get("extract_sha256"), "semantic verification extract_sha256")
    _sha256_text(result.get("claim_sha256"), "semantic verification claim_sha256")
    _text(result.get("assessor_id"), "semantic verification assessor_id")
    contract_sha = _sha256_text(
        result.get("contract_sha256"), "semantic verification contract_sha256"
    )
    if contract_sha != SEMANTIC_CONTRACT_SHA256:
        raise CurieContractError(
            "semantic verification contract_sha256 does not match the active semantic contract"
        )
    expected_id = _verification_id(result)
    if str(result.get("verification_id") or "") != expected_id:
        raise CurieContractError(
            "semantic verification identity does not match its provenance content"
        )
    return json.loads(json.dumps(result))


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
        validated_extract = validate_evidence_extract(extract)
        claim = _text(claim, "semantic verification claim")
        try:
            raw = self.assessor(
                extract=json.loads(json.dumps(validated_extract)), claim=claim
            )
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
            "evidence_id": str(validated_extract["evidence_id"]),
            "paper_id": str(validated_extract["paper_id"]),
            "source_fidelity": "PASS",
            **assessment,
            "verdict": _policy_verdict(assessment),
            "reason": assessment["reason"],
            "extract_sha256": evidence_extract_sha256(validated_extract),
            "claim_sha256": hashlib.sha256(claim.encode("utf-8")).hexdigest(),
            "assessor_id": self.assessor_id,
            "contract_sha256": SEMANTIC_CONTRACT_SHA256,
        }
        result["verification_id"] = _verification_id(result)
        return validate_semantic_verification(result)


def reasoning_authorized(result: dict) -> bool:
    validated = validate_semantic_verification(result)
    return (
        validated["source_fidelity"] == "PASS"
        and validated["verdict"] == "PASS"
        and validated["entailment"] in {"SUPPORTED", "CONTRADICTED"}
    )


def admit_reasoning_evidence(extracts: list[dict], semantic_results: list[dict]) -> list[dict]:
    """Return only exact extracts explicitly authorized by semantic verification."""
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
        if semantic["extract_sha256"] != evidence_extract_sha256(validated_extract):
            raise CurieContractError(
                f"semantic verification exact extract SHA mismatch for {evidence_id}; evidence changed"
            )
        if reasoning_authorized(semantic):
            admitted.append(validated_extract)
    return admitted
