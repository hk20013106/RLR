"""PaperQA2 retrieval boundary for Curie.

PaperQA2 is optional retrieval/reranking infrastructure. It may propose source
text candidates, but it has no authority to certify source fidelity, assign an
evidence role, mutate workflow state, or bypass the independent verifier.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable

from .contracts import CurieContractError

PAPERQA2_CANDIDATE_SCHEMA_VERSION = "L05PaperQA2Candidate/v1"
PAPERQA2_RUNTIME_SCHEMA_VERSION = "PaperQA2Runtime/v1"


def _text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    return text


def _source_identity(paper: dict) -> dict:
    ids = paper.get("identifiers") if isinstance(paper.get("identifiers"), dict) else {}
    source = {
        key: str(ids[key])
        for key in (
            "doi", "pmid", "pmcid", "openalex_id",
            "semantic_scholar_paper_id", "semantic_scholar_corpus_id",
        )
        if str(ids.get(key) or "").strip()
    }
    if not source:
        source["paper_id"] = _text(paper.get("paper_id"), "PaperQA2 paper_id")
    return source


def _candidate_id(paper_id: str, section: str, locator: str, text: str) -> str:
    raw = json.dumps(
        [paper_id, section, locator, text], ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "EC_PQA2_" + hashlib.sha256(raw).hexdigest()[:16]


def validate_paperqa2_candidate(candidate: dict) -> dict:
    if not isinstance(candidate, dict):
        raise CurieContractError("PaperQA2 candidate must be an object")
    if candidate.get("schema_version") != PAPERQA2_CANDIDATE_SCHEMA_VERSION:
        raise CurieContractError("PaperQA2 candidate schema_version is invalid")
    for field in ("evidence_id", "paper_id", "section", "text", "locator"):
        _text(candidate.get(field), f"PaperQA2 candidate {field}")
    if candidate.get("verification_status") != "UNVERIFIED":
        raise CurieContractError(
            "PaperQA2 cannot self-certify evidence; verification_status must be UNVERIFIED"
        )
    if "role" in candidate:
        raise CurieContractError("PaperQA2 candidate must not assign an evidence role")
    retrieval = candidate.get("retrieval")
    if not isinstance(retrieval, dict):
        raise CurieContractError("PaperQA2 candidate retrieval must be an object")
    if retrieval.get("engine") != "paperqa2":
        raise CurieContractError("PaperQA2 candidate retrieval.engine must be paperqa2")
    _text(retrieval.get("backend_id"), "PaperQA2 backend_id")
    if not isinstance(retrieval.get("source_identity"), dict) or not retrieval["source_identity"]:
        raise CurieContractError("PaperQA2 source_identity must be a non-empty object")
    runtime = retrieval.get("runtime")
    if runtime is not None:
        if not isinstance(runtime, dict):
            raise CurieContractError("PaperQA2 runtime provenance must be an object")
        if runtime.get("schema_version") != PAPERQA2_RUNTIME_SCHEMA_VERSION:
            raise CurieContractError("PaperQA2 runtime provenance schema_version is invalid")
        for field in (
            "package", "version", "upstream_repo", "upstream_tag", "upstream_commit",
            "fork_repo", "python_executable", "paperqa_repo", "pqa_home",
            "pdf_path", "pdf_sha256",
        ):
            _text(runtime.get(field), f"PaperQA2 runtime {field}")
    return json.loads(json.dumps(candidate))


class PaperQA2Retriever:
    """Thin adapter around an injected PaperQA2-compatible backend."""

    def __init__(self, *, backend: Callable, backend_id: str = "paperqa2/v1") -> None:
        if not callable(backend):
            raise CurieContractError("PaperQA2 backend must be callable")
        self.backend = backend
        self.backend_id = _text(backend_id, "PaperQA2 backend_id")

    def retrieve(self, *, paper: dict, question: str) -> list[dict]:
        if not isinstance(paper, dict):
            raise CurieContractError("PaperQA2 paper must be an object")
        paper_id = _text(paper.get("paper_id"), "PaperQA2 paper_id")
        question = _text(question, "PaperQA2 question")
        try:
            raw_items = self.backend(paper=paper, question=question)
        except Exception:
            raise
        if not isinstance(raw_items, list):
            raise CurieContractError("PaperQA2 backend must return a list")
        source_identity = _source_identity(paper)
        candidates = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise CurieContractError("PaperQA2 backend item must be an object")
            if raw.get("verification_status") not in (None, "", "UNVERIFIED"):
                raise CurieContractError(
                    "PaperQA2 backend attempted to self-certify verification; only UNVERIFIED is allowed"
                )
            if "role" in raw:
                raise CurieContractError(
                    "PaperQA2 backend attempted to assign an evidence role"
                )
            text = _text(raw.get("text"), "PaperQA2 candidate text")
            locator = _text(raw.get("locator"), "PaperQA2 candidate locator")
            section = _text(raw.get("section"), "PaperQA2 candidate section")
            candidate = {
                "schema_version": PAPERQA2_CANDIDATE_SCHEMA_VERSION,
                "evidence_id": _candidate_id(paper_id, section, locator, text),
                "paper_id": paper_id,
                "section": section,
                "text": text,
                "locator": locator,
                "verification_status": "UNVERIFIED",
                "retrieval": {
                    "engine": "paperqa2",
                    "backend_id": self.backend_id,
                    "source_identity": source_identity,
                },
            }
            if isinstance(raw.get("score"), (int, float)) and not isinstance(raw.get("score"), bool):
                candidate["retrieval"]["rerank_score"] = float(raw["score"])
            for provenance_key in ("runtime", "paperqa2", "source_alignment"):
                if provenance_key in raw:
                    if not isinstance(raw[provenance_key], dict):
                        raise CurieContractError(
                            f"PaperQA2 backend {provenance_key} provenance must be an object"
                        )
                    candidate["retrieval"][provenance_key] = json.loads(
                        json.dumps(raw[provenance_key])
                    )
            candidates.append(validate_paperqa2_candidate(candidate))
        return candidates


def _validate_fallback_candidates(items: object) -> list[dict]:
    if not isinstance(items, list):
        raise CurieContractError("declared fallback retriever must return a list")
    validated = []
    for item in items:
        if not isinstance(item, dict):
            raise CurieContractError("fallback evidence candidate must be an object")
        if item.get("verification_status") != "UNVERIFIED":
            raise CurieContractError(
                "fallback retrieval candidates must remain UNVERIFIED"
            )
        for field in ("evidence_id", "paper_id", "section", "text", "locator"):
            _text(item.get(field), f"fallback candidate {field}")
        retrieval = item.get("retrieval")
        if not isinstance(retrieval, dict):
            raise CurieContractError("fallback candidate retrieval must be an object")
        _text(retrieval.get("engine"), "fallback candidate retrieval engine")
        if not isinstance(retrieval.get("source_identity"), dict) or not retrieval["source_identity"]:
            raise CurieContractError("fallback candidate source_identity must be non-empty")
        validated.append(json.loads(json.dumps(item)))
    return validated


def retrieve_with_declared_fallback(
    *, primary: PaperQA2Retriever, fallback, paper: dict, question: str
) -> dict:
    """Run PaperQA2, with only an explicit declared fallback on backend failure."""
    try:
        candidates = primary.retrieve(paper=paper, question=question)
    except Exception as exc:
        failure = {
            "engine": "paperqa2",
            "reason": str(exc),
            "exception_type": type(exc).__name__,
        }
        if fallback is None:
            return {
                "route": "INSUFFICIENT",
                "candidates": [],
                "primary_failure": failure,
            }
        if not hasattr(fallback, "retrieve"):
            raise CurieContractError("declared fallback has no retrieve method")
        items = fallback.retrieve(paper=paper, question=question)
        return {
            "route": "fallback",
            "candidates": _validate_fallback_candidates(items),
            "primary_failure": failure,
        }
    return {
        "route": "paperqa2",
        "candidates": candidates,
        "primary_failure": None,
    }
