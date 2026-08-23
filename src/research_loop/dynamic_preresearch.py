"""Dynamic pre-research prompt boundary driven only by current scientific state."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from research_loop import research_seed
from research_loop.paths import _candidate_file, _pre_research_file
from research_loop.preresearch import PRE_RESEARCH_MAP
from research_loop.yamlio import _load_yaml_front


def _load_delta(commands, project: Path, cand_id: str, key: str) -> dict:
    path = commands._delta_for_candidate(project, key, cand_id)
    if not path or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _canonical_semantics(project: Path, cand_id: str) -> tuple[str, str, str]:
    seed = research_seed.load_l1_research_seed(project, cand_id)
    return (
        str(seed["scientific_question"]),
        str(seed["hypothesis_seed"]),
        str(seed["round_id"]),
    )


def _state_context(commands, project: Path, cand_id: str, node: str) -> str:
    if node == "L4":
        selected = _load_delta(commands, project, cand_id, "L3_oppenheimer")
        return json.dumps(selected, ensure_ascii=False, sort_keys=True)
    if node == "L7":
        approved = _load_delta(commands, project, cand_id, "L6_oppenheimer")
        return json.dumps(approved, ensure_ascii=False, sort_keys=True)
    if node == "L8.5":
        l7 = _load_delta(commands, project, cand_id, "L7_turing")
        l8 = _load_delta(commands, project, cand_id, commands._l8_storage_key(project))
        return json.dumps(
            {"execution_results": l7, "evidence_audit": l8},
            ensure_ascii=False,
            sort_keys=True,
        )
    return ""


def _prompt(node: str, question: str, hypothesis: str, round_id: str,
            context: str, output_file: Path, project: Path) -> str:
    common = f"""# Dynamic Pre-Research: {node}

Round: {round_id}
Canonical scientific question: {question}
Current-round hypothesis: {hypothesis}

SEARCH POLICY:
- Derive the ACTUAL search queries from the authoritative state shown here.
- Do not use repository-embedded project/domain example queries.
- Issue multiple complementary queries when needed and record every issued query,
  including zero-result queries, in the Query log.
- Persist real source/tool receipts. Never invent a citation or retrieval result.
"""
    if node == "L0.5":
        objective = """
OBJECTIVE:
Use Academic Research Skills to discover primary literature relevant to the
canonical question and current hypothesis. Retrieve source-located evidence
needed for downstream hypothesis generation. The resulting run is the frozen
L0.5 EvidencePack consumed by L1.
"""
    elif node == "L4":
        objective = f"""
OBJECTIVE:
Derive methodology-search queries from the scientific question, selected
hypotheses, data constraints, and current method-design problem. Search for
methods and evidence needed to construct candidate strategies.

CURRENT UPSTREAM METHOD CONTEXT:
{context or '(no upstream method context available)'}
"""
    elif node == "L7":
        objective = f"""
OBJECTIVE:
Derive code/package/repository searches from the APPROVED L6 strategy and its
required scripts/software. Search for reusable implementations that satisfy the
actual approved method; do not assume a named package or algorithm in advance.

APPROVED METHOD CONTEXT:
{context or '(approved L6 strategy not available)'}
"""
    elif node == "L8.5":
        objective = f"""
OBJECTIVE:
Derive literature-verification queries from the concrete L7 results and L8
evidence audit. Search specifically for evidence that supports, contradicts,
or leaves unresolved those observed findings.

ACTUAL RESULT CONTEXT:
{context or '(L7/L8 result context not available)'}
"""
    else:
        raise ValueError(f"unsupported dynamic pre-research node {node}")
    return common + objective + f"""
OUTPUT:
Write the structured pre-research artifact to:
{output_file.as_posix()}

For literature stages include Runtime digest, Query log, Tool receipt, and
Source count. For code search include the actual derived queries, repositories
or packages inspected, version/commit evidence when available, and the reason
each candidate is relevant.

Project root: {project.as_posix()}
"""


def install(commands_module) -> None:
    if getattr(commands_module, "_DYNAMIC_PRERESEARCH_INSTALLED", False):
        return
    original = commands_module.cmd_pre_research

    def cmd_pre_research(args):
        node = str(args.node)
        # Preserve explicit synthetic/placeholder fixture behavior for historical
        # tests; production prompt generation always uses the dynamic path below.
        if getattr(args, "write_synthetic", False) or getattr(args, "write_placeholder", False):
            return original(args)
        config = PRE_RESEARCH_MAP.get(node)
        if config is None:
            print(f"ERROR: no pre-research defined for node {node}", file=sys.stderr)
            return 2
        project = Path(args.project_dir)
        candidate = _candidate_file(project, args.cand_id)
        if not candidate.is_file():
            print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
            return 2
        try:
            question, hypothesis, round_id = _canonical_semantics(
                project, str(args.cand_id)
            )
        except research_seed.ResearchSeedError as exc:
            print(f"ERROR: canonical ResearchSeed is invalid: {exc}", file=sys.stderr)
            return 3
        output_file = (
            Path(args.output_dir) / f"{node}_research.md"
            if getattr(args, "output_dir", None)
            else _pre_research_file(project, node)
        )
        context = _state_context(
            commands_module, project, str(args.cand_id), node
        )
        print(_prompt(
            node, question, hypothesis, round_id, context, output_file, project
        ))
        return 0

    commands_module.cmd_pre_research = cmd_pre_research
    commands_module._DYNAMIC_PRERESEARCH_INSTALLED = True
