"""Compatibility facade for the single RLR internal-language contract.

Language policy is owned by :mod:`research_loop.l0_language`. This module keeps
older L0.5 imports stable without defining a second classifier or validator.
"""
from __future__ import annotations

import re

from research_loop.l0_language import (
    L0LanguageError,
    classify_user_language,
    validate_internal_english,
)

from .contracts import CurieContractError

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def contains_cjk(value: object) -> bool:
    """Compatibility helper; language policy remains owned upstream."""
    return bool(_CJK.search(str(value or "")))


def classify_supported_input_language(
    value: object,
    *,
    name: str = "scientific input",
) -> str:
    try:
        return classify_user_language(value, name=name)
    except L0LanguageError as exc:
        raise CurieContractError(str(exc)) from exc


def validate_english_retrieval_query(
    value: object,
    *,
    name: str = "English retrieval query",
) -> str:
    try:
        return validate_internal_english(value, name=name)
    except L0LanguageError as exc:
        raise CurieContractError(str(exc)) from exc


def validate_english_retrieval_queries(
    values: object,
    *,
    name: str = "English retrieval queries",
    min_items: int = 1,
    max_items: int | None = None,
) -> list[str]:
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
