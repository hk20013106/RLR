"""Install the canonical L0.5 discovery-stage semantics onto Deep Research."""
from __future__ import annotations

import json
from pathlib import Path


TARGET_NODE = "L0.5"


def install(deep_research_module) -> None:
    dr = deep_research_module
    if getattr(dr, "_L0_5_DEEP_RESEARCH_INSTALLED", False):
        return

    dr._STAGES.add(TARGET_NODE)

    original_stage_instruction = dr._stage_instruction

    def _stage_instruction(node: str) -> str:
        if node == TARGET_NODE:
            return (
                "Run literature discovery for downstream hypothesis generation. "
                "Derive actual search queries from the canonical L0 scientific "
                "question and current-round hypothesis. For every material claim, "
                "retrieve source-located Results, Discussion, and Conclusion "
                "evidence from identifiable primary research papers."
            )
        return original_stage_instruction(node)

    dr._stage_instruction = _stage_instruction

    original_audit = dr.audit_evidence_pack

    def audit_evidence_pack(project_dir, candidate_id, node, *, run_id=None):
        ok, reason = original_audit(
            project_dir, candidate_id, node, run_id=run_id
        )
        if not ok or node != TARGET_NODE:
            return ok, reason

        artifact = dr._artifact(
            project_dir, candidate_id, node, run_id=run_id
        )
        if not artifact:
            return False, f"evidence pack missing for {candidate_id} {node}"
        root = Path(project_dir)
        records = []
        for ref in artifact.get("papers", []):
            try:
                records.append(
                    json.loads((root / ref["path"]).read_text(encoding="utf-8"))
                )
            except (KeyError, OSError, json.JSONDecodeError):
                return False, "L0.5 evidence references an unreadable paper record"
        located = [
            item
            for record in records
            for item in record.get("evidence_extracts", [])
            if item.get("verification_status") == "located" and item.get("locator")
        ]
        requirements = (
            ("Results", dr._is_results_section),
            ("Discussion", dr._is_discussion_section),
            ("Conclusion", dr._is_conclusion_section),
        )
        for label, matcher in requirements:
            if not any(matcher(item.get("section")) for item in located):
                return False, f"L0.5 evidence lacks located {label} extract"
        return True, ""

    dr.audit_evidence_pack = audit_evidence_pack
    dr._L0_5_DEEP_RESEARCH_INSTALLED = True
