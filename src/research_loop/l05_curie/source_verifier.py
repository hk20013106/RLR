"""Generic deterministic source-fidelity verifier for Curie candidates.

Retrieval engines may propose text and locators. This verifier independently
locates the proposed text in supplied source bytes and is the only component in
this generic path allowed to promote an UNVERIFIED candidate to a LOCATED
EvidenceExtract. Upstream locators remain provenance only; the authoritative
locator is derived from the independently supplied source.
"""
from __future__ import annotations

import hashlib
import json
import re

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


def _location_pattern(value: str) -> re.Pattern[str]:
    tokens = value.split()
    if not tokens:
        raise CurieContractError("source candidate text must contain non-whitespace text")
    return re.compile(r"\s+".join(re.escape(token) for token in tokens))


def _unique_source_span(source_text: str, candidate_text: str) -> tuple[int, int]:
    matches = list(_location_pattern(candidate_text).finditer(source_text))
    if not matches:
        raise CurieContractError(
            "candidate text was not located in the independently supplied source"
        )
    if len(matches) != 1:
        raise CurieContractError(
            "candidate text has multiple source locations; independent locator is ambiguous"
        )
    match = matches[0]
    return match.start(), match.end()


class ExactTextSourceVerifier:
    """Verify one unique source span for an unverified retrieval candidate."""

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
        start, end = _unique_source_span(source_text, candidate_text)

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
        upstream_locator = _text(
            candidate.get("locator"), "source candidate upstream locator"
        )

        extract = {
            "schema_version": EVIDENCE_EXTRACT_SCHEMA_VERSION,
            "evidence_id": _text(candidate.get("evidence_id"), "source candidate evidence_id"),
            "paper_id": _text(candidate.get("paper_id"), "source candidate paper_id"),
            "section": _text(candidate.get("section"), "source candidate section"),
            "text": candidate_text,
            "locator": f"char:{start}:{end}",
            "role": normalized_role,
            "verification_status": "LOCATED",
            "retrieval": {
                "engine": "independent-source-verifier",
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "upstream_engine": upstream_engine,
                "upstream_locator": upstream_locator,
                "source_identity": json.loads(json.dumps(source_identity)),
            },
        }
        if retrieval.get("backend_id"):
            extract["retrieval"]["upstream_backend_id"] = str(
                retrieval["backend_id"]
            )
        for provenance_key in ("runtime", "paperqa2", "source_alignment"):
            if provenance_key in retrieval:
                if not isinstance(retrieval[provenance_key], dict):
                    raise CurieContractError(
                        f"source candidate {provenance_key} provenance must be an object"
                    )
                extract["retrieval"][provenance_key] = json.loads(
                    json.dumps(retrieval[provenance_key])
                )
        return validate_evidence_extract(extract)
