"""JSON stdin/stdout bridge executed by the pinned PaperQA2 environment."""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import subprocess
import sys
import os


def _text(value, name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{name} must be non-empty")
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


async def _run(request: dict) -> dict:
    pdf_path = pathlib.Path(_text(request.get("pdf_path"), "pdf_path")).resolve()
    repo = pathlib.Path(_text(request.get("paperqa_repo"), "paperqa_repo")).resolve()
    pqa_home = pathlib.Path(_text(request.get("pqa_home"), "pqa_home")).resolve()
    if not pdf_path.is_file() or pdf_path.read_bytes()[:5] != b"%PDF-":
        raise ValueError("pdf_path must point to a real PDF")
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
        pdf_path,
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
    session = await docs.aget_evidence(
        question,
        settings=settings,
        embedding_model=embedding_model,
    )
    context_scores = {context.text.name: context.score for context in session.contexts}
    hits = []
    for text, score in zip(ranked, scores, strict=True):
        hits.append({
            "text": text.text,
            "locator": text.name,
            "section": "PaperQA2",
            "score": float(score),
            "context_score": context_scores.get(text.name),
            "docname": text.doc.docname,
            "content_hash": text.doc.content_hash,
        })
    pdf_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    return {
        "engine": "paperqa2",
        "runtime": {
            "schema_version": "PaperQA2Runtime/v1",
            "package": "paper-qa",
            "version": str(__version__),
            "upstream_repo": "https://github.com/Future-House/paper-qa",
            "upstream_tag": _git(repo, "describe", "--tags", "--exact-match", "HEAD"),
            "upstream_commit": _git(repo, "rev-parse", "HEAD"),
            "fork_repo": "https://github.com/hk20013106/paper-qa",
            "pdf_sha256": pdf_sha256,
        },
        "hits": hits,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin)
    result = asyncio.run(_run(request))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
