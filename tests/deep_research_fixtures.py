"""Small synthetic Deep Research fixtures for tests that exercise real gates."""
from __future__ import annotations

import json
from pathlib import Path

from research_loop import deep_research
from research_loop.paths import _pre_research_file


def persist_synthetic_evidence(project_dir, candidate_id, node, queries, *, result_context=""):
    """Persist a source-located pack and its matching pre-research summary."""
    payload = {
        "schema_version": deep_research.SCHEMA_VERSION,
        "queries": list(queries),
        "papers": [{
            "url": f"https://example.invalid/synthetic-evidence/{node}/{candidate_id}",
            "title": "Synthetic evidence fixture",
            "source_database": "Synthetic fixture database",
            "metadata": {"fixture": True},
            "source_metadata_response": {"candidate_id": candidate_id, "node": node},
            "open_access": False,
            "extracts": [
                {"section": "Results", "text": "Synthetic observed result.", "locator": "Results 1"},
                {"section": "Discussion", "text": "Synthetic discussion.", "locator": "Discussion 1"},
                {"section": "Conclusion", "text": "Synthetic conclusion.", "locator": "Conclusion 1"},
            ],
        }],
    }
    artifact = deep_research.persist_run(
        project_dir, candidate_id, node, payload,
        deep_research.skill_receipt("codex", ["codex", "exec"], "synthetic fixture", "test"),
        result_context=result_context,
    )
    if node == "L8.5":
        artifact["verification"] = [{
            "finding": "Synthetic L7/L8 result",
            "verdict": "supports",
            "evidence_ids": [artifact["papers"][0]["evidence_ids"][0]],
        }]
        run_path = Path(project_dir) / artifact["path"]
        run_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    pre_research = _pre_research_file(project_dir, node)
    pre_research.parent.mkdir(parents=True, exist_ok=True)
    pre_research.write_text(deep_research.render_pre_research_markdown(artifact), encoding="utf-8")
    ok, reason = deep_research.audit_evidence_pack(project_dir, candidate_id, node)
    assert ok, reason
    return artifact
