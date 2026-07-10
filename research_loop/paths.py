"""Pure path / hash leaf helpers (Phase 1b leaf extraction).

No engine imports -> safe leaf. research_loop_v04 imports these back
(inward shim) so external importers keep working unchanged. Delta-domain
path helpers stay in the engine until Phase 2 (they need DELTA_PERSONA).
"""
import hashlib
from pathlib import Path

from research_loop.topology import AGENTS


LAYER_TEMPLATE_FILE = {
    "L0": "L0_skill_memory_preflight.md",
    "L1": "L1_idea_divergence.md",
    "L2": "L2_idea_falsification.md",
    "L3": "L3_candidate_triage.md",
    "L4": "L4_method_brainstorm.md",
    "L5": "L5_method_falsification.md",
    "L6": "L6_analysis_plan.md",
    "L7": "L7_execution.md",
    "L8": "L8_evidence_audit.md",
    "L8.5": "L8.5_literature_verification.md",
    "L9a": "L9a_result_falsification.md",
    "L9b": "L9b_biology_interpretation.md",
    "L10a": "L10a_value_assessment.md",
    "L10b": "L10b_final_decision.md",
    "L10c": "L10c_aggregate_report.md",
}

PERSONA_TEMPLATE_FILE = {p: f"{i + 1:02d}_{p}.md" for i, p in enumerate(AGENTS)}

def _layer_template_path(node_id):
    """Relative path to a node's layer template (real on-disk filename)."""
    fname = LAYER_TEMPLATE_FILE.get(node_id, f"{node_id}.md")
    return f"templates/v03_layers/{fname}"

def _persona_template_path(persona):
    """Relative path to a persona's template (real on-disk filename)."""
    fname = PERSONA_TEMPLATE_FILE.get(persona, f"{persona}.md")
    return f"templates/v03_personas/{fname}"

def _candidate_file(project_dir, cand_id):
    return Path(project_dir) / "01_Candidates" / f"{cand_id}.md"

def _sha256(path):
    """Hex sha256 of a file's bytes, or None if it does not exist."""
    p = Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()

def _audit_dir(project_dir):
    d = Path(project_dir) / "08_Audit"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _pre_research_file(project_dir, node):
    """Canonical path for a node's pre-research summary. Written by
    `pre-research` (by the orchestrator) and injected by `assemble-context`."""
    return (Path(project_dir) / "02_Agent_Notes" / "_pre_research"
            / f"{node}_research.md")
