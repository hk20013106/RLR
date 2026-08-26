"""Compatibility facade for provenance behavior owned by Curie modules.

The canonical discovery and selector implementations now enforce query lineage
directly. These private delegates preserve historical module-path imports without
reintroducing import-time mutation or a second provenance implementation.
"""
from __future__ import annotations

def _record_matches(multisource_module, canonical: dict, observed: dict) -> bool:
    """Delegate the historical helper name to the canonical multisource owner."""
    return multisource_module._record_matches(canonical, observed)


def _attach_originating_queries(multisource_module, result: dict) -> dict:
    """Delegate the historical helper name to the canonical multisource owner."""
    return multisource_module._attach_originating_queries(result)


def _strict_query_ids(record: dict) -> list[str]:
    """Delegate the historical helper name to the canonical selector owner."""
    from .selector import _query_ids

    return _query_ids(record)


def install(multisource_module=None, selector_module=None) -> None:
    """Preserve the historical entry point; Curie modules own this behavior."""
    return None
