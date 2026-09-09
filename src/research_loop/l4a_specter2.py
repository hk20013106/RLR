"""Lazy SPECTER2 semantic pre-ranking for contextual L4A candidates.

The module deliberately owns neither bibliographic identity nor selector
policy.  It accepts canonical Curie records and returns semantic scores for
the caller's paper-by-method candidate set.  The heavyweight runtime is
loaded only when the real ranker is requested, so normal RLR imports and unit
tests do not require torch or the adapter-transformers stack.
"""
from __future__ import annotations

import math
import os
from functools import lru_cache
from typing import Any


BASE_MODEL = "allenai/specter2_base"
BASE_REVISION = "3447645e1def9117997203454fa4495937bfbd83"
PAPER_ADAPTER = "allenai/specter2"
PAPER_REVISION = "2081559630a80fc5851d8f798a05ba81e9468089"
QUERY_ADAPTER = "allenai/specter2_adhoc_query"
QUERY_REVISION = "3f4448817028388648a74349ece07af4518ec5bd"
MAX_LENGTH = 512
DEFAULT_BATCH_SIZE = 8


class Specter2Error(RuntimeError):
    """Raised when the configured SPECTER2 runtime cannot produce scores."""


def _text(value: object) -> str:
    return str(value or "").strip()


def build_paper_text(title: object, abstract: object, sep_token: object) -> str:
    """Build the official SPECTER2 paper input, allowing title-only records."""

    title_text = _text(title)
    abstract_text = _text(abstract)
    if not title_text:
        raise ValueError("SPECTER2 paper title must be non-empty")
    if not abstract_text:
        return title_text
    separator = _text(sep_token)
    if not separator:
        raise ValueError("SPECTER2 tokenizer separator must be non-empty")
    return f"{title_text}{separator}{abstract_text}"


def _record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _record_paper_id(record: dict[str, Any]) -> str:
    paper_id = _text(record.get("paper_id"))
    if not paper_id:
        raise ValueError("canonical SPECTER2 record has no paper_id")
    return paper_id


def _validate_records(records: list[dict[str, Any]]) -> list[str]:
    if not isinstance(records, list):
        raise TypeError("SPECTER2 canonical_records must be a list")
    paper_ids: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("SPECTER2 canonical record must be an object")
        paper_id = _record_paper_id(record)
        if paper_id in paper_ids:
            raise ValueError(f"SPECTER2 received duplicate paper_id: {paper_id}")
        if not _text(record.get("title")):
            raise ValueError(f"SPECTER2 record {paper_id} has no title")
        paper_ids.append(paper_id)
    return paper_ids


def _configured_batch_size(value: object = None) -> int:
    raw = value
    if raw is None:
        raw = os.environ.get("RLR_SPECTER2_BATCH_SIZE")
    try:
        number = int(raw) if raw not in (None, "") else DEFAULT_BATCH_SIZE
    except (TypeError, ValueError):
        number = DEFAULT_BATCH_SIZE
    return number if number > 0 else DEFAULT_BATCH_SIZE


def _configured_device(torch: Any, value: object = None) -> str:
    requested = _text(value or os.environ.get("RLR_SPECTER2_DEVICE")).casefold()
    if requested in {"", "auto"}:
        requested = "cuda" if bool(torch.cuda.is_available()) else "cpu"
    if requested == "cuda" and not bool(torch.cuda.is_available()):
        return "cpu"
    if requested not in {"cpu", "cuda"}:
        raise ValueError("RLR_SPECTER2_DEVICE must be one of auto, cpu, or cuda")
    return requested


class Specter2Ranker:
    """Official SPECTER2 adapter runtime with batched deterministic inference."""

    def __init__(
        self,
        tokenizer: Any,
        model: Any,
        torch: Any,
        *,
        device: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.tokenizer = tokenizer
        self.model = model
        self.torch = torch
        self.device = str(device)
        self.batch_size = _configured_batch_size(batch_size)
        self.model.eval()

    @classmethod
    def from_pretrained(
        cls, *, device: str | None = None, batch_size: int | None = None
    ) -> "Specter2Ranker":
        try:
            import torch
            from adapters import AutoAdapterModel
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(
                BASE_MODEL, revision=BASE_REVISION
            )
            model = AutoAdapterModel.from_pretrained(
                BASE_MODEL, revision=BASE_REVISION
            )
            model.load_adapter(
                PAPER_ADAPTER,
                source="hf",
                revision=PAPER_REVISION,
                load_as="proximity",
            )
            model.load_adapter(
                QUERY_ADAPTER,
                source="hf",
                revision=QUERY_REVISION,
                load_as="adhoc_query",
            )
            selected_device = _configured_device(torch, device)
            model.to(selected_device)
            model.eval()
            return cls(
                tokenizer,
                model,
                torch,
                device=selected_device,
                batch_size=_configured_batch_size(batch_size),
            )
        except Specter2Error:
            raise
        except Exception as exc:  # pragma: no cover - exercised by runtime smoke
            raise Specter2Error(
                "SPECTER2 runtime could not load the pinned base model/adapters: "
                f"{exc}"
            ) from exc

    def receipt(self) -> dict[str, Any]:
        """Return auditable runtime identity without inventing paper identity."""

        return {
            "implementation": "research_loop.l4a_specter2.Specter2Ranker",
            "base_model": BASE_MODEL,
            "base_revision": BASE_REVISION,
            "paper_adapter": PAPER_ADAPTER,
            "paper_revision": PAPER_REVISION,
            "query_adapter": QUERY_ADAPTER,
            "query_revision": QUERY_REVISION,
            "max_length": MAX_LENGTH,
            "batch_size": self.batch_size,
            "device": self.device,
            "deterministic_inference": True,
            "no_grad": True,
        }

    def _encode(self, texts: list[str], adapter_name: str) -> Any:
        if not texts:
            raise ValueError("SPECTER2 cannot encode an empty text batch")
        self.model.set_active_adapters(adapter_name)
        chunks = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            inputs = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                return_tensors="pt",
                return_token_type_ids=False,
                max_length=MAX_LENGTH,
            )
            if "token_type_ids" in inputs:
                del inputs["token_type_ids"]
            inputs = {
                key: value.to(self.device) for key, value in inputs.items()
            }
            with self.torch.no_grad():
                output = self.model(**inputs)
            hidden = getattr(output, "last_hidden_state", None)
            if hidden is None or getattr(hidden, "ndim", 0) != 3:
                raise Specter2Error(
                    "SPECTER2 model output has no 3-dimensional last_hidden_state"
                )
            chunks.append(hidden[:, 0, :].detach().cpu())
        embeddings = self.torch.cat(chunks, dim=0)
        if embeddings.ndim != 2 or embeddings.shape[0] != len(texts):
            raise Specter2Error(
                "SPECTER2 embedding count/shape does not match the input batch"
            )
        return embeddings

    def rank_method_papers(
        self, method_query: str, canonical_records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        query = _text(method_query)
        if not query:
            raise ValueError("SPECTER2 method query must be non-empty")
        paper_ids = _validate_records(canonical_records)
        if not paper_ids:
            return []
        separator = self.tokenizer.sep_token
        paper_texts = [
            build_paper_text(
                record.get("title"),
                _record_metadata(record).get("abstract"),
                separator,
            )
            for record in canonical_records
        ]
        paper_embeddings = self._encode(paper_texts, "proximity")
        query_embedding = self._encode([query], "adhoc_query")[0]
        paper_norms = paper_embeddings.norm(dim=1).clamp_min(1e-12)
        query_norm = query_embedding.norm().clamp_min(1e-12)
        scores = (paper_embeddings / paper_norms.unsqueeze(1)) @ (
            query_embedding / query_norm
        )
        if not bool(self.torch.isfinite(scores).all()):
            raise Specter2Error("SPECTER2 cosine similarity produced a non-finite value")
        scored = [
            (index, float(scores[index].item()))
            for index in range(len(paper_ids))
        ]
        if any(not math.isfinite(score) for _, score in scored):
            raise Specter2Error("SPECTER2 cosine similarity produced a non-finite value")
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [
            {
                "paper_id": paper_ids[index],
                "semantic_score": score,
                "semantic_rank": rank,
            }
            for rank, (index, score) in enumerate(scored, 1)
        ]


@lru_cache(maxsize=1)
def _cached_specter2_ranker() -> Specter2Ranker:
    return Specter2Ranker.from_pretrained()


def get_specter2_ranker() -> Specter2Ranker:
    """Return the process-scoped lazy ranker; tests can replace this seam."""

    return _cached_specter2_ranker()


def ranker_receipt(ranker: object) -> dict[str, Any]:
    receipt = getattr(ranker, "receipt", None)
    if callable(receipt):
        value = receipt()
        if isinstance(value, dict):
            return dict(value)
    return {
        "implementation": f"injected:{type(ranker).__module__}.{type(ranker).__name__}",
        "deterministic_inference": True,
        "injected": True,
    }


def rank_method_papers(
    method_query: str,
    canonical_records: list[dict[str, Any]],
    *,
    ranker: object | None = None,
) -> list[dict[str, Any]]:
    """Rank canonical records, with an explicit seam for deterministic tests."""

    _validate_records(canonical_records)
    selected_ranker = ranker if ranker is not None else get_specter2_ranker()
    method = getattr(selected_ranker, "rank_method_papers", None)
    if not callable(method):
        raise TypeError("SPECTER2 ranker must expose rank_method_papers")
    raw = method(method_query, canonical_records)
    if not isinstance(raw, list):
        raise TypeError("SPECTER2 ranker result must be a list")

    known_ids = {_text(record.get("paper_id")) for record in canonical_records}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise TypeError("SPECTER2 ranker result item must be an object")
        paper_id = _text(item.get("paper_id"))
        if not paper_id or paper_id not in known_ids:
            raise ValueError(
                f"SPECTER2 ranker returned unknown paper_id: {paper_id or '<empty>'}"
            )
        if paper_id in seen:
            raise ValueError(f"SPECTER2 ranker returned duplicate paper_id: {paper_id}")
        seen.add(paper_id)
        score = item.get("semantic_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"SPECTER2 score for {paper_id} is not numeric")
        score = float(score)
        if not math.isfinite(score):
            raise ValueError(f"SPECTER2 score for {paper_id} is not finite")
        if not -1.0 <= score <= 1.0:
            raise ValueError(f"SPECTER2 cosine score for {paper_id} is outside [-1, 1]")
        rank = item.get("semantic_rank", index)
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ValueError(f"SPECTER2 rank for {paper_id} is invalid")
        normalized.append({
            "paper_id": paper_id,
            "semantic_score": score,
            "semantic_rank": rank,
        })
    ranks = [int(item["semantic_rank"]) for item in normalized]
    if len(ranks) != len(set(ranks)) or set(ranks) != set(range(1, len(ranks) + 1)):
        raise ValueError("SPECTER2 ranker result ranks must be unique and contiguous")
    return normalized
