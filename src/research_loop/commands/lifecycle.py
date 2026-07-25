"""Lifecycle CLI command family extracted from engine.py."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pitfall_ledger as pl

from research_loop import deep_research, l0_contract, l0_intake
from research_loop.commands.ledger import _ledger_for
from research_loop.common import (
    _append_decision, _check_dependencies, _dep_fix_hint, _empty_value_for_schema,
    _everos_scopes_for, _load_loop_memory, _mkdirs, _now, _require_status,
    _set_status, _sha256_file, _stamp,
)
from research_loop.delta import (
    DELTA_SCHEMAS, _delta_belongs_to_candidate, _delta_for_candidate,
)
from research_loop.hypothesis_ledger import LedgerError, binding_path
from research_loop.paths import (
    _candidate_file, _layer_template_path, _persona_template_path,
)
from research_loop.templates import (
    _candidate_template, _decision_log_template, _dependencies_md,
    _handoff_template, _index_template, _knowledge_base_md, _note_template,
    _preflight_template,
)
from research_loop.topology import AGENTS, DECISION_TRANSITIONS, NODE_MAP
from research_loop.yamlio import _load_yaml_front, _replace_field

# Preserve repository-relative lookup semantics from the former engine owner.
__file__ = str(Path(__file__).resolve().parents[1] / "engine.py")

VALID_STATUSES = [
    "NEW", "IDEA_PROPOSED", "IDEA_REJECTED", "IDEA_SELECTED",
    "METHOD_PROPOSED", "METHOD_REJECTED", "METHOD_APPROVED",
    "NEEDS_EXECUTION", "EXECUTED", "AUDITED", "UNDER_REVIEW",
    "KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED",
]

KNOWLEDGE_BASE_ACCESS = {
    "L1": "read-write", "L4": "read-write", "L8.5": "read-write",
    "L0": "read",
    "L9a": "read", "L9b": "read",
    "L10a": "read", "L10b": "read", "L10c": "read",
}

FINAL_STATUSES = {"KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED"}

PREFLIGHT_FILES = [
    "skill_use_plan.md", "input_manifest.md",
    "output_manifest.md", "forbidden_shortcuts.md",
]

REQUIRED_DEPENDENCIES = [
    {"kind": "python", "name": "yaml", "label": "PyYAML", "pip": "PyYAML",
     "needed_for": "manage_literature_db.py (growable literature DB; L1/L4/L8.5)"},
    {"kind": "port", "name": "zotero", "label": "Zotero", "addr": "127.0.0.1:23119",
     "attest_env": "RLR_ZOTERO",
     "needed_for": "reference manager / citation source for the literature DB"},
    {"kind": "env", "name": "obsidian", "label": "Obsidian vault", "env": "OBSIDIAN_VAULT",
     "check_path": True, "attest_env": "RLR_OBSIDIAN",
     "needed_for": "end-of-round human-readable sync (sync_to_obsidian.py)"},
]

def _pitfall_warnings_for_node(project_dir, node_id):
    """Return a list of relevant confirmed pitfall summaries for a DAG node.
    Injected into next-step output so the orchestrator sees prior pitfalls
    before assembling context for that node."""
    try:
        rules = pl.scan_pitfalls(project_dir, node=node_id)
    except Exception:
        return []
    warnings = []
    for r in rules:
        warnings.append({
            "id": r.get("id", ""),
            "category": r.get("category", ""),
            "severity": r.get("severity", "warn"),
            "error_class": r.get("error_class", "agent"),
            "prevention_rule": r.get("prevention_rule", ""),
        })
    return warnings

def cmd_next_step(args):
    """Output JSON scheduling packet for the next DAG node."""
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(json.dumps({"error": f"no candidate {args.cand_id}"}))
        return 1
    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "NEW")

    if status in FINAL_STATUSES:
        if status == "KEEP":
            node_info = NODE_MAP.get("L10c")
            if node_info:
                result = {
                    "node": "L10c",
                    "persona": node_info["persona"],
                    "is_parallel": False,
                    "is_execution": False,
                    "context_files": ["ALL"],
                    "action_hint": node_info["action_hint"],
        "must": ["Aggregate all deltas in DAG order", "Generate FINAL_REPORT.md and FINAL_REPORT_CN.md"],
        "must_not": ["Execute code", "Change status", "Skip any delta"],
        "stop_conditions": ["Any delta missing"],
                    "advance_command": "aggregate-report",
                    "template_path": _layer_template_path("L10c"),
                    "persona_template_path": _persona_template_path(node_info["persona"]),
                    "tools_policy": node_info.get("tools_policy"),
                    "everos_read_scopes": _everos_scopes_for(node_info, project_dir.name),
                    "knowledge_base": node_info.get("knowledge_base"),
                }
                _warnings = pl.scan_pitfalls(project_dir, node="L10c")
                if _warnings:
                    result["pitfall_warnings"] = _warnings
                print(json.dumps(result, indent=2))
                return 0
        print(json.dumps({"terminal": True, "status": status}))
        return 0

    status_to_nodes = {
        "NEW": ["L0"],
        "IDEA_PROPOSED": ["L1", "L2", "L3"],
        "IDEA_SELECTED": ["L4"],
        "METHOD_PROPOSED": ["L5", "L6"],
        "METHOD_APPROVED": ["L7"],
        "NEEDS_EXECUTION": ["L7"],
        "EXECUTED": ["L8"],
        "AUDITED": ["L8.5"],
        "UNDER_REVIEW": ["L9_parallel", "L10a", "L10b"],
    }

    node_candidates = status_to_nodes.get(status, [])
    node_id = None
    if node_candidates:
        for cand_node in node_candidates:
            if cand_node == "L9_parallel":
                if (_delta_belongs_to_candidate(
                        project_dir, "L9a_feynman", args.cand_id)
                        and _delta_belongs_to_candidate(
                            project_dir, "L9b_darwin", args.cand_id)):
                    continue
                node_id = "L9_parallel"
                break
            ni = NODE_MAP.get(cand_node)
            if ni:
                delta_key = f"{cand_node}_{ni['persona'].lower()}"
                if _delta_belongs_to_candidate(
                        project_dir, delta_key, args.cand_id):
                    continue
                node_id = cand_node
                break
        else:
            node_id = node_candidates[-1]

    if node_id is None:
        print(json.dumps({"error": f"no next step for status {status}"}))
        return 1

    if node_id == "L9_parallel":
        nodes = []
        for nid in ["L9a", "L9b"]:
            ni = NODE_MAP[nid]
            nodes.append({
                "node": nid,
                "persona": ni["persona"],
                "context_files": ni["context_inputs"],
                "action_hint": ni["action_hint"],
                "advance_command": ni.get("advance_command"),
                "template_path": _layer_template_path(nid),
                "persona_template_path": _persona_template_path(ni["persona"]),
                "tools_policy": ni.get("tools_policy"),
                "everos_read_scopes": _everos_scopes_for(ni, project_dir.name),
                "knowledge_base": ni.get("knowledge_base"),
            })
        result = {
            "is_parallel": True,
            "nodes": nodes,
        }
        result["pitfall_warnings"] = {
            "L9a": _pitfall_warnings_for_node(project_dir, "L9a"),
            "L9b": _pitfall_warnings_for_node(project_dir, "L9b"),
        }
        print(json.dumps(result, indent=2))
        return 0

    node_info = NODE_MAP[node_id]
    result = {
        "node": node_id,
        "persona": node_info["persona"],
        "is_parallel": node_info.get("is_parallel", False),
        "is_execution": node_info.get("is_execution", False),
        "context_files": node_info["context_inputs"],
        "action_hint": node_info["action_hint"],
        "advance_command": node_info.get("advance_command"),
        "advance_status": node_info.get("advance_status"),
        "advance_reason": node_info.get("advance_reason"),
        "template_path": _layer_template_path(node_id),
        "persona_template_path": _persona_template_path(node_info["persona"]),
        "tools_policy": node_info.get("tools_policy"),
        "everos_read_scopes": _everos_scopes_for(node_info, project_dir.name),
        "knowledge_base": node_info.get("knowledge_base"),
    }
    # L7 is reused under both METHOD_APPROVED and NEEDS_EXECUTION. Its DAG
    # advance_command (execution-gate) only applies at METHOD_APPROVED -- that
    # gate is what opens NEEDS_EXECUTION. Once the gate is open, Turing runs
    # and emits the L7 delta, after which the candidate must advance to
    # EXECUTED via `decision`. Without this override next-step would keep
    # returning L7/execution-gate and the walk would dead-end before L8.
    if status == "NEEDS_EXECUTION" and node_id == "L7":
        delta_done = _delta_belongs_to_candidate(
            project_dir, "L7_turing", args.cand_id)
        result["advance_command"] = "decision"
        result["advance_status"] = "EXECUTED"
        result["advance_reason"] = ("Turing execution complete, mark EXECUTED "
                                    "and route to Curie")
        result["action_hint"] = (
            "L7 delta present; advance to EXECUTED (route to Curie)"
            if delta_done else
            "Turing: execute approved scripts in the controlled workspace, "
            "emit the L7 delta, then advance to EXECUTED")
    result["pitfall_warnings"] = _pitfall_warnings_for_node(project_dir, node_id)
    print(json.dumps(result, indent=2))
    return 0

def cmd_new_project(args):
    name = args.name
    topic = args.topic or ""
    project_dir = Path(name)
    store_path = getattr(args, "knowledge_store", None) or os.environ.get(
        "RLR_HYPOTHESIS_STORE"
    )
    if not store_path:
        print("ERROR: new-project requires --knowledge-store or "
              "RLR_HYPOTHESIS_STORE", file=sys.stderr)
        return 2
    if project_dir.exists():
        print(f"ERROR: {project_dir} already exists; refusing to overwrite.",
              file=sys.stderr)
        return 2
    _mkdirs(project_dir)
    (project_dir / "00_Project_Index.md").write_text(
        _index_template(name, topic), encoding="utf-8")
    pl.init_ledger(project_dir)
    try:
        _ledger_for(project_dir, store_path, require_binding=False).bind_project(project_dir)
    except LedgerError as exc:
        print(f"ERROR: hypothesis ledger project binding failed: {exc}", file=sys.stderr)
        return 2
    print(f"Created V0.7 project: {project_dir.resolve()}")
    print("Next: run `preflight` (Linnaeus L0) before any candidate work.")
    return 0

def cmd_new_candidate(args):
    project_dir = Path(args.project_dir)
    idx = project_dir / "00_Project_Index.md"
    if not idx.exists():
        print(f"ERROR: not a project dir (no 00_Project_Index.md): {project_dir}",
              file=sys.stderr)
        return 2
    from_memory = getattr(args, "from_memory", None)
    loop_type = getattr(args, "loop_type", None) or ""
    explicit_rt = getattr(args, "round_type", None)
    # Round type is explicit (never inferred from file existence). If not given,
    # derive from --from-memory, but a conflicting explicit value is an error.
    if explicit_rt == "initial" and from_memory:
        print("ERROR: --round-type initial conflicts with --from-memory "
              "(a from-memory candidate is a continuation)", file=sys.stderr)
        return 2
    if explicit_rt == "continuation" and not from_memory:
        print("ERROR: --round-type continuation requires --from-memory "
              "(a continuation must link to a prior loop-memory seed)",
              file=sys.stderr)
        return 2
    round_type = explicit_rt or ("continuation" if from_memory else "initial")

    mem_fields = {}
    mem = {}
    continuation_ledger = None
    if from_memory:
        if not loop_type:
            print("ERROR: --from-memory requires --loop-type", file=sys.stderr)
            return 2
        try:
            mem = _load_loop_memory(from_memory)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        if binding_path(project_dir).exists():
            snapshot = mem.get("hypothesis_ledger")
            if not isinstance(snapshot, dict) or not mem.get("next_round_hypothesis_id"):
                print("ERROR: bound project continuation requires v2 loop-memory ledger snapshot and successor hypothesis ID", file=sys.stderr)
                return 2
            try:
                ledger = _ledger_for(project_dir, getattr(args, "knowledge_store", None))
            except LedgerError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            if snapshot.get("store_id") != ledger.store_id:
                print("ERROR: loop-memory ledger store_id does not match configured store", file=sys.stderr)
                return 2
            binding = ledger.require_activated_project(project_dir)
            if snapshot.get("project_id") != binding["project_id"]:
                print("ERROR: loop-memory project_id does not match activated project", file=sys.stderr)
                return 2
            if mem.get("loop_type") != loop_type:
                print("ERROR: --loop-type does not match the L10b continuation proposal", file=sys.stderr)
                return 2
            continuation_ledger = ledger
        mem_fields = {
            "from_memory": True, "loop_type": loop_type,
            "prior_candidate": mem["source_candidate_id"],
            "memory_file": str(from_memory),
            "memory_hash": _sha256_file(from_memory),
        }
        if mem.get("next_round_hypothesis_id"):
            mem_fields["hypothesis_id"] = mem["next_round_hypothesis_id"]

    if from_memory:
        continuation_key = (
            f"{_sha256_file(from_memory)}:{mem.get('next_round_hypothesis_id', '')}"
        )
        cand_id = "C" + hashlib.sha256(
            continuation_key.encode("utf-8")
        ).hexdigest()[:16].upper()
    else:
        cand_id = "C" + _stamp()

    # --- structured source_input (from --source-input-file, or flags, or the
    # legacy single --input description as an inline input) -------------------
    si_override = getattr(args, "source_input_file", None)
    if si_override:
        try:
            _txt = Path(si_override).read_text(encoding="utf-8")
            if str(si_override).lower().endswith(".json"):
                _sid = json.loads(_txt)
            else:
                import yaml as _yaml
                _sid = _yaml.safe_load(_txt)
        except Exception as e:
            print(f"ERROR: cannot read --source-input-file {si_override}: {e}",
                  file=sys.stderr)
            return 2
        if not isinstance(_sid, dict):
            print(f"ERROR: --source-input-file must contain a mapping",
                  file=sys.stderr)
            return 2
        source_input = l0_contract.build_source_input(
            input_type=_sid.get("input_type"),
            files=_sid.get("files"), location=_sid.get("location"),
            description=_sid.get("description", args.input),
            fmt=_sid.get("format", ""),
            verification_status=_sid.get("verification_status"),
            reason=_sid.get("reason"))
    elif getattr(args, "input_type", None) or getattr(args, "input_files", None):
        source_input = l0_contract.build_source_input(
            input_type=getattr(args, "input_type", None),
            files=[f for f in (getattr(args, "input_files", None) or [])],
            location=getattr(args, "input_location", None),
            description=args.input,
            fmt=getattr(args, "input_format", "") or "")
    else:
        # legacy single-flag caller: the free-text --input becomes an inline
        # source_input (no files -> no existence check -> back-compat).
        source_input = l0_contract.build_source_input(
            input_type="inline", description=args.input, fmt="unspecified")

    # --- build + persist the structured input contract artifact -------------
    if round_type == "continuation":
        prev_decision = (mem.get("previous_final_decision")
                         or mem.get("terminal_decision") or "")
        prev_conclusion = (mem.get("previous_conclusion")
                           or mem.get("final_reason") or "")
        new_hyp = (mem.get("new_hypothesis")
                   or mem.get("next_round_hypothesis") or args.claim)
        parent_rid = mem.get("parent_round_id")
        round_id = str(mem.get("round_id")
                       or (int(parent_rid) + 1 if str(parent_rid or "").isdigit()
                           else 2))
        contract = l0_contract.build_continuation_contract(
            cand_id, round_id, parent_rid, mem.get("source_candidate_id"),
            args.question, source_input,
            previous_round={
                "hypothesis": mem.get("previous_hypothesis", ""),
                "final_decision": prev_decision,
                "conclusion": prev_conclusion,
                "memory_hash": mem_fields.get("memory_hash", ""),
            },
            new_hypothesis=new_hyp)
    else:
        round_id = "1"
        parent_rid = None
        contract = l0_contract.build_initial_contract(
            cand_id, round_id, args.question, source_input,
            new_hypothesis=args.claim)

    ic_path, ic_hash = l0_contract.write_contract(project_dir, cand_id, contract)
    try:
        ic_rel = ic_path.relative_to(project_dir).as_posix()
    except ValueError:
        ic_rel = ic_path.as_posix()

    # Frontmatter carries ONLY pointers to the artifact (flat scalar keys).
    mem_fields.update({
        "input_contract_path": ic_rel,
        "input_contract_hash": ic_hash,
        "schema_version": l0_contract.L0_CONTRACT_SCHEMA_VERSION,
        "round_type": round_type,
        "round_id": round_id,
        "parent_round_id": (parent_rid if parent_rid is not None else ""),
        "previous_candidate_id": (mem.get("source_candidate_id", "")
                                  if round_type == "continuation" else ""),
    })

    body = _candidate_template(cand_id, args.title, args.input,
                                   args.question, args.claim,
                                   input_alias=getattr(args, "input_alias", "") or "",
                                   extra_front=mem_fields)
    cf = _candidate_file(project_dir, cand_id)
    if cf.exists() and from_memory:
        existing = _load_yaml_front(cf)
        if (existing.get("memory_hash") == mem_fields.get("memory_hash")
                and existing.get("hypothesis_id") == mem_fields.get("hypothesis_id")):
            if continuation_ledger is not None:
                continuation_ledger.create_continuation_occurrence(
                    project_dir=project_dir, candidate_id=cand_id,
                    round_id=round_id, hypothesis_id=mem_fields["hypothesis_id"],
                    memory_path=from_memory, memory_hash=mem_fields["memory_hash"],
                )
            print(cand_id)
            print(f"  -> {cf}")
            return 0
        print(f"ERROR: continuation candidate collision: {cf}", file=sys.stderr)
        return 2
    cf.write_text(body, encoding="utf-8")
    if continuation_ledger is not None:
        try:
            continuation_ledger.create_continuation_occurrence(
                project_dir=project_dir, candidate_id=cand_id, round_id=round_id,
                hypothesis_id=mem_fields["hypothesis_id"], memory_path=from_memory,
                memory_hash=mem_fields["memory_hash"],
            )
        except LedgerError as exc:
            print(f"ERROR: continuation occurrence failed: {exc}", file=sys.stderr)
            return 2
    _append_decision(project_dir, cand_id, "-", "NEW", "candidate created",
                     agent="Oppenheimer", kind="seed")
    print(cand_id)
    print(f"  -> {cf}")
    return 0

def _print_intake_failure(result):
    print("Cannot create L0 contract.", file=sys.stderr)
    if result["missing_fields"]:
        print("Missing required fields:", file=sys.stderr)
        for field in result["missing_fields"]:
            print(f"- {field}", file=sys.stderr)
    if result["errors"]:
        print("Validation errors:", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)

def cmd_normalize_l0_input(args):
    """Normalize a labelled natural-language request into a strict L0 artifact."""
    project_dir = Path(args.project)
    if not (project_dir / "00_Project_Index.md").exists():
        print(f"ERROR: not a project dir (no 00_Project_Index.md): {project_dir}",
              file=sys.stderr)
        return 2
    request_path = Path(args.input)
    try:
        request_text = request_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot read request file {request_path}: {exc}", file=sys.stderr)
        return 2

    memory, memory_hash = None, ""
    if args.from_memory:
        if not args.loop_type:
            print("ERROR: --from-memory requires --loop-type", file=sys.stderr)
            return 2
        try:
            memory = _load_loop_memory(args.from_memory)
            memory_hash = _sha256_file(args.from_memory)
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    cand_id = "C" + _stamp()
    if _candidate_file(project_dir, cand_id).exists():
        print(f"ERROR: candidate id collision: {cand_id}", file=sys.stderr)
        return 2
    result = l0_intake.normalize_request(
        request_path, request_text, cand_id, data=args.data, dataset=args.dataset,
        memory=memory, memory_hash=memory_hash)
    if result["missing_fields"] or result["errors"]:
        _print_intake_failure(result)
        return 2

    contract = result["contract"]
    round_type = contract["round_type"]
    mem_fields = {
        "schema_version": l0_contract.L0_CONTRACT_SCHEMA_VERSION,
        "round_type": round_type,
        "round_id": contract["round_id"],
        "parent_round_id": contract.get("parent_round_id") or "",
        "previous_candidate_id": contract.get("previous_candidate_id") or "",
    }
    if memory:
        mem_fields.update({
            "from_memory": True, "loop_type": args.loop_type,
            "prior_candidate": memory.get("source_candidate_id", ""),
            "memory_file": str(args.from_memory), "memory_hash": memory_hash,
        })
    raw_contract = l0_contract.serialize_contract(contract)
    mem_fields["input_contract_path"] = (
        f"01_Candidates/{cand_id}.l0_input.yaml")
    mem_fields["input_contract_hash"] = hashlib.sha256(raw_contract).hexdigest()
    errors = l0_contract.validate_l0_input_contract(
        contract, mem_fields, project_dir, cand_id,
        artifact_path=project_dir / mem_fields["input_contract_path"],
        raw_bytes=raw_contract)
    if errors:
        _print_intake_failure({"missing_fields": [], "errors": errors})
        return 2

    source = contract["source_input"]
    print(f"Round type: {round_type}")
    print(f"Scientific question: {contract['scientific_question']}")
    print(f"Source data: {source.get('location')} [{len(source.get('files', []))} files]")
    if round_type == "continuation":
        print(f"Previous decision: {contract['previous_round']['final_decision']}")
    print(f"Current hypothesis: {contract['current_round']['hypothesis']}")
    print("Contract valid: yes")
    if args.dry_run:
        print(l0_contract.serialize_contract(contract).decode("utf-8"), end="")
        return 0

    body = _candidate_template(
        cand_id, contract["scientific_question"], source["description"],
        contract["scientific_question"], contract["current_round"]["hypothesis"],
        extra_front=mem_fields)
    _candidate_file(project_dir, cand_id).write_text(body, encoding="utf-8")
    artifact_path, _ = l0_contract.write_contract(project_dir, cand_id, contract)
    _append_decision(project_dir, cand_id, "-", "NEW", "candidate created",
                     agent="Oppenheimer", kind="seed")
    print(f"Written to: 01_Candidates/{artifact_path.name}")
    if args.run_l0:
        runner = Path(__file__).resolve().parents[1] / "run_loop.py"
        return subprocess.run([sys.executable, str(runner), "run", str(project_dir),
                               cand_id, "--stop-after-node", "L0"]).returncode
    return 0

def cmd_preflight(args):
    project_dir = Path(args.project_dir)
    idx = project_dir / "00_Project_Index.md"
    if not idx.exists():
        print(f"ERROR: not a project dir (no 00_Project_Index.md): {project_dir}",
              file=sys.stderr)
        return 2
    name = _load_yaml_front(idx).get("project_name", project_dir.name)
    pf = project_dir / "00_Preflight"
    pf.mkdir(parents=True, exist_ok=True)
    created, skipped = [], []
    runtime_file = deep_research.runtime_config_path(project_dir)
    if not runtime_file.exists() or args.force:
        runtime_file.write_text(json.dumps(deep_research.default_runtime_config(), indent=2),
                                encoding="utf-8")
        created.append(runtime_file.name)
    else:
        skipped.append(runtime_file.name)
    for fname in PREFLIGHT_FILES:
        target = pf / fname
        if target.exists() and not args.force:
            skipped.append(fname)
            continue
        target.write_text(_preflight_template(name, fname), encoding="utf-8")
        created.append(fname)
    dep_target = pf / "dependencies.md"
    if not dep_target.exists() or args.force:
        dep_target.write_text(_dependencies_md(name), encoding="utf-8")
        created.append("dependencies.md")
    else:
        skipped.append("dependencies.md")
    kb_target = pf / "knowledge_base.md"
    if not kb_target.exists() or args.force:
        kb_target.write_text(_knowledge_base_md(name), encoding="utf-8")
        created.append("knowledge_base.md")
    else:
        skipped.append("knowledge_base.md")
    print(f"Preflight (Linnaeus L0) for {name}:")
    for f in created:
        print(f"  created  00_Preflight/{f}")
    for f in skipped:
        print(f"  skipped  00_Preflight/{f} (exists; use --force to overwrite)")

    # --- L0 DEPENDENCY GATE (hard stop; must never be skipped) ---
    ok, missing = _check_dependencies(project_dir)
    try:
        runtime_spec, _runtime_version = deep_research.load_runtime_spec(project_dir)
        runtime_ok, runtime_reason = deep_research.runtime_ready(runtime_spec)
    except deep_research.DeepResearchError as exc:
        runtime_ok, runtime_reason = False, str(exc)
    print("\nL0 dependency gate:")
    for d in ok:
        print(f"  OK       {d['kind']}:{d['name']}")
    for d in missing:
        print(f"  MISSING  {d['kind']}:{d['name']} ({d.get('label', d['name'])})"
              f"  -- {d['needed_for']}", file=sys.stderr)
    if runtime_ok:
        print("  OK       deep_research:Academic Research runtime")
    else:
        print(f"  MISSING  deep_research:Academic Research runtime -- {runtime_reason}",
              file=sys.stderr)
    if missing or not runtime_ok:
        print("\nPREFLIGHT GATE: STOP -- required dependencies missing.",
              file=sys.stderr)
        print("The loop must NOT proceed past L0. Satisfy each, then re-run "
              "`preflight` (or `check-deps`):", file=sys.stderr)
        for d in missing:
            print(f"  {d['name']}: {_dep_fix_hint(d)}", file=sys.stderr)
        return 3
    print("\nPREFLIGHT GATE: PASS -- all required dependencies present.")

    # --- L0 PITFALL GATE (after deps; must never be skipped) ---
    # A confirmed hard_stop pitfall scoped to L0 (or a promoted preflight gate)
    # blocks the boot: the loop must not re-enter a known-fatal trap until the
    # pitfall is resolved (fixed, or retired via pitfall-status).
    passed, blocking = pl.hard_stop_check(project_dir, node="L0")
    if not passed:
        print("\nL0 PITFALL GATE: STOP -- confirmed hard_stop pitfall(s) "
              "apply at L0:", file=sys.stderr)
        for r in blocking:
            print(f"  [{r['id']}] {r['category']}: {r['rule']}", file=sys.stderr)
            print(f"           root cause: {r['root_cause']}", file=sys.stderr)
        print("Resolve each, then retire it (`pitfall-status ... --status "
              "obsolete`) or fix the cause, before re-running preflight.",
              file=sys.stderr)
        return 3
    print("L0 PITFALL GATE: PASS -- no blocking confirmed pitfalls.")
    return 0

def cmd_check_deps(args):
    """Standalone L0 dependency check (same gate as preflight); non-zero = STOP."""
    project_dir = Path(args.project_dir) if getattr(args, "project_dir", None) else None
    ok, missing = _check_dependencies(project_dir)
    for d in ok:
        print(f"OK       {d['kind']}:{d['name']}")
    for d in missing:
        print(f"MISSING  {d['kind']}:{d['name']} ({d.get('label', d['name'])})"
              f"  -- {d['needed_for']}\n         satisfy: {_dep_fix_hint(d)}",
              file=sys.stderr)
    runtime_ok, runtime_reason = True, ""
    if project_dir is not None:
        try:
            runtime_spec, _runtime_version = deep_research.load_runtime_spec(project_dir)
            runtime_ok, runtime_reason = deep_research.runtime_ready(runtime_spec)
        except deep_research.DeepResearchError as exc:
            runtime_ok, runtime_reason = False, str(exc)
        if runtime_ok:
            print("OK       deep_research:Academic Research runtime")
        else:
            print(f"MISSING  deep_research:Academic Research runtime -- {runtime_reason}",
                  file=sys.stderr)
    if missing or not runtime_ok:
        print("DEPENDENCY GATE: STOP -- satisfy the missing dependencies above; "
              "the loop must not proceed.", file=sys.stderr)
        return 3
    print("DEPENDENCY GATE: PASS")

    # L0 pitfall gate (same hard_stop gate as preflight). Only when a project
    # dir is known -- pitfalls are per-project.
    if project_dir is not None:
        passed, blocking = pl.hard_stop_check(project_dir, node="L0")
        if not passed:
            print("PITFALL GATE: STOP -- confirmed hard_stop pitfall(s) apply "
                  "at L0:", file=sys.stderr)
            for r in blocking:
                print(f"  [{r['id']}] {r['category']}: {r['rule']}",
                      file=sys.stderr)
            return 3
        print("PITFALL GATE: PASS")
    return 0

def cmd_note(args):
    project_dir = Path(args.project_dir)
    if args.agent not in AGENTS:
        print(f"ERROR: unknown persona '{args.agent}'. Valid: {AGENTS}",
              file=sys.stderr)
        return 2
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        text = args.text or ""
    if not text.strip():
        print("ERROR: --text or --file required and non-empty", file=sys.stderr)
        return 2
    idx = _load_yaml_front(project_dir / "00_Project_Index.md")
    project_name = idx.get("project_name", project_dir.name)
    nid = args.agent + _stamp()
    body = _note_template(project_name, args.cand_id, args.agent, text)
    nf = (Path(project_dir) / "02_Agent_Notes" / args.agent /
          f"{nid}_{args.cand_id}.md")
    nf.write_text(body, encoding="utf-8")
    print(nid)
    print(f"  -> {nf}")
    return 0

def cmd_demo(args):
    pd = (Path(__file__).resolve().parents[3] / "demos" / "other_examples"
          / "DemoProject_v03")
    if pd.exists():
        print(f"ERROR: {pd} already exists; remove it first.", file=sys.stderr)
        return 2
    _mkdirs(pd)
    name = "DemoProject_v03"
    (pd / "00_Project_Index.md").write_text(
        _index_template(name, "RLR V0.7 DAG demo"), encoding="utf-8")

    pf = pd / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        (pf / fname).write_text(_preflight_template(name, fname), encoding="utf-8")

    c1 = "C" + _stamp()
    (pd / "01_Candidates" / f"{c1}.md").write_text(
        _candidate_template(
            c1,
            "High-rate co-expression module tracks Sk/Sm vs Rn",
            "length_scaled_counts.csv (primary); sample_metadata_checked.csv (primary)",
            "Is there a co-expression module whose eigengene tracks the high-heart-rate species contrast?",
            "A WGCNA module eigengene correlates with the high-heart-rate species contrast (Sk/Sm vs Rn) independent of chamber."),
        encoding="utf-8")
    _append_decision(pd, c1, "-", "NEW", "candidate created",
                     agent="Oppenheimer", kind="seed")

    delta_nodes = [
        ("L0", "Linnaeus", "L0_linnaeus"),
        ("L1", "Einstein", "L1_einstein"),
        ("L2", "Feynman", "L2_feynman"),
        ("L3", "Oppenheimer", "L3_oppenheimer"),
        ("L4", "Fisher", "L4_fisher"),
        ("L5", "Tukey", "L5_tukey"),
        ("L6", "Oppenheimer", "L6_oppenheimer"),
        ("L7", "Turing", "L7_turing"),
        ("L8", "Curie", "L8_curie"),
        ("L9a", "Feynman", "L9a_feynman"),
        ("L9b", "Darwin", "L9b_darwin"),
        ("L10a", "Jobs", "L10a_jobs"),
        ("L10b", "Oppenheimer", "L10b_oppenheimer"),
    ]
    for node, persona, delta_key in delta_nodes:
        schema = DELTA_SCHEMAS.get(delta_key, {})
        empty_delta = {}
        for k, v in schema.items():
            empty_delta[k] = _empty_value_for_schema(v)
        delta_path = pd / "02_Agent_Notes" / persona / f"{delta_key}_delta.json"
        delta_path.write_text(
            json.dumps(empty_delta, indent=2, ensure_ascii=False),
            encoding="utf-8")

    print(f"\nDemo v0.4 project created at: {pd.resolve()}")
    print(f"  candidate: {c1}")
    print(f"  delta files: {len(delta_nodes)} empty schemas in 02_Agent_Notes/")
    print("\nDAG walk instructions:")
    print("  L0  Linnaeus   -> next-step, assemble-context --node L0")
    print("  L1  Einstein   -> next-step, assemble-context --node L1")
    print("  L2  Feynman    -> next-step, assemble-context --node L2")
    print("  L3  Oppenheimer-> triage-idea --decision select --reason ...")
    print("  L4  Fisher     -> next-step, assemble-context --node L4")
    print("  L5  Tukey      -> next-step, assemble-context --node L5")
    print("  L6  Oppenheimer-> triage-method --decision approve --reason ...")
    print("  L7  Turing     -> execution-gate, then assemble-context --node L7")
    print("  L8  Curie      -> next-step, assemble-context --node L8")
    print("  L9a Feynman    -> next-step (parallel), assemble-context --node L9a")
    print("  L9b Darwin     -> next-step (parallel), assemble-context --node L9b")
    print("  L10a Jobs      -> next-step, assemble-context --node L10a")
    print("  L10b Oppenheimer-> decision --status KEEP --reason ...")
    print("  L10c Linnaeus  -> aggregate-report")
    print(f"\n  python research_loop_v04.py list {pd}")
    print(f"  python research_loop_v04.py show {pd} {c1}")
    print(f"  python research_loop_v04.py aggregate-report {pd} {c1}")
    return 0

def cmd_decision(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    if args.status not in VALID_STATUSES:
        print(f"ERROR: invalid status '{args.status}'. Valid: {VALID_STATUSES}",
              file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    frm = fm.get("current_status", "NEW")
    # Ordering guard: reject illegal jumps (e.g. KEEP from NEW) unless --force.
    # Same-status logging and -> ARCHIVED are always allowed.
    legal = (args.status == frm
             or args.status == "ARCHIVED"
             or args.status in DECISION_TRANSITIONS.get(frm, set()))
    if not legal and not args.force:
        allowed = sorted(DECISION_TRANSITIONS.get(frm, set())) or ["(none)"]
        print(f"ERROR: illegal transition {frm} -> {args.status}. "
              f"Allowed from {frm}: {', '.join(allowed)} (plus same-status / "
              f"ARCHIVED). Use --force to override.", file=sys.stderr)
        return 1
    if not legal and args.force:
        print(f"WARNING: forced illegal transition {frm} -> {args.status}",
              file=sys.stderr)
    seq = _append_decision(project_dir, args.cand_id, frm, args.status,
                           args.reason, args.route or "", agent="Oppenheimer",
                           kind="decision")
    _set_status(project_dir, args.cand_id, args.status, args.route or "Oppenheimer")
    if args.status in FINAL_STATUSES:
        _replace_field(cf, "final_decision", f"{args.status}: {args.reason}")
        (project_dir / "05_Decision_Log" /
         f"final_decision_{args.cand_id}.md").write_text(
            _decision_log_template(seq, args.cand_id, frm, args.status,
                                   args.reason, args.route or "",
                                   agent="Oppenheimer", kind="final_decision"),
            encoding="utf-8")
    if args.status in ("DROP", "ARCHIVED"):
        archive = project_dir / "99_Archive"
        archive.mkdir(exist_ok=True)
        target = archive / cf.name
        if not target.exists():
            cf.rename(target)
            print(f"  archived -> {target}")
        else:
            print(f"  WARN: archive target exists, left in place: {target}",
                  file=sys.stderr)
    print(f"D{seq:04d}: {frm} -> {args.status}")
    return 0

def cmd_route(args):
    project_dir = Path(args.project_dir)
    if args.to not in AGENTS:
        print(f"ERROR: unknown persona '{args.to}'. Valid: {AGENTS}", file=sys.stderr)
        return 2
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    frm = fm.get("current_owner", "Oppenheimer")
    hid = "H" + _stamp()
    body = _handoff_template(
        hid, args.cand_id, frm, args.to, args.reason,
        args.action or f"Review candidate {args.cand_id}.",
        args.input_files or "", args.constraints or "",
        args.expected or "", args.stop or "")
    hf = Path(project_dir) / "03_Handoffs" / f"{hid}_{args.cand_id}.md"
    hf.write_text(body, encoding="utf-8")
    _replace_field(cf, "latest_handoff", hid)
    _replace_field(cf, "current_owner", args.to)
    _replace_field(cf, "updated_at", _now())
    print(hid)
    print(f"  -> {hf}")
    return 0

def cmd_triage_idea(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    if not _require_status(fm, args.cand_id, "IDEA_PROPOSED"):
        return 2
    delta = _delta_for_candidate(project_dir, "L3_oppenheimer", args.cand_id)
    if delta and str(delta).endswith(".v2.json"):
        try:
            data = json.loads(delta.read_text(encoding="utf-8"))
            decisions = data["triage"]
            selected = [item for item in decisions if item["disposition"] == "SELECTED"]
            reason = "; ".join(item["reason"] for item in decisions)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"ERROR: invalid committed L3 v2 delta: {exc}", file=sys.stderr)
            return 1
        if getattr(args, "decision", None) or getattr(args, "reason", None):
            print("ERROR: v2 triage-idea derives decision and reason from committed L3 delta", file=sys.stderr)
            return 2
        decision = "select" if selected else "reject"
    else:
        decision, reason = args.decision, args.reason
        if not decision or not reason:
            print("ERROR: legacy triage-idea requires --decision and --reason", file=sys.stderr)
            return 2
    frm = fm.get("current_status")
    if decision == "select":
        to, owner = "IDEA_SELECTED", "Fisher"
    else:
        to, owner = "DROP", "Oppenheimer"
    seq = _append_decision(project_dir, args.cand_id, frm, to, reason,
                           route_to=owner, agent="Oppenheimer",
                           kind="candidate_triage")
    (project_dir / "05_Decision_Log" /
     f"candidate_triage_decision_{args.cand_id}.md").write_text(
        _decision_log_template(seq, args.cand_id, frm, to, reason, owner,
                               agent="Oppenheimer", kind="candidate_triage"),
        encoding="utf-8")
    _set_status(project_dir, args.cand_id, to, owner)
    if to == "DROP":
        _replace_field(cf, "final_decision", f"DROP: {reason}")
        archive = project_dir / "99_Archive"
        archive.mkdir(exist_ok=True)
        target = archive / cf.name
        if not target.exists():
            cf.rename(target)
            print(f"  archived -> {target}")
        else:
            print(f"  WARN: archive target exists, left in place: {target}", file=sys.stderr)
    print(f"candidate_triage: {frm} -> {to} (route: {owner})")
    return 0

def cmd_triage_method(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    if not _require_status(fm, args.cand_id, "METHOD_PROPOSED"):
        return 2
    delta = _delta_for_candidate(project_dir, "L6_oppenheimer", args.cand_id)
    if delta and str(delta).endswith(".v2.json"):
        try:
            data = json.loads(delta.read_text(encoding="utf-8"))
            decision = "approve" if data["method_decision"] == "APPROVE" else "reject"
            reason = data["reason"]
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"ERROR: invalid committed L6 v2 delta: {exc}", file=sys.stderr)
            return 1
        if getattr(args, "decision", None) or getattr(args, "reason", None):
            print("ERROR: v2 triage-method derives decision and reason from committed L6 delta", file=sys.stderr)
            return 2
    else:
        decision, reason = args.decision, args.reason
        if not decision or not reason:
            print("ERROR: legacy triage-method requires --decision and --reason", file=sys.stderr)
            return 2
    frm = fm.get("current_status")
    if decision == "approve":
        to, owner = "METHOD_APPROVED", "Oppenheimer"
    else:
        to, owner = "DROP", "Oppenheimer"
    seq = _append_decision(project_dir, args.cand_id, frm, to, reason,
                           route_to=owner, agent="Oppenheimer",
                           kind="analysis_plan")
    (project_dir / "05_Decision_Log" /
     f"analysis_plan_decision_{args.cand_id}.md").write_text(
        _decision_log_template(seq, args.cand_id, frm, to, reason, owner,
                               agent="Oppenheimer", kind="analysis_plan"),
        encoding="utf-8")
    _set_status(project_dir, args.cand_id, to, owner)
    if to == "DROP":
        _replace_field(cf, "final_decision", f"DROP: {reason}")
        archive = project_dir / "99_Archive"
        archive.mkdir(exist_ok=True)
        target = archive / cf.name
        if not target.exists():
            cf.rename(target)
            print(f"  archived -> {target}")
        else:
            print(f"  WARN: archive target exists, left in place: {target}", file=sys.stderr)
    print(f"analysis_plan: {frm} -> {to} (route: {owner})")
    if to == "METHOD_APPROVED":
        print("  approved plan recorded; run `execution-gate` before Turing.")
    return 0
