"""Compatibility support for L4 catalogs with navigation-only sources."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def install(navigation_module) -> None:
    """Allow source-blocked catalogs without fabricating durable anchors.

    The legacy evidence persister requires one paper record. A metadata-only
    carrier satisfies that internal precondition, then is removed before the
    final run artifact and Markdown are written. Real navigation records remain.
    """
    module = navigation_module
    if getattr(module, "_NAVIGATION_CARRIER_INSTALLED", False):
        return
    original_split = module._split
    original_persist_navigation = module._persist_navigation

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

    def persist_navigation(dr, project: Path, artifact: dict, navigation: list[dict]):
        retained = []
        for ref in artifact.get("papers", []):
            try:
                paper_path = project / ref["path"]
                record = json.loads(paper_path.read_text(encoding="utf-8"))
            except (KeyError, OSError, json.JSONDecodeError):
                retained.append(ref)
                continue
            if record.get("paper_type") != "navigation_carrier":
                retained.append(ref)
                continue
            source_path = str(record.get("source_payload_path") or "")
            if source_path:
                try:
                    (project / source_path).unlink()
                except OSError:
                    pass
            try:
                paper_path.unlink()
            except OSError:
                pass
        artifact["papers"] = retained
        original_persist_navigation(dr, project, artifact, navigation)

    module._split = split
    module._persist_navigation = persist_navigation
    module._NAVIGATION_CARRIER_INSTALLED = True
