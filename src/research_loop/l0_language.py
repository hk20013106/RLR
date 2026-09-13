"""One-time user-language normalization at the L0 -> ResearchSeed boundary.

Raw user intake may be Chinese or English. Canonical internal scientific
semantics are English-only. This module owns language classification and the
pure normalize-once contract; provider execution is supplied by the caller.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Callable


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
_ASCII_LETTER = re.compile(r"[A-Za-z]")


class L0LanguageError(ValueError):
    """Raised when user-language normalization cannot produce safe English."""


def _is_cjk(char: str) -> bool:
    return bool(_CJK.fullmatch(char))


def _is_greek(char: str) -> bool:
    return bool(_GREEK.fullmatch(char))


def _isolated_scientific_greek(text: str, index: int) -> bool:
    char = text[index]
    if not _is_greek(char):
        return False
    previous = text[index - 1] if index else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    return not (
        (previous.isalpha() and _is_greek(previous))
        or (following.isalpha() and _is_greek(following))
    )


def _unsupported_alphabetic_chars(text: str) -> list[str]:
    unsupported = []
    for index, char in enumerate(text):
        if not char.isalpha():
            continue
        if "A" <= char <= "Z" or "a" <= char <= "z" or _is_cjk(char):
            continue
        if _isolated_scientific_greek(text, index):
            continue
        unsupported.append(char)
    return unsupported


def classify_user_language(value: object, *, name: str = "user scientific input") -> str:
    """Return ``zh`` or ``en``; every other natural-language script fails closed."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        raise L0LanguageError(f"{name} must be a non-empty string")
    if _unsupported_alphabetic_chars(text):
        raise L0LanguageError(
            f"{name} uses an unsupported input language; only Chinese and English are supported"
        )
    if _CJK.search(text):
        return "zh"
    if _ASCII_LETTER.search(text):
        return "en"
    raise L0LanguageError(
        f"{name} must contain supported Chinese or English scientific text"
    )


def validate_internal_english(value: object, *, name: str = "internal scientific text") -> str:
    """Require English natural-language text while allowing scientific symbols."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        raise L0LanguageError(f"{name} must be a non-empty string")
    if _CJK.search(text) or _unsupported_alphabetic_chars(text):
        raise L0LanguageError(f"{name} must be English internal scientific text")
    if not _ASCII_LETTER.search(text):
        raise L0LanguageError(f"{name} must contain English scientific text")
    return text


def _digest(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_semantic_fields(
    fields: dict[str, str],
    *,
    translator: Callable[[dict[str, str]], tuple[dict[str, str], dict]] | None = None,
) -> tuple[dict[str, str], dict]:
    """Normalize user-facing semantic fields exactly once into internal English.

    English fields pass through byte-for-byte. If any field is Chinese, the
    supplied translator is invoked once for the complete field set. Its output
    must preserve every key, leave originally-English fields unchanged, and
    return English text for every field.
    """
    if not isinstance(fields, dict) or not fields:
        raise L0LanguageError("semantic fields must be a non-empty mapping")
    clean: dict[str, str] = {}
    languages: dict[str, str] = {}
    for key, value in fields.items():
        name = str(key or "").strip()
        if not name:
            raise L0LanguageError("semantic field name must be non-empty")
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        language = classify_user_language(text, name=name)
        clean[name] = text
        languages[name] = language

    if set(languages.values()) == {"en"}:
        normalized = {
            key: validate_internal_english(value, name=key)
            for key, value in clean.items()
        }
        return normalized, {
            "schema_version": "L0LanguageNormalization/v1",
            "mode": "passthrough",
            "source_languages": languages,
            "target_language": "en",
            "input_sha256": _digest(clean),
            "output_sha256": _digest(normalized),
            "provider_receipt": None,
        }

    if translator is None:
        raise L0LanguageError(
            "Chinese user input requires the configured one-time English normalization provider"
        )
    translated, provider_receipt = translator(dict(clean))
    if not isinstance(translated, dict) or set(translated) != set(clean):
        raise L0LanguageError(
            "English normalization provider must return exactly the supplied semantic fields"
        )
    normalized: dict[str, str] = {}
    for key, value in translated.items():
        normalized[key] = validate_internal_english(value, name=f"normalized {key}")
        if languages[key] == "en" and normalized[key] != clean[key]:
            raise L0LanguageError(
                f"English field {key} must pass through unchanged during normalization"
            )
    return normalized, {
        "schema_version": "L0LanguageNormalization/v1",
        "mode": "translated",
        "source_languages": languages,
        "target_language": "en",
        "input_sha256": _digest(clean),
        "output_sha256": _digest(normalized),
        "provider_receipt": dict(provider_receipt or {}),
    }
