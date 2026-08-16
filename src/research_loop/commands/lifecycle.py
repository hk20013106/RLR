"""Lifecycle CLI command family extracted from engine.py."""

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pitfall_ledger as pl

from research_loop import deep_research, l0_contract, l0_data, l0_intake, l0_state
from research_loop.commands.ledger import _ledger_for
from research_loop.common import (
    REQUIRED_DEPENDENCIES,
    _append_decision, _check_dependencies, _dep_fix_hint, _empty_value_for_schema,
    _everos_scopes_for, _load_loop_memory, _mkdirs, _now, _require_status,
    _set_status, _sha256_file, _stamp,
)
from research_loop.delta import (
    DELTA_SCHEMAS, artifact_for_node, artifact_key_for,
    _delta_belongs_to_candidate, _delta_for_candidate,
)
from research_loop.hypothesis_ledger import LedgerError, binding_path
from research_loop.compatibility import (
    DEFAULT_NATIVE_PROFILE, PROFILE_V20, get_profile,
)
from research_loop.paths import (
    _candidate_file, _layer_template_path, _persona_template_path,
)
from research_loop.templates import (
    _candidate_template, _decision_log_template, _dependencies_md,
    _handoff_template, _index_template, _knowledge_base_md, _note_template,
    _preflight_template,
)
from research_loop.topology import AGENTS, DECISION_TRANSITIONS, NODE_MAP, topology_for_profile
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


def _candidate_l8_artifact(project_dir, knowledge_store=None):
    """Resolve candidate-template L8 labels from the immutable project profile."""
    project = Path(project_dir)
    if binding_path(project).exists():
        try:
            binding = json.loads(
                binding_path(project).read_text(encoding="utf-8")
            )
            profile_id = str(binding.get("profile_id") or PROFILE_V20)
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(
                f"cannot read project profile binding: {binding_path(project)}"
            ) from exc
    else:
        profile_id = DEFAULT_NATIVE_PROFILE
    try:
        return artifact_for_node(get_profile(profile_id), "L8")
    except ValueError as exc:
        raise LedgerError(f"invalid project profile binding: {profile_id}") from exc

PREFLIGHT_FILES = [
    "skill_use_plan.md", "input_manifest.md",
    "output_manifest.md", "forbidden_shortcuts.md",
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
    # Unbound directories are legacy read-only inputs. Bound projects always
    # select the topology from their immutable ledger profile.
    profile_id = PROFILE_V20
    if binding_path(project_dir).exists():
        try:
            profile_id = _ledger_for(project_dir, getattr(args, "knowledge_store", None)).project_profile(project_dir)
        except LedgerError as exc:
            print(json.dumps({"error": str(exc)}))
            return 1
    _, node_map, _ = topology_for_profile(profile_id)
    profile = get_profile(profile_id)
    profile_metadata = {
        "profile_id": profile.profile_id,
        "schema_version": profile.delta_schema_version,
        "topology_version": profile.topology_version,
        "persona_catalog_version": profile.persona_catalog_version,
    }

    if status in FINAL_STATUSES:
        # KEEP and REVISE both represent completed L10b decisions whose round
        # still needs the shared L10c finalization boundary. DROP/DOWNGRADE and
        # ARCHIVED remain terminal here and do not open a continuation round.
        if status in {"KEEP", "REVISE"}:
            node_info = node_map.get("L10c")
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
                result.update(profile_metadata)
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
        "UNDER_REVIEW": (["L9_parallel", "L10a", "L10b"]
                         if profile_id == PROFILE_V20 else ["L9a", "L9b", "L10a", "L10b"]),
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
            ni = node_map.get(cand_node)
            if ni:
                delta_key = artifact_key_for(cand_node, ni["persona"], profile_id=profile_id)
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
            ni = node_map[nid]
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
        result.update(profile_metadata)
        result["pitfall_warnings"] = {
            "L9a": _pitfall_warnings_for_node(project_dir, "L9a"),
            "L9b": _pitfall_warnings_for_node(project_dir, "L9b"),
        }
        print(json.dumps(result, indent=2))
        return 0

    node_info = node_map[node_id]
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
    result.update(profile_metadata)
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
    profile_id = getattr(args, "profile", DEFAULT_NATIVE_PROFILE)
    if profile_id == PROFILE_V20:
        print("ERROR: v2.0-legacy is read-only and cannot be used for new projects.",
              file=sys.stderr)
        return 2
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
        _ledger_for(project_dir, store_path, require_binding=False).bind_project(
            project_dir, profile_id=profile_id)
    except LedgerError as exc:
        print(f"ERROR: hypothesis ledger project binding failed: {exc}", file=sys.stderr)
        return 2
    print(f"Created v0.9.2 native project: {project_dir.resolve()}")
    print("Next: run `preflight` (Linnaeus L0) before any candidate work.")
    return 0


def _load_continuation_runtime(project_dir, from_memory, loop_type,
                               knowledge_store=None):
    """Load verified continuation identity without touching project artifacts."""
    if not loop_type:
        raise ValueError("--from-memory requires --loop-type")
    mem = _load_loop_memory(from_memory)
    continuation_ledger = None
    if binding_path(project_dir).exists():
        snapshot = mem.get("hypothesis_ledger")
        if not isinstance(snapshot, dict) or not mem.get("next_round_hypothesis_id"):
            raise ValueError(
                "bound project continuation requires v2 loop-memory ledger snapshot "
                "and successor hypothesis ID"
            )
        ledger = _ledger_for(project_dir, knowledge_store)
        if snapshot.get("store_id") != ledger.store_id:
            raise ValueError(
                "loop-memory ledger store_id does not match configured store"
            )
        binding = ledger.require_activated_project(project_dir)
        if snapshot.get("project_id") != binding["project_id"]:
            raise ValueError(
                "loop-memory project_id does not match activated project"
            )
        if mem.get("loop_type") != loop_type:
            raise ValueError(
                "--loop-type does not match the L10b continuation proposal"
            )
        continuation_ledger = ledger

    mem_fields = {
        "from_memory": True,
        "loop_type": loop_type,
        "prior_candidate": mem["source_candidate_id"],
        "memory_file": str(from_memory),
        "memory_hash": _sha256_file(from_memory),
    }
    if mem.get("next_round_hypothesis_id"):
        mem_fields["hypothesis_id"] = mem["next_round_hypothesis_id"]
    continuation_key = (
        f"{mem_fields['memory_hash']}:{mem.get('next_round_hypothesis_id', '')}"
    )
    cand_id = "C" + hashlib.sha256(
        continuation_key.encode("utf-8")
    ).hexdigest()[:16].upper()
    return mem, mem_fields, continuation_ledger, cand_id


def _continuation_contract(cand_id, mem, mem_fields, question, claim,
                           source_input, inherited_inputs):
    prev_decision = (mem.get("previous_final_decision")
                     or mem.get("terminal_decision") or "")
    prev_conclusion = (mem.get("previous_conclusion")
                       or mem.get("final_reason") or "")
    new_hyp = (mem.get("new_hypothesis")
               or mem.get("next_round_hypothesis") or claim)
    parent_rid = mem.get("parent_round_id")
    round_id = str(mem.get("round_id")
                   or (int(parent_rid) + 1 if str(parent_rid or "").isdigit()
                       else 2))
    contract = l0_contract.build_continuation_contract(
        cand_id, round_id, parent_rid, mem.get("source_candidate_id"),
        question, source_input,
        previous_round={
            "hypothesis": mem.get("previous_hypothesis", ""),
            "final_decision": prev_decision,
            "conclusion": prev_conclusion,
            "memory_hash": mem_fields.get("memory_hash", ""),
        },
        new_hypothesis=new_hyp,
    )
    return l0_contract.promote_to_current_schema(
        contract, inherited_inputs=inherited_inputs
    ), round_id, parent_rid


def _source_input_from_args(args):
    si_override = getattr(args, "source_input_file", None)
    if si_override:
        try:
            text = Path(si_override).read_text(encoding="utf-8")
            if str(si_override).lower().endswith(".json"):
                sid = json.loads(text)
            else:
                import yaml as _yaml
                sid = _yaml.safe_load(text)
        except Exception as exc:
            raise ValueError(
                f"cannot read --source-input-file {si_override}: {exc}"
            ) from exc
        if not isinstance(sid, dict):
            raise ValueError("--source-input-file must contain a mapping")
        return l0_contract.build_source_input(
            input_type=sid.get("input_type"), files=sid.get("files"),
            location=sid.get("location"),
            description=sid.get("description", args.input),
            fmt=sid.get("format", ""),
            verification_status=sid.get("verification_status"),
            reason=sid.get("reason"),
        ), True
    if getattr(args, "input_type", None) or getattr(args, "input_files", None):
        return l0_contract.build_source_input(
            input_type=getattr(args, "input_type", None),
            files=[f for f in (getattr(args, "input_files", None) or [])],
            location=getattr(args, "input_location", None),
            description=args.input,
            fmt=getattr(args, "input_format", "") or "",
        ), False
    return l0_contract.build_source_input(
        input_type="inline", description=args.input, fmt="unspecified"
    ), False


def _contract_path(project_dir, cand_id):
    return _candidate_file(Path(project_dir), cand_id).with_suffix(
        ".l0_input.yaml"
    )


def _atomic_replace(path: Path, data: bytes):
    """Replace one artifact through a same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(data)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _replace_frontmatter_scalar(text, key, value):
    pattern = re.compile(rf"(?m)^{re.escape(key)}:.*$")
    replacement = f"{key}: {value}"
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise ValueError(f"candidate frontmatter is missing {key}")
    return updated


def _recovery_progress_reasons(project_dir, cand_id, existing_binding=None):
    project = Path(project_dir)
    reasons = []
    for key in sorted(DELTA_SCHEMAS):
        path = _delta_for_candidate(project, key, cand_id)
        if path is not None and path.is_file():
            reasons.append(f"delta:{key}")
    decision_files = list((project / "05_Decision_Log").glob(f"D*_{cand_id}.md"))
    if len(decision_files) > 1:
        reasons.append("candidate has decisions beyond the seed")
    if (project / "04_Analysis_Outputs" / "_exec_manifest" /
            f"{cand_id}_L7.json").is_file():
        reasons.append("L7 execution manifest exists")
    if any(project.glob(f"_turing_workspace_{cand_id}_*")):
        reasons.append("Turing workspace exists")
    if (project / "08_Run_Receipts" / cand_id).is_dir():
        reasons.append("runtime receipts exist")
    if any((project / name).is_file() for name in (
        f"FINAL_REPORT_{cand_id}.md", f"FINAL_REPORT_CN_{cand_id}.md"
    )):
        reasons.append("candidate report exists")
    if existing_binding is not None and existing_binding.get("authorized_inputs"):
        reasons.append("CurrentRoundDataBinding already authorizes local inputs")
    return reasons


def _is_defective_continuation(contract):
    if not isinstance(contract, dict):
        return False
    source = contract.get("source_input")
    return (
        str(contract.get("schema_version") or "") == "1.0"
        and contract.get("round_type") == "continuation"
        and not contract.get("inherited_inputs")
        and isinstance(source, dict)
        and source.get("input_type") == "inline"
        and not source.get("files")
        and not source.get("location")
    )


def cmd_new_candidate(args):
    """Create a candidate without overwriting deterministic retries."""
    project_dir = Path(args.project_dir)
    idx = project_dir / "00_Project_Index.md"
    if not idx.exists():
        print(f"ERROR: not a project dir (no 00_Project_Index.md): {project_dir}",
              file=sys.stderr)
        return 2

    from_memory = getattr(args, "from_memory", None)
    loop_type = getattr(args, "loop_type", None) or ""
    explicit_rt = getattr(args, "round_type", None)
    if explicit_rt == "initial" and from_memory:
        print("ERROR: --round-type initial conflicts with --from-memory "
              "(a from-memory candidate is a continuation)", file=sys.stderr)
        return 2
    if explicit_rt == "continuation" and not from_memory:
        print("ERROR: --round-type continuation requires --from-memory "
              "(a continuation must link to a prior loop-memory seed)",
              file=sys.stderr)
        return 2
    if getattr(args, "inherit_previous_source", False) and not from_memory:
        print("ERROR: --inherit-previous-source requires --from-memory",
              file=sys.stderr)
        return 2
    round_type = explicit_rt or ("continuation" if from_memory else "initial")

    mem_fields = {}
    mem = {}
    continuation_ledger = None
    if from_memory:
        try:
            mem, mem_fields, continuation_ledger, cand_id = (
                _load_continuation_runtime(
                    project_dir, from_memory, loop_type,
                    getattr(args, "knowledge_store", None),
                )
            )
        except (FileNotFoundError, ValueError, LedgerError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    else:
        cand_id = "C" + _stamp()

    try:
        source_input, _source_override = _source_input_from_args(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if round_type == "continuation":
        inherited_inputs = []
        if getattr(args, "inherit_previous_source", False):
            try:
                inherited_inputs = l0_state.project_verified_source_selectors(
                    project_dir, mem,
                )
            except l0_state.L0StateError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
        contract, round_id, parent_rid = _continuation_contract(
            cand_id, mem, mem_fields, args.question, args.claim,
            source_input, inherited_inputs,
        )
    else:
        round_id = "1"
        parent_rid = None
        contract = l0_contract.build_initial_contract(
            cand_id, round_id, args.question, source_input,
            new_hypothesis=args.claim,
        )

    raw_contract = l0_contract.serialize_contract(contract)
    ic_hash = hashlib.sha256(raw_contract).hexdigest()
    ic_path = _contract_path(project_dir, cand_id)
    try:
        ic_rel = ic_path.relative_to(project_dir).as_posix()
    except ValueError:
        ic_rel = ic_path.as_posix()
    mem_fields.update({
        "input_contract_path": ic_rel,
        "input_contract_hash": ic_hash,
        "schema_version": contract["schema_version"],
        "round_type": round_type,
        "round_id": round_id,
        "parent_round_id": (parent_rid if parent_rid is not None else ""),
        "previous_candidate_id": (
            mem.get("source_candidate_id", "")
            if round_type == "continuation" else ""
        ),
    })
    try:
        l8_artifact = _candidate_l8_artifact(
            project_dir, getattr(args, "knowledge_store", None)
        )
    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    body = _candidate_template(
        cand_id, args.title, args.input, args.question, args.claim,
        input_alias=getattr(args, "input_alias", "") or "",
        extra_front=mem_fields,
        l8_persona=l8_artifact.display_persona,
        l8_storage_key=l8_artifact.storage_key,
    )
    cf = _candidate_file(project_dir, cand_id)

    # Deterministic continuation IDs are immutable creation keys.  Check both
    # identity and the complete canonical contract before any sidecar write.
    if cf.exists():
        if not from_memory:
            print(f"ERROR: candidate already exists; refusing overwrite: {cf}",
                  file=sys.stderr)
            return 2
        existing = _load_yaml_front(cf)
        existing_contract, _existing_path, existing_raw = (
            l0_contract.load_contract(project_dir, cand_id)
        )
        existing_hash = (
            hashlib.sha256(existing_raw).hexdigest()
            if existing_raw is not None else ""
        )
        identity_matches = (
            existing.get("memory_hash") == mem_fields.get("memory_hash")
            and existing.get("hypothesis_id") == mem_fields.get("hypothesis_id")
        )
        if not identity_matches:
            print(f"ERROR: continuation candidate collision: {cf}",
                  file=sys.stderr)
            return 2
        if (existing.get("input_contract_hash") != existing_hash
                or existing.get("input_contract_path") != ic_rel):
            print(
                "ERROR: existing continuation candidate and L0 contract are "
                "out of sync; refusing overwrite",
                file=sys.stderr,
            )
            return 2
        if existing_raw == raw_contract:
            if continuation_ledger is not None:
                continuation_ledger.create_continuation_occurrence(
                    project_dir=project_dir, candidate_id=cand_id,
                    round_id=round_id, hypothesis_id=mem_fields["hypothesis_id"],
                    memory_path=from_memory, memory_hash=mem_fields["memory_hash"],
                )
            print(cand_id)
            print(f"  -> {cf}")
            return 0
        print(
            "ERROR: existing continuation candidate has a different contract; "
            "refusing overwrite. Use the explicit recover-continuation command "
            "only after a pristine-seed audit.",
            file=sys.stderr,
        )
        return 2
    if ic_path.exists():
        print(
            f"ERROR: orphaned L0 contract exists without candidate; refusing "
            f"overwrite: {ic_path}",
            file=sys.stderr,
        )
        return 2

    l0_contract.write_contract(project_dir, cand_id, contract)
    cf.write_text(body, encoding="utf-8")
    if continuation_ledger is not None:
        try:
            continuation_ledger.create_continuation_occurrence(
                project_dir=project_dir, candidate_id=cand_id,
                round_id=round_id, hypothesis_id=mem_fields["hypothesis_id"],
                memory_path=from_memory, memory_hash=mem_fields["memory_hash"],
            )
        except LedgerError as exc:
            print(f"ERROR: continuation occurrence failed: {exc}", file=sys.stderr)
            return 2
    _append_decision(project_dir, cand_id, "-", "NEW", "candidate created",
                     agent="Oppenheimer", kind="seed")
    print(cand_id)
    print(f"  -> {cf}")
    return 0


def cmd_recover_continuation(args):
    """Explicitly upgrade one pristine defective continuation seed."""
    project_dir = Path(args.project_dir)
    cand_id = str(args.cand_id)
    cf = _candidate_file(project_dir, cand_id)
    if not cf.is_file():
        print(f"ERROR: no candidate {cand_id}", file=sys.stderr)
        return 2
    existing_fm = _load_yaml_front(cf)
    from_memory = getattr(args, "from_memory", None) or existing_fm.get("memory_file")
    loop_type = getattr(args, "loop_type", None) or existing_fm.get("loop_type")
    if not from_memory or not loop_type:
        print(
            "ERROR: recovery requires the original --from-memory seed and "
            "--loop-type (or both must be present in candidate frontmatter)",
            file=sys.stderr,
        )
        return 2

    try:
        mem, mem_fields, _ledger, deterministic_id = _load_continuation_runtime(
            project_dir, from_memory, loop_type,
            getattr(args, "knowledge_store", None),
        )
    except (FileNotFoundError, ValueError, LedgerError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if deterministic_id != cand_id:
        print(
            f"ERROR: candidate identity mismatch: memory resolves to "
            f"{deterministic_id}, not {cand_id}",
            file=sys.stderr,
        )
        return 2
    if (existing_fm.get("memory_hash") != mem_fields.get("memory_hash")
            or existing_fm.get("hypothesis_id") != mem_fields.get("hypothesis_id")
            or existing_fm.get("previous_candidate_id") != mem.get("source_candidate_id")):
        print(
            "ERROR: recovery identity does not match candidate memory/hypothesis "
            "pointers; refusing mutation",
            file=sys.stderr,
        )
        return 2
    if existing_fm.get("current_status", "NEW") != "NEW":
        print(
            "ERROR: recovery is forbidden after candidate status progressed "
            f"beyond NEW ({existing_fm.get('current_status')})",
            file=sys.stderr,
        )
        return 2

    existing_contract, contract_path, existing_raw = l0_contract.load_contract(
        project_dir, cand_id
    )
    if not isinstance(existing_contract, dict) or existing_raw is None:
        print(
            f"ERROR: existing continuation contract is missing/unreadable: "
            f"{contract_path}",
            file=sys.stderr,
        )
        return 2
    old_contract_hash = hashlib.sha256(existing_raw).hexdigest()
    if (existing_fm.get("input_contract_hash") != old_contract_hash
            or existing_fm.get("input_contract_path") !=
            str(contract_path.relative_to(project_dir).as_posix())):
        print(
            "ERROR: existing candidate and L0 contract are already out of sync; "
            "recovery cannot safely infer which state is authoritative",
            file=sys.stderr,
        )
        return 2
    if not _is_defective_continuation(existing_contract):
        print(
            "ERROR: existing contract is not the known pristine data-less "
            "schema-1.0 continuation form; refusing recovery",
            file=sys.stderr,
        )
        return 2

    binding_path_value = l0_data.current_round_data_binding_path(
        project_dir, cand_id
    )
    existing_binding = None
    if binding_path_value.is_file():
        try:
            existing_binding = l0_data.load_current_round_data_binding(
                project_dir, cand_id
            )
        except l0_data.L0DataError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    reasons = _recovery_progress_reasons(
        project_dir, cand_id, existing_binding=existing_binding
    )
    if reasons:
        print(
            "ERROR: recovery is forbidden because the candidate has progressed: "
            + "; ".join(reasons),
            file=sys.stderr,
        )
        return 2

    try:
        inherited_inputs = l0_state.project_verified_source_selectors(
            project_dir, mem,
        )
    except l0_state.L0StateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    source_input = existing_contract.get("source_input")
    new_contract, round_id, parent_rid = _continuation_contract(
        cand_id, mem, mem_fields,
        existing_contract.get("scientific_question", ""),
        mem.get("next_round_hypothesis") or mem.get("new_hypothesis") or "",
        source_input, inherited_inputs,
    )
    new_raw = l0_contract.serialize_contract(new_contract)
    new_hash = hashlib.sha256(new_raw).hexdigest()
    audit_path = (project_dir / "08_Audit" / "continuation_recovery" /
                  f"{cand_id}_contract_upgrade.json")
    audit_payload = {
        "schema_version": "ContinuationContractRecovery/v1",
        "operation": "upgrade_defective_continuation",
        "candidate_id": cand_id,
        "source_candidate_id": mem.get("source_candidate_id", ""),
        "round_id": str(round_id),
        "parent_round_id": str(parent_rid or ""),
        "memory_hash": mem_fields["memory_hash"],
        "old_contract_sha256": old_contract_hash,
        "new_contract_sha256": new_hash,
        "old_schema_version": str(existing_contract.get("schema_version") or ""),
        "new_schema_version": str(new_contract.get("schema_version") or ""),
        "inherited_inputs": inherited_inputs,
        "reason": "explicit recovery of an unstarted v0.9.1 data-less continuation",
    }
    audit_text = json.dumps(
        audit_payload, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    if audit_path.exists() and audit_path.read_text(encoding="utf-8") != audit_text:
        print(f"ERROR: recovery audit collision: {audit_path}", file=sys.stderr)
        return 2

    old_candidate_bytes = cf.read_bytes()
    new_candidate_text = cf.read_text(encoding="utf-8")
    try:
        new_candidate_text = _replace_frontmatter_scalar(
            new_candidate_text, "input_contract_hash", new_hash
        )
        new_candidate_text = _replace_frontmatter_scalar(
            new_candidate_text, "schema_version", new_contract["schema_version"]
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    old_binding_bytes = (
        binding_path_value.read_bytes() if binding_path_value.is_file() else None
    )
    evidence_binding = None
    evidence_path_value = (
        project_dir / "08_Audit" / "l0_restore" /
        f"{cand_id}_evidence_binding.json"
    )
    old_evidence_bytes = (
        evidence_path_value.read_bytes() if evidence_path_value.is_file() else None
    )
    try:
        _atomic_replace(contract_path, new_raw)
        _atomic_replace(cf, new_candidate_text.encode("utf-8"))
        if existing_binding is not None:
            evidence_binding = l0_state.restore_previous_round(
                project_dir, cand_id
            )
            l0_data.recover_current_round_data_binding(
                project_dir, cand_id, evidence_binding,
                expected_old_contract_sha256=old_contract_hash,
            )
        if not audit_path.exists():
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("x", encoding="utf-8") as handle:
                handle.write(audit_text)
    except (OSError, ValueError, l0_state.L0StateError, l0_data.L0DataError) as exc:
        try:
            _atomic_replace(contract_path, existing_raw)
            _atomic_replace(cf, old_candidate_bytes)
            if old_binding_bytes is not None:
                _atomic_replace(binding_path_value, old_binding_bytes)
            elif binding_path_value.exists():
                binding_path_value.unlink()
            if old_evidence_bytes is not None:
                _atomic_replace(evidence_path_value, old_evidence_bytes)
            elif evidence_path_value.exists():
                evidence_path_value.unlink()
        except OSError as rollback_exc:
            print(
                f"ERROR: recovery failed ({exc}) and rollback failed ({rollback_exc})",
                file=sys.stderr,
            )
            return 2
        print(f"ERROR: recovery failed and was rolled back: {exc}", file=sys.stderr)
        return 2

    print(cand_id)
    print(f"  -> recovered contract {contract_path}")
    print(f"  -> audit {audit_path}")
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
        "schema_version": contract["schema_version"],
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

    try:
        l8_artifact = _candidate_l8_artifact(
            project_dir, getattr(args, "knowledge_store", None)
        )
    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    body = _candidate_template(
        cand_id, contract["scientific_question"], source["description"],
        contract["scientific_question"], contract["current_round"]["hypothesis"],
        extra_front=mem_fields,
        l8_persona=l8_artifact.display_persona,
        l8_storage_key=l8_artifact.storage_key,
    )
    plans_dir = project_dir / "01_Candidates" / "_research_plans"
    plans_dir_existed_before = plans_dir.exists()

    cand_path = _candidate_file(project_dir, cand_id)
    sidecar_path = project_dir / mem_fields["input_contract_path"]
    snapshot_path = None
    prov = contract.get("provenance", {})
    if isinstance(prov, dict) and prov.get("parser_mode") == "plan-v1":
        snapshot_rel = prov.get("research_plan_snapshot_path")
        if snapshot_rel:
            snapshot_path = project_dir / snapshot_rel

    for target in (cand_path, sidecar_path, snapshot_path):
        if target and target.exists():
            print(f"ERROR: target file already exists: {target}", file=sys.stderr)
            return 2

    created_paths = []
    try:
        cand_path.write_text(body, encoding="utf-8")
        created_paths.append(cand_path)

        artifact_path, _ = l0_contract.write_contract(project_dir, cand_id, contract)
        created_paths.append(artifact_path)

        if snapshot_path:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_bytes(request_path.read_bytes())
            created_paths.append(snapshot_path)
    except Exception as exc:
        cleanup_errors = []
        for path in reversed(created_paths):
            try:
                if path.exists():
                    path.unlink()
            except OSError as cleanup_exc:
                cleanup_errors.append(f"{path.name}: {cleanup_exc}")

        if not plans_dir_existed_before and plans_dir.exists():
            try:
                plans_dir.rmdir()
            except OSError:
                pass

        err_msg = f"structured intake write failed: {exc}; created candidate artifacts were rolled back"
        if cleanup_errors:
            err_msg += f" (cleanup errors: {'; '.join(cleanup_errors)})"
        print(f"ERROR: {err_msg}", file=sys.stderr)
        return 2

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
        try:
            runtime_config = deep_research.default_runtime_config(
                getattr(args, "backend", None))
        except deep_research.DeepResearchError as exc:
            print(f"ERROR: cannot pick a Deep Research backend: {exc}", file=sys.stderr)
            return 2
        runtime_file.write_text(json.dumps(runtime_config, indent=2), encoding="utf-8")
        created.append(runtime_file.name)
        if runtime_config["backend"] == "claude":
            print("NOTE: set plugin_dir in "
                  f"{runtime_file.name} to the academic-research-skills plugin path; "
                  "deep-research-run stays blocked until it is set.", file=sys.stderr)
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

    # Single component-level authority: _check_dependencies delegates framework
    # probes to l0_preflight and persists preflight_receipt.json. Lifecycle only
    # formats/enforces those results; it never repeats an ARS/service probe.
    ok, missing, advisory = _check_dependencies(project_dir)
    print("\nL0 dependency gate:")
    for d in ok:
        print(f"  OK       {d['kind']}:{d['name']}")
    for d in advisory:
        print(f"  WARN     {d['kind']}:{d['name']} -- {d.get('error_code')}: "
              f"{d.get('detail')} (readiness only; future consumer: {d['needed_for']})",
              file=sys.stderr)
    for d in missing:
        print(f"  MISSING  {d['kind']}:{d['name']} ({d.get('label', d['name'])})"
              f"  -- {d['needed_for']}", file=sys.stderr)
    if missing:
        print("\nPREFLIGHT GATE: STOP -- required dependencies missing.",
              file=sys.stderr)
        print("The loop must NOT proceed past L0. Satisfy each, then re-run "
              "`preflight` (or `check-deps`):", file=sys.stderr)
        for d in missing:
            print(f"  {d['name']}: {_dep_fix_hint(d)}", file=sys.stderr)
        return 3
    if advisory:
        print("\nPREFLIGHT GATE: PASS WITH WARNINGS -- blocking dependencies present; "
              "future literature-transport readiness is incomplete.")
    else:
        print("\nPREFLIGHT GATE: PASS -- all required dependencies present.")

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
    """Standalone L0 component gate; non-zero means a blocking dependency failed."""
    project_dir = Path(args.project_dir) if getattr(args, "project_dir", None) else None
    ok, missing, advisory = _check_dependencies(project_dir)
    for d in ok:
        print(f"OK       {d['kind']}:{d['name']}")
    for d in advisory:
        print(f"WARN     {d['kind']}:{d['name']} -- {d.get('error_code')}: "
              f"{d.get('detail')} (readiness only; future consumer: {d['needed_for']})",
              file=sys.stderr)
    for d in missing:
        print(f"MISSING  {d['kind']}:{d['name']} ({d.get('label', d['name'])})"
              f"  -- {d['needed_for']}\n         satisfy: {_dep_fix_hint(d)}",
              file=sys.stderr)
    if missing:
        print("DEPENDENCY GATE: STOP -- satisfy the missing dependencies above; "
              "the loop must not proceed.", file=sys.stderr)
        return 3
    print("DEPENDENCY GATE: PASS")

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
        ("L8", "Tukey", "L8_tukey"),
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
    print("  L8  Tukey      -> next-step, assemble-context --node L8")
    print("  L9a Feynman    -> next-step, assemble-context --node L9a")
    print("  L9b Darwin     -> after finalized L9a, assemble-context --node L9b")
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
