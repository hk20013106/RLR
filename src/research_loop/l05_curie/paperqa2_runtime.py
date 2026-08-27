"""Explicit external PaperQA2 runtime and source-candidate alignment.

The PaperQA2 process is retrieval-only. It returns ranked chunks and immutable
runtime provenance. Alignment to an independently acquired source paragraph is
still an UNVERIFIED candidate operation; only the source verifier may emit a
LOCATED EvidenceExtract.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from research_loop.process_runner import DEFAULT_PROCESS_RUNNER, ProcessRunner

from .contracts import CurieContractError
from .paperqa2 import PAPERQA2_RUNTIME_SCHEMA_VERSION, PaperQA2Retriever

_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_RUNTIME = (
    "package", "version", "upstream_repo", "upstream_tag", "upstream_commit",
    "fork_repo", "pdf_sha256",
)
PAPERQA2_PACKAGE = "paper-qa"
PAPERQA2_VERSION = "2026.8.12"
PAPERQA2_UPSTREAM_REPO = "https://github.com/Future-House/paper-qa"
PAPERQA2_UPSTREAM_TAG = "v2026.08.12"
PAPERQA2_UPSTREAM_COMMIT = "57e89f7223b0960d5ee5ea048c69e3c47e088572"
PAPERQA2_FORK_REPO = "https://github.com/hk20013106/paper-qa"
PAPERQA2_BACKEND_ID = "paperqa2-fork-v2026.08.12/sparse-docs-v1"
SOURCE_ALIGNMENT_METHOD = "token-coverage-multimatch/v2"
MIN_SOURCE_TOKEN_COVERAGE = 0.5
_PINNED_RUNTIME = {
    "package": PAPERQA2_PACKAGE,
    "version": PAPERQA2_VERSION,
    "upstream_repo": PAPERQA2_UPSTREAM_REPO,
    "upstream_tag": PAPERQA2_UPSTREAM_TAG,
    "upstream_commit": PAPERQA2_UPSTREAM_COMMIT,
    "fork_repo": PAPERQA2_FORK_REPO,
}


def _text(value: object, name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise CurieContractError(f"{name} must be a non-empty string")
    return value


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise CurieContractError(f"PaperQA2 PDF is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tokens(value: object) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.findall(r"[\w]+", normalized, flags=re.UNICODE)


def validate_pinned_paperqa2_runtime(runtime: object, *, pdf_sha256: str) -> dict:
    """Validate immutable PaperQA2 integration provenance at every use boundary."""
    if not isinstance(runtime, dict):
        raise CurieContractError("PaperQA2 bridge runtime provenance must be an object")
    if runtime.get("schema_version") != PAPERQA2_RUNTIME_SCHEMA_VERSION:
        raise CurieContractError("PaperQA2 bridge runtime schema_version is invalid")
    for field in _REQUIRED_RUNTIME:
        _text(runtime.get(field), f"PaperQA2 bridge runtime {field}")
    commit = str(runtime["upstream_commit"]).lower()
    if not _GIT_COMMIT.fullmatch(commit):
        raise CurieContractError("PaperQA2 bridge upstream_commit must be a 40-character git SHA")
    for field, expected in _PINNED_RUNTIME.items():
        observed = commit if field == "upstream_commit" else str(runtime[field])
        if observed != expected:
            raise CurieContractError(
                f"PaperQA2 runtime {field} does not match the pinned integration"
            )
    if runtime["pdf_sha256"].lower() != pdf_sha256:
        raise CurieContractError("PaperQA2 runtime PDF hash does not match the requested PDF")
    return copy.deepcopy(runtime)


class PaperQA2SubprocessBackend:
    """Call the pinned PaperQA2 checkout through an explicit JSON bridge."""

    def __init__(
        self,
        *,
        python_executable: str | Path,
        bridge_script: str | Path,
        paperqa_repo: str | Path,
        pqa_home: str | Path,
        timeout_seconds: int = 300,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.python_executable = Path(python_executable).resolve()
        self.bridge_script = Path(bridge_script).resolve()
        self.paperqa_repo = Path(paperqa_repo).resolve()
        self.pqa_home = Path(pqa_home).resolve()
        self.backend_id = PAPERQA2_BACKEND_ID
        self.runner = runner or DEFAULT_PROCESS_RUNNER
        if not self.python_executable.is_file():
            raise CurieContractError(f"PaperQA2 Python executable is missing: {self.python_executable}")
        if not self.bridge_script.is_file():
            raise CurieContractError(f"PaperQA2 bridge script is missing: {self.bridge_script}")
        if not self.paperqa_repo.is_dir():
            raise CurieContractError(f"PaperQA2 repository is missing: {self.paperqa_repo}")
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise CurieContractError("PaperQA2 timeout_seconds must be a positive integer")
        self.timeout_seconds = timeout_seconds
        self.pqa_home.mkdir(parents=True, exist_ok=True)

    def __call__(self, *, paper: dict, question: str) -> list[dict]:
        if not isinstance(paper, dict):
            raise CurieContractError("PaperQA2 subprocess paper must be an object")
        pdf_path = Path(_text(paper.get("pdf_path"), "PaperQA2 paper pdf_path")).resolve()
        pdf_sha256 = _sha256_file(pdf_path)
        request = {
            "paper_id": _text(paper.get("paper_id"), "PaperQA2 paper_id"),
            "title": _text(paper.get("title"), "PaperQA2 paper title"),
            "doi": str((paper.get("identifiers") or {}).get("doi") or "").strip(),
            "pdf_path": str(pdf_path),
            "question": _text(question, "PaperQA2 question"),
            "pqa_home": str(self.pqa_home),
            "paperqa_repo": str(self.paperqa_repo),
            "k": 5,
        }
        environment = os.environ.copy()
        environment["PQA_HOME"] = str(self.pqa_home)
        try:
            completed = self.runner.run(
                [str(self.python_executable), str(self.bridge_script)],
                cwd=str(self.paperqa_repo),
                env=environment,
                input_text=json.dumps(request, ensure_ascii=False),
                timeout=self.timeout_seconds,
                encoding="utf-8",
                errors="strict",
            )
        except OSError as exc:
            raise CurieContractError(
                f"PaperQA2 subprocess could not start: {exc}"
            ) from exc
        if completed.terminal_state == "timed_out":
            raise CurieContractError("PaperQA2 subprocess timed out")
        if completed.returncode != 0:
            raise CurieContractError(
                f"PaperQA2 subprocess failed with exit code {completed.returncode}"
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CurieContractError("PaperQA2 bridge did not return JSON") from exc
        if not isinstance(payload, dict) or payload.get("engine") != "paperqa2":
            raise CurieContractError("PaperQA2 bridge engine identity is invalid")
        runtime = validate_pinned_paperqa2_runtime(
            payload.get("runtime"),
            pdf_sha256=pdf_sha256,
        )
        runtime.update({
            "python_executable": str(self.python_executable),
            "paperqa_repo": str(self.paperqa_repo),
            "pqa_home": str(self.pqa_home),
            "pdf_path": str(pdf_path),
        })
        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise CurieContractError("PaperQA2 bridge hits must be a list")
        results = []
        for hit in hits:
            if not isinstance(hit, dict):
                raise CurieContractError("PaperQA2 bridge hit must be an object")
            text = _text(hit.get("text"), "PaperQA2 bridge hit text")
            locator = _text(hit.get("locator"), "PaperQA2 bridge hit locator")
            section = _text(hit.get("section"), "PaperQA2 bridge hit section")
            score = hit.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise CurieContractError("PaperQA2 bridge hit score must be numeric")
            results.append({
                "text": text,
                "locator": locator,
                "section": section,
                "score": float(score),
                "runtime": runtime,
                "paperqa2": {
                    "chunk_locator": locator,
                    "chunk_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "context_score": hit.get("context_score"),
                },
            })
        return results


class PaperQA2CurieRuntime:
    """Run retrieval, retain UNVERIFIED candidates, then call a verifier."""

    def __init__(self, *, backend, backend_id: str) -> None:
        if not callable(backend):
            raise CurieContractError("PaperQA2 Curie backend must be callable")
        self.backend = backend
        self.backend_id = _text(backend_id, "PaperQA2 Curie backend_id")

    def retrieve_and_verify(
        self,
        *,
        paper: dict,
        question: str,
        source_candidates: list[dict],
        verify,
    ) -> dict:
        if not callable(verify):
            raise CurieContractError("PaperQA2 Curie source verifier must be callable")
        chunks = self.backend(paper=paper, question=question)
        if not isinstance(chunks, list):
            raise CurieContractError("PaperQA2 Curie backend must return a list")
        aligned = align_paperqa2_chunks(
            chunks=chunks,
            source_candidates=source_candidates,
        )
        unverified = PaperQA2Retriever(
            backend=lambda **_kwargs: aligned,
            backend_id=self.backend_id,
        ).retrieve(paper=paper, question=question)
        located = verify(unverified)
        if not isinstance(located, list):
            raise CurieContractError("PaperQA2 Curie source verifier must return a list")
        return {
            "chunks": copy.deepcopy(chunks),
            "unverified": unverified,
            "located": copy.deepcopy(located),
        }


def align_paperqa2_chunks(*, chunks: list[dict], source_candidates: list[dict]) -> list[dict]:
    """Map retrieved chunks to exact source paragraphs without certifying them.

    Every independently sourced paragraph that clears the lexical coverage
    threshold may be proposed, but each source locator retains only its
    strongest PaperQA2 alignment across all chunks. Equal-coverage ties are
    resolved deterministically by chunk index and then source-candidate index.
    """
    if not isinstance(chunks, list) or not isinstance(source_candidates, list):
        raise CurieContractError("PaperQA2 source alignment requires candidate lists")
    if not source_candidates:
        raise CurieContractError("PaperQA2 source alignment has no independent source candidates")

    best_by_locator: dict[str, tuple[float, int, int, dict, str]] = {}
    for chunk_index, chunk in enumerate(chunks):
        chunk_text = _text(chunk.get("text"), "PaperQA2 chunk text")
        chunk_tokens = set(_tokens(chunk_text))
        if not chunk_tokens:
            continue
        for source_index, source in enumerate(source_candidates):
            source_text = _text(source.get("text"), "source candidate text")
            locator = _text(source.get("locator"), "source candidate locator")
            source_tokens = set(_tokens(source_text))
            if not source_tokens:
                continue
            coverage = len(chunk_tokens & source_tokens) / len(source_tokens)
            if coverage < MIN_SOURCE_TOKEN_COVERAGE:
                continue
            candidate = (coverage, chunk_index, source_index, source, chunk_text)
            existing = best_by_locator.get(locator)
            if existing is None or (
                coverage > existing[0]
                or (
                    coverage == existing[0]
                    and (chunk_index, source_index) < (existing[1], existing[2])
                )
            ):
                best_by_locator[locator] = candidate

    if not best_by_locator:
        raise CurieContractError("PaperQA2 retrieved chunks could not align to source candidates")

    aligned: list[dict] = []
    winners = sorted(
        best_by_locator.items(),
        key=lambda item: (item[1][1], item[1][2], item[0]),
    )
    for locator, (coverage, chunk_index, source_index, source, chunk_text) in winners:
        chunk = chunks[chunk_index]
        aligned_item = {
            "text": _text(source.get("text"), "source candidate text"),
            "locator": locator,
            "section": _text(source.get("section"), "source candidate section"),
            "score": float(chunk.get("score", 0.0)),
            "paperqa2": copy.deepcopy(chunk.get("paperqa2", {
                "chunk_locator": _text(chunk.get("locator"), "PaperQA2 chunk locator"),
                "chunk_sha256": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
            })),
            "source_alignment": {
                "method": SOURCE_ALIGNMENT_METHOD,
                "chunk_index": chunk_index,
                "source_candidate_index": source_index,
                "source_token_coverage": coverage,
            },
        }
        if chunk.get("runtime") is not None:
            aligned_item["runtime"] = copy.deepcopy(chunk["runtime"])
        aligned.append(aligned_item)
    return aligned
