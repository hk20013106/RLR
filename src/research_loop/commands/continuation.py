import json
import sys
from pathlib import Path

from research_loop.commands.ledger import _ledger_for
from research_loop.common import _sha256_file
from research_loop.delta import _delta_for_candidate
from research_loop.delta_render import SEED_SCHEMA_KEYS
from research_loop.hypothesis_ledger import LedgerError, binding_path
from research_loop.l0_state import round_manifest_path, write_round_manifest
from research_loop.ledger import (
    _branch_ledger_path, _read_branch_ledger,
    _modality_ledger_path, _read_modality_ledger,
)
from research_loop.paths import _candidate_file
from research_loop.yamlio import _load_yaml_front


def _list_card_ids(project_dir, cand_id, sub):
    d = Path(project_dir) / "09_Literature_Database" / sub
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def _build_loop_memory(project_dir, cand_id, knowledge_store=None):
    project_dir = Path(project_dir)
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}

    def _d(key):
        p = _delta_for_candidate(project_dir, key, cand_id)
        if p and p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    l1 = _d("L1_einstein")
    l10 = _d("L10b_oppenheimer")
    primary_id = l1.get("primary_hypothesis_id", "")
    primary_item = next((item for item in l1.get("hypotheses", [])
                         if item.get("hypothesis_id") == primary_id), {})
    previous_hypothesis = (l1.get("primary_hypothesis")
                           or primary_item.get("statement") or "")
    branches = l1.get("candidate_branches", []) or []
    bl = _read_branch_ledger(project_dir, cand_id)
    ml = _read_modality_ledger(project_dir, cand_id)
    # Round lineage: the source candidate's round_id (legacy candidates predate
    # it -> default "1"); the next round is +1.
    _src_rid = str(fm.get("round_id") or "1")
    _next_rid = str(int(_src_rid) + 1) if _src_rid.isdigit() else _src_rid
    memory = {
        "source_candidate_id": cand_id,
        "terminal_node": "L10c",
        "terminal_decision": l10.get("decision", ""),
        "original_question": fm.get("question", ""),
        "previous_hypothesis": previous_hypothesis,
        "final_reason": l10.get("reason", ""),
        "next_round_hypothesis": l10.get("next_round_hypothesis", ""),
        # v1.0 input-contract seed fields: decision and conclusion are kept as
        # SEPARATE clean fields (no "DROP: reason" munge). new_hypothesis is
        # stored distinct from previous_hypothesis. round_id/parent_round_id link
        # the continuation's contract to this round.
        "previous_final_decision": l10.get("decision", ""),
        "previous_conclusion": l10.get("reason", ""),
        "new_hypothesis": l10.get("next_round_hypothesis", ""),
        "round_id": _next_rid,
        "parent_round_id": _src_rid,
        "required_new_search_directions": l10.get("next_steps", []) or [],
        "evidence_kept": l10.get("evidence_kept", []) or [],
        "evidence_dropped": l10.get("evidence_dropped", []) or [],
        "explored_branches": [b.get("id") for b in branches],
        "unexplored_branches": [b for b in bl.get("branches", []) if b.get("status") == "ignored"],
        "data_modalities_used": ml.get("used", []),
        "data_modalities_available_unused": ml.get("available_unused", []),
        "paper_card_ids": _list_card_ids(project_dir, cand_id, "paper_cards"),
        "method_card_ids": _list_card_ids(project_dir, cand_id, "method_cards"),
        "hashes": {},
    }
    # v2 binds continuation context to an immutable event cursor.  It never
    # asks the shared ledger for whatever happens to be current in another
    # project after this memory has been emitted.
    if binding_path(project_dir).exists():
        try:
            ledger = _ledger_for(project_dir, knowledge_store)
            snapshot = ledger.snapshot_candidate(project_dir, cand_id, _src_rid)
        except LedgerError as exc:
            raise LedgerError(f"v2 loop-memory requires the bound knowledge store: {exc}") from exc
        proposal = l10.get("next_round_proposal") or {}
        memory.update({
            "schema_version": "2.0",
            "hypothesis_ledger": snapshot,
            "previous_hypothesis_ids": [item.get("hypothesis_id") for item in l10.get("hypothesis_decisions", []) if item.get("hypothesis_id")],
            "next_round_hypothesis_id": proposal.get("hypothesis_id", ""),
            "next_round_hypothesis": proposal.get("statement", memory["next_round_hypothesis"]),
            "loop_type": proposal.get("loop_type", ""),
        })
    return memory


def _write_exec_manifest(project_dir, cand_id, delta):
    d = Path(project_dir) / "04_Analysis_Outputs" / "_exec_manifest"
    d.mkdir(parents=True, exist_ok=True)
    man = {"candidate_id": cand_id, "scripts": [
        {"name": s.get("name"), "branch_id": s.get("branch_id"),
         "method_card_ids": s.get("method_card_ids", []), "grounded_by": s.get("grounded_by"),
         "input_hashes": s.get("input_hashes", []), "output_hashes": s.get("output_hashes", []),
         "output_files": s.get("output_files", [])}
        for s in delta.get("scripts_run", [])]}
    (d / f"{cand_id}_L7.json").write_text(json.dumps(man, indent=2, sort_keys=True), encoding="utf-8")


def _loop_memory_to_md(mem):
    out = [f"# Next-Loop Memory -- {mem['source_candidate_id']}", ""]
    for k in SEED_SCHEMA_KEYS:
        out.append(f"## {k}")
        v = mem.get(k)
        out.append(json.dumps(v, ensure_ascii=False, indent=2) if isinstance(v, (list, dict)) else str(v))
        out.append("")
    return "\n".join(out)


def cmd_branch_status(args):
    """Set a branch's exploration status in this candidate's branch ledger."""
    p = _branch_ledger_path(args.project_dir, args.cand_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    led = _read_branch_ledger(args.project_dir, args.cand_id)
    led.setdefault("branches", [])
    led["branches"] = [b for b in led["branches"] if b.get("id") != args.branch]
    led["branches"].append({
        "id": args.branch, "description": args.description or "",
        "status": args.status, "data_available": bool(args.data_path),
        "data_path": args.data_path or "", "why_deferred": args.why or ""})
    p.write_text(json.dumps(led, indent=2, sort_keys=True), encoding="utf-8")
    print(f"branch {args.branch} -> {args.status}")
    return 0


def cmd_modality_scan(args):
    """Record used vs available data modalities for this candidate."""
    p = _modality_ledger_path(args.project_dir, args.cand_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    used = list(dict.fromkeys(args.used or []))
    avail = list(dict.fromkeys(args.available or []))
    led = {"used": used, "available_unused": [m for m in avail if m not in used]}
    p.write_text(json.dumps(led, indent=2, sort_keys=True), encoding="utf-8")
    print(f"modality ledger: used={used} unused={led['available_unused']}")
    return 0


def cmd_emit_loop_memory(args):
    """L10c: emit next-loop semantic state linked to immutable round evidence."""
    project_dir = Path(args.project_dir)
    # aggregate-report normally freezes the round manifest first.  For direct
    # callers/legacy flows, create it here if absent; never rebuild an existing
    # manifest after later controller receipts have appeared.
    fm = _load_yaml_front(_candidate_file(project_dir, args.cand_id))
    manifest_path = round_manifest_path(
        project_dir, args.cand_id, str(fm.get("round_id") or "1"))
    try:
        if manifest_path.exists():
            manifest_hash = _sha256_file(manifest_path)
        else:
            manifest_path, manifest_hash = write_round_manifest(
                project_dir, args.cand_id)
        mem = _build_loop_memory(project_dir, args.cand_id,
                                 getattr(args, "knowledge_store", None))
    except (LedgerError, Exception) as exc:
        # Preserve the existing LedgerError-facing CLI behavior while making
        # deterministic manifest failures equally fail closed.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    mem["round_manifest_path"] = manifest_path.relative_to(project_dir).as_posix()
    mem["round_manifest_sha256"] = manifest_hash
    out_dir = project_dir / "08_Audit" / "loop_memory"
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"{args.cand_id}_next_loop_memory.json"
    json_text = json.dumps(mem, ensure_ascii=False, indent=2, sort_keys=True)
    if jp.exists() and jp.read_text(encoding="utf-8") != json_text:
        print(f"ERROR: loop-memory collision: {jp}", file=sys.stderr)
        return 2
    if not jp.exists():
        with jp.open("x", encoding="utf-8") as handle:
            handle.write(json_text)
    mp = out_dir / f"{args.cand_id}_next_loop_memory.md"
    markdown = _loop_memory_to_md(mem)
    if mp.exists() and mp.read_text(encoding="utf-8") != markdown:
        print(f"ERROR: loop-memory markdown collision: {mp}", file=sys.stderr)
        return 2
    if not mp.exists():
        with mp.open("x", encoding="utf-8") as handle:
            handle.write(markdown)
    print("loop-memory written:")
    print(f"  {jp}")
    print(f"  {mp}")
    return 0