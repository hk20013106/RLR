"""First-class L0.5 scheduling and Deep Research command boundary."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_loop import research_evidence_binding, research_seed
from research_loop.compatibility import get_profile
from research_loop.topology import topology_for_profile


def _research_step(packet: dict) -> dict:
    profile_id = str(packet["profile_id"])
    _nodes, node_map, _sequence = topology_for_profile(profile_id)
    node = node_map["L0.5"]
    return {
        "node": "L0.5",
        "persona": node["persona"],
        "is_parallel": False,
        "is_execution": False,
        "node_kind": "research",
        "research_required": True,
        "research_persona": node["research_persona"],
        "pre_research": node["pre_research"],
        "context_files": list(node["context_inputs"]),
        "action_hint": node["action_hint"],
        "advance_command": None,
        "tools_policy": node.get("tools_policy"),
        "knowledge_base": node.get("knowledge_base"),
        "profile_id": packet.get("profile_id"),
        "schema_version": packet.get("schema_version"),
        "topology_version": packet.get("topology_version"),
        "persona_catalog_version": packet.get("persona_catalog_version"),
    }


def install_lifecycle(lifecycle_module) -> None:
    if getattr(lifecycle_module, "_L0_5_ROUTING_INSTALLED", False):
        return
    original = lifecycle_module.cmd_next_step

    def cmd_next_step(args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = original(args)
        raw_out = stdout.getvalue()
        raw_err = stderr.getvalue()
        if rc != 0:
            sys.stdout.write(raw_out)
            sys.stderr.write(raw_err)
            return rc
        try:
            packet = json.loads(raw_out)
        except json.JSONDecodeError:
            sys.stdout.write(raw_out)
            sys.stderr.write(raw_err)
            return rc
        if packet.get("node") != "L1":
            print(json.dumps(packet, indent=2))
            sys.stderr.write(raw_err)
            return rc
        try:
            profile = get_profile(str(packet.get("profile_id") or ""))
        except ValueError:
            print(json.dumps(packet, indent=2))
            sys.stderr.write(raw_err)
            return rc
        if profile.delta_schema_version != "2.1":
            print(json.dumps(packet, indent=2))
            sys.stderr.write(raw_err)
            return rc

        try:
            seed = research_seed.load_l1_research_seed(
                args.project_dir, str(args.cand_id)
            )
            state, detail = research_evidence_binding.binding_state(
                args.project_dir, seed
            )
        except research_seed.ResearchSeedError as exc:
            print(json.dumps({
                "error": f"L0.5 cannot resolve canonical ResearchSeed: {exc}"
            }))
            return 3

        if state == "invalid":
            print(json.dumps({
                "error": f"L0.5 frozen evidence binding is invalid: {detail}"
            }))
            return 3
        if state == "missing":
            print(json.dumps(_research_step(packet), indent=2))
            sys.stderr.write(raw_err)
            return 0

        packet["l0_5_evidence_run_id"] = detail
        packet["evidence_run_id"] = detail
        print(json.dumps(packet, indent=2))
        sys.stderr.write(raw_err)
        return 0

    lifecycle_module.cmd_next_step = cmd_next_step
    lifecycle_module._L0_5_ROUTING_INSTALLED = True


def install_research_command(commands_module, deep_research_module) -> None:
    if getattr(commands_module, "_L0_5_RESEARCH_COMMAND_INSTALLED", False):
        return
    original = commands_module.cmd_deep_research_run
    dr = deep_research_module

    def cmd_deep_research_run(args):
        if str(args.node) != "L0.5":
            return original(args)
        project = Path(args.project_dir)
        candidate = commands_module._candidate_file(project, args.cand_id)
        if not candidate.is_file():
            print(f"ERROR: candidate not found: {args.cand_id}", file=sys.stderr)
            return 2
        if str(getattr(args, "l4a_manifest", "") or "").strip():
            print("ERROR: --l4a-manifest is valid only for --node L4", file=sys.stderr)
            return 2

        try:
            seed = research_seed.load_l1_research_seed(project, args.cand_id)
            state, detail = research_evidence_binding.binding_state(project, seed)
        except research_seed.ResearchSeedError as exc:
            print(f"ERROR: L0.5 canonical ResearchSeed is invalid: {exc}", file=sys.stderr)
            return 3
        if state == "valid":
            print(
                f"ERROR: current ResearchSeed is already frozen to L0.5 run {detail}",
                file=sys.stderr,
            )
            return 3
        if state == "invalid":
            print(f"ERROR: L0.5 evidence binding is invalid: {detail}", file=sys.stderr)
            return 3

        try:
            spec, skill_version = commands_module._deep_research_spec_from_args(args)
        except dr.DeepResearchError as exc:
            print(f"ERROR: Deep Research runtime is not configured: {exc}", file=sys.stderr)
            return 3
        if not getattr(args, "allow_host_mismatch", False):
            try:
                same_host, host_reason = dr.host_matches(
                    spec, explicit=getattr(args, "backend", None) is not None
                )
            except dr.DeepResearchError as exc:
                print(f"ERROR: Deep Research host is not declarable: {exc}", file=sys.stderr)
                return 3
            if not same_host:
                print(f"ERROR: Deep Research host mismatch: {host_reason}", file=sys.stderr)
                return 3
        consistent, reason = dr.validate_spec_consistency(spec)
        if not consistent:
            print(f"ERROR: Deep Research runtime spec is inconsistent: {reason}", file=sys.stderr)
            return 3
        ready, reason = dr.runtime_ready(spec)
        if not ready:
            print(f"ERROR: Deep Research runtime is not ready: {reason}", file=sys.stderr)
            return 3

        try:
            profile, binding = commands_module._bound_profile(project)
            _nodes, node_map, _sequence = topology_for_profile(profile.profile_id)
            node_info = node_map["L0.5"]
            persona = str(node_info.get("research_persona") or "")
            if not node_info.get("research_required") or not persona:
                raise dr.DeepResearchError("L0.5 has no declared research persona")
            run_dir = (
                project / "08_Audit" / "deep_research_runtime"
                / args.cand_id / "L0_5"
            )
            artifact = dr.run_and_persist(
                project,
                args.cand_id,
                "L0.5",
                str(seed["scientific_question"]),
                str(seed["hypothesis_seed"]),
                spec,
                run_dir,
                skill_version,
                "",
                project_id=str(binding["project_id"]),
                round_id=str(seed["round_id"]),
                profile_id=profile.profile_id,
                research_persona=persona,
            )
            ok, reason = dr.audit_evidence_pack(
                project, args.cand_id, "L0.5", run_id=artifact["run_id"]
            )
            if not ok:
                print(f"ERROR: L0.5 evidence gate failed: {reason}", file=sys.stderr)
                return 3
            research_evidence_binding.write_binding(
                project, seed, artifact["run_id"]
            )
        except (
            dr.DeepResearchError,
            research_evidence_binding.ResearchEvidenceBindingError,
            KeyError,
            ValueError,
        ) as exc:
            print(f"ERROR: L0.5 Deep Research failed: {exc}", file=sys.stderr)
            return 3

        print(json.dumps(artifact, ensure_ascii=False, indent=2))
        return 0

    commands_module.cmd_deep_research_run = cmd_deep_research_run
    commands_module._L0_5_RESEARCH_COMMAND_INSTALLED = True
