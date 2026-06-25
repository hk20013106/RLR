#!/usr/bin/env python3
"""Research Loop Room v0.4 — DAG-driven subagent architecture.

v0.4 converts each persona into an independent subagent with physical context
isolation via DAG topology. Cognitive agents receive context as embedded text
(Path B); Turing executes in a controlled workspace (Path A).

Each agent outputs a structured delta JSON. The candidate file stays read-only.
L10c Linnaeus aggregates all deltas into FINAL_REPORT.

v0.3 is preserved for reference. v0.4 adds pre-research steps before L1/L4/L7.

Usage:
    python research_loop_v04.py --help
    python research_loop_v04.py demo
    python research_loop_v04.py new-project NAME [TOPIC]
    python research_loop_v04.py new-candidate PROJECT_DIR --title T --question Q --claim C --input I
    python research_loop_v04.py preflight PROJECT_DIR
    python research_loop_v04.py next-step PROJECT_DIR CAND_ID
    python research_loop_v04.py assemble-context PROJECT_DIR CAND_ID --node NODE
    python research_loop_v04.py emit-delta PROJECT_DIR CAND_ID --node NODE --persona P --file F
    python research_loop_v04.py decision PROJECT_DIR CAND_ID --status S --reason R [--route P]
    python research_loop_v04.py route PROJECT_DIR CAND_ID --to PERSONA --reason R
    python research_loop_v04.py triage-idea PROJECT_DIR CAND_ID --decision select|reject --reason R
    python research_loop_v04.py triage-method PROJECT_DIR CAND_ID --decision approve|reject --reason R
    python research_loop_v04.py execution-gate PROJECT_DIR CAND_ID
    python research_loop_v04.py prepare-turing-workspace PROJECT_DIR CAND_ID [--file F ...] [--clean]
    python research_loop_v04.py aggregate-report PROJECT_DIR CAND_ID
    python research_loop_v04.py obsidian-sync PROJECT_DIR [--vault PATH]
    python research_loop_v04.py list PROJECT_DIR
    python research_loop_v04.py show PROJECT_DIR CAND_ID
"""

import argparse
import os
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

__version__ = "0.4.5"


class RLRError(Exception):
    """Recoverable, user-facing error: printed cleanly by main(), no traceback."""

# --- personas ---------------------------------------------------------------

AGENTS = ["Linnaeus", "Einstein", "Feynman", "Oppenheimer", "Fisher",
          "Tukey", "Turing", "Curie", "Darwin", "Jobs"]

PERSONA_TITLE = {
    "Linnaeus": "Catalog Master",
    "Einstein": "Conceptual Explorer",
    "Feynman": "Reality Checker",
    "Oppenheimer": "Cold Director",
    "Fisher": "Design Architect",
    "Tukey": "EDA Scout",
    "Turing": "Execution Engine",
    "Curie": "Evidence Auditor",
    "Darwin": "Evolutionary Biologist",
    "Jobs": "Story Strategist",
}

VALID_STATUSES = [
    "NEW", "IDEA_PROPOSED", "IDEA_REJECTED", "IDEA_SELECTED",
    "METHOD_PROPOSED", "METHOD_REJECTED", "METHOD_APPROVED",
    "NEEDS_EXECUTION", "EXECUTED", "AUDITED", "UNDER_REVIEW",
    "KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED",
]

# Legal status transitions for the generic `decision` command. triage-idea,
# triage-method and execution-gate use their own commands and are NOT gated by
# this table. A same-status decision (logging only) and a transition to
# ARCHIVED are always allowed; any other transition not listed here requires
# `decision --force` (so KEEP-from-NEW and similar jumps fail by default while
# manual recovery stays possible).
DECISION_TRANSITIONS = {
    "NEW": {"IDEA_PROPOSED"},
    "IDEA_PROPOSED": {"IDEA_SELECTED", "IDEA_REJECTED", "DROP"},
    "IDEA_SELECTED": {"METHOD_PROPOSED"},
    "IDEA_REJECTED": {"DROP"},
    "METHOD_PROPOSED": {"METHOD_APPROVED", "METHOD_REJECTED", "DROP"},
    "METHOD_REJECTED": {"IDEA_SELECTED", "METHOD_PROPOSED", "DROP"},
    "METHOD_APPROVED": {"NEEDS_EXECUTION"},
    "NEEDS_EXECUTION": {"EXECUTED"},
    "EXECUTED": {"AUDITED"},
    "AUDITED": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"KEEP", "REVISE", "DOWNGRADE", "DROP"},
    "REVISE": {"IDEA_PROPOSED", "METHOD_PROPOSED", "NEEDS_EXECUTION", "UNDER_REVIEW"},
    "DOWNGRADE": {"DROP"},
    "KEEP": set(),
    "DROP": set(),
    "ARCHIVED": set(),
}

# --- DAG topology (14 nodes, L9a/L9b parallel) ------------------------------
# Each node: (node_id, persona, layer, status_before, status_after_optional,
#             context_inputs, is_parallel, is_execution, advance_command,
#             action_hint)

DAG_NODES = [
    {
        "node": "L0", "persona": "Linnaeus", "layer": 0,
        "status_before": "NEW", "advance_command": "decision",
        "advance_status": "IDEA_PROPOSED", "advance_reason": "Preflight complete, route to Einstein",
        "context_inputs": ["candidate_frontmatter"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Scan skills inventory, verify input data, create skill_use_plan",
        "agent_type": "default",
    },
    {
        "node": "L1", "persona": "Einstein", "layer": 1,
        "status_before": "IDEA_PROPOSED", "advance_command": "decision",
        "advance_status": "IDEA_PROPOSED", "advance_reason": "Einstein hypotheses generated, route to Feynman",
        "context_inputs": ["candidate_frontmatter", "L0"],
        "is_parallel": False, "is_execution": False,
        "pre_research": "deep_research",
        "action_hint": "Generate scientific hypotheses about the research question",
        "agent_type": "default",
    },
    {
        "node": "L2", "persona": "Feynman", "layer": 2,
        "status_before": "IDEA_PROPOSED", "advance_command": "decision",
        "advance_status": "IDEA_PROPOSED", "advance_reason": "Feynman falsification complete, route to Oppenheimer",
        "context_inputs": ["candidate_frontmatter", "L1"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Blind-review and attack the L1 hypotheses",
        "agent_type": "default",
    },
    {
        "node": "L3", "persona": "Oppenheimer", "layer": 3,
        "status_before": "IDEA_PROPOSED", "advance_command": "triage-idea",
        "advance_status": "IDEA_SELECTED", "advance_reason": "",
        "context_inputs": ["L1", "L2"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Triage hypotheses: select testable ones, reject weak ones",
        "agent_type": "default",
    },
    {
        "node": "L4", "persona": "Fisher", "layer": 4,
        "status_before": "IDEA_SELECTED", "advance_command": "decision",
        "advance_status": "METHOD_PROPOSED", "advance_reason": "Fisher method design complete, route to Tukey",
        "context_inputs": ["L1", "L3", "L2"],
        "is_parallel": False, "is_execution": False,
        "pre_research": "literature_review",
        "action_hint": "Design experimental/analysis strategies",
        "agent_type": "default",
    },
    {
        "node": "L5", "persona": "Tukey", "layer": 5,
        "status_before": "METHOD_PROPOSED", "advance_command": "decision",
        "advance_status": "METHOD_PROPOSED", "advance_reason": "Tukey QC review complete, route to Oppenheimer",
        "context_inputs": ["L4", "L2"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Critique the method design from EDA/QC perspective",
        "agent_type": "default",
    },
    {
        "node": "L6", "persona": "Oppenheimer", "layer": 6,
        "status_before": "METHOD_PROPOSED", "advance_command": "triage-method",
        "advance_status": "METHOD_APPROVED", "advance_reason": "",
        "context_inputs": ["L4", "L5"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Approve or reject the analysis plan",
        "agent_type": "default",
    },
    {
        "node": "L7", "persona": "Turing", "layer": 7,
        "status_before": "METHOD_APPROVED", "advance_command": "execution-gate",
        "advance_status": "NEEDS_EXECUTION", "advance_reason": "",
        "context_inputs": ["L6", "L0"],
        "is_parallel": False, "is_execution": True,
        "pre_research": "code_search",
        "action_hint": "Execute approved scripts in controlled workspace",
        "agent_type": "worker",
    },
    {
        "node": "L8", "persona": "Curie", "layer": 8,
        "status_before": "EXECUTED", "advance_command": "decision",
        "advance_status": "AUDITED", "advance_reason": "Curie evidence audit complete, route to literature verification",
        "context_inputs": ["L7", "L6", "candidate_frontmatter"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Audit execution results, verify reproducibility, assign evidence level",
        "agent_type": "default",
    },
    {
        "node": "L8.5", "persona": "Curie", "layer": 8,
        "status_before": "AUDITED", "advance_command": "decision",
        "advance_status": "UNDER_REVIEW", "advance_reason": "L8.5 literature verification complete, route to review",
        "context_inputs": ["L7", "L8", "candidate_frontmatter"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Search PubMed/EuropePMC based on L7/L8 actual results to verify findings",
        "agent_type": "default",
    },
    {
        "node": "L9a", "persona": "Feynman", "layer": 9,
        "status_before": "UNDER_REVIEW", "advance_command": "decision",
        "advance_status": "UNDER_REVIEW", "advance_reason": "L9a falsification complete",
        "context_inputs": ["L1", "L7", "L8", "L8.5"],
        "is_parallel": True, "is_execution": False,
        "action_hint": "Hard falsification of results from statistical/logical completeness",
        "agent_type": "default",
    },
    {
        "node": "L9b", "persona": "Darwin", "layer": 9,
        "status_before": "UNDER_REVIEW", "advance_command": None,
        "advance_status": None, "advance_reason": None,
        "context_inputs": ["L1", "L7", "L8", "L8.5"],
        "is_parallel": True, "is_execution": False,
        "action_hint": "Biological interpretation of results",
        "agent_type": "default",
    },
    {
        "node": "L10a", "persona": "Jobs", "layer": 10,
        "status_before": "UNDER_REVIEW", "advance_command": "decision",
        "advance_status": "UNDER_REVIEW", "advance_reason": "Jobs value assessment complete",
        "context_inputs": ["candidate_frontmatter", "L8", "L8.5", "L9a", "L9b"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Assess value, frame manuscript direction",
        "agent_type": "default",
    },
    {
        "node": "L10b", "persona": "Oppenheimer", "layer": 10,
        "status_before": "UNDER_REVIEW", "advance_command": "decision",
        "advance_status": "KEEP", "advance_reason": "",
        "context_inputs": ["L10a", "L8", "L8.5", "L9a", "L9b"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Final decision: KEEP / REVISE / DOWNGRADE / DROP",
        "agent_type": "default",
    },
    {
        "node": "L10c", "persona": "Linnaeus", "layer": 10,
        "status_before": "KEEP", "advance_command": "aggregate-report",
        "advance_status": None, "advance_reason": None,
        "context_inputs": ["ALL"],
        "is_parallel": False, "is_execution": False,
        "action_hint": "Aggregate all deltas into FINAL_REPORT",
        "agent_type": "default",
    },
]

# Map: node_id -> node dict
PRE_RESEARCH_MAP = {
    "L1": {"type": "deep_research", "skill": "academic-research-suite",
           "description": "Search literature for convergent evolution, cardiac co-expression, high heart rate adaptation",
           "queries": [
               "convergent evolution cardiac gene expression high heart rate",
               "co-expression modules WGCNA cross-species heart",
               "molecular convergence bat shrew cardiac adaptation",
               "module eigengene species trait correlation heart rate",
           ]},
    "L4": {"type": "literature_review", "skill": "academic-research-suite",
           "description": "Search methodology papers: WGCNA cross-species, module preservation, convergent transcriptomics",
           "queries": [
               "WGCNA module preservation cross-species Zsummary",
               "module trait correlation WGCNA cardiac tissue",
               "gene set enrichment GSEA ranked kME WGCNA",
               "signed vs unsigned WGCNA network cardiac",
               "module preservation statistics Zsummary medianRank",
           ]},
    "L7": {"type": "code_search", "skill": "github-search",
           "description": "Search GitHub/Bioconductor for WGCNA pipelines, GSEA wrappers, ECM score tools",
           "queries": [
               "WGCNA pipeline R script cross-species module preservation",
               "clusterProfiler GSEA kME ranked gene list R",
               "ECM extracellular matrix score gene set R",
               "WGCNA signed network soft threshold power R",
           ]},
    "L8.5": {"type": "literature_verification", "skill": "academic-research-suite",
             "description": "Search PubMed/EuropePMC for papers that CONFIRM or "
                            "CONTRADICT the actual L7/L8 findings (grounded in the "
                            "real results, not just the question)",
             "queries": [
                 "<gene/module from L7 key_results> cardiac expression",
                 "<phenotype from candidate> convergent evolution heart",
                 "<method from L6/L7> validation cross-species",
             ]},
}

NODE_MAP = {n["node"]: n for n in DAG_NODES}

# Per-node access to the external KNOWLEDGE BASE (09_Literature_Database/).
# Declared explicitly (not derivable -- it is a policy choice):
#   - read-write: the literature SEARCHERS (they find + add papers).
#   - read:       L0 (catalogs/declares the KB) + the review/decision/report nodes
#                 (L9/L10) that CONSULT accumulated literature to falsify/interpret/
#                 value/decide/report. They cite existing entries; they do NOT add.
#   - none:       everyone else -- they get literature only via embedded deltas
#                 (pre-research summaries + the L8.5 papers), never direct DB access.
KNOWLEDGE_BASE_ACCESS = {
    "L1": "read-write", "L4": "read-write", "L8.5": "read-write",
    "L0": "read",
    "L9a": "read", "L9b": "read",
    "L10a": "read", "L10b": "read", "L10c": "read",
}

# Attach the declared info-flow policy to each node (surfaced by next-step and
# the assemble-context manifest; ENFORCEMENT is the orchestrator's job, not the
# script's). Derived where possible so they cannot drift from the DAG:
#   - tools_policy: only the execution node (Turing/L7) gets filesystem access,
#     and only inside its workspace ("workspace-fs"); every cognitive node is
#     "no-fs" (its entire input is the embedded context text).
#   - everos_read_scopes: mirror the node's context_inputs so EverOS routing can
#     never grant a node a memory channel the delta DAG doesn't already grant.
#     "<id>" is substituted with the project id when a manifest is built.
#   - knowledge_base: per the explicit KNOWLEDGE_BASE_ACCESS policy above.
for _n in DAG_NODES:
    _n.setdefault("tools_policy",
                  "workspace-fs" if _n.get("is_execution") else "no-fs")
    _n.setdefault("knowledge_base",
                  KNOWLEDGE_BASE_ACCESS.get(_n["node"], "none"))
    if "everos_read_scopes" not in _n:
        _scopes = ["global_methods", "projects/<id>/public"]
        for _inp in _n["context_inputs"]:
            if _inp == "candidate_frontmatter":
                continue
            if _inp == "ALL":
                _scopes.append("projects/<id>/node_outputs/*")
                continue
            _scopes.append(f"projects/<id>/node_outputs/{_inp}")
        if _n.get("is_execution"):
            _scopes.append(f"projects/<id>/execution/{_n['node']}")
        _n["everos_read_scopes"] = _scopes
del _n

# Order of single-path nodes (L9a and L9b are parallel, listed together)
DAG_SEQUENCE = ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L8.5",
                "L9_parallel", "L10a", "L10b", "L10c"]

# Map: node_id -> layer template filename on disk. The files are named
# descriptively (e.g. L7_execution.md), not L7.md, so next-step must map the
# node id to the real filename or the orchestrator gets a dead path.
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

# Map: persona -> persona template filename on disk (numbered 01..10 in AGENTS
# order, e.g. 02_Einstein.md). next-step must map to the real filename.
PERSONA_TEMPLATE_FILE = {p: f"{i + 1:02d}_{p}.md" for i, p in enumerate(AGENTS)}


def _layer_template_path(node_id):
    """Relative path to a node's layer template (real on-disk filename)."""
    fname = LAYER_TEMPLATE_FILE.get(node_id, f"{node_id}.md")
    return f"templates/v03_layers/{fname}"


def _persona_template_path(persona):
    """Relative path to a persona's template (real on-disk filename)."""
    fname = PERSONA_TEMPLATE_FILE.get(persona, f"{persona}.md")
    return f"templates/v03_personas/{fname}"

# --- delta schemas ----------------------------------------------------------
# Each persona outputs a structured delta JSON. Schemas are Python dicts
# checked by a simple validator (no external JSON Schema library).

DELTA_SCHEMAS = {
    "L0_linnaeus": {
        "skills_found": list, "skills_gaps": list, "input_verified": dict,
        "environment": dict, "skill_use_plan": list, "forbidden_shortcuts": list
    },
    "L1_einstein": {
        "hypotheses": [{"id": str, "text": str, "testable": bool, "rationale": str}],
        "key_uncertainty": str, "primary_hypothesis": str
    },
    "L2_feynman": {
        "attacks": [{"hypothesis_id": str, "severity": str, "text": str}],
        "confounders": [{"name": str, "severity": str, "text": str}],
        "diagnostic_tests": [{"name": str, "text": str}], "verdict": str
    },
    "L3_oppenheimer": {
        "selected": list, "rejected": list, "reason": str, "route_to": str
    },
    "L4_fisher": {
        "strategies": [{"id": str, "name": str, "steps": list, "samples": int, "status": str}],
        "recommended": str,
        "scripts_needed": [{"name": str, "purpose": str, "status": str}],
        "key_decisions": list
    },
    "L5_tukey": {
        "attacks": [{"target": str, "severity": str, "text": str}],
        "qc_checkpoints": [{"name": str, "text": str}],
        "failure_stop_rules": [{"name": str, "text": str}]
    },
    "L6_oppenheimer": {
        "approved_strategy": str, "modifications": list, "reason": str,
        "analysis_plan": {"scripts": list, "parameters": dict, "outputs": list}
    },
    "L7_turing": {
        "scripts_run": [{"name": str, "exit_code": int, "output_files": list}],
        "key_results": dict, "warnings": list, "failures": list
    },
    "L8_curie": {
        "evidence_verified": [{"file": str, "check": str, "result": str}],
        "evidence_level": str, "caveats": list
    },
    "L8.5_curie": {
        "searched_keywords": list,
        "papers": [{"pmid": str, "title": str, "abstract": str, "comparison": str, "relevance": str}],
        "summary": str
    },
    "L9a_feynman": {
        "falsification_risks": [{"name": str, "severity": str, "resolvable": bool, "text": str}],
        "survives": list, "falsified": list
    },
    "L9b_darwin": {
        "module_interpretations": [{"module": str, "meaning": str, "genes": list, "evidence": str}],
        "convergent_evolution": str, "limitations": list
    },
    "L10a_jobs": {
        "value_assessment": str, "headline": str,
        "publishable_now": list, "needs_more_work": list,
        "manuscript_framing": str
    },
    "L10b_oppenheimer": {
        "decision": str, "evidence_level": str, "reason": str, "next_steps": list
    },
}

# Map: delta key -> persona name (for file path resolution)
DELTA_PERSONA = {
    "L0_linnaeus": "Linnaeus", "L1_einstein": "Einstein",
    "L2_feynman": "Feynman", "L3_oppenheimer": "Oppenheimer",
    "L4_fisher": "Fisher", "L5_tukey": "Tukey",
    "L6_oppenheimer": "Oppenheimer", "L7_turing": "Turing",
    "L8_curie": "Curie", "L8.5_curie": "Curie", "L9a_feynman": "Feynman",
    "L9b_darwin": "Darwin", "L10a_jobs": "Jobs",
    "L10b_oppenheimer": "Oppenheimer",
}

# DAG order for reading deltas in aggregate-report
DELTA_DAG_ORDER = [
    "L0_linnaeus", "L1_einstein", "L2_feynman", "L3_oppenheimer",
    "L4_fisher", "L5_tukey", "L6_oppenheimer", "L7_turing",
    "L8_curie", "L8.5_curie", "L9a_feynman", "L9b_darwin",
    "L10a_jobs", "L10b_oppenheimer",
]

FINAL_STATUSES = {"KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED"}

PREFLIGHT_FILES = [
    "skill_use_plan.md", "input_manifest.md",
    "output_manifest.md", "forbidden_shortcuts.md",
]

# --- L0 dependency gate -----------------------------------------------------
# Runtime dependencies the L0 preflight HARD-CHECKS. A missing REQUIRED
# dependency STOPS the loop (preflight exits non-zero) -- it must NEVER be
# skipped. Project-specific deps are declared in 00_Preflight/dependencies.md
# and are checked the same way.
REQUIRED_DEPENDENCIES = [
    {"kind": "python", "name": "yaml", "label": "PyYAML", "pip": "PyYAML",
     "needed_for": "manage_literature_db.py (growable literature DB; L1/L4/L8.5)"},
    {"kind": "skill", "name": "academic-research-suite", "label": "Academic Research skill",
     "attest_env": "RLR_SKILL_ACADEMIC_RESEARCH",
     "needed_for": "real literature search in pre-research (L1/L4) + L8.5 verification"},
    {"kind": "port", "name": "zotero", "label": "Zotero", "addr": "127.0.0.1:23119",
     "attest_env": "RLR_ZOTERO",
     "needed_for": "reference manager / citation source for the literature DB"},
    {"kind": "env", "name": "obsidian", "label": "Obsidian vault", "env": "OBSIDIAN_VAULT",
     "check_path": True, "attest_env": "RLR_OBSIDIAN",
     "needed_for": "end-of-round human-readable sync (sync_to_obsidian.py)"},
]


def _port_open(host, port, timeout=0.6):
    import socket
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _dep_present(dep):
    """True if a dependency is satisfied. A non-empty `attest_env` env var ALWAYS
    satisfies it -- the fail-closed escape hatch for things Python cannot
    introspect (Claude skills, GUI apps like Zotero/Obsidian)."""
    import os
    ae = dep.get("attest_env")
    if ae and os.environ.get(ae, "").strip():
        return True
    kind, name = dep.get("kind"), dep.get("name", "")
    if kind == "python":
        import importlib.util
        return importlib.util.find_spec(name) is not None
    if kind == "command":
        return shutil.which(name) is not None
    if kind == "env":
        v = os.environ.get(dep.get("env", name), "").strip()
        return bool(v) and (not dep.get("check_path") or Path(v).expanduser().exists())
    if kind == "port":
        host, _, port = (dep.get("addr") or "").partition(":")
        return bool(port) and _port_open(host or "127.0.0.1", port)
    if kind == "skill":
        return False  # only satisfiable via attest_env (handled above): fail closed
    return False


def _dep_fix_hint(dep):
    kind, ae = dep.get("kind"), dep.get("attest_env")
    if kind == "python":
        return f"pip install {dep.get('pip', dep['name'])}"
    if kind == "command":
        return f"install / put on PATH: {dep['name']}"
    if kind == "skill":
        return f"enable {dep.get('label', dep['name'])}, then attest: set {ae}=1"
    if kind == "port":
        return (f"start {dep.get('label', dep['name'])} (connector {dep.get('addr')})"
                + (f", or set {ae}=1" if ae else ""))
    if kind == "env":
        return (f"set ${dep.get('env')}" + (" to an existing path" if dep.get("check_path") else "")
                + (f", or set {ae}=1" if ae else ""))
    return "(see 00_Preflight/dependencies.md)"


def _parse_declared_deps(project_dir):
    """Extra required deps declared in 00_Preflight/dependencies.md: lines of the
    form '- python: NAME', '- command: NAME', or '- env: VAR' under a
    '## Required' heading."""
    f = Path(project_dir) / "00_Preflight" / "dependencies.md"
    deps, required = [], False
    if not f.exists():
        return deps
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("##"):
            required = "required" in s.lower()
            continue
        if required:
            m = re.match(r"-\s*(python|command|env):\s*([^\s(]+)", s, re.I)
            if m:
                deps.append({"kind": m.group(1).lower(), "name": m.group(2),
                             "needed_for": "declared in dependencies.md"})
    return deps


def _check_dependencies(project_dir=None):
    """Check framework + project-declared dependencies. Returns (ok, missing),
    each a list of dep dicts with an added 'present' flag."""
    items = [dict(d) for d in REQUIRED_DEPENDENCIES]
    if project_dir:
        seen = {(d["kind"], d["name"]) for d in items}
        for d in _parse_declared_deps(project_dir):
            if (d["kind"], d["name"]) not in seen:
                items.append(d)
    ok, missing = [], []
    for d in items:
        d = dict(d)
        d["present"] = _dep_present(d)
        (ok if d["present"] else missing).append(d)
    return ok, missing


def _knowledge_base_md(name):
    """L0 declares the external knowledge base exists + the per-node access policy."""
    rows = "\n".join(f"| {n['node']:5} | {n['persona']:11} | {n.get('knowledge_base','none')} |"
                     for n in DAG_NODES)
    return f"""---
project_name: {_yaml_value(name)}
preflight_file: knowledge_base.md
owner: Linnaeus
created_at: {_yaml_value(_now())}
---

# External Knowledge Base -- {name}  (declared at L0)

This project has a **growable literature database** at `09_Literature_Database/`
(managed by `manage_literature_db.py`; papers are cited via Obsidian wikilinks
`[[09_Literature_Database/<citekey>|Title]]` and reused across rounds).

## Per-node access policy (HARD rule)

The `knowledge_base` permission is declared per node, surfaced in the
`assemble-context` isolation directive, and recorded in every context manifest
(audit). The orchestrator enforces it.

- **read-write** -- may search literature AND add papers (`manage_literature_db.py add`).
- **read** -- may READ the DB to cite existing papers; may NOT add.
- **none** -- NO direct DB access; gets literature only via embedded deltas
  (pre-research summaries + the L8.5 papers delta), never by touching the DB.

| node  | persona     | knowledge_base |
|-------|-------------|----------------|
{rows}

Rule: only the literature SEARCHERS (L1 / L4 / L8.5) may write; L0 and the
review/decision/report nodes (L9 / L10) may read; all other nodes have none.
"""


def _dependencies_md(name):
    blocks = []
    for d in REQUIRED_DEPENDENCIES:
        blocks.append(f"- {d['kind']}: {d['name']}  ({d.get('label', d['name'])})")
        blocks.append(f"    needed for: {d.get('needed_for','')}")
        blocks.append(f"    satisfy:    {_dep_fix_hint(d)}")
    req = "\n".join(blocks)
    return f"""---
project_name: {_yaml_value(name)}
preflight_file: dependencies.md
owner: Linnaeus
created_at: {_yaml_value(_now())}
---

# Dependencies -- {name}  (L0 gate)

> Linnaeus L0 HARD-CHECKS every required dependency below. If any is MISSING,
> `preflight` STOPS (non-zero exit) and the loop MUST NOT proceed past L0. Do not
> skip. Satisfy it, then re-run `preflight` (or `check-deps`).
>
> Things Python cannot introspect (Claude skills, GUI apps) are FAIL-CLOSED: they
> are only considered present if their `attest_env` env var is set (or auto-detected,
> e.g. Zotero's connector port / the Obsidian vault path). Set the env vars in your
> shell/profile to attest availability.
>
> Declare extra deps as lines: `- python: <module>`, `- command: <exe>`, `- env: <VAR>`.

## Required (framework)

{req}

## Required (project)

_Add project-specific runtime deps here as checkable lines (only listed lines are
checked). Example for R at L7:_  `- command: Rscript`

## Notes

- R packages (WGCNA, clusterProfiler, ...) are verified by the R scripts at L7
  (.libPaths + requireNamespace), not by L0.
- Attestation env vars: RLR_SKILL_ACADEMIC_RESEARCH, RLR_ZOTERO, RLR_OBSIDIAN
  (set to 1 to attest), and OBSIDIAN_VAULT (path to your vault).
"""

LAYERS = [
    ("L0",  "Skill & Memory Preflight",            "Linnaeus"),
    ("L1",  "Idea Divergence",                      "Einstein"),
    ("L2",  "Idea Falsification",                   "Feynman"),
    ("L3",  "Candidate Triage Decision",            "Oppenheimer"),
    ("L4",  "Method Brainstorm",                    "Fisher"),
    ("L5",  "Method Falsification / Skill Match",   "Tukey"),
    ("L6",  "Analysis Plan Decision",               "Oppenheimer"),
    ("L7",  "Execution",                            "Turing"),
    ("L8",  "Evidence Audit",                       "Curie"),
    ("L9a", "Result Falsification",                 "Feynman"),
    ("L9b", "Biology Interpretation",               "Darwin"),
    ("L10a","Value Assessment",                     "Jobs"),
    ("L10b","Final Decision",                      "Oppenheimer"),
    ("L10c","Aggregation & Report",                "Linnaeus"),
]

# --- small helpers ----------------------------------------------------------

def _now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def _stamp():
    return _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")

def _date():
    return _dt.datetime.now().strftime("%Y-%m-%d")

def _slug(s):
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"^_+|_+$", "", s) or "candidate"

def _candidate_file(project_dir, cand_id):
    return Path(project_dir) / "01_Candidates" / f"{cand_id}.md"

def _delta_file(project_dir, delta_key):
    """Return path to a delta JSON file given its key (e.g. L1_einstein)."""
    persona = DELTA_PERSONA.get(delta_key, "")
    if not persona:
        return None
    return Path(project_dir) / "02_Agent_Notes" / persona / f"{delta_key}_delta.json"

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
    """Canonical path for a node's pre-research summary (v0.4). Written by
    `pre-research` (by the orchestrator) and injected by `assemble-context`."""
    return (Path(project_dir) / "02_Agent_Notes" / "_pre_research"
            / f"{node}_research.md")

def _input_alias(source_input):
    """Path-free alias for a source_input description: directory parts of any
    path-like token are dropped, keeping only file/basename + free text. Lets
    cognitive nodes see *what* the inputs are without the raw filesystem layout.
    """
    if not source_input:
        return ""
    return re.sub(r"\S*[\\/]\S*",
                  lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1],
                  source_input)

def _everos_scopes_for(node_info, project_id):
    """Concrete EverOS read scopes for a node (declared, not enforced here)."""
    return [s.replace("<id>", project_id)
            for s in node_info.get("everos_read_scopes", [])]

def _next_seq(project_dir, prefix):
    d = Path(project_dir) / "05_Decision_Log"
    n = 0
    if d.exists():
        for f in d.glob(f"{prefix}[0-9]*.md"):
            m = re.match(rf"^{re.escape(prefix)}(\d+)", f.stem)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1

def _yaml_value(v):
    """Render a scalar value as a safe single-line YAML string."""
    if v is None:
        v = ""
    v = str(v).replace("\n", " ").strip()
    if v == "" or re.search(r"[:#{}\[\],&*!|>'\"%@`]|^-| $", v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v

def _load_yaml_front(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]
    out = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip()
            if len(v) >= 2 and v[0] == chr(34) and v[-1] == chr(34):
                v = v[1:-1].replace(chr(92)+chr(34), chr(34)).replace(chr(92)*2, chr(92))
            out[k.strip()] = v
    return out

def _save_yaml_front(path, frontmatter):
    """Write a YAML frontmatter block to *path*, replacing any existing one."""
    lines = ["---"]
    for k, v in frontmatter.items():
        lines.append(f"{k}: {_yaml_value(v)}")
    lines.append("---")
    lines.append("")
    fm_text = "\n".join(lines)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text.startswith("---"):
        end = text.find("\n---", 4)
        if end >= 0:
            body = text[end + 4:]
        else:
            body = ""
        text = fm_text + body.lstrip("\n")
    else:
        text = fm_text + text
    path.write_text(text, encoding="utf-8")

def _replace_field(path, key, value):
    text = path.read_text(encoding="utf-8")
    # Fail loud if the file has no YAML frontmatter: otherwise neither the regex
    # nor the "---\n" fallback below matches, and the field update is silently
    # dropped (the candidate keeps a stale status with no error). A missing
    # frontmatter means the file is corrupted -- surface it.
    if not text.startswith("---") or text.find("\n---", 4) < 0:
        raise RLRError(
            f"{path}: missing YAML frontmatter delimiters; refusing to update "
            f"'{key}' (file may be corrupted or truncated)")
    pat = re.compile(rf"^{re.escape(key)}: .*$", re.M)
    new = f"{key}: {_yaml_value(value)}"
    if pat.search(text):
        text = pat.sub(lambda m: new, text, count=1)
    else:
        text = text.replace("---\n", "---\n" + new + "\n", 1)
    path.write_text(text, encoding="utf-8")

def strip_candidate_to_frontmatter(candidate_path, include_source_path=False):
    """Read a candidate .md, return only frontmatter dict (not body).

    Returns dict with: candidate_id, title, question, claim, current_status.
    The body is never returned -- it may contain downstream info that must
    stay invisible to subagents (Path B isolation).
    """
    fm = _load_yaml_front(Path(candidate_path))
    keep = {}
    for k in ("candidate_id", "title", "question", "claim",
              "current_status", "current_owner"):
        if k in fm:
            keep[k] = fm[k]
    # Input visibility (problem 3): cognitive nodes see only the path-free
    # alias; the input-verification node (L0) sees the real source_input path.
    if include_source_path and "source_input" in fm:
        keep["source_input"] = fm["source_input"]
    if fm.get("input_alias"):
        keep["input_alias"] = fm["input_alias"]
    elif not include_source_path and "source_input" in fm:
        keep["input_alias"] = _input_alias(fm["source_input"])  # back-compat
    return keep

def _require_status(fm, cand_id, expected):
    cur = fm.get("current_status", "?")
    if cur != expected:
        print(f"ERROR: {cand_id} is {cur}, expected {expected} for this command.",
              file=sys.stderr)
        return False
    return True

def _set_status(project_dir, cand_id, new_status, owner=None):
    cf = _candidate_file(project_dir, cand_id)
    _replace_field(cf, "current_status", new_status)
    if owner:
        _replace_field(cf, "current_owner", owner)
    _replace_field(cf, "updated_at", _now())

def _append_decision(project_dir, cand_id, frm, to, reason, route_to="",
                     agent="Oppenheimer", kind="decision"):
    seq = _next_seq(project_dir, "D")
    body = _decision_log_template(seq, cand_id, frm, to, reason, route_to,
                                  agent=agent, kind=kind)
    f = Path(project_dir) / "05_Decision_Log" / f"D{seq:04d}_{cand_id}.md"
    f.write_text(body, encoding="utf-8")
    cf = _candidate_file(project_dir, cand_id)
    if cf.exists():
        line = f"- [{_now()}] ({kind}/{agent}) {frm} -> {to}: {reason}"
        if route_to:
            line += f" | next: {route_to}"
        text = cf.read_text(encoding="utf-8")
        text = text.replace("## Decision History\n",
                            "## Decision History\n" + line + "\n", 1)
        cf.write_text(text, encoding="utf-8")
    return seq

def _mkdirs(project_dir):
    """v0.4 directory layout (same structure as v0.2)."""
    p = Path(project_dir)
    for sub in ["00_Preflight", "01_Candidates", "03_Handoffs",
                "04_Analysis_Outputs", "05_Decision_Log",
                "06_Manuscript_Direction", "07_Obsidian_Sync",
                "08_Audit", "99_Archive"]:
        (p / sub).mkdir(parents=True, exist_ok=True)
    for agent in AGENTS:
        (p / "02_Agent_Notes" / agent).mkdir(parents=True, exist_ok=True)
    return p

def _fmt_list(lst):
    if not lst:
        return "_none_"
    if isinstance(lst, list):
        return ", ".join(str(x) for x in lst)
    return str(lst)

def _fmt_dict(d):
    if not d:
        return "_none_"
    if isinstance(d, dict):
        return "; ".join(f"{k}={v}" for k, v in d.items())
    return str(d)

def _empty_value_for_schema(v):
    """Create an empty default matching a delta schema field type."""
    if v is list:
        return []
    if v is dict:
        return {}
    if v is str:
        return ""
    if v is bool:
        return False
    if v is int:
        return 0
    if isinstance(v, list):
        return []
    if isinstance(v, dict):
        return {}
    return None

def _validate_delta(schema, data, path=""):
    """Recursively validate *data* against a delta *schema*, returning errors.

    A schema node may be:
      - a bare type (list/dict/str/bool/int): isinstance check only;
      - a list literal [elem_schema]: data must be a list and every element is
        validated against elem_schema (e.g. [{"id": str}] => list of objects);
      - a dict literal {k: subschema}: data must be a dict; every declared key
        is required (extra keys allowed) and validated against its subschema.

    This is what lets the validator reject hypotheses=[{"foo": 1}] (element
    missing the required id/text) instead of only checking the top-level type.
    """
    loc = path or "<root>"
    if isinstance(schema, dict):
        if not isinstance(data, dict):
            return [f"{loc}: expected object, got {type(data).__name__}"]
        errors = []
        for k, sub in schema.items():
            kp = f"{path}.{k}" if path else k
            if k not in data:
                errors.append(f"missing required key: {kp}")
            else:
                errors += _validate_delta(sub, data[k], kp)
        return errors
    if isinstance(schema, list):
        if not isinstance(data, list):
            return [f"{loc}: expected list, got {type(data).__name__}"]
        errors = []
        if schema:  # typed element schema -> validate each element
            elem = schema[0]
            for i, item in enumerate(data):
                errors += _validate_delta(elem, item, f"{path}[{i}]")
        return errors
    if schema is list and not isinstance(data, list):
        return [f"{loc}: expected list, got {type(data).__name__}"]
    if schema is dict and not isinstance(data, dict):
        return [f"{loc}: expected dict, got {type(data).__name__}"]
    if schema is bool and not isinstance(data, bool):
        return [f"{loc}: expected bool, got {type(data).__name__}"]
    if schema is int and (not isinstance(data, int) or isinstance(data, bool)):
        return [f"{loc}: expected int, got {type(data).__name__}"]
    if schema is str and not isinstance(data, str):
        return [f"{loc}: expected str, got {type(data).__name__}"]
    return []

# --- templates --------------------------------------------------------------

def _candidate_template_v03(cand_id, title, source_input, question, claim,
                            input_alias=""):
    claim_or_question = f"{question} | {claim}"
    alias = input_alias or _input_alias(source_input)
    return f"""---
candidate_id: {_yaml_value(cand_id)}
title: {_yaml_value(title)}
question: {_yaml_value(question)}
claim: {_yaml_value(claim)}
hypothesis: ""
source_input: {_yaml_value(source_input)}
input_alias: {_yaml_value(alias)}
current_status: NEW
current_owner: Linnaeus
selected_method: ""
approved_analysis_plan: ""
evidence_level: ""
final_decision: ""
claim_or_question: {_yaml_value(claim_or_question)}
created_at: {_yaml_value(_now())}
updated_at: {_yaml_value(_now())}
---

# {title}

## Question

{question}

## Claim

{claim}

## Source Input

{source_input}

## Idea Summary (L1 Einstein / L2 Feynman)

_append via delta JSON (L1_einstein_delta, L2_feynman_delta)_

## Method Summary (L4 Fisher / L5 Tukey)

_append via delta JSON (L4_fisher_delta, L5_tukey_delta)_

## Evidence Summary (L8 Curie)

_append via delta JSON (L8_curie_delta); level = STRONG | MODERATE | WEAK | INVALID_

## Weakness Summary (L2 / L9a Feynman)

_append via delta JSON_

## Biology Summary (L9b Darwin)

_append via delta JSON (L9b_darwin_delta)_

## Value / Manuscript (L10a Jobs)

_append via delta JSON (L10a_jobs_delta)_

## Analysis Needed

_filled by Oppenheimer when approving a plan_

## Decision History

_append-only log of status changes (Oppenheimer only)_

## Latest Handoff

_updated on each route_

## Final Decision

_filled only when a terminal status is reached_
"""

def _index_template_v03(name, topic):
    layers = "\n".join(f"- **{lid} {ltitle}** - {owner}"
                       for lid, ltitle, owner in LAYERS)
    personas = ", ".join(f"{p} | {PERSONA_TITLE[p]}" for p in AGENTS)
    return f"""---
project_name: {_yaml_value(name)}
topic: {_yaml_value(topic)}
version: {_yaml_value(__version__)}
framework: gated-multi-loop-council-v03
created_at: {_yaml_value(_now())}
---

# {name} - Research Loop Room v0.4 Index

Topic: {topic}

## Council (10 personas)

{personas}

## DAG Topology (14 nodes L0-L10c)

{layers}

## Statuses

{", ".join(VALID_STATUSES)}

## Hard Invariants

- Only **Oppenheimer** changes candidate status.
- Only **Turing** executes code, and only after the Execution Gate passes.
- Execution Gate requires: `00_Preflight/skill_use_plan.md`,
  `00_Preflight/input_manifest.md`, and an approved plan (status METHOD_APPROVED).
- Each persona runs as an isolated subagent (v0.4).
- State flows between subagents via delta JSON files only.

## DAG Node Flow

L0 Linnaeus -> L1 Einstein -> L2 Feynman -> L3 Oppenheimer
-> L4 Fisher -> L5 Tukey -> L6 Oppenheimer -> L7 Turing
-> L8 Curie -> L9a Feynman || L9b Darwin -> L10a Jobs
-> L10b Oppenheimer -> L10c Linnaeus (FINAL_REPORT)

## Boot Gate (00_Preflight/)

Run `preflight` before any candidate work.

## Obsidian

Run `obsidian-sync` to copy delta JSON + FINAL_REPORT to vault.
"""

def _handoff_template(hid, cand_id, frm, to, reason, action,
                      inputs, constraints, expected, stop):
    return f"""---
handoff_id: {_yaml_value(hid)}
candidate_id: {_yaml_value(cand_id)}
from_agent: {_yaml_value(frm)}
to_agent: {_yaml_value(to)}
reason: {_yaml_value(reason)}
required_action: {_yaml_value(action)}
input_files: {_yaml_value(inputs)}
constraints: {_yaml_value(constraints)}
expected_output: {_yaml_value(expected)}
stop_condition: {_yaml_value(stop)}
created_at: {_yaml_value(_now())}
---

# Handoff {hid}

- **From:** {frm} ({PERSONA_TITLE.get(frm, "?")})
- **To:** {to} ({PERSONA_TITLE.get(to, "?")})
- **Candidate:** {cand_id}
- **Reason:** {reason}

## Required Action

{action}

## Input Files

{inputs or "_none_"}

## Constraints

{constraints or "_none_"}

## Expected Output

{expected or "_none_"}

## Stop Condition

{stop or "_none_"}
"""

def _decision_log_template(seq, cand_id, frm_status, to_status, reason,
                           route_to, agent="Oppenheimer", kind="decision"):
    return f"""---
log_id: {_yaml_value("D" + f"{seq:04d}")}
candidate_id: {_yaml_value(cand_id)}
kind: {_yaml_value(kind)}
decided_by: {_yaml_value(agent)}
from_status: {_yaml_value(frm_status)}
to_status: {_yaml_value(to_status)}
reason: {_yaml_value(reason)}
route_to: {_yaml_value(route_to or "")}
created_at: {_yaml_value(_now())}
---

# Decision D{seq:04d} - {cand_id}

- **Kind:** {kind}
- **Decided by:** {agent}
- **From:** {frm_status}
- **To:** {to_status}
- **Reason:** {reason}
- **Next route:** {route_to or "_none (terminal or pending)_"}
"""

def _note_template(project_name, cand_id, agent, text):
    return f"""---
project: {_yaml_value(project_name)}
candidate_id: {_yaml_value(cand_id)}
agent: {_yaml_value(agent)}
title: {_yaml_value(PERSONA_TITLE.get(agent, ""))}
created_at: {_yaml_value(_now())}
---

# {agent} | {PERSONA_TITLE.get(agent, "")} - Note on {cand_id}

{text}
"""

def _preflight_template(name, fname):
    title = fname.replace(".md", "").replace("_", " ").title()
    common_head = f"""---
project_name: {_yaml_value(name)}
preflight_file: {_yaml_value(fname)}
owner: Linnaeus
created_at: {_yaml_value(_now())}
---

# {title} - {name}

> Maintained by **Linnaeus | Catalog Master** (L0 boot gate). Linnaeus organizes
> and registers; he never interprets data or runs code.
"""
    if fname == "skill_use_plan.md":
        body = """
## Available skills (inventory)

_List local/project skills discovered (AGENTS.md, skills inventory, plugins)._

| skill | source | relevance to this project | will use? |
|-------|--------|----------------------------|-----------|
| _e.g. single-cell-rna-qc_ | local | QC of scRNA inputs | yes |

## Skill-use plan per layer

- **L1 Idea (Einstein):** academic/deep-research skills if available.
- **L4 Method (Fisher):** reuse existing analysis skills/code patterns.
- **L7 Execution (Turing):** which skill/code pattern executes the plan.
- **L9 Biology (Darwin):** biological database skills.

## Reuse-first rule

Do NOT build from scratch where a relevant skill or prior code pattern exists.
"""
    elif fname == "input_manifest.md":
        body = """
## Input classification

Classify every input as: **primary**, **fallback**, **reference-only**, or
**forbidden**. Execution may only consume primary/fallback inputs.

| file / path | role | classification | notes |
|-------------|------|----------------|-------|
| _e.g. results/length_scaled_counts.csv_ | expression matrix | primary | length-scaled |

## Required inputs for execution

_List the inputs the approved plan must have before the Execution Gate opens._
"""
    elif fname == "output_manifest.md":
        body = """
## Declared outputs

Outputs live in project results dirs; Obsidian links to them (no duplication).

| output | produced by (layer/persona) | path | status |
|--------|-----------------------------|------|--------|
| _e.g. module_assignment.csv_ | L7 Turing | 04_Analysis_Outputs/... | planned |
"""
    else:  # forbidden_shortcuts.md
        body = """
## Forbidden shortcuts (anti-patterns from the first WGCNA loop)

1. Starting analysis before skills inventory is checked (L0).
2. Skipping Obsidian/project memory initialization.
3. Jumping into code before L6 analysis plan is approved.
4. Building scripts from scratch when a skill/code pattern exists.
5. Ad-hoc debugging / infinite retry loops (max 2 retries per method).
6. Treating literature plausibility as data support.
7. Monolithic scripts for complex analyses (split into modules).
8. Changing candidate status outside Oppenheimer.
9. Running code outside Turing.
10. KEEP without an Evidence audit (Curie).
"""
    return common_head + body

# --- Phase 1 commands: next-step, assemble-context, emit-delta --------------

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
                    "advance_command": "aggregate-report",
                    "template_path": _layer_template_path("L10c"),
                    "persona_template_path": _persona_template_path(node_info["persona"]),
                    "tools_policy": node_info.get("tools_policy"),
                    "everos_read_scopes": _everos_scopes_for(node_info, project_dir.name),
                    "knowledge_base": node_info.get("knowledge_base"),
                }
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
                l9a = _delta_file(project_dir, "L9a_feynman")
                l9b = _delta_file(project_dir, "L9b_darwin")
                if l9a and l9a.exists() and l9b and l9b.exists():
                    continue
                node_id = "L9_parallel"
                break
            ni = NODE_MAP.get(cand_node)
            if ni:
                delta_key = f"{cand_node}_{ni['persona'].lower()}"
                df = _delta_file(project_dir, delta_key)
                if df and df.exists():
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
        l7 = _delta_file(project_dir, "L7_turing")
        delta_done = bool(l7 and l7.exists())
        result["advance_command"] = "decision"
        result["advance_status"] = "EXECUTED"
        result["advance_reason"] = ("Turing execution complete, mark EXECUTED "
                                    "and route to Curie")
        result["action_hint"] = (
            "L7 delta present; advance to EXECUTED (route to Curie)"
            if delta_done else
            "Turing: execute approved scripts in the controlled workspace, "
            "emit the L7 delta, then advance to EXECUTED")
    print(json.dumps(result, indent=2))
    return 0

def cmd_pre_research(args):
    """Output a pre-research prompt for the orchestrator to execute before a node.

    For L1: deep research (academic-research-suite) on the scientific question.
    For L4: literature review on methods used in similar studies.
    For L7: code search on GitHub/Bioconductor for existing pipelines.

    The orchestrator runs the research, saves results to
    02_Agent_Notes/_pre_research/<node>_research.md, then proceeds.
    """
    project_dir = Path(args.project_dir)
    node = args.node

    research_config = PRE_RESEARCH_MAP.get(node)
    if research_config is None:
        print(f"ERROR: no pre-research defined for node {node}", file=sys.stderr)
        return 2

    research_type = research_config["type"]
    queries = research_config["queries"]

    # Ground the research in THIS candidate's question/claim so it generalizes
    # beyond the seed queries (which are domain examples to adapt, not fixed).
    cf = _candidate_file(project_dir, args.cand_id)
    fm = _load_yaml_front(cf) if cf.exists() else {}
    question = fm.get("question", "")
    claim = fm.get("claim", "")
    title = fm.get("title", args.cand_id)
    round_id = 1
    try:
        round_id = int(fm.get("round_id", 1))
    except Exception:
        pass

    if getattr(args, "output_dir", None):
        output_file = Path(args.output_dir) / f"{node}_research.md"
    else:
        output_file = _pre_research_file(project_dir, node)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    focus = research_config.get("description", "")
    grounding = (f"## This study\n"
                 f"- Title: {title}\n"
                 f"- Question: {question}\n"
                 f"- Claim: {claim}\n"
                 f"- Research focus for this step: {focus}\n\n"
                 f"Adapt the seed queries below to THIS question/claim and the "
                 f"actual data; they are domain examples, not a fixed list.\n")

    if research_type == "deep_research":
        prompt = f"""# Pre-Research: Deep Literature Search (before {node})

You MUST run this BEFORE generating the {node} delta.
This is Round {round_id} of the research loop.

{grounding}

## Core Requirements:
1. **CRITICAL**: You MUST use the `academic-research-suite` skill (which includes literature search tools like PubMed/bioRxiv/OpenAlex/Tavily) to perform a real-literature review.
2. **Database Verification & Reuse**:
   - First, scan the literature database directory `{project_dir.as_posix()}/09_Literature_Database` (if it exists) to see what papers have been reviewed in previous rounds.
   - If there are relevant papers, read them and incorporate/expand on their findings.
   - Search the web/academic databases for new papers to answer the queries and expand our understanding.
3. **Database Registration**:
   - For every new paper you find and select, you MUST add it to the growable literature database by running:
     `python manage_literature_db.py add {project_dir.as_posix()} --round {round_id} --json-data "<JSON_STRING>"`
   - Ensure the `<JSON_STRING>` is a single-line valid JSON string. Escape quotes properly. It must contain the following keys:
     - "doi": string (or empty)
     - "title": string
     - "authors": string (or list of strings)
     - "journal": string
     - "year": integer/string
     - "core_arguments": list of strings (key findings or arguments)
     - "evidence_level": "STRONG", "MODERATE", or "WEAK"
     - "tags": list of strings
     - "summary": string (relevance, methods, results summary)
     - "url": string (or empty)

Use the academic-research-suite / search tools to query (seed queries):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Write a structured summary to: {output_file.as_posix()}

Format of {output_file.as_posix()}:
IMPORTANT: Cite papers using Obsidian Wikilinks pointing to the literature database files (e.g., `[[09_Literature_Database/citekey|Paper Title]]` where `citekey` is the filename without `.md`).

## Key Findings
- Finding 1 (citing [[09_Literature_Database/citekey|Paper Title]], Year)
- Finding 2 (citing [[09_Literature_Database/citekey|Paper Title]], Year)

## Methods Used in Literature
- Method 1
- Method 2

## Gaps Our Study Addresses
- Gap 1
- Gap 2

This summary will be injected into the {node} assemble-context as additional input.
"""
    elif research_type == "literature_review":
        prompt = f"""# Pre-Research: Method Literature Review (before {node})

You MUST run this BEFORE generating the {node} delta.
This is Round {round_id} of the research loop.

{grounding}

## Core Requirements:
1. **CRITICAL**: You MUST use the `academic-research-suite` skill (which includes literature search tools like PubMed/bioRxiv/OpenAlex/Tavily) to perform a real-literature review.
2. **Database Verification & Reuse**:
   - First, scan the literature database directory `{project_dir.as_posix()}/09_Literature_Database` (if it exists) to see what papers have been reviewed in previous rounds.
   - If there are relevant papers, read them and incorporate/expand on their findings.
   - Search the web/academic databases for new papers to answer the queries and expand our understanding.
3. **Database Registration**:
   - For every new paper you find and select, you MUST add it to the growable literature database by running:
     `python manage_literature_db.py add {project_dir.as_posix()} --round {round_id} --json-data "<JSON_STRING>"`
   - Ensure the `<JSON_STRING>` is a single-line valid JSON string. Escape quotes properly. It must contain the following keys:
     - "doi": string (or empty)
     - "title": string
     - "authors": string (or list of strings)
     - "journal": string
     - "year": integer/string
     - "core_arguments": list of strings (key findings or arguments)
     - "evidence_level": "STRONG", "MODERATE", or "WEAK"
     - "tags": list of strings
     - "summary": string (relevance, methods, results summary)
     - "url": string (or empty)

Search for papers on methodology used in similar studies (seed queries):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Focus on:
- What analysis approaches others have used for similar questions
- Standard pipelines and parameters
- Common pitfalls and how they were addressed

Write a structured summary to: {output_file.as_posix()}

Format of {output_file.as_posix()}:
IMPORTANT: Cite papers using Obsidian Wikilinks pointing to the literature database files (e.g., `[[09_Literature_Database/citekey|Paper Title]]` where `citekey` is the filename without `.md`).

## Methods Found
- Method 1 (citing [[09_Literature_Database/citekey|Paper Title]], parameters/settings used)
- Method 2 (citing [[09_Literature_Database/citekey|Paper Title]], parameters/settings used)

## Recommended Approach
- What to adopt and why (referencing papers in the database)

## Pitfalls to Avoid
- Pitfall 1 (how others failed, citing [[09_Literature_Database/citekey|Paper Title]])

This summary will be injected into the {node} assemble-context as additional input.
"""
    elif research_type == "code_search":
        prompt = f"""# Pre-Research: Code Search (before {node})

You MUST run this BEFORE generating the {node} delta.

{grounding}
Search GitHub, Bioconductor, and CRAN for existing code (seed queries):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Check:
- Bioconductor packages (WGCNA, clusterProfiler, fgsea, etc.)
- GitHub repos with WGCNA pipelines
- Existing R scripts for module preservation, GSEA, ECM scoring

Write a structured summary to: {output_file}

Format:
## Existing Tools Found
- tool 1 (repo/package, what it does, URL)
- tool 2 (repo/package, what it does, URL)

## Reusable Code
- script/function 1 (what it does, how to use)

## Gap: What We Must Write Ourselves
- gap 1 (why no existing tool fits)

This summary will be injected into the {node} assemble-context as additional input.
"""
    elif research_type == "literature_verification":
        # Ground the search in the ACTUAL L7/L8 findings, not just the question,
        # so L8.5 verifies real results against published literature.
        def _ld(key):
            p = _delta_file(project_dir, key)
            if p and p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return None
            return None
        l7 = _ld("L7_turing") or {}
        l8 = _ld("L8_curie") or {}
        findings = json.dumps({"L7_key_results": l7.get("key_results"),
                               "L8_evidence_level": l8.get("evidence_level"),
                               "L8_evidence_verified": l8.get("evidence_verified")},
                              ensure_ascii=False, indent=2)
        prompt = f"""# Pre-Research: Literature Verification (before {node})

You MUST run this BEFORE generating the {node} delta.

{grounding}
## Actual results to verify (from L7 execution + L8 audit)
{findings}

Knowledge base (your access for L8.5 is read-write):
1. First, scan `{project_dir.as_posix()}/09_Literature_Database` (if it exists) to
   reuse papers already reviewed in previous rounds.
2. Use the academic-research-suite skill to search PubMed/EuropePMC for papers that
   CONFIRM or CONTRADICT these SPECIFIC findings (concrete entities: the genes,
   modules, phenotypes, methods above).
3. For every new paper you select, you MUST add it to the database:
   `python manage_literature_db.py add {project_dir.as_posix()} --round {round_id} --json-data "<JSON_STRING>"`
4. Cite papers via Obsidian wikilinks `[[09_Literature_Database/<citekey>|Title]]`.

Seed queries (adapt to the actual results above):
"""
        for i, q in enumerate(queries, 1):
            prompt += f"{i}. {q}\n"
        prompt += f"""
Write a structured summary to: {output_file}

Format:
## Papers Found (verifying actual results)
- [[09_Literature_Database/<citekey>|Title]] (PMID) -- confirms / contradicts / extends WHICH finding above

## Verdict
- Does the published literature support the L7/L8 findings? Any contradictions?

This summary will be injected into the {node} assemble-context as additional input.
"""

    print(prompt)
    print(f"\n[pre-research] output target: {output_file}")
    return 0


def _condense_delta(delta_key, data):
    """Return a token-efficient, condensed copy of the delta data for aggregation."""
    if not isinstance(data, dict):
        return data
    import copy
    d = copy.deepcopy(data)
    
    # 1. Truncate large lists in L0 Linnaeus skills found
    if delta_key == "L0_linnaeus":
        if "skills_found" in d and isinstance(d["skills_found"], list) and len(d["skills_found"]) > 10:
            d["skills_found"] = d["skills_found"][:5] + [f"... ({len(d['skills_found'])} skills found in total)"]
            
    # 2. Truncate large lists of steps in L4 Fisher
    elif delta_key == "L4_fisher":
        if "strategies" in d and isinstance(d["strategies"], list):
            for s in d["strategies"]:
                if isinstance(s, dict) and "steps" in s and isinstance(s["steps"], list) and len(s["steps"]) > 5:
                    s["steps"] = s["steps"][:3] + [f"... ({len(s['steps'])} steps total)"]
                    
    # 3. Truncate large output_files or script results in L7 Turing
    elif delta_key == "L7_turing":
        if "scripts_run" in d and isinstance(d["scripts_run"], list):
            for s in d["scripts_run"]:
                if isinstance(s, dict) and "output_files" in s and isinstance(s["output_files"], list) and len(s["output_files"]) > 5:
                    s["output_files"] = s["output_files"][:3] + [f"... ({len(s['output_files'])} output files total)"]
                    
    # 4. Truncate evidence verified list in L8 Curie
    elif delta_key == "L8_curie":
        if "evidence_verified" in d and isinstance(d["evidence_verified"], list) and len(d["evidence_verified"]) > 10:
            d["evidence_verified"] = d["evidence_verified"][:5] + [f"... ({len(d['evidence_verified'])} files audited in total)"]

    # 5. Truncate long paper abstracts in L8.5 (Curie literature verification)
    elif delta_key == "L8.5_curie":
        if "papers" in d and isinstance(d["papers"], list):
            for p in d["papers"]:
                if isinstance(p, dict) and "abstract" in p and isinstance(p["abstract"], str) and len(p["abstract"]) > 150:
                    p["abstract"] = p["abstract"][:150] + "... (truncated abstract)"
                    
    # 6. Truncate huge gene lists in L9b Darwin module interpretations
    elif delta_key == "L9b_darwin":
        if "module_interpretations" in d and isinstance(d["module_interpretations"], list):
            for m in d["module_interpretations"]:
                if isinstance(m, dict) and "genes" in m and isinstance(m["genes"], list) and len(m["genes"]) > 5:
                    m["genes"] = m["genes"][:5] + [f"... ({len(m['genes'])} genes total)"]
                    
    return d


def cmd_assemble_context(args):
    """Path B core: assemble context text for a DAG node."""
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2

    node_id = args.node
    if node_id not in NODE_MAP:
        print(f"ERROR: unknown node {node_id}", file=sys.stderr)
        return 2

    node_info = NODE_MAP[node_id]
    inputs = node_info["context_inputs"]

    kb = node_info.get("knowledge_base", "none")
    sections = []
    directive = ("ISOLATION DIRECTIVE: Your entire input is below. Work only with "
                 "the information provided; do not access the filesystem")
    if kb == "read-write":
        directive += (", EXCEPT the external knowledge base 09_Literature_Database/, "
                      "which you MAY read AND add to (via manage_literature_db.py).")
    elif kb == "read":
        directive += (", EXCEPT the external knowledge base 09_Literature_Database/, "
                      "which you MAY READ to cite existing papers (Obsidian "
                      "wikilinks) -- you may NOT add to it.")
    else:
        directive += (". You have NO knowledge-base access; cite only papers "
                      "already present in your context.")
    sections.append(directive)
    sections.append("")

    injected = []  # audit: deltas actually embedded {delta_key, sha256, path}

    for inp in inputs:
        if inp == "candidate_frontmatter":
            # L0 (input verification) sees the real source_input path; every
            # other cognitive node sees only the path-free alias.
            fm = strip_candidate_to_frontmatter(
                cf, include_source_path=(node_id == "L0"))
            lines = ["=== CANDIDATE FRONTMATTER ==="]
            for k, v in fm.items():
                lines.append(f"  {k}: {v}")
            sections.append("\n".join(lines))
            sections.append("")
        elif inp == "ALL":
            # L10c: read all deltas
            for delta_key in DELTA_DAG_ORDER:
                df = _delta_file(project_dir, delta_key)
                if df and df.exists():
                    try:
                        data = json.loads(df.read_text(encoding="utf-8"))
                        lines = [f"=== DELTA: {delta_key} ==="]
                        condensed = _condense_delta(delta_key, data)
                        lines.append(json.dumps(condensed, indent=2, ensure_ascii=False))
                        sections.append("\n".join(lines))
                        sections.append("")
                        injected.append({"delta_key": delta_key,
                                         "sha256": _sha256(df), "path": str(df)})
                    except json.JSONDecodeError:
                        sections.append(f"=== DELTA: {delta_key} (parse error) ===")
                        sections.append("")
        else:
            # Delta reference (e.g. "L0", "L1", "L9a"): scan for the delta
            # whose key matches this node id (e.g. "L1" -> "L1_einstein") and
            # embed it as text.
            found = False
            corrupt = False
            for dk in DELTA_DAG_ORDER:
                if dk.startswith(inp + "_"):
                    df = _delta_file(project_dir, dk)
                    if df and df.exists():
                        try:
                            data = json.loads(df.read_text(encoding="utf-8"))
                            lines = [f"=== DELTA: {dk} ==="]
                            lines.append(json.dumps(data, indent=2, ensure_ascii=False))
                            sections.append("\n".join(lines))
                            sections.append("")
                            injected.append({"delta_key": dk,
                                             "sha256": _sha256(df), "path": str(df)})
                            found = True
                        except json.JSONDecodeError:
                            # File exists but is unreadable -- surface it as an
                            # error rather than silently reporting "not emitted".
                            sections.append(f"=== DELTA: {dk} (parse error) ===")
                            sections.append("")
                            corrupt = True
            if not found and not corrupt:
                sections.append(f"=== DELTA: {inp} (not yet emitted) ===")
                sections.append("")

    # v0.4: inject the pre-research summary (deep research before L1, method
    # literature review before L4, code search before L7) if this node has one.
    # The DAG topology is unchanged; this is extra reference context produced by
    # the orchestrator via `pre-research` and embedded here as text.
    pre_research_meta = None
    pr_cfg = PRE_RESEARCH_MAP.get(node_id)
    if pr_cfg:
        prf = _pre_research_file(project_dir, node_id)
        if prf.exists():
            sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}) ===")
            sections.append(prf.read_text(encoding="utf-8"))
            sections.append("")
            pre_research_meta = {"type": pr_cfg["type"], "path": str(prf),
                                 "sha256": _sha256(prf), "present": True}
        else:
            sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}): NOT YET RUN ===")
            sections.append(
                f"Run first: python research_loop_v04.py pre-research "
                f"{project_dir} {args.cand_id} --node {node_id}")
            sections.append("")
            pre_research_meta = {"type": pr_cfg["type"], "path": str(prf),
                                 "sha256": None, "present": False}

    # Inject persona template (full role definition: personality, responsibilities,
    # forbidden actions, delta schema)
    persona = node_info["persona"]
    sections.append(f"=== PERSONA: {persona} | {PERSONA_TITLE.get(persona, '')} ===")
    sections.append(f"Action: {node_info['action_hint']}")
    sections.append("")
    _script_dir = Path(__file__).resolve().parent
    ptpl = _script_dir / _persona_template_path(persona)
    if ptpl.exists():
        sections.append(f"--- PERSONA TEMPLATE ({ptpl.name}) ---")
        sections.append(ptpl.read_text(encoding="utf-8"))
        sections.append("")
    # Inject layer template (step-specific execution instructions)
    ltpl = _script_dir / _layer_template_path(node_id)
    if ltpl.exists():
        sections.append(f"--- LAYER TEMPLATE ({ltpl.name}) ---")
        sections.append(ltpl.read_text(encoding="utf-8"))
        sections.append("")

    # v0.4 bilingual: instruct agent to include Chinese translations
    sections.append("=== BILINGUAL OUTPUT DIRECTIVE ===")
    sections.append("Your delta JSON must include a \"cn\" key with Chinese")
    sections.append("translations of all human-readable field values (hypothesis")
    sections.append("text, rationale, attacks, verdicts, reasons, interpretations,")
    sections.append("etc.). The top-level English fields remain the canonical")
    sections.append("machine-readable values; the \"cn\" key provides Chinese for")
    sections.append("FINAL_REPORT_CN.md generation. Example:")
    sections.append('  {"hypotheses": [{"id":"H1","text":"...","cn":"..."}],')
    sections.append('   "primary_hypothesis": "...",')
    sections.append('   "cn": {"primary_hypothesis": "...", "key_uncertainty": "..."}}')
    sections.append("")

    # Audit (problem 5): write a context_manifest declaring exactly what this
    # node was allowed and shown -- inputs, per-delta sha256, the DECLARED tools
    # / EverOS policy (problems 1/2; the script declares, the orchestrator
    # enforces), workspace, timestamp. emit-delta --receipt verifies against it.
    project_id = project_dir.name
    workspaces = sorted(project_dir.glob("_turing_workspace_*"))
    manifest_id = _stamp()
    manifest = {
        "manifest_id": manifest_id,
        "candidate_id": args.cand_id,
        "node": node_id,
        "persona": persona,
        "timestamp": _now(),
        "allowed_inputs": list(inputs),
        "injected_deltas": injected,
        "tools_policy": node_info.get("tools_policy"),
        "everos_read_scopes": _everos_scopes_for(node_info, project_id),
        "knowledge_base": node_info.get("knowledge_base"),
        "workspace": (str(workspaces[-1])
                      if (node_info.get("is_execution") and workspaces) else None),
        "pre_research": pre_research_meta,
    }
    mpath = (_audit_dir(project_dir)
             / f"context_manifest_{node_id}_{manifest_id}.json")
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                     encoding="utf-8")

    print("\n".join(sections))
    print(f"[audit] context manifest: {mpath}", file=sys.stderr)
    return 0

def cmd_emit_delta(args):
    """Validate delta JSON against schema and write to 02_Agent_Notes/."""
    project_dir = Path(args.project_dir)
    src = Path(args.file)
    if not src.exists():
        print(f"ERROR: delta file not found: {src}", file=sys.stderr)
        return 2

    delta_key = f"{args.node}_{args.persona.lower()}"
    schema = DELTA_SCHEMAS.get(delta_key)
    if schema is None:
        print(f"ERROR: no schema for {delta_key}", file=sys.stderr)
        return 2

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        return 2

    # Recursive structural validation against the (possibly nested) schema:
    # enforces container types AND the required keys of objects inside lists and
    # dicts (so hypotheses=[{"foo":1}] -- element missing id/text -- is rejected,
    # not just hypotheses="str").
    errors = _validate_delta(schema, data)

    # L0 dependency checks
    if args.node == "L0":
        dep_errors = []
        # 1. Check Obsidian Vault
        vault = os.environ.get("OBSIDIAN_VAULT")
        if not vault:
            dep_errors.append("Obsidian Vault path is not set in environment variable $OBSIDIAN_VAULT.")
        else:
            expanded_vault = Path(os.path.expandvars(vault)).expanduser()
            if not expanded_vault.is_dir():
                dep_errors.append(f"Obsidian Vault directory does not exist: {vault}")
        # 2. Check Zotero
        zotero_env = os.environ.get("ZOTERO_API_KEY") or os.environ.get("ZOTERO_USER_ID")
        zotero_dirs = [
            os.path.expandvars(r"%PROGRAMFILES%\Zotero\zotero.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Zotero\zotero.exe"),
            os.path.expanduser(r"~\AppData\Local\Zotero"),
        ]
        zotero_found = bool(zotero_env) or any(os.path.exists(d) for d in zotero_dirs)
        if not zotero_found:
            dep_errors.append("Zotero is not installed or Zotero API credentials ($ZOTERO_API_KEY / $ZOTERO_USER_ID) are missing.")
        # 3. Check Academic Research Suite / Skill
        skills = data.get("skills_found", [])
        has_academic = any("academic" in s.lower() for s in skills)
        custom_dirs = [
            Path(r"C:\Users\hk200\.gemini\config\plugins\custom-skills\skills\academic-research-suite"),
            Path(r"C:\Users\hk200\.codex\skills\academic-research-suite"),
            Path(project_dir) / ".agents" / "skills" / "academic-research-suite",
        ]
        if not has_academic and not any(d.exists() for d in custom_dirs):
            dep_errors.append("academic-research-suite skill is not found in skills catalog or plugins directory.")
        if dep_errors:
            errors.extend(dep_errors)

    # Check for extra keys
    extra = set(data.keys()) - set(schema.keys())
    if extra:
        print(f"WARNING: extra keys (allowed): {extra}", file=sys.stderr)

    if errors:
        print("DELTA VALIDATION: REJECT", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        
        # Issue 6: Auto-correction instructions
        schema_keys = list(schema.keys())
        print("\n=== AI AUTO-CORRECTION INSTRUCTIONS ===", file=sys.stdout)
        print("Your previous delta JSON validation failed. Please review the errors above and correct the file:\n", file=sys.stdout)
        for e in errors:
            print(f"- ERROR: {e}", file=sys.stdout)
        print(f"\nRequired schema keys for {delta_key}: {schema_keys}", file=sys.stdout)
        print("Expected JSON structure:", file=sys.stdout)
        print(json.dumps(schema, indent=2, default=lambda x: x.__name__), file=sys.stdout)
        print("========================================\n", file=sys.stdout)
        return 1

    # Receipt verification (problem 5). Policy A (optional but verified): if a
    # context_manifest is supplied, confirm the upstream deltas this node
    # consumed still hash to what the manifest recorded -- catches an upstream
    # delta being re-emitted/changed between assemble-context and emit-delta.
    # No receipt -> skip; receipt + mismatch -> reject.
    manifest_id = None
    verification = "skipped (no receipt)"
    mismatches = []
    if args.receipt:
        rp = Path(args.receipt)
        if not rp.exists():
            print(f"ERROR: receipt not found: {rp}", file=sys.stderr)
            return 2
        try:
            manifest = json.loads(rp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid receipt JSON: {e}", file=sys.stderr)
            return 2
        manifest_id = manifest.get("manifest_id")
        for inj in manifest.get("injected_deltas", []):
            cur = _sha256(_delta_file(project_dir, inj.get("delta_key")))
            if cur != inj.get("sha256"):
                mismatches.append(inj.get("delta_key"))
        verification = "pass" if not mismatches else "FAIL"
        if mismatches:
            print("DELTA VALIDATION: REJECT (receipt hash mismatch)",
                  file=sys.stderr)
            print(f"  upstream deltas changed since assemble-context: "
                  f"{', '.join(str(m) for m in mismatches)}", file=sys.stderr)
            return 1

    # Write to 02_Agent_Notes/<persona>/<node>_<persona>_delta.json
    out_file = _delta_file(project_dir, delta_key)
    if out_file is None:
        out_dir = Path(project_dir) / "02_Agent_Notes" / args.persona
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{delta_key}_delta.json"
    else:
        out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    # Run receipt (problem 5): record what was produced + the verification
    # outcome, referencing the context_manifest. Keeps the delta itself pure.
    receipt_id = _stamp()
    run_receipt = {
        "receipt_id": receipt_id,
        "candidate_id": args.cand_id,
        "node": args.node,
        "persona": args.persona,
        "delta_key": delta_key,
        "emitted_at": _now(),
        "output_delta_sha256": _sha256(out_file),
        "context_manifest_id": manifest_id,
        "upstream_verification": verification,
        "mismatches": mismatches,
    }
    rr = _audit_dir(project_dir) / f"run_receipt_{args.node}_{receipt_id}.json"
    rr.write_text(json.dumps(run_receipt, indent=2, ensure_ascii=False),
                  encoding="utf-8")

    print(f"DELTA VALIDATION: PASS")
    print(f"  schema: {delta_key}")
    print(f"  written: {out_file}")
    print(f"  run receipt: {rr} (upstream: {verification})")
    return 0

# --- Phase 2 commands -------------------------------------------------------

def cmd_new_project(args):
    name = args.name
    topic = args.topic or ""
    project_dir = Path(name)
    if project_dir.exists():
        print(f"ERROR: {project_dir} already exists; refusing to overwrite.",
              file=sys.stderr)
        return 2
    _mkdirs(project_dir)
    (project_dir / "00_Project_Index.md").write_text(
        _index_template_v03(name, topic), encoding="utf-8")
    print(f"Created v0.4 project: {project_dir.resolve()}")
    print("Next: run `preflight` (Linnaeus L0) before any candidate work.")
    return 0


def cmd_new_candidate(args):
    project_dir = Path(args.project_dir)
    idx = project_dir / "00_Project_Index.md"
    if not idx.exists():
        print(f"ERROR: not a project dir (no 00_Project_Index.md): {project_dir}",
              file=sys.stderr)
        return 2
    cand_id = "C" + _stamp()
    body = _candidate_template_v03(cand_id, args.title, args.input,
                                   args.question, args.claim,
                                   input_alias=getattr(args, "input_alias", "") or "")
    cf = _candidate_file(project_dir, cand_id)
    cf.write_text(body, encoding="utf-8")
    _append_decision(project_dir, cand_id, "-", "NEW", "candidate created",
                     agent="Oppenheimer", kind="seed")
    print(cand_id)
    print(f"  -> {cf}")
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
    print("\nL0 dependency gate:")
    for d in ok:
        print(f"  OK       {d['kind']}:{d['name']}")
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
    print("\nPREFLIGHT GATE: PASS -- all required dependencies present.")
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
    if missing:
        print("DEPENDENCY GATE: STOP -- satisfy the missing dependencies above; "
              "the loop must not proceed.", file=sys.stderr)
        return 3
    print("DEPENDENCY GATE: PASS")
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
    pd = Path("DemoProject_v03")
    if pd.exists():
        print(f"ERROR: {pd} already exists; remove it first.", file=sys.stderr)
        return 2
    _mkdirs(pd)
    name = "DemoProject_v03"
    (pd / "00_Project_Index.md").write_text(
        _index_template_v03(name, "RLR v0.4 DAG demo"), encoding="utf-8")

    pf = pd / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        (pf / fname).write_text(_preflight_template(name, fname), encoding="utf-8")

    c1 = "C" + _stamp()
    (pd / "01_Candidates" / f"{c1}.md").write_text(
        _candidate_template_v03(
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
    frm = fm.get("current_status")
    if args.decision == "select":
        to, owner = "IDEA_SELECTED", "Fisher"
    else:
        to, owner = "DROP", "Oppenheimer"
    seq = _append_decision(project_dir, args.cand_id, frm, to, args.reason,
                           route_to=owner, agent="Oppenheimer",
                           kind="candidate_triage")
    (project_dir / "05_Decision_Log" /
     f"candidate_triage_decision_{args.cand_id}.md").write_text(
        _decision_log_template(seq, args.cand_id, frm, to, args.reason, owner,
                               agent="Oppenheimer", kind="candidate_triage"),
        encoding="utf-8")
    _set_status(project_dir, args.cand_id, to, owner)
    if to == "DROP":
        _replace_field(cf, "final_decision", f"DROP: {args.reason}")
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
    frm = fm.get("current_status")
    if args.decision == "approve":
        to, owner = "METHOD_APPROVED", "Oppenheimer"
    else:
        to, owner = "DROP", "Oppenheimer"
    seq = _append_decision(project_dir, args.cand_id, frm, to, args.reason,
                           route_to=owner, agent="Oppenheimer",
                           kind="analysis_plan")
    (project_dir / "05_Decision_Log" /
     f"analysis_plan_decision_{args.cand_id}.md").write_text(
        _decision_log_template(seq, args.cand_id, frm, to, args.reason, owner,
                               agent="Oppenheimer", kind="analysis_plan"),
        encoding="utf-8")
    _set_status(project_dir, args.cand_id, to, owner)
    if to == "DROP":
        _replace_field(cf, "final_decision", f"DROP: {args.reason}")
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


def cmd_execution_gate(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    pf = project_dir / "00_Preflight"
    missing = []
    if not (pf / "skill_use_plan.md").exists():
        missing.append("00_Preflight/skill_use_plan.md")
    if not (pf / "input_manifest.md").exists():
        missing.append("00_Preflight/input_manifest.md")
    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "?")
    if status != "METHOD_APPROVED":
        missing.append(f"approved analysis plan (candidate is {status}, "
                       f"need METHOD_APPROVED)")
    if missing:
        print("EXECUTION GATE: REJECT")
        for m in missing:
            print(f"  missing: {m}")
        print("  Turing may NOT execute. Resolve the above (Linnaeus L0 / "
              "Oppenheimer L6) first.")
        return 1
    _append_decision(project_dir, args.cand_id, status, "NEEDS_EXECUTION",
                     "execution gate passed: preflight + approved plan present",
                     route_to="Turing", agent="Oppenheimer",
                     kind="execution_gate")
    _set_status(project_dir, args.cand_id, "NEEDS_EXECUTION", "Turing")
    print("EXECUTION GATE: PASS")
    print("  skill_use_plan.md ........ OK")
    print("  input_manifest.md ........ OK")
    print("  approved analysis plan ... OK (METHOD_APPROVED)")
    print(f"  {args.cand_id} -> NEEDS_EXECUTION (route: Turing)")
    return 0


def cmd_prepare_turing_workspace(args):
    """Path A: build an isolated execution workspace for Turing (L7).

    Copies the deltas Turing is allowed to see (L0, L6), the preflight files,
    and any explicitly allowlisted input data files into a fresh
    PROJECT_DIR/_turing_workspace_<ts>/ tree (same disk, shutil.copy2, never
    hard links). Turing runs scripts in scripts/, writes to results/, and reads
    only from inputs/; the project tree and raw inputs stay untouched.
    """
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "?")
    if status != "NEEDS_EXECUTION":
        print(f"ERROR: {args.cand_id} is {status}; Turing workspace requires "
              f"NEEDS_EXECUTION (run execution-gate first).", file=sys.stderr)
        return 1

    if args.clean:
        for old in sorted(project_dir.glob("_turing_workspace_*")):
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)

    ws = project_dir / f"_turing_workspace_{_stamp()}"
    inputs = ws / "inputs"
    for sub in (inputs, ws / "scripts", ws / "results"):
        sub.mkdir(parents=True, exist_ok=True)

    copied, missing = [], []

    # Deltas Turing is allowed to see per the DAG (L6 approved plan, L0 skills).
    for delta_key in ("L0_linnaeus", "L6_oppenheimer"):
        df = _delta_file(project_dir, delta_key)
        if df and df.exists():
            shutil.copy2(df, inputs / df.name)
            copied.append(f"inputs/{df.name}")
        else:
            missing.append(f"{delta_key} delta")

    # Preflight files (skill plan, manifests, forbidden shortcuts).
    pf = project_dir / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        src = pf / fname
        if src.exists():
            shutil.copy2(src, inputs / fname)
            copied.append(f"inputs/{fname}")
        else:
            missing.append(f"00_Preflight/{fname}")

    # Explicitly allowlisted input data files (paths drawn from input_manifest).
    for raw in (args.file or []):
        src = Path(raw)
        if src.exists() and src.is_file():
            shutil.copy2(src, inputs / src.name)
            copied.append(f"inputs/{src.name} (<- {src})")
        else:
            missing.append(f"allowlisted file not found: {raw}")

    manifest = [
        "---",
        f"workspace: {_yaml_value(ws.name)}",
        f"candidate_id: {_yaml_value(args.cand_id)}",
        f"created_at: {_yaml_value(_now())}",
        f"status_at_creation: {_yaml_value(status)}",
        "---",
        "",
        f"# Turing Workspace (Path A) - {args.cand_id}",
        "",
        "Isolated execution workspace. Turing runs scripts in `scripts/`, writes",
        "outputs to `results/`, and reads only the files in `inputs/`. The project",
        "tree and the raw inputs are NOT modified from here.",
        "",
        "## Copied in",
        "",
    ]
    manifest += ([f"- {c}" for c in copied] or ["- _none_"])
    if missing:
        manifest += ["", "## Missing (not copied)", ""]
        manifest += [f"- {m}" for m in missing]
    (ws / "WORKSPACE_MANIFEST.md").write_text("\n".join(manifest) + "\n",
                                              encoding="utf-8")

    print(f"Turing workspace ready: {ws}")
    print(f"  inputs/ ... {len(copied)} file(s) copied")
    print("  scripts/ .. (Turing writes modular scripts here)")
    print("  results/ .. (Turing writes outputs here)")
    if missing:
        print(f"  WARN: {len(missing)} expected item(s) missing:", file=sys.stderr)
        for m in missing:
            print(f"    - {m}", file=sys.stderr)
    return 0


def cmd_list(args):
    project_dir = Path(args.project_dir)
    cdir = project_dir / "01_Candidates"
    adir = project_dir / "99_Archive"
    print(f"# Candidates in {project_dir}\n")
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            fm = _load_yaml_front(f)
            print(f"- [{fm.get('current_status','?')}] {fm.get('candidate_id','?')}"
                  f"  owner={fm.get('current_owner','?')}  | {fm.get('title','')}")
    print("\n# Archived\n")
    if adir.exists():
        for f in sorted(adir.glob("*.md")):
            fm = _load_yaml_front(f)
            print(f"- [{fm.get('current_status','?')}] {fm.get('candidate_id','?')}"
                  f"  | {fm.get('title','')}")
    return 0


def cmd_show(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        cf = Path(project_dir) / "99_Archive" / f"{args.cand_id}.md"
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    print(cf.read_text(encoding="utf-8"))
    return 0

# --- obsidian sync ----------------------------------------------------------

def cmd_obsidian_sync(args):
    """Sync delta JSON + FINAL_REPORT + audit trail to Obsidian vault and index.

    Copies candidates, decision logs, delta JSON, final reports, and the
    08_Audit/ manifests+receipts into the vault, and builds an index whose
    "Audit Trail" section lets the info-flow be replayed from inside Obsidian.
    """
    import shutil

    project_dir = Path(args.project_dir)
    idx = project_dir / "00_Project_Index.md"
    if not idx.exists():
        print(f"ERROR: not a project dir: {project_dir}", file=sys.stderr)
        return 2
    name = _load_yaml_front(idx).get("project_name", project_dir.name)

    vault_str = getattr(args, "vault", None) or "OBSIDIAN_VAULT env var"
    vault = Path(vault_str)
    if not vault.exists():
        print(f"WARNING: vault not found: {vault} - writing index only", file=sys.stderr)
        vault = None

    sync = project_dir / "07_Obsidian_Sync"
    sync.mkdir(parents=True, exist_ok=True)

    vault_dest = None
    copied = 0
    if vault:
        vault_dest = vault / "ResearchLoop" / name
        vault_dest.mkdir(parents=True, exist_ok=True)

    # Copy 00_Project_Index.md
    if vault_dest:
        shutil.copy2(idx, vault_dest / "00_Project_Index.md")
        copied += 1

    # Copy FINAL_REPORT*.md if they exist
    for rpt in sorted(project_dir.glob("FINAL_REPORT*.md")):
        if vault_dest:
            shutil.copy2(rpt, vault_dest / rpt.name)
            copied += 1

    # Copy all delta JSON from 02_Agent_Notes/*/
    notes_dir = project_dir / "02_Agent_Notes"
    delta_files = []
    if notes_dir.exists():
        for persona_dir in sorted(notes_dir.iterdir()):
            if not persona_dir.is_dir():
                continue
            for f in sorted(persona_dir.glob("*_delta.json")):
                delta_files.append((persona_dir.name, f))
                if vault_dest:
                    dst_dir = vault_dest / "02_Agent_Notes" / persona_dir.name
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst_dir / f.name)
                    copied += 1

    # Also copy candidate files and decision logs
    for sub in ["01_Candidates", "05_Decision_Log"]:
        src_dir = project_dir / sub
        if not src_dir.exists():
            continue
        if vault_dest:
            dst_dir = vault_dest / sub
            dst_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(src_dir.glob("*.md")):
            if vault_dest:
                shutil.copy2(f, vault_dest / sub / f.name)
                copied += 1

    # Copy audit artifacts (08_Audit/*.json) and collect them for the index
    audit_dir = project_dir / "08_Audit"
    manifest_files, receipt_files = [], []
    if audit_dir.exists():
        if vault_dest:
            (vault_dest / "08_Audit").mkdir(parents=True, exist_ok=True)
        for f in sorted(audit_dir.glob("*.json")):
            if f.name.startswith("run_receipt_"):
                receipt_files.append(f)
            elif f.name.startswith("context_manifest_"):
                manifest_files.append(f)
            if vault_dest:
                shutil.copy2(f, vault_dest / "08_Audit" / f.name)
                copied += 1

    # Build wikilink index
    sections = [
        f"---\nproject_name: {_yaml_value(name)}\nkind: obsidian_index\n"
        f"version: {_yaml_value(__version__)}\n"
        f"synced_at: {_yaml_value(_now())}\n---\n",
        f"# {name} - Obsidian Index (v0.4)\n",
        "> Synced to vault. Wikilinks resolve inside Obsidian.\n",
        "## Project\n\n- [[00_Project_Index|Project Index]]\n",
    ]

    # Candidates section
    cand_lines = []
    cdir = project_dir / "01_Candidates"
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            fm = _load_yaml_front(f)
            cand_lines.append(
                f"- [[01_Candidates/{f.stem}|{fm.get('candidate_id', f.stem)}]] "
                f"- **{fm.get('current_status', '?')}** "
                f"(owner {fm.get('current_owner', '?')}) - {fm.get('title', '')}")
    if not cand_lines:
        cand_lines = ["_none_"]
    sections.append("## Candidates\n\n" + "\n".join(cand_lines) + "\n")

    # Decision log section
    dlines = []
    ddir = project_dir / "05_Decision_Log"
    if ddir.exists():
        for f in sorted(ddir.glob("*.md")):
            dlines.append(f"- [[05_Decision_Log/{f.stem}|{f.stem}]]")
    if not dlines:
        dlines = ["_none_"]
    sections.append("## Decision Log\n\n" + "\n".join(dlines) + "\n")

    # Delta files section
    delta_lines = []
    for persona, f in delta_files:
        delta_lines.append(f"- [[02_Agent_Notes/{persona}/{f.stem}|{f.stem}]]")
    if not delta_lines:
        delta_lines = ["_none_"]
    sections.append("## Delta Files (DAG)\n\n" + "\n".join(delta_lines) + "\n")

    # Final reports section
    rpt_lines = []
    for rpt in sorted(project_dir.glob("FINAL_REPORT*.md")):
        rpt_lines.append(f"- [[{rpt.stem}|{rpt.stem}]]")
    if not rpt_lines:
        rpt_lines = ["_none_"]
    sections.append("## Final Reports\n\n" + "\n".join(rpt_lines) + "\n")

    # Audit trail section: run receipts (chronological) + context manifests.
    # Makes the info-flow replayable from inside Obsidian: which node saw what,
    # and whether its upstream hashes verified.
    receipts = []
    for f in receipt_files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            r = {}
        receipts.append((r.get("emitted_at", ""), f, r))
    receipts.sort(key=lambda t: t[0])
    audit_block = ""
    if receipts:
        rows = ["| node | persona | upstream | emitted_at | receipt |",
                "| ---- | ------- | -------- | ---------- | ------- |"]
        for _ts, f, r in receipts:
            rows.append(
                f"| {r.get('node', '?')} | {r.get('persona', '?')} "
                f"| {r.get('upstream_verification', '?')} "
                f"| {r.get('emitted_at', '?')} "
                f"| [[08_Audit/{f.stem}|{f.stem}]] |")
        audit_block += "### Run receipts\n\n" + "\n".join(rows) + "\n\n"
    if manifest_files:
        mani = [f"- [[08_Audit/{f.stem}|{f.stem}]]" for f in manifest_files]
        audit_block += "### Context manifests\n\n" + "\n".join(mani) + "\n"
    if not audit_block:
        audit_block = "_none_\n"
    sections.append("## Audit Trail (info-flow)\n\n" + audit_block)

    index_text = "\n".join(sections)

    out_local = sync / "00_Obsidian_Index.md"
    out_local.write_text(index_text, encoding="utf-8")

    if vault_dest:
        out_vault = vault_dest / "00_Obsidian_Index.md"
        out_vault.write_text(index_text, encoding="utf-8")
        print(f"Obsidian sync -> {out_vault} ({copied} files copied)")
    else:
        print(f"Obsidian sync (index only) -> {out_local}")
    return 0


# --- aggregate report (L10c Linnaeus) ---------------------------------------

# Section titles for English and Chinese reports
SECTION_TITLES_EN = {
    "L0_linnaeus": "L0 - Preflight (Linnaeus)",
    "L1_einstein": "L1 - Hypotheses (Einstein)",
    "L2_feynman": "L2 - Idea Falsification (Feynman)",
    "L3_oppenheimer": "L3 - Candidate Triage (Oppenheimer)",
    "L4_fisher": "L4 - Method Design (Fisher)",
    "L5_tukey": "L5 - Method Falsification (Tukey)",
    "L6_oppenheimer": "L6 - Analysis Plan Approval (Oppenheimer)",
    "L7_turing": "L7 - Execution (Turing)",
    "L8_curie": "L8 - Evidence Audit (Curie)",
    "L9a_feynman": "L9a - Result Falsification (Feynman)",
    "L9b_darwin": "L9b - Biology Interpretation (Darwin)",
    "L10a_jobs": "L10a - Value Assessment (Jobs)",
    "L10b_oppenheimer": "L10b - Final Decision (Oppenheimer)",
}

SECTION_TITLES_CN = {
    "L0_linnaeus": "L0 - \u9884\u68c0 (Linnaeus)",
    "L1_einstein": "L1 - \u5047\u8bf4\u751f\u6210 (Einstein)",
    "L2_feynman": "L2 - \u5047\u8bf4\u8bc1\u4f2a (Feynman)",
    "L3_oppenheimer": "L3 - \u5019\u9009\u7b5b\u9009 (Oppenheimer)",
    "L4_fisher": "L4 - \u65b9\u6848\u8bbe\u8ba1 (Fisher)",
    "L5_tukey": "L5 - \u65b9\u6848\u8bc1\u4f2a (Tukey)",
    "L6_oppenheimer": "L6 - \u5206\u6790\u8ba1\u5212\u5ba1\u6279 (Oppenheimer)",
    "L7_turing": "L7 - \u6267\u884c (Turing)",
    "L8_curie": "L8 - \u8bc1\u636e\u5ba1\u67e5 (Curie)",
    "L9a_feynman": "L9a - \u7ed3\u679c\u8bc1\u4f2a (Feynman)",
    "L9b_darwin": "L9b - \u751f\u7269\u5b66\u89e3\u8bfb (Darwin)",
    "L10a_jobs": "L10a - \u4ef7\u503c\u8bc4\u4f30 (Jobs)",
    "L10b_oppenheimer": "L10b - \u6700\u7ec8\u51b3\u7b56 (Oppenheimer)",
}

# EN -> CN translations for the field labels emitted by _format_delta_body.
# Applied to each delta body when building FINAL_REPORT_CN.md (Bug 3 fix:
# previously only section TITLES were translated, leaving the body labels in
# English). Ordered longest-first via the list so a short label (e.g.
# "**Reason:**") never partially clobbers a longer one.
DELTA_LABELS_CN = [
    ("**Skills found:**", "**\u53d1\u73b0\u7684\u6280\u80fd\uff1a**"),
    ("**Skills gaps:**", "**\u6280\u80fd\u7f3a\u53e3\uff1a**"),
    ("**Input verified:**", "**\u8f93\u5165\u6821\u9a8c\uff1a**"),
    ("**Environment:**", "**\u73af\u5883\uff1a**"),
    ("**Skill use plan:**", "**\u6280\u80fd\u4f7f\u7528\u8ba1\u5212\uff1a**"),
    ("**Forbidden shortcuts:**", "**\u7981\u6b62\u7684\u6377\u5f84\uff1a**"),
    ("**Primary hypothesis:**", "**\u4e3b\u5047\u8bf4\uff1a**"),
    ("**Key uncertainty:**", "**\u5173\u952e\u4e0d\u786e\u5b9a\u6027\uff1a**"),
    ("**Confounders:**", "**\u6df7\u6742\u56e0\u7d20\uff1a**"),
    ("**Diagnostic tests:**", "**\u8bca\u65ad\u6027\u68c0\u9a8c\uff1a**"),
    ("**Verdict:**", "**\u88c1\u51b3\uff1a**"),
    ("**Selected:**", "**\u5df2\u9009\u4e2d\uff1a**"),
    ("**Rejected:**", "**\u5df2\u5426\u51b3\uff1a**"),
    ("**Route to:**", "**\u8def\u7531\u81f3\uff1a**"),
    ("**Recommended:**", "**\u63a8\u8350\u65b9\u6848\uff1a**"),
    ("**Scripts needed:**", "**\u6240\u9700\u811a\u672c\uff1a**"),
    ("**Key decisions:**", "**\u5173\u952e\u51b3\u7b56\uff1a**"),
    ("**QC checkpoints:**", "**\u8d28\u63a7\u68c0\u67e5\u70b9\uff1a**"),
    ("**Failure stop rules:**", "**\u5931\u8d25\u505c\u6b62\u89c4\u5219\uff1a**"),
    ("**Approved strategy:**", "**\u6279\u51c6\u7684\u7b56\u7565\uff1a**"),
    ("**Modifications:**", "**\u4fee\u6539\u9879\uff1a**"),
    ("**Analysis plan:**", "**\u5206\u6790\u8ba1\u5212\uff1a**"),
    ("**Key results:**", "**\u5173\u952e\u7ed3\u679c\uff1a**"),
    ("**Warnings:**", "**\u8b66\u544a\uff1a**"),
    ("**Failures:**", "**\u5931\u8d25\uff1a**"),
    ("**Evidence level:**", "**\u8bc1\u636e\u7ea7\u522b\uff1a**"),
    ("**Caveats:**", "**\u6ce8\u610f\u4e8b\u9879\uff1a**"),
    ("**Survives:**", "**\u901a\u8fc7\u9879\uff1a**"),
    ("**Falsified:**", "**\u88ab\u8bc1\u4f2a\u9879\uff1a**"),
    ("**Convergent evolution:**", "**\u8d8b\u540c\u8fdb\u5316\uff1a**"),
    ("**Limitations:**", "**\u5c40\u9650\u6027\uff1a**"),
    ("**Value assessment:**", "**\u4ef7\u503c\u8bc4\u4f30\uff1a**"),
    ("**Headline:**", "**\u6838\u5fc3\u7ed3\u8bba\uff1a**"),
    ("**Publishable now:**", "**\u5f53\u524d\u53ef\u53d1\u8868\uff1a**"),
    ("**Needs more work:**", "**\u4ecd\u9700\u5de5\u4f5c\uff1a**"),
    ("**Manuscript framing:**", "**\u8bba\u6587\u6846\u67b6\uff1a**"),
    ("**Decision:**", "**\u51b3\u5b9a\uff1a**"),
    ("**Next steps:**", "**\u540e\u7eed\u6b65\u9aa4\uff1a**"),
    ("**Reason:**", "**\u7406\u7531\uff1a**"),
    # indented bullet sub-labels
    ("- Rationale:", "- \u63a8\u7406\uff1a"),
    ("- Output files:", "- \u8f93\u51fa\u6587\u4ef6\uff1a"),
    ("- Scripts:", "- \u811a\u672c\uff1a"),
    ("- Parameters:", "- \u53c2\u6570\uff1a"),
    ("- Outputs:", "- \u8f93\u51fa\uff1a"),
    ("- Steps:", "- \u6b65\u9aa4\uff1a"),
    ("- Genes:", "- \u57fa\u56e0\uff1a"),
    ("- Evidence:", "- \u8bc1\u636e\uff1a"),
    # inline key=value tokens
    ("testable=", "\u53ef\u68c0\u9a8c="),
    ("resolvable=", "\u53ef\u89e3\u51b3="),
    ("samples=", "\u6837\u672c\u6570="),
    ("status=", "\u72b6\u6001="),
    ("exit=", "\u9000\u51fa\u7801="),
    ("_none_", "_\u65e0_"),
]


def _translate_delta_body_cn(text):
    """Translate _format_delta_body output labels into Chinese (Bug 3 fix)."""
    for en, cn in DELTA_LABELS_CN:
        text = text.replace(en, cn)
    return text


def _format_delta_body(delta_key, delta, lang="en"):
    """Format a delta dict as markdown content (language-agnostic)."""
    if delta is None:
        return "_No delta found._\n"
    if isinstance(delta, dict) and "cn" in delta and lang == "cn":
        cn_delta = delta["cn"]
        # Only use cn sub-dict if it has the same structure as the English delta.
        # If cn fields have simplified types (e.g. attacks as string instead of list),
        # fall back to English content to avoid AttributeError in list traversal.
        _compatible = True
        for _k in ("attacks", "confounders", "diagnostic_tests",
                   "hypotheses", "strategies", "scripts_needed",
                   "qc_checkpoints", "failure_stop_rules",
                   "scripts_run", "evidence_verified",
                   "falsification_risks", "module_interpretations",
                   "publishable_now", "needs_more_work", "next_steps"):
            if _k in delta and _k in cn_delta:
                if type(delta[_k]) != type(cn_delta[_k]):
                    _compatible = False
                    break
        if _compatible:
            delta = cn_delta
    if isinstance(delta, dict) and "_error" in delta:
        return f"_Error reading delta: {delta['_error']}_\n"

    L = []
    if delta_key == "L0_linnaeus":
        L.append(f"**Skills found:** {_fmt_list(delta.get('skills_found'))}")
        L.append(f"**Skills gaps:** {_fmt_list(delta.get('skills_gaps'))}")
        L.append(f"**Input verified:** {_fmt_dict(delta.get('input_verified'))}")
        L.append(f"**Environment:** {_fmt_dict(delta.get('environment'))}")
        L.append(f"**Skill use plan:** {_fmt_list(delta.get('skill_use_plan'))}")
        L.append(f"**Forbidden shortcuts:** {_fmt_list(delta.get('forbidden_shortcuts'))}")
    elif delta_key == "L1_einstein":
        for h in delta.get("hypotheses", []):
            L.append(f"- **{h.get('id', '?')}:** {h.get('text', '')} (testable={h.get('testable', '?')})")
            L.append(f"  - Rationale: {h.get('rationale', '')}")
        L.append(f"\n**Primary hypothesis:** {delta.get('primary_hypothesis', '')}")
        L.append(f"**Key uncertainty:** {delta.get('key_uncertainty', '')}")
    elif delta_key == "L2_feynman":
        for a in delta.get("attacks", []):
            L.append(f"- **[{a.get('severity', '?')}]** {a.get('hypothesis_id', '?')}: {a.get('text', '')}")
        L.append("\n**Confounders:**")
        for c in delta.get("confounders", []):
            L.append(f"- [{c.get('severity', '?')}] {c.get('name', '')}: {c.get('text', '')}")
        L.append("\n**Diagnostic tests:**")
        for t in delta.get("diagnostic_tests", []):
            L.append(f"- {t.get('name', '')}: {t.get('text', '')}")
        L.append(f"\n**Verdict:** {delta.get('verdict', '')}")
    elif delta_key == "L3_oppenheimer":
        L.append(f"**Selected:** {_fmt_list(delta.get('selected'))}")
        L.append(f"**Rejected:** {_fmt_list(delta.get('rejected'))}")
        L.append(f"**Reason:** {delta.get('reason', '')}")
        L.append(f"**Route to:** {delta.get('route_to', '')}")
    elif delta_key == "L4_fisher":
        for s in delta.get("strategies", []):
            L.append(f"- **{s.get('id', '?')}: {s.get('name', '')}** (samples={s.get('samples', '?')}, status={s.get('status', '?')})")
            L.append(f"  - Steps: {_fmt_list(s.get('steps'))}")
        L.append(f"\n**Recommended:** {delta.get('recommended', '')}")
        L.append("\n**Scripts needed:**")
        for s in delta.get("scripts_needed", []):
            L.append(f"- {s.get('name', '')}: {s.get('purpose', '')} (status={s.get('status', '?')})")
        L.append(f"\n**Key decisions:** {_fmt_list(delta.get('key_decisions'))}")
    elif delta_key == "L5_tukey":
        for a in delta.get("attacks", []):
            L.append(f"- **[{a.get('severity', '?')}]** {a.get('target', '')}: {a.get('text', '')}")
        L.append("\n**QC checkpoints:**")
        for q in delta.get("qc_checkpoints", []):
            L.append(f"- {q.get('name', '')}: {q.get('text', '')}")
        L.append("\n**Failure stop rules:**")
        for fr in delta.get("failure_stop_rules", []):
            L.append(f"- {fr.get('name', '')}: {fr.get('text', '')}")
    elif delta_key == "L6_oppenheimer":
        L.append(f"**Approved strategy:** {delta.get('approved_strategy', '')}")
        L.append(f"**Modifications:** {_fmt_list(delta.get('modifications'))}")
        L.append(f"**Reason:** {delta.get('reason', '')}")
        ap = delta.get("analysis_plan", {})
        L.append("\n**Analysis plan:**")
        L.append(f"- Scripts: {_fmt_list(ap.get('scripts'))}")
        L.append(f"- Parameters: {_fmt_dict(ap.get('parameters'))}")
        L.append(f"- Outputs: {_fmt_list(ap.get('outputs'))}")
    elif delta_key == "L7_turing":
        for s in delta.get("scripts_run", []):
            L.append(f"- **{s.get('name', '')}** exit={s.get('exit_code', '?')}")
            L.append(f"  - Output files: {_fmt_list(s.get('output_files'))}")
        L.append(f"\n**Key results:** {_fmt_dict(delta.get('key_results'))}")
        if delta.get("warnings"):
            L.append(f"**Warnings:** {_fmt_list(delta.get('warnings'))}")
        if delta.get("failures"):
            L.append(f"**Failures:** {_fmt_list(delta.get('failures'))}")
    elif delta_key == "L8_curie":
        for e in delta.get("evidence_verified", []):
            L.append(f"- {e.get('file', '')}: {e.get('check', '')} = {e.get('result', '')}")
        L.append(f"\n**Evidence level:** {delta.get('evidence_level', '')}")
        if delta.get("caveats"):
            L.append(f"**Caveats:** {_fmt_list(delta.get('caveats'))}")
    elif delta_key == "L9a_feynman":
        for r in delta.get("falsification_risks", []):
            L.append(f"- **[{r.get('severity', '?')}]** {r.get('name', '')} (resolvable={r.get('resolvable', '?')}): {r.get('text', '')}")
        L.append(f"\n**Survives:** {_fmt_list(delta.get('survives'))}")
        L.append(f"**Falsified:** {_fmt_list(delta.get('falsified'))}")
    elif delta_key == "L9b_darwin":
        for m in delta.get("module_interpretations", []):
            L.append(f"- **{m.get('module', '')}:** {m.get('meaning', '')}")
            L.append(f"  - Genes: {_fmt_list(m.get('genes'))}")
            L.append(f"  - Evidence: {m.get('evidence', '')}")
        L.append(f"\n**Convergent evolution:** {delta.get('convergent_evolution', '')}")
        L.append(f"**Limitations:** {_fmt_list(delta.get('limitations'))}")
    elif delta_key == "L10a_jobs":
        L.append(f"**Value assessment:** {delta.get('value_assessment', '')}")
        L.append(f"**Headline:** {delta.get('headline', '')}")
        L.append(f"\n**Publishable now:** {_fmt_list(delta.get('publishable_now'))}")
        L.append(f"**Needs more work:** {_fmt_list(delta.get('needs_more_work'))}")
        L.append(f"\n**Manuscript framing:** {delta.get('manuscript_framing', '')}")
    elif delta_key == "L10b_oppenheimer":
        L.append(f"**Decision:** {delta.get('decision', '')}")
        L.append(f"**Evidence level:** {delta.get('evidence_level', '')}")
        L.append(f"**Reason:** {delta.get('reason', '')}")
        L.append("\n**Next steps:**")
        for s in delta.get("next_steps", []):
            L.append(f"- {s}")
    return "\n".join(L) + "\n" if L else "_Empty delta._\n"


def cmd_aggregate_report(args):
    """L10c Linnaeus: read all delta JSON, generate FINAL_REPORT.md + _CN.md."""
    import json

    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)

    # Read all deltas in DAG order
    deltas = {}
    for delta_key in DELTA_DAG_ORDER:
        persona = DELTA_PERSONA[delta_key]
        delta_path = _delta_file(project_dir, delta_key)
        if delta_path and delta_path.exists():
            try:
                deltas[delta_key] = json.loads(delta_path.read_text(encoding="utf-8"))
            except Exception as e:
                deltas[delta_key] = {"_error": str(e)}
        else:
            deltas[delta_key] = None

    title = fm.get("title", args.cand_id)
    question = fm.get("question", "")
    claim = fm.get("claim", "")
    status = fm.get("current_status", "?")

    # --- English report ---
    en = []
    en.append(f"# Final Report: {title}\n")
    en.append(f"**Candidate:** {args.cand_id}")
    en.append(f"**Status:** {status}")
    en.append(f"**Generated:** {_now()}")
    en.append(f"**Framework:** RLR v{__version__}\n")
    en.append(f"## Scientific Question\n\n{question}\n")
    en.append(f"## Claim\n\n{claim}\n")

    for delta_key in DELTA_DAG_ORDER:
        title_en = SECTION_TITLES_EN.get(delta_key, delta_key)
        en.append(f"## {title_en}\n")
        en.append(_format_delta_body(delta_key, deltas.get(delta_key)))
        en.append("")

    final = fm.get("final_decision", "")
    en.append("---\n")
    en.append(f"**Final decision:** {final}\n")
    en.append(f"_Report generated by RLR v{__version__} aggregate-report (L10c Linnaeus)_")

    en_report = "\n".join(en)
    en_path = project_dir / "FINAL_REPORT.md"
    en_path.write_text(en_report, encoding="utf-8")

    # --- Chinese report ---
    cn = []
    cn.append(f"# \u6700\u7ec8\u62a5\u544a: {title}\n")
    cn.append(f"**\u5019\u9009\u7f16\u53f7:** {args.cand_id}")
    cn.append(f"**\u72b6\u6001:** {status}")
    cn.append(f"**\u751f\u6210\u65f6\u95f4:** {_now()}")
    cn.append(f"**\u6846\u67b6:** RLR v{__version__}\n")
    cn.append(f"## \u79d1\u5b66\u95ee\u9898\n\n{question}\n")
    cn.append(f"## \u4e3b\u5f20\n\n{claim}\n")
    cn.append("> \u6ce8\uff1a\u4ee5\u4e0b delta \u5185\u5bb9\u7531\u5404 persona \u751f\u6210\uff0c\u5982\u672a\u5305\u542b `cn` \u5b57\u6bb5\u5219\u4e3a\u82f1\u6587\u539f\u6587\u3002\u4e0b\u4e00\u8f6e v0.4 \u5faa\u73af\u5c06\u8981\u6c42 agent \u540c\u65f6\u8f93\u51fa\u4e2d\u6587\u7248\u672c\u3002\n")
    cn.append("> \u6ce8\uff1a\u4ee5\u4e0b delta \u5185\u5bb9\u7531\u5404 persona \u751f\u6210\uff0c\u5982\u672a\u5305\u542b `cn` \u5b57\u6bb5\u5219\u4e3a\u82f1\u6587\u539f\u6587\u3002\u4e0b\u4e00\u8f6e v0.4 \u5faa\u73af\u5c06\u8981\u6c42 agent \u540c\u65f6\u8f93\u51fa\u4e2d\u6587\u7248\u672c\u3002\n")

    for delta_key in DELTA_DAG_ORDER:
        title_cn = SECTION_TITLES_CN.get(delta_key, delta_key)
        cn.append(f"## {title_cn}\n")
        cn.append(_translate_delta_body_cn(
            _format_delta_body(delta_key, deltas.get(delta_key), lang="cn")))
        cn.append("")

    cn.append("---\n")
    cn.append(f"**\u6700\u7ec8\u51b3\u7b56:** {final}\n")
    cn.append(f"_\u62a5\u544a\u7531 RLR v{__version__} aggregate-report (L10c Linnaeus) \u751f\u6210_")

    cn_report = "\n".join(cn)
    cn_path = project_dir / "FINAL_REPORT_CN.md"
    cn_path.write_text(cn_report, encoding="utf-8")

    found = sum(1 for v in deltas.values() if v is not None)
    print(f"FINAL_REPORT generated:")
    print(f"  EN: {en_path}")
    print(f"  CN: {cn_path}")
    print(f"  deltas found: {found}/{len(DELTA_DAG_ORDER)}")
    return 0


# --- cli --------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="research_loop_v04.py",
        description="Research Loop Room v0.4 - DAG-driven subagent architecture "
                    "(14 nodes, 10 personas, physical context isolation).")
    p.add_argument("--version", action="version", version=f"v{__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # demo
    sp = sub.add_parser("demo", help="generate a v0.4 demo project with DAG structure")
    sp.set_defaults(func=cmd_demo)

    # new-project
    sp = sub.add_parser("new-project", help="create a new v0.4 project folder")
    sp.add_argument("name")
    sp.add_argument("topic", nargs="?", default="")
    sp.set_defaults(func=cmd_new_project)

    # preflight
    sp = sub.add_parser("preflight", help="L0 Linnaeus boot gate (00_Preflight/)")
    sp.add_argument("project_dir")
    sp.add_argument("--force", action="store_true", help="overwrite existing files")
    sp.set_defaults(func=cmd_preflight)

    # check-deps (L0 dependency gate, standalone)
    sp = sub.add_parser("check-deps",
                        help="L0 dependency gate: verify required deps; STOP (non-zero) if missing")
    sp.add_argument("project_dir", nargs="?", default=None,
                    help="project dir (to also check 00_Preflight/dependencies.md)")
    sp.set_defaults(func=cmd_check_deps)

    # new-candidate
    sp = sub.add_parser("new-candidate", help="create a candidate with split frontmatter")
    sp.add_argument("project_dir")
    sp.add_argument("--title", required=True)
    sp.add_argument("--question", required=True, help="scientific question")
    sp.add_argument("--claim", required=True, help="testable claim/hypothesis")
    sp.add_argument("--input", required=True, help="source data description")
    sp.add_argument("--input-alias", dest="input_alias",
                    help="path-free input label for cognitive nodes "
                         "(default: derived from --input)")
    sp.set_defaults(func=cmd_new_candidate)

    # next-step
    sp = sub.add_parser("next-step", help="get next DAG node for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_next_step)

    # assemble-context
    sp = sub.add_parser("assemble-context", help="assemble context text for a DAG node")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True, help="DAG node (e.g. L1)")
    sp.set_defaults(func=cmd_assemble_context)

    # emit-delta
    sp = sub.add_parser("emit-delta", help="validate and save a delta JSON")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True)
    sp.add_argument("--persona", required=True)
    sp.add_argument("--file", required=True, help="delta JSON file to import")
    sp.add_argument("--receipt", help="context_manifest JSON from assemble-context; "
                    "verifies upstream delta hashes if provided")
    sp.set_defaults(func=cmd_emit_delta)

    # route
    sp = sub.add_parser("route", help="hand a candidate to a persona")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--to", required=True, choices=AGENTS)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--action")
    sp.add_argument("--input-files", dest="input_files")
    sp.add_argument("--constraints")
    sp.add_argument("--expected")
    sp.add_argument("--stop")
    sp.set_defaults(func=cmd_route)

    # note
    sp = sub.add_parser("note", help="append a persona note")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--agent", required=True, choices=AGENTS)
    sp.add_argument("--text")
    sp.add_argument("--file", help="read note body from a file")
    sp.set_defaults(func=cmd_note)

    # triage-idea
    sp = sub.add_parser("triage-idea",
                        help="L3 Oppenheimer: IDEA_PROPOSED -> SELECTED/REJECTED")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--decision", required=True, choices=["select", "reject"])
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=cmd_triage_idea)

    # triage-method
    sp = sub.add_parser("triage-method",
                        help="L6 Oppenheimer: METHOD_PROPOSED -> APPROVED/REJECTED")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--decision", required=True, choices=["approve", "reject"])
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=cmd_triage_method)

    # execution-gate
    sp = sub.add_parser("execution-gate",
                        help="reject Execution unless preflight + approved plan exist")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_execution_gate)

    # prepare-turing-workspace
    sp = sub.add_parser("prepare-turing-workspace",
                        help="Path A: build isolated execution workspace for Turing (L7)")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--file", action="append",
                    help="allowlisted input data file to copy into the workspace (repeatable)")
    sp.add_argument("--clean", action="store_true",
                    help="remove existing _turing_workspace_* dirs first")
    sp.set_defaults(func=cmd_prepare_turing_workspace)

    # decision
    sp = sub.add_parser("decision", help="Oppenheimer status change")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--status", required=True, choices=VALID_STATUSES)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--route", help="next owner persona")
    sp.add_argument("--force", action="store_true",
                    help="override the legal-transition guard (manual recovery)")
    sp.set_defaults(func=cmd_decision)

    # aggregate-report
    sp = sub.add_parser("aggregate-report", help="L10c Linnaeus: generate FINAL_REPORT")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_aggregate_report)

    # obsidian-sync
    pr = sub.add_parser("pre-research",
                        help="prepare deep research / literature review / code search context for a node")
    pr.add_argument("project_dir")
    pr.add_argument("cand_id")
    pr.add_argument("--node", required=True,
                    help="which node to prepare research for (L1, L4, L7)")
    pr.add_argument("--output-dir",
                    help="override save dir (default: 02_Agent_Notes/_pre_research/, "
                         "which is where assemble-context reads it from)")
    pr.set_defaults(func=cmd_pre_research)

    sp = sub.add_parser("obsidian-sync", help="sync deltas + report to Obsidian vault")
    sp.add_argument("project_dir")
    sp.add_argument("--vault", help="Obsidian vault root (default: OBSIDIAN_VAULT env var)")
    sp.set_defaults(func=cmd_obsidian_sync)

    # list
    sp = sub.add_parser("list", help="list candidates")
    sp.add_argument("project_dir")
    sp.set_defaults(func=cmd_list)

    # show
    sp = sub.add_parser("show", help="show a candidate file")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_show)

    return p

def main(argv=None):
    # Force UTF-8 stdout/stderr so context/report printing never crashes on a
    # non-default-codepage char (Windows console is often GBK/cp936). Deltas and
    # pre-research routinely contain arrows, em-dashes, Greek, <=, etc.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RLRError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())



