"""Shared language contract for retrieval text sent to English literature systems.

This module owns only the retrieval-language invariant. It does not plan
queries, invoke providers, retrieve papers, rank evidence, or own identity.
Input-language support is intentionally limited to Chinese and English.
"""
from __future__ import annotations

import re
import unicodedata

from .contracts import CurieContractError


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
_ASCII_LETTER = re.compile(r"[A-Za-z]")


def contains_cjk(value: object) -> bool:
    """Return whether text contains a Chinese Han ideograph."""
    return bool(_CJK.search(str(value or "")))


def _is_cjk_char(char: str) -> bool:
    return bool(_CJK.fullmatch(char))


def _is_greek_char(char: str) -> bool:
    return bool(_GREEK.fullmatch(char))


def _isolated_scientific_greek(text: str, index: int) -> bool:
    """Allow Greek symbols such as β-catenin, TGF-β, ΔFosB, or μm.

    Consecutive Greek alphabetic characters are treated as a Greek-language
    word and remain unsupported. This permits scientific notation without
    expanding the supported natural-language set beyond Chinese and English.
    """
    char = text[index]
    if not _is_greek_char(char):
        return False
    previous = text[index - 1] if index else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    return not (
        (previous.isalpha() and _is_greek_char(previous))
        or (following.isalpha() and _is_greek_char(following))
    )


def _unsupported_alphabetic_chars(text: str) -> list[str]:
    """Return alphabetic characters outside Chinese/ASCII plus scientific symbols."""
    unsupported = []
    for index, char in enumerate(text):
        if not char.isalpha():
            continue
        if "A" <= char <= "Z" or "a" <= char <= "z" or _is_cjk_char(char):
            continue
        if _isolated_scientific_greek(text, index):
            continue
        unsupported.append(char)
    return unsupported


def classify_supported_input_language(
    value: object,
    *,
    name: str = "scientific input",
) -> str:
    """Classify supported input as Chinese or English; reject other languages.

    Mixed Chinese + ASCII scientific terminology is classified as Chinese and
    therefore goes through provider translation/planning. English scientific
    text may contain isolated Greek symbols such as β-catenin or α-synuclein.
    Other alphabetic scripts are intentionally out of scope and fail closed.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    unsupported = _unsupported_alphabetic_chars(text)
    if unsupported:
        raise CurieContractError(
            f"{name} uses an unsupported input language; only Chinese and English are supported"
        )
    if _CJK.search(text):
        return "zh"
    if _ASCII_LETTER.search(text):
        return "en"
    raise CurieContractError(
        f"{name} must contain supported Chinese or English scientific text"
    )


def validate_english_retrieval_query(
    value: object,
    *,
    name: str = "English retrieval query",
) -> str:
    """Validate one query at the boundary to an English literature system.

    Retrieval queries may contain digits, scientific punctuation, and isolated
    Greek scientific symbols, but natural-language alphabetic text must remain
    English. Chinese and unsupported language scripts fail closed.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    if _CJK.search(text) or _unsupported_alphabetic_chars(text):
        raise CurieContractError(f"{name} must contain English-only scientific text")
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
