"""Canonical research CLI command family.

Research-stage identity, dynamic query derivation, Deep Research dispatch, and
ResearchSeed evidence freezing are owned here. Search policy contains no
project-specific query catalog; every production prompt is derived from current
authoritative state.
"""

import json
import sys
from pathlib import Path

from research_loop import deep_research, deep_research_task
from research_loop import l4_evidence_bundle, l4_pipeline, research_seed
from research_loop.common import _now
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE, PROFILE_V20, get_profile
from research_loop.delta import _delta_for_candidate, artifact_for_node
from research_loop.hypothesis_ledger import binding_path
from research_loop.paths import _candidate_file, _pre_research_file
from research_loop.preresearch import (
    PRE_RESEARCH_MAP,
    _LIT_PRE_RESEARCH_TYPES,
    _validate_pre_research_content,
    pre_research_config,
)
from research_loop.yamlio import _load_yaml_front
from research_loop.topology import topology_for_profile


def _bound_profile(project_dir):
    path = binding_path(project_dir)
    if not path.is_file():
        return get_profile(PROFILE_V20), {"project_id": Path(project_dir).name}
    try:
        binding = json.loads(path.read_text(encoding="utf-8"))
        return get_profile(str(binding["profile_id"])), binding
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise deep_research.DeepResearchError(
            f"invalid project profile binding: {exc}"
        ) from exc


def _l8_storage_key(project_dir):
    profile, _ = _bound_profile(project_dir)
    return artifact_for_node(profile, "L8").storage_key


def _load_delta(project_dir: Path, cand_id: str, key: str) -> dict:
    path = _delta_for_candidate(project_dir, key, cand_id)
    if not path or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _canonical_semantics(project_dir: Path, cand_id: str, *, required: bool):
    try:
        seed = research_seed.load_l1_research_seed(project_dir, cand_id)
    except research_seed.ResearchSeedError:
        if required:
            raise
        return None
    return seed


def _research_state_context(project_dir: Path, cand_id: str, node: str) -> str:
    if node == "L4":
        return json.dumps(
            {"selected_hypotheses": _load_delta(project_dir, cand_id, "L3_oppenheimer")},
            ensure_ascii=False,
            sort_keys=True,
        )
    if node == "L7":
        return json.dumps(
            {"approved_strategy": _load_delta(project_dir, cand_id, "L6_oppenheimer")},
            ensure_ascii=False,
            sort_keys=True,
        )
    if node == "L8.5":
        try:
            l8_key = _l8_storage_key(project_dir)
        except deep_research.DeepResearchError:
            l8_key = "L8_curie"
        return json.dumps(
            {
                "execution_results": _load_delta(project_dir, cand_id, "L7_turing"),
                "evidence_audit": _load_delta(project_dir, cand_id, l8_key),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    return ""


def _dynamic_prompt(
    *,
    project_dir: Path,
    node: str,
    research_type: str,
    question: str,
    hypothesis: str,
    round_id: str,
    focus: str,
    state_context: str,
    output_file: Path,
) -> str:
    grounding = f"""# Dynamic Pre-Research: {node}

Round: {round_id}
Canonical scientific question: {question}
Current-round hypothesis: {hypothesis}
Research focus: {focus}

SEARCH POLICY:
- Derive the ACTUAL search queries from the authoritative state shown here.
- Do not use repository-embedded project/domain example queries.
- Issue multiple complementary queries when needed and record every issued query,
  including zero-result queries, in the Query log.
- Persist real source/tool receipts. Never invent a citation or retrieval result.
"""

    if node in {"L0.5", "L1"}:
        objective = """
OBJECTIVE:
Discover primary literature relevant to the canonical question and current
hypothesis. Retrieve source-located evidence needed for downstream hypothesis
reasoning. For native projects this run is the frozen L0.5 EvidencePack consumed
by Einstein; historical profiles retain the former L1 research target.
"""
    elif node == "L4":
        objective = f"""
OBJECTIVE:
Derive methodology-search queries from the scientific question, selected
hypotheses, data constraints, and current method-design problem. Search for
methods and evidence needed to construct candidate strategies.

CURRENT METHOD CONTEXT:
{state_context or '(no selected-method context available)'}
"""
    elif node == "L7":
        objective = f"""
OBJECTIVE:
Derive code/package/repository searches from the APPROVED L6 strategy and its
required scripts/software. Search for reusable implementations that satisfy the
actual approved method; do not assume a named package or algorithm in advance.

APPROVED STRATEGY CONTEXT:
{state_context or '(approved L6 strategy not available)'}
"""
    elif node == "L8.5":
        objective = f"""
OBJECTIVE:
Derive literature-verification queries from the concrete L7 results and L8
evidence audit. Search specifically for evidence that supports, contradicts,
or leaves unresolved those observed findings.

ACTUAL RESULT CONTEXT:
{state_context or '(L7/L8 result context not available)'}
"""
    else:
        raise ValueError(f"unsupported pre-research node {node}")

    if research_type in _LIT_PRE_RESEARCH_TYPES:
        requirements = f"""
RETRIEVAL REQUIREMENTS:
- Use the configured academic research skill/runtime.
- Reuse relevant registered literature when it is part of the authorized
  research stage, and register newly selected sources with stable identifiers.
- Every selected source must retain DOI/PMID/URL or equivalent locator evidence.

OUTPUT:
Write the structured artifact to: {output_file.as_posix()}
It must include `## Runtime digest`, `## Query log`, `## Tool receipt`, and
`## Source count` with the actual issued queries and retrieval receipts.
"""
    else:
        requirements = f"""
REUSE REQUIREMENTS:
- Search existing repositories/packages before proposing new implementation.
- Record the actual derived queries, candidates inspected, stable version/commit
  information when available, relevance, and why a candidate can/cannot be reused.

OUTPUT:
Write the structured code-search artifact to: {output_file.as_posix()}
"""
    return grounding + objective + requirements + f"\nProject root: {project_dir.as_posix()}\n"


def cmd_pre_research(args):
    """Render a research prompt derived only from current authoritative state."""
    project_dir = Path(args.project_dir)
    node = str(args.node)
    try:
        profile, binding = _bound_profile(project_dir)
    except deep_research.DeepResearchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    research_config = pre_research_config(node, profile.profile_id)
    if research_config is None:
        print(f"ERROR: no pre-research defined for node {node}", file=sys.stderr)
        return 2

    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.is_file():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)

    seed_required = node in {"L0.5", "L1"}
    try:
        seed = _canonical_semantics(
            project_dir, str(args.cand_id), required=seed_required
        )
    except research_seed.ResearchSeedError as exc:
        print(f"ERROR: canonical ResearchSeed is invalid: {exc}", file=sys.stderr)
        return 3
    if seed is not None:
        question = str(seed["scientific_question"])
        hypothesis = str(seed["hypothesis_seed"])
        round_id = str(seed["round_id"])
    else:
        question = str(fm.get("question") or "")
        hypothesis = str(fm.get("claim") or "")
        round_id = str(fm.get("round_id") or "1")

    output_file = (
        Path(args.output_dir) / f"{node}_research.md"
        if getattr(args, "output_dir", None)
        else _pre_research_file(project_dir, node)
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)

    research_type = str(research_config["type"])
    write_placeholder = bool(getattr(args, "write_placeholder", False))
    write_synthetic = bool(getattr(args, "write_synthetic", False))

    # Test-only fixture writers remain explicit CLI options. Production prompt
    # generation below never emits or consumes hardcoded domain query strings.
    should_write_placeholder = (
        write_placeholder
        or (not write_synthetic and not output_file.exists()
            and research_type in _LIT_PRE_RESEARCH_TYPES)
    )
    if should_write_placeholder:
        output_file.write_text(
            f"""# Pre-Research: {research_type.replace('_', ' ').title()} (before {node})

## Runtime digest
NOT YET RUN

## Query log
- NOT YET RUN

## Tool receipt
- tool: none | time: {_now()} | summary: NOT YET RUN

## Source count
0
""",
            encoding="utf-8",
        )
    elif write_synthetic and research_type in _LIT_PRE_RESEARCH_TYPES:
        synthetic_content = f"""# Synthetic Pre-Research (before {node})

## Runtime digest
- doi:10.1000/abc123 — synthetic fixture finding.

## Query log
- canonical question evidence
- alternative explanation evidence (0 results)

## Tool receipt
- tool: synthetic-test | time: 2026-07-05T10:00:00 | summary: 1 fixture source

## Source count
1
"""
        output_file.write_text(synthetic_content, encoding="utf-8")
        payload = {
            "schema_version": deep_research.SCHEMA_VERSION,
            "queries": [question, hypothesis],
            "papers": [{
                "doi": "10.1000/abc123",
                "title": "Synthetic Evidence Fixture",
                "source_database": "synthetic-test",
                "metadata": {},
                "source_metadata_response": {"fixture": "write-synthetic"},
                "open_access": False,
                "extracts": [
                    {"section": "Results", "text": "Synthetic result.", "locator": "Results"},
                    {"section": "Discussion", "text": "Synthetic discussion.", "locator": "Discussion"},
                    {"section": "Conclusion", "text": "Synthetic conclusion.", "locator": "Conclusion"},
                    {"section": "Methods", "text": "Synthetic method.", "locator": "Methods"},
                ],
            }],
        }
        if research_type in {"literature_review", "literature_verification"}:
            payload["review_search"] = {
                "query": "synthetic review query",
                "status": "none_found",
                "receipt": "synthetic-test 0",
            }
        _, node_map, _ = topology_for_profile(profile.profile_id)
        research_persona = str(
            node_map[node].get("research_persona") or "Curie"
        )
        artifact = deep_research.persist_run(
            project_dir,
            args.cand_id,
            node,
            payload,
            deep_research.skill_receipt(
                "codex", ["synthetic-test"], "synthetic-test", "test-only"
            ),
            project_id=str(binding["project_id"]),
            round_id=round_id,
            profile_id=profile.profile_id,
            research_persona=research_persona,
        )
        try:
            if node == "L0.5":
                research_seed.write_research_evidence_binding(
                    project_dir, seed, artifact["run_id"], "L0.5"
                )
            elif node == "L1":
                research_seed.write_l1_evidence_binding(
                    project_dir, seed, artifact["run_id"]
                )
        except research_seed.ResearchSeedError as exc:
            print(f"ERROR: evidence binding failed: {exc}", file=sys.stderr)
            return 3

    prompt = _dynamic_prompt(
        project_dir=project_dir,
        node=node,
        research_type=research_type,
        question=question,
        hypothesis=hypothesis,
        round_id=round_id,
        focus=str(research_config.get("description") or ""),
        state_context=_research_state_context(project_dir, args.cand_id, node),
        output_file=output_file,
    )
    print(prompt)
    print(f"\n[pre-research] output target: {output_file}")
    return 0


def cmd_audit_pre_research(args):
    """Audit the research artifacts applicable to the project's profile."""
    project_dir = Path(args.project_dir)
    try:
        profile, _binding = _bound_profile(project_dir)
    except deep_research.DeepResearchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    configs = dict(PRE_RESEARCH_MAP)
    legacy_l1 = pre_research_config("L1", profile.profile_id)
    if legacy_l1 is not None:
        configs["L1"] = legacy_l1

    results = {}
    for node, pr_cfg in configs.items():
        if pr_cfg.get("type") not in _LIT_PRE_RESEARCH_TYPES:
            results[node] = {"status": "NOT_APPLICABLE", "reason": "non-literature node"}
            continue
        prf = _pre_research_file(project_dir, node)
        if not prf.exists():
            results[node] = {
                "status": "FAIL",
                "reason": f"artifact missing ({prf.as_posix()})",
            }
            continue
        try:
            text = prf.read_text(encoding="utf-8", errors="replace")
            ok, reason = _validate_pre_research_content(text, pr_cfg)
        except Exception as exc:
            ok, reason = False, f"error reading/parsing: {exc}"
        results[node] = {"status": "PASS" if ok else "FAIL", "reason": reason}

    print(json.dumps({"project_dir": project_dir.as_posix(), "results": results}, indent=2))
    return 0


def _deep_research_spec_from_args(args):
    overrides = {
        "backend": args.backend,
        "executable": args.executable,
        "plugin_dir": args.plugin_dir,
        "model": args.model,
        "timeout": args.timeout,
        "skill_path": args.skill_path,
        "skill_version": args.skill_version,
    }
    return deep_research.load_runtime_spec(args.project_dir, overrides)


def cmd_deep_research_run(args):
    """Execute one declared research stage and persist verified evidence."""
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: candidate not found: {args.cand_id}", file=sys.stderr)
        return 2

    l4a_manifest = str(getattr(args, "l4a_manifest", "") or "").strip()
    if l4a_manifest and args.node != "L4":
        print("ERROR: --l4a-manifest is valid only for --node L4", file=sys.stderr)
        return 2

    try:
        profile, binding = _bound_profile(project_dir)
        _, node_map, _ = topology_for_profile(profile.profile_id)
        node_info = node_map[str(args.node)]
        research_persona = str(node_info.get("research_persona") or "")
        if not node_info.get("research_required") or not research_persona:
            raise deep_research.DeepResearchError(
                f"{args.node} has no declared research persona"
            )
    except (deep_research.DeepResearchError, KeyError, ValueError) as exc:
        print(f"ERROR: Deep Research identity is invalid: {exc}", file=sys.stderr)
        return 3

    if l4a_manifest:
        fm = _load_yaml_front(cf)
        try:
            run_dir = (
                project_dir / "08_Audit" / "deep_research_runtime"
                / args.cand_id / "L4"
            )
            artifact = l4_evidence_bundle.run_l4b_from_manifest(
                l4_pipeline,
                deep_research,
                project_dir,
                args.cand_id,
                l4a_manifest,
                run_dir,
                project_id=str(binding["project_id"]),
                round_id=str(fm.get("round_id") or "1"),
                profile_id=profile.profile_id,
                research_persona=research_persona,
            )
            ok, reason = deep_research.audit_evidence_pack(
                project_dir, args.cand_id, "L4", run_id=artifact["run_id"]
            )
        except (deep_research.DeepResearchError, KeyError, ValueError) as exc:
            print(f"ERROR: L4B resume failed: {exc}", file=sys.stderr)
            return 3
        if not ok:
            print(f"ERROR: L4B evidence gate failed: {reason}", file=sys.stderr)
            return 3
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
        return 0

    discovery_seed = None
    if str(args.node) in {"L0.5", "L1"}:
        try:
            discovery_seed = research_seed.load_l1_research_seed(
                project_dir, args.cand_id
            )
        except research_seed.ResearchSeedError as exc:
            print(f"ERROR: canonical ResearchSeed is invalid: {exc}", file=sys.stderr)
            return 3
        if str(args.node) == "L0.5":
            state, detail = research_seed.research_evidence_binding_state(
                project_dir, discovery_seed, "L0.5"
            )
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
        spec, skill_version = _deep_research_spec_from_args(args)
    except deep_research.DeepResearchError as exc:
        print(f"ERROR: Deep Research runtime is not configured: {exc}", file=sys.stderr)
        return 3
    if not getattr(args, "allow_host_mismatch", False):
        try:
            same_host, host_reason = deep_research.host_matches(
                spec, explicit=getattr(args, "backend", None) is not None
            )
        except deep_research.DeepResearchError as exc:
            print(f"ERROR: Deep Research host is not declarable: {exc}", file=sys.stderr)
            return 3
        if not same_host:
            print(f"ERROR: Deep Research host mismatch: {host_reason}", file=sys.stderr)
            return 3
    consistent, consistency_reason = deep_research.validate_spec_consistency(spec)
    if not consistent:
        print(
            f"ERROR: Deep Research runtime spec is inconsistent: {consistency_reason}",
            file=sys.stderr,
        )
        return 3
    ready, reason = deep_research.runtime_ready(spec)
    if not ready:
        print(f"ERROR: Deep Research runtime is not ready: {reason}", file=sys.stderr)
        return 3

    fm = _load_yaml_front(cf)
    fallback_seed = None
    if discovery_seed is None:
        fallback_seed = _canonical_semantics(project_dir, args.cand_id, required=False)
    semantic_seed = discovery_seed or fallback_seed
    if semantic_seed is not None:
        dispatch_question = str(semantic_seed["scientific_question"])
        dispatch_hypothesis = str(semantic_seed["hypothesis_seed"])
        dispatch_round_id = str(semantic_seed["round_id"])
    else:
        dispatch_question = str(fm.get("question") or "")
        dispatch_hypothesis = str(fm.get("claim") or "")
        dispatch_round_id = str(fm.get("round_id") or "1")

    run_dir = (
        project_dir / "08_Audit" / "deep_research_runtime"
        / args.cand_id / str(args.node).replace(".", "_")
    )
    result_context = _research_state_context(
        project_dir, args.cand_id, str(args.node)
    )
    try:
        artifact = deep_research.run_and_persist(
            project_dir,
            args.cand_id,
            args.node,
            dispatch_question,
            dispatch_hypothesis,
            spec,
            run_dir,
            skill_version,
            result_context,
            project_id=str(binding["project_id"]),
            round_id=dispatch_round_id,
            profile_id=profile.profile_id,
            research_persona=research_persona,
        )
        ok, reason = deep_research.audit_evidence_pack(
            project_dir, args.cand_id, args.node, run_id=artifact["run_id"]
        )
    except deep_research.DeepResearchError as exc:
        print(f"ERROR: Deep Research failed: {exc}", file=sys.stderr)
        return 3
    if not ok:
        print(f"ERROR: Deep Research evidence gate failed: {reason}", file=sys.stderr)
        return 3

    try:
        if str(args.node) == "L0.5":
            research_seed.write_research_evidence_binding(
                project_dir, discovery_seed, artifact["run_id"], "L0.5"
            )
        elif str(args.node) == "L1":
            research_seed.write_l1_evidence_binding(
                project_dir, discovery_seed, artifact["run_id"]
            )
    except research_seed.ResearchSeedError as exc:
        print(f"ERROR: evidence binding failed: {exc}", file=sys.stderr)
        return 3

    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_start(args):
    """Start the existing Deep Research command in a detached worker."""
    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: project directory not found: {project_dir}", file=sys.stderr)
        return 2
    if (not args.cand_id or "/" in args.cand_id or "\\" in args.cand_id or
            args.cand_id in {".", ".."}):
        print(f"ERROR: invalid candidate ID: {args.cand_id}", file=sys.stderr)
        return 2
    if not _candidate_file(project_dir, args.cand_id).exists():
        print(f"ERROR: candidate not found: {args.cand_id}", file=sys.stderr)
        return 2
    try:
        artifact = deep_research_task.start_task(args)
    except deep_research_task.DetachedTaskError as exc:
        print(f"ERROR: Deep Research task could not start: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_status(args):
    """Read the last status written by a detached Deep Research worker."""
    try:
        artifact = deep_research_task.get_status(args.project_dir, args.task_id)
    except deep_research_task.DetachedTaskError as exc:
        print(f"ERROR: Deep Research task status failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_collect(args):
    """Collect a detached result after repeating the existing exact-run audit."""
    try:
        artifact = deep_research_task.collect_task(
            args.project_dir, args.task_id, deep_research.audit_evidence_pack
        )
    except deep_research_task.DetachedTaskError as exc:
        print(f"ERROR: Deep Research task collection failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


def cmd_deep_research_worker(args):
    """Hidden detached entry point; reuse the full synchronous handler."""
    return deep_research_task.run_worker(
        args.project_dir, args.task_id, cmd_deep_research_run
    )


def cmd_audit_literature_evidence(args):
    ok, reason = deep_research.audit_evidence_pack(
        args.project_dir, args.cand_id, args.node
    )
    print(json.dumps({
        "candidate_id": args.cand_id,
        "node": args.node,
        "status": "PASS" if ok else "FAIL",
        "reason": reason,
    }, indent=2))
    return 0 if ok else 3


def cmd_literature_report(args):
    if args.node:
        nodes = args.node
    else:
        try:
            profile, _ = _bound_profile(args.project_dir)
        except deep_research.DeepResearchError:
            profile = get_profile(PROFILE_V20)
        nodes = (
            ["L0.5", "L4", "L8.5"]
            if profile.profile_id == DEFAULT_NATIVE_PROFILE
            else ["L1", "L4", "L8.5"]
        )
    text = deep_research.render_evidence_digest(
        args.project_dir, args.cand_id, nodes
    )
    if args.format == "json":
        print(json.dumps({
            "candidate_id": args.cand_id,
            "nodes": nodes,
            "digest": text,
        }, ensure_ascii=False))
    else:
        print(text, end="")
    return 0
