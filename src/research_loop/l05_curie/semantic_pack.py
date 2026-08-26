"""Compatibility facade for semantic admission owned by :mod:`.store`."""
from __future__ import annotations

def _validate_semantic_pack(pack: dict) -> dict:
    from .store import _validate_semantic_pack as validate

    return validate(pack)


def install(store_module=None) -> None:
    """Preserve the historical entry point; store behavior is now native."""
    return None
