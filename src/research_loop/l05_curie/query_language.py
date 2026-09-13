"""Shared language contract for retrieval text sent to English literature systems.

This module owns only the retrieval-language invariant.  It does not plan
queries, invoke providers, retrieve papers, rank evidence, or own identity.
"""
from __future__ import annotations

import re
import unicodedata

from .contracts import CurieContractError


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_ASCII_LETTER = re.compile(r"[A-Za-z]")


def contains_cjk(value: object) -> bool:
    """Return whether text contains a CJK ideograph."""
    return bool(_CJK.search(str(value or "")))


def validate_english_retrieval_query(
    value: object,
    *,
    name: str = "English retrieval query",
) -> str:
    """Validate one query at the boundary to an English literature system.

    Scientific queries may still contain digits, punctuation, gene symbols,
    Greek letters, and other normal scientific notation.  They must contain an
    ASCII alphabetic term and must not contain CJK ideographs.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    if _CJK.search(text):
        raise CurieContractError(f"{name} must not contain CJK characters")
    if not _ASCII_LETTER.search(text):
        raise CurieContractError(f"{name} must contain English scientific text")
    return text


def validate_english_retrieval_queries(
    values: object,
    *,
    name: str = "English retrieval queries",
    min_items: int = 1,
    max_items: int | None = None,
) -> list[str]:
    """Validate an ordered query list without changing query identity."""
    if not isinstance(values, list):
        raise CurieContractError(f"{name} must be a list")
    if len(values) < min_items or (max_items is not None and len(values) > max_items):
        if max_items is None:
            raise CurieContractError(f"{name} must contain at least {min_items} item(s)")
        raise CurieContractError(
            f"{name} must contain between {min_items} and {max_items} items"
        )
    result: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values, 1):
        query = validate_english_retrieval_query(
            value,
            name=f"{name} item {index}",
        )
        key = query.casefold()
        if key in seen:
            raise CurieContractError(f"{name} must not contain duplicate queries")
        seen.add(key)
        result.append(query)
    return result
