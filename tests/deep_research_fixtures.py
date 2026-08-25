"""Small synthetic Deep Research fixtures for tests that exercise real gates."""
from __future__ import annotations

import json
from pathlib import Path

from research_loop import deep_research, l05_curie, research_seed
from research_loop.compatibility import get_profile
from research_loop.hypothesis_ledger import binding_path
from research_loop.paths import _pre_research_file
from research_loop.topology import topology_for_profile
from research_loop.yamlio import _load_yaml_front


def persist_synthetic_evidence(project_dir, candidate_id, node, queries, *, result_context=""):
    """Persist source-located evidence using the authority of the bound profile.

    Historical v2.0 fixtures retain the legacy ResearchSeed -> Deep Research
    binding. Native v2.1 fixtures use the same synthetic source only as a test
    acquisition backend, freeze it into a Curie EvidencePack, and bind that pack
    through the native authority path. This keeps test setup representative of
    production Phase 3 without giving Einstein a legacy acquisition fallback.
    """
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
    binding = json.loads(binding_path(project_dir).read_text(encoding="utf-8"))
    profile_id = str(binding["profile_id"])
    profile = get_profile(profile_id)
    candidate = _load_yaml_front(
        Path(project_dir) / "01_Candidates" / f"{candidate_id}.md"
    )
    _, node_map, _ = topology_for_profile(profile_id)
    artifact = deep_research.persist_run(
        project_dir, candidate_id, node, payload,
        deep_research.skill_receipt("codex", ["codex", "exec"], "synthetic fixture", "test"),
        result_context=result_context,
        project_id=str(binding["project_id"]),
        round_id=str(candidate.get("round_id") or "1"),
        profile_id=profile_id,
        research_persona=str(node_map[node].get("research_persona") or "Curie"),
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
    if node == "L1":
        seed = research_seed.load_l1_research_seed(project_dir, candidate_id)
        if profile.delta_schema_version == "2.1":
            manifest = l05_curie.freeze_l1_deep_research_run(
                project_dir,
                candidate_id=str(seed["candidate_id"]),
                round_id=str(seed["round_id"]),
                seed_sha256=research_seed.seed_sha256(seed),
                run_id=artifact["run_id"],
            )
            research_seed.write_l1_native_evidence_binding(
                project_dir, seed, manifest, artifact["run_id"]
            )
        else:
            research_seed.write_l1_evidence_binding(
                project_dir, seed, artifact["run_id"]
            )
    return artifact
