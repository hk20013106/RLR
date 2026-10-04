"""PaperQA2 retrieval boundary for Curie.

PaperQA2 is optional retrieval/reranking infrastructure. It may propose source
text candidates, but it has no authority to certify source fidelity, assign an
evidence role, mutate workflow state, or bypass the independent verifier.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable

from .contracts import (
    CurieContractError, _canonical_json, _require_exact_keys, _require_int,
    _require_sha256, _require_text, _validate_gap,
)

PAPERQA2_CANDIDATE_SCHEMA_VERSION = "L05PaperQA2Candidate/v1"
PAPERQA2_RUNTIME_SCHEMA_VERSION = "PaperQA2Runtime/v1"
PAPERQA2_DOCUMENT_RUNTIME_SCHEMA_VERSION = "PaperQA2Runtime/v2"
PAPERQA2_CORPUS_TASK_SCHEMA_VERSION = "PaperQA2CorpusTask/v1"
PAPERQA2_CORPUS_RESULT_SCHEMA_VERSION = "PaperQA2CorpusResult/v1"


def canonical_corpus_bytes(value: object) -> bytes:
    """Use the existing Curie serializer and acquisition artifact's single LF."""
    try:
        return _canonical_json(value).encode("utf-8") + b"\n"
    except (ValueError, TypeError, UnicodeError) as exc:
        raise CurieContractError("corpus artifact must be strict UTF-8 JSON") from exc


def _validate_evidence_focus(focus: dict | None) -> dict | None:
    if focus is None:
        return None
    _require_exact_keys(focus, {"coverage_request_sha256", "coverage_assessment_sha256", "gaps"}, "evidence_focus")
    canonical_corpus_bytes(focus)
    for key in ("coverage_request_sha256", "coverage_assessment_sha256"):
        _require_sha256(focus[key], f"evidence_focus.{key}")
    gaps = focus["gaps"]
    if not isinstance(gaps, list) or not gaps:
        raise CurieContractError("evidence_focus.gaps must be non-empty")
    for gap in gaps:
        _validate_gap(gap, strict=True)
    ids = [gap["gap_id"] for gap in gaps]
    if ids != sorted(set(ids)):
        raise CurieContractError("evidence_focus gaps must have unique ascending gap_id")
    return copy.deepcopy(focus)


def _corpus_task_id(task: dict, *, acquisition_run_id: str, attempt_index: int) -> str:
    _require_text(acquisition_run_id, "acquisition_run_id")
    _require_int(attempt_index, "attempt_index", maximum=3)
    identity = {"acquisition_run_id": acquisition_run_id, "attempt_index": attempt_index,
                "task": {k: v for k, v in task.items() if k != "task_id"}}
    return "PQA_" + hashlib.sha256(canonical_corpus_bytes(identity)).hexdigest()[:24]


def validate_paperqa2_corpus_task(task: dict, *, acquisition_run_id: str, attempt_index: int) -> dict:
    """Validate only observable wire facts; provenance and source fidelity are independent."""
    _require_exact_keys(task, {"schema_version", "task_id", "research_seed_sha256", "question",
                               "evidence_focus", "parser_profile", "settings_sha256", "corpus", "budget"}, "corpus task")
    canonical_corpus_bytes(task)
    if task["schema_version"] != PAPERQA2_CORPUS_TASK_SCHEMA_VERSION or task["parser_profile"] != "jats-paragraphs/v2":
        raise CurieContractError("corpus task schema_version/parser_profile is invalid")
    for key in ("research_seed_sha256", "settings_sha256"):
        _require_sha256(task[key], f"corpus task {key}")
    _require_text(task["question"], "corpus task question")
    _validate_evidence_focus(task["evidence_focus"])
    if attempt_index == 1 and task["evidence_focus"] is not None:
        raise CurieContractError("first attempt evidence_focus must be null")
    _require_exact_keys(task["budget"], {"evidence_k"}, "corpus task budget")
    _require_int(task["budget"]["evidence_k"], "evidence_k")
    corpus = task["corpus"]
    if not isinstance(corpus, list) or not 1 <= len(corpus) <= 90:
        raise CurieContractError("worker corpus requires 1-90 papers")
    papers = set()
    for paper in corpus:
        _require_exact_keys(paper, {"paper_id", "title", "document_path", "document_sha256", "media_type", "source_units"}, "corpus paper")
        paper_id = _require_text(paper["paper_id"], "corpus paper_id")
        if paper_id in papers:
            raise CurieContractError("duplicate corpus paper_id")
        papers.add(paper_id)
        _require_text(paper["title"], "corpus title")
        _require_sha256(paper["document_sha256"], "corpus document_sha256")
        path = _require_text(paper["document_path"], "corpus document_path")
        windows = PureWindowsPath(path)
        posix = PurePosixPath(path)
        if windows.drive or windows.root or posix.is_absolute() or ".." in windows.parts or ".." in posix.parts or ":" in path:
            raise CurieContractError("corpus document_path must be project-relative without traversal or drive")
        if paper["media_type"] != "application/xml":
            raise CurieContractError("corpus media_type must be application/xml")
        units = paper["source_units"]
        if not isinstance(units, list) or not units:
            raise CurieContractError("corpus source_units must be non-empty")
        locators = set()
        for unit in units:
            _require_exact_keys(unit, {"source_locator", "section", "source_text"}, "source unit")
            for key in unit:
                _require_text(unit[key], f"source unit {key}")
            if unit["source_locator"] in locators:
                raise CurieContractError("duplicate corpus source_locator")
            locators.add(unit["source_locator"])
    if task["task_id"] != _corpus_task_id(task, acquisition_run_id=acquisition_run_id, attempt_index=attempt_index):
        raise CurieContractError("corpus task_id does not match run/attempt/content identity")
    return copy.deepcopy(task)


def validate_paperqa2_corpus_result(result: dict, *, task: dict, settings: dict, expected_runtime: dict) -> dict:
    from .paperqa2_runtime import _PINNED_RUNTIME, _validate_corpus_settings

    _require_exact_keys(result, {"schema_version", "task_id", "task_sha256", "runtime", "execution", "evidence"}, "corpus result")
    canonical_corpus_bytes(result)
    if result["schema_version"] != PAPERQA2_CORPUS_RESULT_SCHEMA_VERSION:
        raise CurieContractError("corpus result schema_version is invalid")
    task_hash = hashlib.sha256(canonical_corpus_bytes(task)).hexdigest()
    _validate_corpus_settings(copy.deepcopy(settings))
    settings_hash = hashlib.sha256(canonical_corpus_bytes(settings)).hexdigest()
    if result["task_id"] != task["task_id"] or result["task_sha256"] != task_hash:
        raise CurieContractError("corpus result task binding mismatch")
    if settings_hash != task["settings_sha256"] or settings["answer"]["evidence_k"] != task["budget"]["evidence_k"]:
        raise CurieContractError("corpus result settings binding mismatch")
    runtime_keys = {"package", "version", "upstream_commit", "upstream_tag", "embedding_model", "summary_llm_model", "settings_sha256"}
    _require_exact_keys(result["runtime"], runtime_keys, "corpus result runtime")
    _require_exact_keys(expected_runtime, runtime_keys - {"settings_sha256"}, "expected corpus runtime")
    expected = {key: expected_runtime[key] for key in runtime_keys - {"settings_sha256"}}
    for key in ("package", "version", "upstream_commit", "upstream_tag"):
        if expected[key] != _PINNED_RUNTIME[key]:
            raise CurieContractError(f"corpus runtime {key} must match pinned integration")
    expected["settings_sha256"] = settings_hash
    if result["runtime"] != expected:
        raise CurieContractError("corpus result runtime mismatch")
    if expected["embedding_model"] != settings["embedding"] or expected["summary_llm_model"] != settings["summary_llm"]:
        raise CurieContractError("corpus runtime models mismatch frozen Settings")
    execution = _require_exact_keys(result["execution"], {"status", "ingested_paper_count", "ingested_text_count", "terminal_context_error_count"}, "corpus execution")
    counts = {"ingested_paper_count": len(task["corpus"]),
              "ingested_text_count": sum(len(p["source_units"]) for p in task["corpus"]),
              "terminal_context_error_count": 0}
    if execution["status"] != "COMPLETE":
        raise CurieContractError("only COMPLETE corpus execution may produce result")
    for key, expected_count in counts.items():
        _require_int(execution[key], key, minimum=0)
        if execution[key] != expected_count:
            raise CurieContractError(f"corpus execution {key} mismatch")
    evidence = result["evidence"]
    if not isinstance(evidence, list) or len(evidence) > task["budget"]["evidence_k"]:
        raise CurieContractError("corpus evidence exceeds evidence_k or is not a list")
    papers = {paper["paper_id"] for paper in task["corpus"]}
    for item in evidence:
        required = {"paper_id", "source_locator", "source_text", "relevance_score"}
        _require_exact_keys(item, required | ({"contextual_summary"} if "contextual_summary" in item else set()), "corpus evidence")
        for key in ("paper_id", "source_locator", "source_text"):
            _require_text(item[key], f"corpus evidence {key}")
        if item["paper_id"] not in papers:
            raise CurieContractError("corpus evidence unknown paper_id")
        _require_int(item["relevance_score"], "relevance_score", maximum=10)
        if "contextual_summary" in item and not isinstance(item["contextual_summary"], str):
            raise CurieContractError("contextual_summary must be a string")
    return copy.deepcopy(result)


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
        schema_version = runtime.get("schema_version")
        common_fields = (
            "package", "version", "upstream_repo", "upstream_tag", "upstream_commit",
            "fork_repo", "python_executable", "paperqa_repo", "pqa_home",
        )
        if schema_version == PAPERQA2_RUNTIME_SCHEMA_VERSION:
            runtime_fields = common_fields + ("pdf_path", "pdf_sha256")
        elif schema_version == PAPERQA2_DOCUMENT_RUNTIME_SCHEMA_VERSION:
            runtime_fields = common_fields + (
                "document_path", "document_sha256", "media_type",
            )
        else:
            raise CurieContractError("PaperQA2 runtime provenance schema_version is invalid")
        for field in runtime_fields:
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
