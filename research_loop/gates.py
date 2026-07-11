"""Audit gates (Phase 3b). Each returns (ok, reason); rc mapping stays in
the engine. Imports only leaf modules -> no cycle.
"""
import json
import datetime as _dt
from pathlib import Path

from research_loop.paths import _candidate_file, _pre_research_file
from research_loop.yamlio import _load_yaml_front
from research_loop.delta import _delta_for_candidate
from research_loop import l0_contract
from research_loop.ledger import _read_branch_ledger, _prior_unexplored_ids
from research_loop.preresearch import (
    _validate_pre_research_content, _parse_pre_research_provenance,
    _query_family_key, _load_query_family_cache,
)


def _audit_pre_research(project_dir, node_id, pr_cfg):
    """V0.5 deep-research gate. Returns (ok, reason).

    Fails closed when the pre-research artifact is missing, empty, a NOT YET RUN
    placeholder, or (for literature nodes) lacks a `## Runtime digest` carrying a
    DOI/PMID/URL. This is the single enforcement point for the canonical V0.5
    runtime -- there is no path that treats absent deep research as success.
    """
    prf = _pre_research_file(project_dir, node_id)
    if not prf.exists():
        return False, f"artifact missing ({prf.as_posix()})"
    text = prf.read_text(encoding="utf-8", errors="replace")
    return _validate_pre_research_content(text, pr_cfg)

def _audit_branch_coverage(project_dir, cand_id):
    """Every prior unexplored branch must be statused in this candidate's ledger.
    Hard-fails only for from_memory + loop_type=divergent."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory") or fm.get("loop_type") != "divergent":
        return True, ""
    prior = set(_prior_unexplored_ids(project_dir, cand_id))
    have = {b.get("id"): b.get("status")
            for b in _read_branch_ledger(project_dir, cand_id).get("branches", [])}
    missing = [b for b in prior if not have.get(b)]
    if missing:
        return False, f"branch gate: prior unexplored branches not statused: {sorted(missing)}"
    return True, ""

DIVERGENCE_MIN_NEW_QUERY_FAMILIES = 2

def _audit_divergence(project_dir, node_id, cand_id):
    """L1 divergence gate. Hard-fails only for from_memory + loop_type=divergent.
    Requires >= DIVERGENCE_MIN_NEW_QUERY_FAMILIES query families not already in the
    cache, and rejects a pre-research artifact that predates candidate creation."""
    project_dir = Path(project_dir)
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    if fm.get("loop_type") != "divergent":
        return True, ""  # correction / data-acquisition bypass the family requirement
    prf = _pre_research_file(project_dir, node_id)
    if not prf.exists():
        return False, f"divergence gate: pre-research artifact missing for {node_id}"
    created = fm.get("created_at", "")
    try:
        if created:
            ct = _dt.datetime.fromisoformat(created).timestamp()
            if prf.stat().st_mtime < ct:
                return False, ("divergence gate: pre-research artifact predates candidate "
                               "creation (stale reuse)")
    except Exception:
        pass
    prov = _parse_pre_research_provenance(prf.read_text(encoding="utf-8"))
    fams = {_query_family_key(q) for q in prov.get("query_log", []) if q.strip()}
    cache = {_query_family_key(q) for q in _load_query_family_cache(project_dir)}
    new = {f for f in fams if f and f not in cache}
    need = DIVERGENCE_MIN_NEW_QUERY_FAMILIES
    if len(new) < need:
        return False, (f"divergence gate: only {len(new)} new query families "
                       f"(need >= {need}); reused={sorted(fams & cache)}")
    return True, ""

def _audit_l10_traceability(project_dir, cand_id, delta):
    """L10b gate: for from_memory candidates, the decision must state whether
    literature changed direction and carry a decision_grounding block."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    if "literature_changed_direction" not in delta:
        return False, "L10b must state `literature_changed_direction` (bool) explicitly"
    if not isinstance(delta.get("literature_changed_direction"), bool):
        return False, "`literature_changed_direction` must be a boolean"
    dg = delta.get("decision_grounding") or {}
    for k in ("paper_card_ids", "method_card_ids", "branch_ids"):
        if k not in dg:
            return False, f"decision_grounding missing `{k}`"
    return True, ""

def _l6_script_branches(project_dir, cand_id):
    p = _delta_for_candidate(project_dir, "L6_oppenheimer", cand_id)
    out = {}
    if p and p.exists():
        try:
            for s in (json.loads(p.read_text(encoding="utf-8")).get("analysis_plan") or {}).get("scripts", []):
                if isinstance(s, dict) and s.get("name"):
                    out[s["name"]] = s.get("branch_id")
        except Exception:
            pass
    return out

def _audit_l7_manifest(project_dir, cand_id, delta):
    """L7 gate: for from_memory candidates, every executed script must map to an
    approved L6 script + a branch_id (consistent with L6's branch)."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    l6 = _l6_script_branches(project_dir, cand_id)
    for s in delta.get("scripts_run", []):
        name = s.get("name")
        if not s.get("branch_id"):
            return False, f"L7 script {name!r}: missing branch_id"
        if name not in l6:
            return False, f"L7 script {name!r} not found in approved L6 analysis_plan"
        if l6[name] and s["branch_id"] != l6[name]:
            return False, f"L7 script {name!r}: branch_id {s['branch_id']!r} != L6 {l6[name]!r}"
    return True, ""

def _critique_ref_valid(project_dir, cand_id, ref):
    """ref form 'L2_feynman#<idx>' or 'L5_tukey#<idx>' -> must point at a real attack."""
    try:
        key, idx = ref.split("#")
        idx = int(idx)
    except Exception:
        return False
    p = _delta_for_candidate(project_dir, key, cand_id)
    if not (p and p.exists()):
        return False
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return 0 <= idx < len(obj.get("attacks", []))

def _audit_l6_traceability(project_dir, cand_id, delta):
    """L6 gate: for from_memory candidates, every analysis-plan script must carry a
    valid grounding (method_card | internal_critique | prior_reuse) and a branch_id."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    scripts = (delta.get("analysis_plan") or {}).get("scripts", [])
    mc_dir = Path(project_dir) / "09_Literature_Database" / "method_cards"
    for s in scripts:
        if isinstance(s, str):
            return False, (f"L6 script {s!r} is a bare string; must be an object with "
                           f"grounding/branch_id/data_modality")
        g = s.get("grounding") or {}
        gtype = g.get("type")
        if gtype == "method_card":
            ids = g.get("method_card_ids", []) or []
            if not ids or not all((mc_dir / f"{i}.json").exists() for i in ids):
                return False, f"L6 script {s.get('name')!r}: method_card grounding refs missing cards"
        elif gtype == "internal_critique":
            ref = g.get("critique_delta_ref", "")
            if not _critique_ref_valid(project_dir, cand_id, ref):
                return False, f"L6 script {s.get('name')!r}: critique_delta_ref {ref!r} not found"
        elif gtype == "prior_reuse":
            if not g.get("reused_from"):
                return False, f"L6 script {s.get('name')!r}: prior_reuse missing reused_from"
        else:
            return False, (f"L6 script {s.get('name')!r}: grounding.type must be one of "
                           f"method_card|internal_critique|prior_reuse")
        if not s.get("branch_id"):
            return False, f"L6 script {s.get('name')!r}: missing branch_id"
    return True, ""

def _audit_l4_methods(project_dir, cand_id, delta):
    """L4 method gate: for from_memory candidates, every method-dependent script
    must cite a full_text method_card, unless marked status=internally_motivated."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    mc_dir = Path(project_dir) / "09_Literature_Database" / "method_cards"

    def _is_fulltext(mc_id):
        p = mc_dir / f"{mc_id}.json"
        if not p.exists():
            return False
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("extracted_from") == "full_text"
        except Exception:
            return False

    for s in delta.get("scripts_needed", []):
        if s.get("status") == "internally_motivated":
            continue
        ids = s.get("grounded_in_method_card_ids", []) or []
        if not any(_is_fulltext(i) for i in ids):
            return False, (f"L4 script {s.get('name')!r} is method-dependent but has no "
                           f"full_text method_card (ids={ids}); add one or mark status "
                           f"'internally_motivated'")
    return True, ""

def _audit_l0_memory(project_dir, cand_id, delta):
    """Gate: from_memory candidates must carry a hash-matching prior_loop_memory.
    No-op for legacy (non-from_memory) candidates."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    plm = delta.get("prior_loop_memory")
    if not plm:
        return False, "candidate is from_memory but L0 delta lacks `prior_loop_memory`"
    expected = fm.get("memory_hash", "")
    if plm.get("memory_hash") != expected:
        return False, (f"prior_loop_memory.memory_hash mismatch: "
                       f"delta={plm.get('memory_hash')!r} frontmatter={expected!r}")
    for req in ("previous_hypothesis", "next_round_hypothesis", "required_new_search_directions"):
        if not plm.get(req):
            return False, f"prior_loop_memory missing `{req}`"
    return True, ""


def _audit_l0_contract(project_dir, cand_id):
    """Strict L0 input-contract gate (strict-on-reaching-L0; no legacy soft-floor).

    Loads the structured input artifact + frontmatter pointers and runs the ONE
    authoritative validator (l0_contract.validate_l0_input_contract). Returns
    (ok, reason). This is the single validation authority shared by
    assemble-context L0 and emit-delta L0."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    contract, ap, raw = l0_contract.load_contract(project_dir, cand_id)
    errs = l0_contract.validate_l0_input_contract(
        contract, fm, project_dir, cand_id, artifact_path=ap, raw_bytes=raw)
    return (len(errs) == 0, "; ".join(errs))
