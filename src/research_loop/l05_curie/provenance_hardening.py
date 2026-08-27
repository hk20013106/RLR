"""Compatibility facade for provenance behavior owned by Curie modules."""
from __future__ import annotations


def install(multisource_module=None, selector_module=None) -> None:
    """Preserve the historical entry point; Curie modules already own behavior."""
    return None
