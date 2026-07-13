"""Branch / modality ledger readers (Phase 3a leaf)."""
import json
from pathlib import Path

from research_loop.paths import _candidate_file
from research_loop.yamlio import _load_yaml_front


def _branch_ledger_path(project_dir, cand_id):
    return Path(project_dir) / "08_Audit" / "branch_ledger" / f"{cand_id}.json"

def _read_branch_ledger(project_dir, cand_id):
    p = _branch_ledger_path(project_dir, cand_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"branches": []}
    return {"branches": []}

def _modality_ledger_path(project_dir, cand_id):
    return Path(project_dir) / "08_Audit" / "modality_ledger" / f"{cand_id}.json"

def _read_modality_ledger(project_dir, cand_id):
    p = _modality_ledger_path(project_dir, cand_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"used": [], "available_unused": []}
    return {"used": [], "available_unused": []}

def _prior_unexplored_ids(project_dir, cand_id):
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    mf = fm.get("memory_file")
    if not mf or not Path(mf).exists():
        return []
    try:
        mem = json.loads(Path(mf).read_text(encoding="utf-8"))
    except Exception:
        return []
    return [b.get("id") for b in mem.get("unexplored_branches", []) if b.get("id")]
