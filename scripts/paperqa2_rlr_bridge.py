"""JSON stdin/stdout bridge executed by the pinned PaperQA2 environment."""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import subprocess
import sys
import os
import logging


def _text(value, name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{name} must be non-empty")
    return value


def _utf8_transport_text(value: object) -> str | None:
    """Return text safe for the strict JSON/UTF-8 transport, or ``None``.

    A lone surrogate is not valid UTF-8.  It must not be replaced in a
    retrieval hit because doing so would change the text used by the
    independent source verifier.  Such a hit is therefore omitted and the
    verifier may truthfully report an unresolved evidence gap.
    """
    if not isinstance(value, str):
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value


def _git(repo: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _json_bytes(value) -> bytes:
    """The bridge's existing JSON transport, with canonical corpus encoding."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON numbers are forbidden")


class _CorpusDiagnostics(logging.Handler):
    def __init__(self, context_error_type):
        super().__init__(level=logging.ERROR)
        self.context_error_type = context_error_type
        self.capture_established = False
        self.capture_failed = False
        self.terminal_context_error_count = 0

    def emit(self, record):
        try:
            if record.name == "paperqa.core" and record.exc_info and isinstance(record.exc_info[1], self.context_error_type):
                self.terminal_context_error_count += 1
        except Exception:
            self.capture_failed = True
            raise


async def _run_corpus(request: dict) -> dict:
    if set(request) != {"worker_mode", "task", "settings", "project_root", "paperqa_repo", "pqa_home"}:
        raise ValueError("invalid corpus invocation envelope")
    task = request["task"]
    if request["worker_mode"] != "corpus-evidence-v1" or task.get("schema_version") != "PaperQA2CorpusTask/v1":
        raise ValueError("unknown corpus mode/schema")
    if task.get("parser_profile") != "jats-paragraphs/v2":
        raise ValueError("unknown corpus parser profile")
    _json_bytes(task)
    settings_bytes = _json_bytes(request["settings"])
    settings_hash = hashlib.sha256(settings_bytes).hexdigest()
    if task.get("settings_sha256") != settings_hash:
        raise ValueError("frozen Settings hash mismatch")
    project = pathlib.Path(request["project_root"]).resolve(strict=True)
    repo = pathlib.Path(request["paperqa_repo"]).resolve(strict=True)
    os.environ["PQA_HOME"] = str(pathlib.Path(request["pqa_home"]).resolve(strict=True))
    import paperqa
    from paperqa import Docs, Settings
    from paperqa.types import Doc, Text
    from paperqa.core import LLMContextError
    if (paperqa.__version__ != "2026.8.12"
            or _git(repo, "rev-parse", "HEAD") != "57e89f7223b0960d5ee5ea048c69e3c47e088572"
            or _git(repo, "describe", "--tags", "--exact-match", "HEAD") != "v2026.08.12"
            or _git(repo, "status", "--porcelain")):
        raise ValueError("PaperQA2 runtime is not a clean pinned checkout")
    try:
        pathlib.Path(paperqa.__file__).resolve().relative_to(repo)
    except ValueError as exc:
        raise ValueError("actual PaperQA2 module is outside the bound checkout") from exc
    settings = Settings(**request["settings"])
    if (settings.embedding != request["settings"]["embedding"]
            or settings.summary_llm != request["settings"]["summary_llm"]
            or settings.answer.evidence_k != task["budget"]["evidence_k"]):
        raise ValueError("native Settings changed frozen model/budget binding")
    diagnostics = _CorpusDiagnostics(LLMContextError)
    logger = logging.getLogger("paperqa.core")
    try:
        try:
            if not logger.isEnabledFor(logging.ERROR):
                raise ValueError("terminal diagnostic logger disabled")
            logger.addHandler(diagnostics)
            diagnostics.capture_established = diagnostics in logger.handlers
            if not diagnostics.capture_established:
                raise ValueError("terminal diagnostic handler not installed")
        except Exception:
            diagnostics.capture_failed = True
            raise
        docs = Docs()
        units_by_identity = {}
        if not task["corpus"]:
            raise ValueError("empty worker corpus forbidden")
        for paper in task["corpus"]:
            value = paper["document_path"]
            path = pathlib.Path(value)
            if path.is_absolute() or path.drive or ".." in path.parts:
                raise ValueError("corpus snapshot path must be project-relative")
            path = (project / path).resolve(strict=True)
            try:
                path.relative_to(project)
            except ValueError as exc:
                raise ValueError("corpus snapshot path escapes project") from exc
            if paper["media_type"] != "application/xml" or hashlib.sha256(path.read_bytes()).hexdigest() != paper["document_sha256"]:
                raise ValueError("corpus snapshot media/hash mismatch")
            doc = Doc(dockey=paper["paper_id"], docname=paper["paper_id"], citation=paper["title"])
            texts = []
            for index, unit in enumerate(paper["source_units"]):
                for key in ("source_locator", "section", "source_text"):
                    if not isinstance(unit.get(key), str) or not unit[key].strip():
                        raise ValueError("source unit fields must be non-empty strings")
                    unit[key].encode("utf-8")
                identity = (paper["paper_id"], unit["source_locator"])
                if identity in units_by_identity:
                    raise ValueError("duplicate input source identity")
                units_by_identity[identity] = unit
                texts.append(Text(doc=doc, text=unit["source_text"], name=f"{paper['paper_id']} text {index + 1}",
                                  source_locator=unit["source_locator"], section=unit["section"]))
            if not await docs.aadd_texts(texts, doc, settings=settings):
                raise ValueError("native aadd_texts refused corpus ingestion")
        if len(docs.docs) != len(task["corpus"]) or len(docs.texts) != len(units_by_identity):
            raise ValueError("native ingestion counts mismatch")
        session = await docs.aget_evidence(task["question"], settings=settings)
        if diagnostics.capture_failed or diagnostics.terminal_context_error_count:
            raise ValueError("native terminal context failure")
        evidence = {}
        for context in session.contexts:
            text = context.text
            identity = (text.doc.dockey, text.source_locator)
            unit = units_by_identity.get(identity)
            if unit is None or text.section != unit["section"]:
                raise ValueError("native Context source identity/section mismatch")
            if not isinstance(text.text, str):
                raise ValueError("native Context original text must be a string")
            text.text.encode("utf-8")
            if type(context.score) is not int or not 1 <= context.score <= 10:
                raise ValueError("native relevance_score is invalid")
            item = {"paper_id": text.doc.dockey, "source_locator": text.source_locator,
                    "source_text": text.text, "relevance_score": context.score,
                    "contextual_summary": context.context}
            _json_bytes(item)
            if identity in evidence and evidence[identity] != item:
                raise ValueError("conflicting duplicate native Context")
            evidence[identity] = item
        if len(evidence) > task["budget"]["evidence_k"]:
            raise ValueError("native evidence exceeds frozen budget")
        return {"schema_version": "PaperQA2CorpusResult/v1", "task_id": task["task_id"],
                "task_sha256": hashlib.sha256(_json_bytes(task)).hexdigest(),
                "runtime": {"package": "paper-qa", "version": paperqa.__version__,
                            "upstream_commit": _git(repo, "rev-parse", "HEAD"),
                            "upstream_tag": _git(repo, "describe", "--tags", "--exact-match", "HEAD"),
                            "embedding_model": settings.embedding, "summary_llm_model": settings.summary_llm,
                            "settings_sha256": settings_hash},
                "execution": {"status": "COMPLETE", "ingested_paper_count": len(docs.docs),
                              "ingested_text_count": len(docs.texts), "terminal_context_error_count": 0},
                "evidence": [evidence[key] for key in sorted(evidence)]}
    finally:
        try:
            logger.removeHandler(diagnostics)
            diagnostics.close()
        except Exception:
            diagnostics.capture_failed = True
            raise
        finally:
            sys.stderr.write(_json_bytes({"paperqa2_corpus_diagnostic": {
                "task_id": task["task_id"], "capture_established": diagnostics.capture_established,
                "capture_failed": diagnostics.capture_failed,
                "terminal_context_error_count": diagnostics.terminal_context_error_count}}).decode("utf-8"))
        if diagnostics.capture_failed:
            raise ValueError("terminal diagnostic capture failed")


async def _run_search_queries(request: dict) -> dict:
    fields = {
        "worker_mode", "question", "count", "settings", "paperqa_repo",
        "pqa_home", "expected_runtime",
    }
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError("invalid keyword-query invocation envelope")
    if request["worker_mode"] != "search-query-v1":
        raise ValueError("unknown keyword-query mode")
    question = request["question"]
    if not isinstance(question, str) or not question.strip():
        raise ValueError("keyword-query question must be non-empty text")
    if type(request["count"]) is not int or request["count"] != 3:
        raise ValueError("keyword-query count must be exactly 3")
    settings_data = request["settings"]
    expected = request["expected_runtime"]
    if (not isinstance(settings_data, dict)
            or not isinstance(expected, dict)
            or set(expected) != {
                "package", "version", "upstream_tag", "upstream_commit",
                "module_path", "clean_checkout", "llm_model",
            }):
        raise ValueError("keyword-query Settings/runtime binding is invalid")
    repo = pathlib.Path(_text(request["paperqa_repo"], "paperqa_repo")).resolve(strict=True)
    pqa_home = pathlib.Path(_text(request["pqa_home"], "pqa_home")).resolve(strict=True)
    expected_module = (repo / "src" / "paperqa" / "agents" / "helpers.py").resolve(strict=True)
    if (expected["package"] != "paper-qa"
            or expected["version"] != "2026.8.12"
            or expected["upstream_tag"] != "v2026.08.12"
            or expected["upstream_commit"] != "57e89f7223b0960d5ee5ea048c69e3c47e088572"
            or expected["module_path"] != str(expected_module)
            or expected["clean_checkout"] is not True
            or not isinstance(expected["llm_model"], str)
            or not expected["llm_model"].strip()
            or settings_data.get("summary_llm") != expected["llm_model"]):
        raise ValueError("keyword-query runtime/model binding is invalid")

    os.environ["PQA_HOME"] = str(pqa_home)
    import paperqa
    from paperqa import Settings
    from paperqa.agents import helpers

    module_path = pathlib.Path(helpers.__file__).resolve(strict=True)
    try:
        module_path.relative_to(repo)
    except ValueError as exc:
        raise ValueError("PaperQA2 search helper is outside the bound checkout") from exc
    if (paperqa.__version__ != expected["version"]
            or _git(repo, "rev-parse", "HEAD") != expected["upstream_commit"]
            or _git(repo, "describe", "--tags", "--exact-match", "HEAD") != expected["upstream_tag"]
            or _git(repo, "status", "--porcelain")
            or str(module_path) != expected["module_path"]):
        raise ValueError("PaperQA2 keyword helper is not the clean bound pin")
    settings = Settings(**settings_data)
    if settings.summary_llm != expected["llm_model"]:
        raise ValueError("native summary Settings changed the frozen model binding")
    summary_llm = settings.get_summary_llm()
    proposals = await helpers.litellm_get_search_query(
        question, count=3, template=None, llm=summary_llm,
    )
    if not isinstance(proposals, list):
        raise ValueError("PaperQA2 keyword helper did not return a proposal list")
    return {
        "proposals": proposals,
        "runtime": {
            "package": "paper-qa",
            "version": paperqa.__version__,
            "upstream_tag": _git(repo, "describe", "--tags", "--exact-match", "HEAD"),
            "upstream_commit": _git(repo, "rev-parse", "HEAD"),
            "module_path": str(module_path),
            "clean_checkout": True,
            "generation_year": int(helpers.get_year()),
            "llm_model": settings.summary_llm,
        },
    }


async def _run(request: dict) -> dict:
    if isinstance(request, dict) and request.get("worker_mode") == "search-query-v1":
        return await _run_search_queries(request)
    if "worker_mode" in request or "task" in request:
        if request.get("worker_mode") != "corpus-evidence-v1":
            raise ValueError("unknown worker mode")
        return await _run_corpus(request)
    document_value = str(request.get("document_path") or "").strip()
    if document_value:
        document_path = pathlib.Path(document_value).resolve()
        media_type = _text(request.get("media_type"), "media_type")
        schema_version = "PaperQA2Runtime/v2"
        if not document_path.is_file():
            raise ValueError("document_path must point to a real file")
    else:
        document_path = pathlib.Path(_text(request.get("pdf_path"), "pdf_path")).resolve()
        media_type = "application/pdf"
        schema_version = "PaperQA2Runtime/v1"
        if not document_path.is_file() or document_path.read_bytes()[:5] != b"%PDF-":
            raise ValueError("pdf_path must point to a real PDF")
    repo = pathlib.Path(_text(request.get("paperqa_repo"), "paperqa_repo")).resolve()
    pqa_home = pathlib.Path(_text(request.get("pqa_home"), "pqa_home")).resolve()
    os.environ["PQA_HOME"] = str(pqa_home)
    from paperqa import Docs, Settings, __version__

    title = _text(request.get("title"), "title")
    doi = str(request.get("doi") or "").strip()
    question = _text(request.get("question"), "question")
    settings = Settings(
        embedding="sparse",
        answer={
            "evidence_k": int(request.get("k") or 5),
            "evidence_skip_summary": True,
            "evidence_text_only_fallback": True,
        },
        parsing={"use_doc_details": False, "multimodal": False},
    )
    docs = Docs()
    await docs.aadd(
        document_path,
        citation=title,
        title=title,
        doi=doi or None,
        settings=settings,
    )
    embedding_model = settings.get_embedding_model()
    await docs.retrieve_texts(
        question,
        settings.answer.evidence_k,
        settings=settings,
        embedding_model=embedding_model,
    )
    ranked, scores = await docs.texts_index.max_marginal_relevance_search(
        question,
        k=settings.answer.evidence_k,
        fetch_k=2 * settings.answer.evidence_k,
        embedding_model=embedding_model,
    )
    # This bridge is retrieval-only.  Calling ``aget_evidence`` here would
    # enter PaperQA2's answer-summary path even though summaries are disabled
    # above.  Some otherwise valid JATS payloads contain lone surrogate code
    # points; the summary model's Pydantic context validator rejects those
    # characters before the retrieved chunks can be returned.  The independent
    # JATS verifier downstream does the evidence-location work, so no summary
    # score is required at this boundary.
    context_scores = {}
    hits = []
    for text, score in zip(ranked, scores, strict=True):
        transport_text = _utf8_transport_text(text.text)
        if transport_text is None:
            continue
        hits.append({
            "text": transport_text,
            "locator": text.name,
            "section": "PaperQA2",
            "score": float(score),
            "context_score": context_scores.get(text.name),
            "docname": text.doc.docname,
            "content_hash": text.doc.content_hash,
        })
    document_sha256 = hashlib.sha256(document_path.read_bytes()).hexdigest()
    runtime = {
        "schema_version": schema_version,
        "package": "paper-qa",
        "version": str(__version__),
        "upstream_repo": "https://github.com/Future-House/paper-qa",
        "upstream_tag": _git(repo, "describe", "--tags", "--exact-match", "HEAD"),
        "upstream_commit": _git(repo, "rev-parse", "HEAD"),
        "fork_repo": "https://github.com/hk20013106/paper-qa",
    }
    if schema_version == "PaperQA2Runtime/v1":
        runtime["pdf_sha256"] = document_sha256
    else:
        runtime.update({
            "document_sha256": document_sha256,
            "media_type": media_type,
        })
    return {
        "engine": "paperqa2",
        "runtime": runtime,
        "hits": hits,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    request = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="strict"),
                         object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    result = asyncio.run(_run(request))
    if request.get("worker_mode") in {"corpus-evidence-v1", "search-query-v1"}:
        sys.stdout.write(_json_bytes(result).decode("utf-8"))
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
