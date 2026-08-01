"""Compatibility support for L4 catalogs with navigation-only sources."""
from __future__ import annotations

import copy


def install(navigation_module) -> None:
    """Allow a source-blocked catalog to persist without fabricating an anchor.

    The underlying legacy evidence persister requires at least one paper record.
    When the raw L4 result contains only navigation evidence, provide a
    metadata-only carrier with no extracts and no source payload. The real
    navigation extracts are persisted separately and never count as anchors.
    """
    module = navigation_module
    if getattr(module, "_NAVIGATION_CARRIER_INSTALLED", False):
        return
    original_split = module._split

    def split(payload: dict):
        method_payload, navigation = original_split(payload)
        if not method_payload.get("papers") and navigation:
            carrier = copy.deepcopy(navigation[0])
            carrier["extracts"] = []
            carrier["source_payload"] = ""
            carrier["open_access"] = False
            carrier["paper_type"] = "navigation_carrier"
            method_payload["papers"] = [carrier]
        return method_payload, navigation

    module._split = split
    module._NAVIGATION_CARRIER_INSTALLED = True
