"""Generic deterministic source-fidelity verifier for Curie candidates.

Retrieval engines may propose text and locators. This verifier independently
checks the proposed text against supplied source bytes and is the only component
in this generic path allowed to promote an UNVERIFIED candidate to a LOCATED
EvidenceExtract.
"""
from __future__ import annotations

import hashlib
import json

from .contracts import (
    EVIDENCE_EXTRACT_SCHEMA_VERSION,
    CurieContractError,
    validate_evidence_extract,
)

_ROLES = {"SUPPORTING", "CONTRADICTORY", "CONTEXT", "METHOD"}


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    return text


def _normalize(value: str) -> str:
    return " ".join(value.split())


class ExactTextSourceVerifier:
    """Verify that an unverified candidate is literally present in source bytes."""

    def verify(self, candidate: dict, *, source_bytes: bytes,
               role: str = "CONTEXT") -> dict:
        if not isinstance(candidate, dict):
            raise CurieContractError("source verifier candidate must be an object")
        if candidate.get("verification_status") != "UNVERIFIED":
            raise CurieContractError(
                "source verifier requires an UNVERIFIED retrieval candidate"
            )
        if not isinstance(source_bytes, (bytes, bytearray)):
            raise CurieContractError("source verifier source_bytes must be bytes")
        raw = bytes(source_bytes)
        try:
            source_text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CurieContractError(
                f"source verifier source is not valid UTF-8 text: {exc}"
            ) from exc
        candidate_text = _text(candidate.get("text"), "source candidate text")
        if _normalize(candidate_text) not in _normalize(source_text):
            raise CurieContractError(
                "candidate text was not located in the independently supplied source"
            )
        normalized_role = str(role or "").strip().upper()
        if normalized_role not in _ROLES:
            raise CurieContractError(
                f"source verifier role must be one of {sorted(_ROLES)}"
            )
        retrieval = candidate.get("retrieval")
        if not isinstance(retrieval, dict):
            raise CurieContractError("source candidate retrieval provenance is missing")
        upstream_engine = _text(
            retrieval.get("engine"), "source candidate upstream retrieval engine"
        )
        source_identity = retrieval.get("source_identity")
        if not isinstance(source_identity, dict) or not source_identity:
            raise CurieContractError(
                "source candidate must carry a non-empty source_identity"
            )
        extract = {
            "schema_version": EVIDENCE_EXTRACT_SCHEMA_VERSION,
            "evidence_id": _text(candidate.get("evidence_id"), "source candidate evidence_id"),
            "paper_id": _text(candidate.get("paper_id"), "source candidate paper_id"),
            "section": _text(candidate.get("section"), "source candidate section"),
            "text": candidate_text,
            "locator": _text(candidate.get("locator"), "source candidate locator"),
            "role": normalized_role,
            "verification_status": "LOCATED",
            "retrieval": {
                "engine": "independent-source-verifier",
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "upstream_engine": upstream_engine,
                "source_identity": json.loads(json.dumps(source_identity)),
            },
        }
        if retrieval.get("backend_id"):
            extract["retrieval"]["upstream_backend_id"] = str(
                retrieval["backend_id"]
            )
        return validate_evidence_extract(extract)
