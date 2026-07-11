#!/usr/bin/env python3
"""Research Loop Room V0.5 — canonical gated runtime engine.

This IS the V0.5 runtime. The filename `research_loop_v04.py` is retained only
for import/CLI stability (run_loop.py and the main-agent protocol import it);
it is not a legacy engine. As of V0.5, `assemble-context` enforces the
deep-research gate (`_audit_pre_research`) on the literature deep-research
stages L1 (deep_research) and L4 (literature_review): it fails closed (rc=3)
when their pre-research artifact is missing, empty, a NOT YET RUN placeholder,
or lacks a `## Runtime digest` with a DOI/PMID/URL. There is no path that
treats absent deep research as success. (L7 code-search / L8.5 keep their prior
soft, budget-0 archived behaviour.)

Each persona is an independent subagent with physical context isolation via DAG
topology. Cognitive agents receive context as embedded text (Path B); Turing
executes in a controlled workspace (Path A). Each agent outputs a structured
delta JSON; the candidate file stays read-only. L10c Linnaeus aggregates all
deltas into FINAL_REPORT.

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
import subprocess
import sys
from pathlib import Path

import pitfall_ledger as pl  # additive: pitfall ledger (no DAG/schema coupling)

__version__ = "0.5.0"


from research_loop.errors import RLRError  # inward shim (Phase 1a)

# --- personas ---------------------------------------------------------------

from research_loop.topology import (  # inward shim (Phase 1a)
    AGENTS, DECISION_TRANSITIONS, DAG_NODES, NODE_MAP,
    DAG_SEQUENCE, DELTA_DAG_ORDER,
)

from research_loop.common import (  # inward shim (Phase 2b-1)
    PERSONA_TITLE, _now, _stamp, _input_alias, _everos_scopes_for,
)

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

# --- DAG topology (15 nodes, L9a/L9b parallel) ------------------------------
# Each node: node_id, persona, status_before, status_after_optional,
#            context_inputs, is_parallel, is_execution, advance_command,
#            action_hint


from research_loop.preresearch import (  # inward shim (Phase 3a)
    LIT_RUNTIME_DIGEST_TOKEN_BUDGET, _LIT_PRE_RESEARCH_TYPES, _DOI_PMID_URL_RE, _runtime_digest_budget_error, _extract_section, _estimate_tokens,
)


# Map: node_id -> node dict
from research_loop.preresearch import PRE_RESEARCH_MAP  # inward shim (Phase 2b-1)


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

# Map: node_id -> layer template filename on disk. The files are named
# descriptively (e.g. L7_execution.md), not L7.md, so next-step must map the
# node id to the real filename or the orchestrator gets a dead path.
from research_loop.paths import (  # inward shim (Phase 1b)
    LAYER_TEMPLATE_FILE, PERSONA_TEMPLATE_FILE,
    _layer_template_path, _persona_template_path,
    _candidate_file, _sha256, _audit_dir, _pre_research_file,
)

# Map: persona -> persona template filename on disk (numbered 01..10 in AGENTS
# order, e.g. 02_Einstein.md). next-step must map to the real filename.





# --- delta schemas ----------------------------------------------------------
# Each persona outputs a structured delta JSON. Schemas are Python dicts
# checked by a simple validator (no external JSON Schema library).

from research_loop.delta import (  # inward shim (Phase 2a)
    DELTA_SCHEMAS, DELTA_PERSONA, _validate_delta,
    _delta_file, _candidate_delta_file,
    _delta_for_candidate, _delta_belongs_to_candidate,
)

# Map: delta key -> persona name (for file path resolution)

# DAG order for reading deltas in aggregate-report

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



def _slug(s):
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"^_+|_+$", "", s) or "candidate"














# V0.5 deep-research gate ----------------------------------------------------
# The mandatory gate covers the literature DEEP-RESEARCH stages: L1
# (deep_research) and L4 (literature_review). These must carry a structured
# `## Runtime digest` with at least one resolvable identifier. Code-search (L7)
# and the budget-0 archived-only verification (L8.5) keep their prior soft
# behaviour (their pre-research is not inlined, so a hard gate there would break
# execution-context assembly without adding deep-research safety).




from research_loop.preresearch import (  # inward shim (Phase 3b)
    _validate_pre_research_content, _parse_section_bullets, _parse_pre_research_provenance, _QF_STOP, _query_family_key, _load_query_family_cache, _merge_query_family_cache,
)


from research_loop.gates import (  # inward shim (Phase 3b)
    _audit_pre_research, _audit_branch_coverage, DIVERGENCE_MIN_NEW_QUERY_FAMILIES, _audit_divergence, _audit_l10_traceability, _l6_script_branches, _audit_l7_manifest, _critique_ref_valid, _audit_l6_traceability, _audit_l4_methods, _audit_l0_memory, _audit_l0_contract,
)
from research_loop import l0_contract
from research_loop import l0_intake


# V0.6 pre-research provenance ------------------------------------------------
# Structured evidence-of-search the artifact MUST carry so a deep-research run is
# reviewable: which queries were issued, which tools ran, and how many sources
# were found. PR1 only PARSES + PERSISTS these (into the context manifest); the
# gate that ENFORCES them lands in PR2 -- this function does not judge.






def _next_seq(project_dir, prefix):
    d = Path(project_dir) / "05_Decision_Log"
    n = 0
    if d.exists():
        for f in d.glob(f"{prefix}[0-9]*.md"):
            m = re.match(rf"^{re.escape(prefix)}(\d+)", f.stem)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1

from research_loop.yamlio import (  # inward shim (Phase 3a)
    _yaml_value, _load_yaml_front, _replace_field,
)



from research_loop.context import (  # inward shim (Phase 2b-2)
    strip_candidate_to_frontmatter, _condense_delta, _generate_contract, cmd_assemble_context, _caveman_required_literals, _caveman_lite, _inject_pre_research,
)

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
                "08_Audit", "10_Pitfall_Ledger", "99_Archive"]:
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


# --- templates --------------------------------------------------------------

def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_loop_memory(path):
    """Load + minimally validate a next_loop_memory.json seed. Raises on error."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"loop-memory seed not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"invalid loop-memory seed JSON: {e}")
    required = {"source_candidate_id", "next_round_hypothesis", "required_new_search_directions"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"loop-memory seed missing keys: {sorted(missing)}")
    return data


def _render_extra_front(extra_front):
    """Render additional frontmatter keys. Booleans emit lowercase true/false."""
    if not extra_front:
        return ""
    lines = []
    for k, v in extra_front.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {_yaml_value(v)}")
    return "\n".join(lines) + "\n"


def _candidate_template_v03(cand_id, title, source_input, question, claim,
                            input_alias="", extra_front=None):
    claim_or_question = f"{question} | {claim}"
    alias = input_alias or _input_alias(source_input)
    extra = _render_extra_front(extra_front)
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
{extra}---

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

| alias | full path | key files | format | classification | verified | notes |
|-------|-----------|-----------|--------|----------------|----------|-------|
_READ EACH input alias from candidate frontmatter. One row per input. Fill ALL columns. Do NOT leave template rows._

## Required inputs for execution

_MUST match the input_verified dict in L0 delta. Every alias must have: path, files, format, classification, verified, notes._
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

    write_placeholder = getattr(args, "write_placeholder", False)
    write_synthetic = getattr(args, "write_synthetic", False)

    # Missing file may get a placeholder; existing file should not be overwritten unless --write-placeholder is explicitly passed.
    should_write_placeholder = False
    if write_placeholder:
        should_write_placeholder = True
    elif not write_synthetic:
        if not output_file.exists():
            should_write_placeholder = True

    if should_write_placeholder and research_type in ("deep_research", "literature_review"):
        placeholder_content = f"""# Pre-Research: {research_type.replace('_', ' ').title()} (before {node})

## Runtime digest
NOT YET RUN

## Query log
- NOT YET RUN

## Tool receipt
- tool: none | time: {_now()} | summary: NOT YET RUN

## Source count
0
"""
        output_file.write_text(placeholder_content, encoding="utf-8")

    elif write_synthetic and research_type in ("deep_research", "literature_review"):
        if research_type == "deep_research":
            synthetic_content = f"""# Pre-Research: Deep Literature Search (before {node})

## Key Findings
- Finding 1 (citing [[09_Literature_Database/smith2020|Smith 2020]], 2020)

## Methods Used in Literature
- Method 1

## Gaps Our Study Addresses
- Gap 1

## Runtime digest
- [[09_Literature_Database/smith2020|Smith 2020]] doi:10.1000/abc123 — core finding: X associates with Y.

## Query log
- convergent evolution heart rate
- cardiac co-expression bat (0 results)

## Tool receipt
- tool: pubmed | time: 2026-07-05T10:00:00 | summary: 1 hit

## Source count
1
"""
        else:  # literature_review
            synthetic_content = f"""# Pre-Research: Method Literature Review (before {node})

## Methods Found
- Method 1 (citing [[09_Literature_Database/smith2020|Smith 2020]], parameters/settings used)

## Recommended Approach
- What to adopt and why (referencing papers in the database)

## Pitfalls to Avoid
- Pitfall 1 (how others failed, citing [[09_Literature_Database/smith2020|Smith 2020]])

## Runtime digest
- [[09_Literature_Database/smith2020|Smith 2020]] doi:10.1000/abc123 — core finding: X associates with Y.

## Query log
- WGCNA module preservation cross-species Zsummary
- signed vs unsigned WGCNA network cardiac

## Tool receipt
- tool: pubmed | time: 2026-07-05T10:00:00 | summary: 1 hit

## Source count
1
"""
        output_file.write_text(synthetic_content, encoding="utf-8")

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

## Query log
The ACTUAL search queries you issued (one bullet per query). Record zero-result
queries explicitly; do NOT omit them.
- <query string> (e.g. "0 results" when empty)

## Tool receipt
One bullet per tool call: tool name, timestamp, one-line return summary.
- tool: <name> | time: <ISO-8601> | summary: <what it returned>

## Source count
<integer> — distinct sources actually retrieved (0 is allowed but must be stated).

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

## Query log
The ACTUAL search queries you issued (one bullet per query). Record zero-result
queries explicitly; do NOT omit them.
- <query string> (e.g. "0 results" when empty)

## Tool receipt
One bullet per tool call: tool name, timestamp, one-line return summary.
- tool: <name> | time: <ISO-8601> | summary: <what it returned>

## Source count
<integer> — distinct sources actually retrieved (0 is allowed but must be stated).

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
            p = _delta_for_candidate(project_dir, key, args.cand_id)
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


def cmd_audit_pre_research(args):
    """Audit existing pre-research artifacts in a project directory."""
    project_dir = Path(args.project_dir)
    results = {}
    for node, pr_cfg in PRE_RESEARCH_MAP.items():
        is_lit = pr_cfg.get("type") in _LIT_PRE_RESEARCH_TYPES
        if not is_lit:
            results[node] = {
                "status": "NOT_APPLICABLE",
                "reason": "non-literature node"
            }
            continue

        prf = _pre_research_file(project_dir, node)
        if not prf.exists():
            results[node] = {
                "status": "FAIL",
                "reason": f"artifact missing ({prf.as_posix()})"
            }
            continue

        try:
            text = prf.read_text(encoding="utf-8", errors="replace")
            ok, reason = _validate_pre_research_content(text, pr_cfg)
            if ok:
                results[node] = {
                    "status": "PASS",
                    "reason": ""
                }
            else:
                results[node] = {
                    "status": "FAIL",
                    "reason": reason
                }
        except Exception as e:
            results[node] = {
                "status": "FAIL",
                "reason": f"error reading/parsing: {e}"
            }

    report = {
        "project_dir": project_dir.as_posix(),
        "results": results
    }
    print(json.dumps(report, indent=2))
    return 0
















# --- 2. Pre-research injection mode-aware logic ---



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

        # L0 input_verified completeness check:
        # Each entry must be a dict with path/files/format/classification/verified/notes.
        # Bare strings like "valid" are rejected — Linnaeus must record full info.
        iv = data.get("input_verified", {})
        if not isinstance(iv, dict) or not iv:
            errors.append("L0 input_verified is empty or not a dict. "
                          "Register every input alias from source_input.")
        else:
            required_iv_keys = {"path", "files", "format",
                                "classification", "verified", "notes"}
            valid_classes = {"primary", "fallback", "reference-only", "forbidden"}
            for alias, entry in iv.items():
                if not isinstance(entry, dict):
                    errors.append(
                        f"input_verified['{alias}'] is a bare "
                        f"{type(entry).__name__} ('{entry}'), not a dict. "
                        f"Must contain: {required_iv_keys}")
                    continue
                missing = required_iv_keys - set(entry.keys())
                if missing:
                    errors.append(
                        f"input_verified['{alias}'] missing keys: {missing}")
                if not entry.get("verified", True):
                    cls = entry.get("classification", "primary")
                    if cls in ("primary", "fallback"):
                        errors.append(
                            f"input_verified['{alias}'].verified is false — "
                            f"primary/fallback input must be confirmed")
                cls = entry.get("classification", "")
                if cls and cls not in valid_classes:
                    errors.append(
                        f"input_verified['{alias}'].classification='{cls}', "
                        f"must be one of {valid_classes}")
                if not entry.get("path"):
                    errors.append(
                        f"input_verified['{alias}'].path is empty")
                if not entry.get("files"):
                    cls = entry.get("classification", "primary")
                    if cls in ("primary", "fallback"):
                        errors.append(
                            f"input_verified['{alias}'].files is empty — "
                            f"primary/fallback input must list key filenames")
        # 1. Check Obsidian Vault
        vault = os.environ.get("OBSIDIAN_VAULT")
        if not vault:
            dep_errors.append("Obsidian Vault path is not set in environment variable $OBSIDIAN_VAULT.")
        else:
            expanded_vault = Path(os.path.expandvars(vault)).expanduser()
            if not expanded_vault.is_dir():
                dep_errors.append(f"Obsidian Vault directory does not exist: {vault}")
            elif not (expanded_vault / ".obsidian").is_dir():
                dep_errors.append(
                    f"Obsidian Vault is not a vault root (missing .obsidian): "
                    f"{expanded_vault}")
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

        # v0.6: cross-loop memory gate (no-op for legacy candidates)
        ok_mem, mem_reason = _audit_l0_memory(project_dir, args.cand_id, data)
        if not ok_mem:
            errors.append(f"prior_loop_memory gate: {mem_reason}")

        # strict L0 input-contract gate: the SAME validator as assemble-context
        # L0 (no receipt/echo). A malformed/absent contract rejects the delta
        # (rc=1) at persist time too.
        ok_c, c_reason = _audit_l0_contract(project_dir, args.cand_id)
        if not ok_c:
            errors.append(f"L0 input-contract gate: {c_reason}")

    # v0.6: L4 method-card grounding gate (no-op for legacy candidates)
    if args.node == "L4":
        ok_m, m_reason = _audit_l4_methods(project_dir, args.cand_id, data)
        if not ok_m:
            errors.append(m_reason)

    # v0.6: L6 script-grounding traceability gate (no-op for legacy candidates)
    if args.node == "L6":
        ok_l6, l6_reason = _audit_l6_traceability(project_dir, args.cand_id, data)
        if not ok_l6:
            errors.append(l6_reason)

    # v0.6: L7 execution-traceability gate (no-op for legacy candidates)
    if args.node == "L7":
        ok_l7, l7_reason = _audit_l7_manifest(project_dir, args.cand_id, data)
        if not ok_l7:
            errors.append(l7_reason)

    # v0.6: L10b decision-traceability gate (no-op for legacy candidates)
    if args.node == "L10b":
        ok_l10, l10_reason = _audit_l10_traceability(project_dir, args.cand_id, data)
        if not ok_l10:
            errors.append(l10_reason)

    declared_candidate = data.get("candidate_id")
    if (declared_candidate is not None
            and str(declared_candidate) != str(args.cand_id)):
        errors.append(
            f"candidate_id mismatch: delta declares '{declared_candidate}', "
            f"command targets '{args.cand_id}'")
    data["candidate_id"] = args.cand_id

    # Check for extra keys (candidate_id is universal ownership metadata).
    extra = set(data.keys()) - set(schema.keys()) - {"candidate_id"}
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
    manifest = {}
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
            injected_path = inj.get("path")
            cur = _sha256(injected_path) if injected_path else None
            if cur != inj.get("sha256"):
                mismatches.append(inj.get("delta_key"))
        verification = "pass" if not mismatches else "FAIL"
        if mismatches:
            print("DELTA VALIDATION: REJECT (receipt hash mismatch)",
                  file=sys.stderr)
            print(f"  upstream deltas changed since assemble-context: "
                  f"{', '.join(str(m) for m in mismatches)}", file=sys.stderr)
            return 1

    # New outputs are candidate-owned; canonical legacy files remain untouched.
    out_file = _candidate_delta_file(project_dir, delta_key, args.cand_id)
    if out_file is None:
        out_dir = Path(project_dir) / "02_Agent_Notes" / args.persona
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{args.cand_id}_{delta_key}_delta.json"
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
        "output_delta_path": str(out_file),
        "output_delta_sha256": _sha256(out_file),
        "context_manifest_id": manifest_id,
        "upstream_verification": verification,
        "mismatches": mismatches,
        "caveman_mode": manifest.get("caveman_mode"),
        "original_est_tokens": manifest.get("original_est_tokens"),
        "compressed_est_tokens": manifest.get("compressed_est_tokens"),
        "compression_applied": manifest.get("compression_applied"),
        "required_fields_preserved": manifest.get(
            "required_fields_preserved"),
        "pre_research": manifest.get("pre_research"),
    }
    rr = _audit_dir(project_dir) / f"run_receipt_{args.node}_{receipt_id}.json"
    rr.write_text(json.dumps(run_receipt, indent=2, ensure_ascii=False),
                  encoding="utf-8")

    print(f"DELTA VALIDATION: PASS")
    print(f"  schema: {delta_key}")
    print(f"  written: {out_file}")
    print(f"  run receipt: {rr} (upstream: {verification})")

    # v0.6: after a valid L7 delta, write the execution-traceability manifest.
    if args.node == "L7":
        try:
            _write_exec_manifest(project_dir, args.cand_id, data)
        except Exception:
            pass

    # v0.6: after a valid L1 delta, register this round's query families in the
    # cross-loop cache so a later divergent loop can prove it searched new ground.
    if args.node == "L1":
        try:
            _prf = _pre_research_file(project_dir, "L1")
            if _prf.exists():
                _prov = _parse_pre_research_provenance(_prf.read_text(encoding="utf-8"))
                _fams = {_query_family_key(q) for q in _prov.get("query_log", []) if q.strip()}
                if _fams:
                    _merge_query_family_cache(project_dir, _fams)
        except Exception:
            pass

    # Auto-record L7 pitfalls: extract failures and warnings from delta,
    # record as draft pitfalls so pitfall-scan picks them up next round.
    if args.node == "L7":
        for f_text in data.get("failures", []):
            failure = str(f_text)[:200]
            pl.record_pitfall(project_dir, args.cand_id, args.node,
                              "execution_failure", failure,
                              failure, "", severity="hard_stop",
                              error_class="system")
            pl.record_pitfall(
                project_dir, args.cand_id, "L0", "preflight_gate_candidate",
                f"Previous L7 execution failure: {failure}"[:200],
                failure,
                "Resolve or explicitly waive the previous L7 execution "
                f"failure before passing L0: {failure}",
                severity="hard_stop", error_class="system",
                promoted_to="preflight_gate")
        for w_text in data.get("warnings", []):
            pl.record_pitfall(project_dir, args.cand_id, args.node,
                              "execution_failure", str(w_text)[:200],
                              str(w_text)[:200], "", severity="warn",
                              error_class="agent")
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
    pl.init_ledger(project_dir)
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
    if from_memory:
        if not loop_type:
            print("ERROR: --from-memory requires --loop-type", file=sys.stderr)
            return 2
        try:
            mem = _load_loop_memory(from_memory)
        except (FileNotFoundError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        mem_fields = {
            "from_memory": True, "loop_type": loop_type,
            "prior_candidate": mem["source_candidate_id"],
            "memory_file": str(from_memory),
            "memory_hash": _sha256_file(from_memory),
        }

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

    body = _candidate_template_v03(cand_id, args.title, args.input,
                                   args.question, args.claim,
                                   input_alias=getattr(args, "input_alias", "") or "",
                                   extra_front=mem_fields)
    cf = _candidate_file(project_dir, cand_id)
    cf.write_text(body, encoding="utf-8")
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

    body = _candidate_template_v03(
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
    if missing:
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


def _registered_candidate_inputs(project_dir, cand_id):
    """Resolve only key files registered for this candidate's input aliases."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf)
    aliases = {x.strip() for x in str(fm.get("input_alias", "")).split(",")
               if x.strip()}
    manifest = Path(project_dir) / "00_Preflight" / "input_manifest.md"
    resolved, missing = [], []
    if not manifest.exists():
        return resolved, ["missing required input manifest: 00_Preflight/input_manifest.md"]
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        columns = [x.strip().strip("`") for x in line.strip().strip("|").split("|")]
        if len(columns) < 3 or columns[0] not in aliases:
            continue
        alias, root, key_files = columns[:3]
        root_path = Path(root)
        for raw in key_files.split(";"):
            relative = raw.strip().strip("`")
            if not relative:
                continue
            src = root_path / Path(relative.replace("/", os.sep))
            if src.exists() and src.is_file():
                resolved.append((src, alias, relative))
            else:
                missing.append(
                    f"missing required input: {alias}/{relative} ({src})")
    found_aliases = {alias for _, alias, _ in resolved}
    for alias in sorted(aliases - found_aliases):
        if not any(f"{alias}/" in item for item in missing):
            missing.append(f"missing required input registration for alias: {alias}")
    return resolved, missing


def _approved_execution_scripts(project_dir, cand_id):
    """Resolve exact script names from the candidate-owned L6 analysis plan."""
    delta = _delta_for_candidate(project_dir, "L6_oppenheimer", cand_id)
    if not delta:
        return [], ["missing execution script plan: L6_oppenheimer delta"]
    try:
        data = json.loads(delta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], ["missing execution script plan: unreadable L6_oppenheimer delta"]
    names = data.get("analysis_plan", {}).get("scripts", [])
    roots = [
        Path(project_dir) / "04_Analysis_Outputs",
        Path(project_dir) / "scripts_v05b",
        Path(project_dir) / "02_Agent_Notes" / "Turing",
    ]
    resolved, missing = [], []
    for name in names:
        script_name = Path(str(name)).name
        matches = []
        for root in roots:
            if root.is_dir():
                matches.extend(p for p in root.rglob(script_name)
                               if p.is_file() and "_turing_workspace_" not in str(p))
        matches = sorted(set(matches))
        if len(matches) == 1:
            resolved.append(matches[0])
        elif not matches:
            missing.append(f"missing execution script: {script_name}")
        else:
            missing.append(
                f"ambiguous execution script: {script_name} ({len(matches)} matches)")
    return resolved, missing


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

    ws = project_dir / f"_turing_workspace_{args.cand_id}_{_stamp()}"
    inputs = ws / "inputs"
    for sub in (inputs, ws / "scripts", ws / "results"):
        sub.mkdir(parents=True, exist_ok=True)

    copied, missing, staged_files = [], [], []

    def stage(src, dest, reason):
        src = Path(src)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(str(dest.relative_to(ws)).replace("\\", "/"))
        staged_files.append({
            "original_path": str(src.resolve()),
            "workspace_path": str(dest.resolve()),
            "sha256": _sha256(dest),
            "reason": reason,
            "candidate_id": args.cand_id,
            "node": "L7",
        })

    # Deltas Turing is allowed to see per the DAG (L6 approved plan, L0 skills).
    for delta_key in ("L0_linnaeus", "L6_oppenheimer"):
        df = _delta_for_candidate(project_dir, delta_key, args.cand_id)
        if df and df.exists():
            stage(df, inputs / df.name, f"DAG-allowed {delta_key} delta")
        else:
            missing.append(f"{delta_key} delta")

    # Preflight files (skill plan, manifests, forbidden shortcuts).
    pf = project_dir / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        src = pf / fname
        if src.exists():
            stage(src, inputs / fname, f"L0 preflight allowlist: {fname}")
        else:
            missing.append(f"00_Preflight/{fname}")

    # Candidate-declared inputs: only registered key files enter the workspace.
    registered, input_missing = _registered_candidate_inputs(
        project_dir, args.cand_id)
    missing.extend(input_missing)
    for src, alias, relative in registered:
        dest = inputs / alias / Path(relative.replace("/", os.sep))
        stage(src, dest, f"registered candidate input: {alias}/{relative}")

    # Explicit CLI files remain a narrow additive allowlist.
    for raw in (args.file or []):
        src = Path(raw)
        if src.exists() and src.is_file():
            stage(src, inputs / "explicit" / src.name,
                  "explicit --file allowlist")
        else:
            missing.append(f"allowlisted file not found: {raw}")

    # Candidate-owned L6 plan: stage exact existing script names only.
    approved_scripts, script_missing = _approved_execution_scripts(
        project_dir, args.cand_id)
    missing.extend(script_missing)
    for src in approved_scripts:
        stage(src, ws / "scripts" / src.name,
              "exact script approved by candidate L6 analysis_plan")

    json_manifest = {
        "workspace": str(ws.resolve()),
        "candidate_id": args.cand_id,
        "node": "L7",
        "created_at": _now(),
        "status_at_creation": status,
        "staged_files": staged_files,
        "missing": missing,
    }
    (ws / "WORKSPACE_MANIFEST.json").write_text(
        json.dumps(json_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

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
        return 1
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
    """Delegate to the single human-readable Obsidian sync implementation."""
    import sync_to_obsidian

    rc = sync_to_obsidian.sync_project(
        args.project_dir, vault_dir=getattr(args, "vault", None))
    return 0 if rc == 0 else 2


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
    "L8.5_curie": "L8.5 - Literature Verification (Curie)",
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
    "L8.5_curie": "L8.5 - \u6587\u732e\u9a8c\u8bc1 (Curie)",
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
    # L8.5 Curie literature verification
    ("**Verification verdict:**", "**\u9a8c\u8bc1\u88c1\u51b3\uff1a**"),
    ("**Evidence alignment:**", "**\u8bc1\u636e\u4e00\u81f4\u6027\uff1a**"),
    ("**Literature gaps:**", "**\u6587\u732e\u7a7a\u767d\uff1a**"),
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
    if not isinstance(delta, dict):
        return f"_Unexpected delta type: {type(delta).__name__}_\n"
    if "cn" in delta and lang == "cn":
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
    elif delta_key == "L8.5_curie":
        for p in delta.get("papers_found", []):
            L.append(f"- **{p.get('title', '?')}** ({p.get('journal', '?')}, {p.get('year', '?')})")
            L.append(f"  - Relevance: {p.get('relevance', '')}")
            if p.get("supports"):
                L.append(f"  - Supports: {p.get('supports', '')}")
            if p.get("contradicts"):
                L.append(f"  - Contradicts: {p.get('contradicts', '')}")
        L.append(f"\n**Verification verdict:** {delta.get('verification_verdict', '')}")
        L.append(f"**Evidence alignment:** {delta.get('evidence_alignment', '')}")
        if delta.get("gaps"):
            L.append(f"**Literature gaps:** {_fmt_list(delta.get('gaps'))}")
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
        nh = delta.get("next_round_hypothesis", "")
        if nh:
            L.append(f"\n**下一轮假说 (Next round hypothesis):** {nh}")
            L.append("\n> [硬约束 - HARD CONSTRAINT] L10b 必须基于本轮结果生成新假说，作为下一轮 RLR 循环的起点。")
    return "\n".join(L) + "\n" if L else "_Empty delta._\n"


# --- v0.6 next-loop memory (divergence contract) ----------------------------

SEED_SCHEMA_KEYS = [
    "source_candidate_id", "terminal_node", "terminal_decision", "original_question",
    "previous_hypothesis", "final_reason", "next_round_hypothesis",
    "previous_final_decision", "previous_conclusion", "new_hypothesis",
    "round_id", "parent_round_id",
    "required_new_search_directions", "evidence_kept", "evidence_dropped",
    "explored_branches", "unexplored_branches", "data_modalities_used",
    "data_modalities_available_unused", "paper_card_ids", "method_card_ids", "hashes",
]


from research_loop.ledger import (  # inward shim (Phase 3a)
    _branch_ledger_path, _read_branch_ledger, _modality_ledger_path, _read_modality_ledger, _prior_unexplored_ids,
)












def _list_card_ids(project_dir, cand_id, sub):
    d = Path(project_dir) / "09_Literature_Database" / sub
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def _build_loop_memory(project_dir, cand_id):
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
    branches = l1.get("candidate_branches", []) or []
    bl = _read_branch_ledger(project_dir, cand_id)
    ml = _read_modality_ledger(project_dir, cand_id)
    # Round lineage: the source candidate's round_id (legacy candidates predate
    # it -> default "1"); the next round is +1.
    _src_rid = str(fm.get("round_id") or "1")
    _next_rid = str(int(_src_rid) + 1) if _src_rid.isdigit() else _src_rid
    return {
        "source_candidate_id": cand_id,
        "terminal_node": "L10c",
        "terminal_decision": l10.get("decision", ""),
        "original_question": fm.get("question", ""),
        "previous_hypothesis": l1.get("primary_hypothesis", ""),
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
    """L10c: emit the next_loop_memory seed (JSON + MD) from this candidate's deltas."""
    project_dir = Path(args.project_dir)
    mem = _build_loop_memory(project_dir, args.cand_id)
    out_dir = project_dir / "08_Audit" / "loop_memory"
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"{args.cand_id}_next_loop_memory.json"
    jp.write_text(json.dumps(mem, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    mp = out_dir / f"{args.cand_id}_next_loop_memory.md"
    mp.write_text(_loop_memory_to_md(mem), encoding="utf-8")
    print("loop-memory written:")
    print(f"  {jp}")
    print(f"  {mp}")
    return 0


def _shared_report_owner(shared_path):
    if not shared_path.exists():
        return None
    head = shared_path.read_text(encoding="utf-8")[:200]
    m = re.search(r"candidate (C\w+)", head)
    return m.group(1) if m else None


def _update_reports_index(project_dir, cand_id, status):
    idx = Path(project_dir) / "00_Reports_Index.md"
    lines = idx.read_text(encoding="utf-8").splitlines() if idx.exists() else ["# Reports Index", ""]
    lines = [ln for ln in lines if f"FINAL_REPORT_{cand_id}.md" not in ln]
    lines.append(f"- [{cand_id}](FINAL_REPORT_{cand_id}.md) -- status: {status}")
    idx.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        delta_path = _delta_for_candidate(project_dir, delta_key, args.cand_id)
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
    en.append("![Continuous enhancer Signal per pathway](03_Figures/deltaSignal_pathway_comparison.png)\n")
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
    # v0.6: candidate-scoped canonical report (never clobbered by another candidate)
    en_path = project_dir / f"FINAL_REPORT_{args.cand_id}.md"
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
    cn_path = project_dir / f"FINAL_REPORT_CN_{args.cand_id}.md"
    cn_path.write_text(cn_report, encoding="utf-8")

    # v0.6: shared FINAL_REPORT.md is a pointer to the latest candidate. Candidate-
    # scoped copies above are never overwritten; the shared file advances with an
    # audit NOTE when it changes owner (silence with --force).
    shared = project_dir / "FINAL_REPORT.md"
    prev_owner = _shared_report_owner(shared)
    banner = f"<!-- shared FINAL_REPORT points to candidate {args.cand_id} -->\n"
    if prev_owner and prev_owner != args.cand_id and not getattr(args, "force", False):
        print(f"NOTE: repointing FINAL_REPORT.md from {prev_owner} to {args.cand_id} "
              f"(candidate-scoped copies preserved).", file=sys.stderr)
    shared.write_text(banner + en_report, encoding="utf-8")
    (project_dir / "FINAL_REPORT_CN.md").write_text(banner + cn_report, encoding="utf-8")
    _update_reports_index(project_dir, args.cand_id, status)

    found = sum(1 for v in deltas.values() if v is not None)
    print(f"FINAL_REPORT generated:")
    print(f"  EN: {en_path}")
    print(f"  CN: {cn_path}")
    print(f"  shared: {shared}")
    print(f"  deltas found: {found}/{len(DELTA_DAG_ORDER)}")
    return 0


# --- pitfall ledger commands ------------------------------------------------

def cmd_record_pitfall(args):
    """Record (or dedup-merge) a pitfall. Defaults to status=draft -- only L8
    Curie promotes a draft to confirmed (pitfall-status)."""
    try:
        pit = pl.record_pitfall(
            args.project_dir, args.cand_id, args.node, args.category,
            args.symptom, args.root_cause, args.prevention_rule,
            severity=args.severity, evidence=args.evidence or "",
            provider=args.provider or "unknown", status=args.status,
            scope=args.scope, error_class=args.error_class)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"recorded pitfall {pit['id']} "
          f"(scope={pit.get('scope', 'project')} node={pit['node']} "
          f"category={pit['category']} severity={pit['severity']} "
          f"status={pit['status']})")
    return 0


def cmd_list_pitfalls(args):
    scope = "global" if getattr(args, "global_", False) else "project"
    rows = pl.list_pitfalls(args.project_dir, status=args.status, node=args.node,
                            category=args.category, severity=args.severity,
                            scope=scope)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("(no pitfalls)")
        return 0
    for p in rows:
        print(f"[{p['id']}] {p['status']:<14} {p['severity']:<9} "
              f"node={p['node']:<6} {p['category']}")
        print(f"    symptom: {p['symptom']}")
        if p.get("prevention_rule"):
            print(f"    prevent: {p['prevention_rule']}")
    return 0


def cmd_pitfall_scan(args):
    """Scan confirmed/promoted pitfalls relevant to a node/category/provider.
    --gate makes it a hard_stop gate (non-zero exit if a hard_stop applies)."""
    if args.gate:
        passed, blocking = pl.hard_stop_check(
            args.project_dir, node=args.node, category=args.category,
            provider=args.provider)
        for r in blocking:
            print(f"BLOCK [{r['id']}] {r['category']}: {r['rule']}",
                  file=sys.stderr)
        if not passed:
            print("PITFALL GATE: STOP", file=sys.stderr)
            return 3
        print("PITFALL GATE: PASS")
        return 0
    rules = pl.scan_pitfalls(args.project_dir, node=args.node,
                             category=args.category, provider=args.provider)
    if args.json:
        print(json.dumps(rules, indent=2, ensure_ascii=False))
        return 0
    if not rules:
        print("(no relevant pitfalls)")
        return 0
    print(pl.format_pitfall_cards(args.project_dir, node=args.node)
          if args.node else
          json.dumps(rules, indent=2, ensure_ascii=False))
    return 0


def cmd_pitfall_status(args):
    """L8 Curie: mark a draft pitfall confirmed / false_positive / obsolete."""
    try:
        pl.confirm_pitfall(args.project_dir, args.id, args.status,
                           confirmed_by=args.by)
    except (ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"pitfall {args.id} -> {args.status} (by {args.by})")
    return 0


def cmd_promote_pitfall(args):
    """Promote a confirmed pitfall into a durable rule (project or global)."""
    try:
        pl.promote_pitfall(args.project_dir, args.id, args.to, scope=args.scope)
    except (ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    target_dir = (pl.global_ledger_path() if args.scope == "global"
                  else pl.ledger_path(args.project_dir))
    print(f"promoted pitfall {args.id} -> {args.to} (scope={args.scope})")
    if args.to == "regression_test":
        print(f"  regression stub written under {target_dir / pl.TESTS_DIR}")
    print(f"  rules file: {target_dir / pl.RULES_FILE}")
    return 0


# --- cli --------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="research_loop_v04.py",
        description="Research Loop Room V0.5 - canonical gated runtime engine "
                    "(DAG-driven subagent architecture; assemble-context "
                    "enforces the V0.5 deep-research gate).")
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
    sp.add_argument("--from-memory", dest="from_memory", default=None,
                    help="path to a next_loop_memory.json seed (divergence loop)")
    sp.add_argument("--loop-type", dest="loop_type", default=None,
                    choices=["divergent", "correction", "data-acquisition"],
                    help="required with --from-memory")
    sp.add_argument("--round-type", dest="round_type", default=None,
                    choices=["initial", "continuation"],
                    help="explicit round type (default: continuation if "
                         "--from-memory else initial)")
    sp.add_argument("--source-input-file", dest="source_input_file", default=None,
                    help="path to a json/yaml file carrying the source_input "
                         "struct {input_type,files,location,description,format}")
    sp.add_argument("--input-type", dest="input_type", default=None,
                    choices=["files", "directory", "dataset", "inline", "other"],
                    help="source_input.input_type")
    sp.add_argument("--input-files", dest="input_files", action="append",
                    default=None, help="source_input file (repeatable)")
    sp.add_argument("--input-location", dest="input_location", default=None,
                    help="source_input.location (path or dataset id)")
    sp.add_argument("--input-format", dest="input_format", default=None,
                    help="source_input.format (e.g. csv, fastq)")
    sp.set_defaults(func=cmd_new_candidate)

    sp = sub.add_parser("normalize-l0-input",
                        help="normalize a labelled request into a strict L0 contract")
    sp.add_argument("--project", required=True, help="existing RLR project directory")
    sp.add_argument("--input", required=True, help="UTF-8 natural-language request file")
    source = sp.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", help="local data file or directory")
    source.add_argument("--dataset", help="stable remote dataset locator")
    sp.add_argument("--from-memory", help="verified next_loop_memory.json for continuation")
    sp.add_argument("--loop-type", choices=["divergent", "correction", "data-acquisition"],
                    help="required with --from-memory")
    sp.add_argument("--dry-run", action="store_true", help="validate and print without writing")
    sp.add_argument("--run-l0", action="store_true", help="start the canonical runner through L0 only")
    sp.set_defaults(func=cmd_normalize_l0_input)

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
    sp.add_argument("--template-mode", choices=["contract", "refs", "full"],
                    default="contract",
                    help="contract: compact (default, ~200 tokens); refs: path+hash only; full: entire templates (debug only)")
    sp.add_argument("--pre-research-mode", choices=["digest", "excerpt", "full", "none"],
                    default="digest",
                    help="digest: Runtime digest section only (default); excerpt: truncated; full: entire file; none: manifest only")
    sp.add_argument("--pre-research-token-budget", type=int, default=None,
                    help="max tokens for pre-research injection (default: node-specific, e.g. L1=800)")
    sp.add_argument("--context-token-budget", type=int, default=8000,
                    help="max estimated tokens for assembled context (default: 8000; 0 disables)")
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

    # emit-loop-memory
    sp = sub.add_parser("emit-loop-memory",
                        help="L10c: emit next_loop_memory seed (JSON+MD) for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_emit_loop_memory)

    # branch-status
    sp = sub.add_parser("branch-status",
                        help="set a branch's exploration status in the ledger")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--branch", required=True)
    sp.add_argument("--description", default="")
    sp.add_argument("--status", required=True, choices=["explored", "partial", "ignored"])
    sp.add_argument("--data-path", dest="data_path", default="")
    sp.add_argument("--why", default="")
    sp.set_defaults(func=cmd_branch_status)

    # modality-scan
    sp = sub.add_parser("modality-scan",
                        help="record used/available data modalities for a candidate")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--used", action="append", default=[])
    sp.add_argument("--available", action="append", default=[])
    sp.set_defaults(func=cmd_modality_scan)

    # aggregate-report
    sp = sub.add_parser("aggregate-report", help="L10c Linnaeus: generate FINAL_REPORT")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--force", action="store_true",
                    help="silence the repoint NOTE when the shared FINAL_REPORT changes owner")
    sp.set_defaults(func=cmd_aggregate_report)

    pr = sub.add_parser("pre-research",
                        help="prepare deep research / literature review / code search context for a node")
    pr.add_argument("project_dir")
    pr.add_argument("cand_id")
    pr.add_argument("--node", required=True,
                    help="which node to prepare research for (L1, L4, L7)")
    pr.add_argument("--output-dir",
                    help="override save dir (default: 02_Agent_Notes/_pre_research/, "
                         "which is where assemble-context reads it from)")
    pr.add_argument("--write-placeholder", action="store_true",
                    help="write initial placeholder template to output file")
    pr.add_argument("--write-synthetic", action="store_true",
                    help="[TEST-ONLY] write completed/synthetic valid pre-research artifact to output file")
    pr.set_defaults(func=cmd_pre_research)

    # audit-pre-research
    sp = sub.add_parser("audit-pre-research",
                        help="Audit pre-research artifacts in a project directory")
    sp.add_argument("project_dir")
    sp.set_defaults(func=cmd_audit_pre_research)

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

    # --- pitfall ledger ---
    sp = sub.add_parser("record-pitfall",
                        help="record (or dedup-merge) a runtime pitfall")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--node", required=True, help="DAG node (e.g. L7) or '*' for global")
    sp.add_argument("--category", required=True,
                    help="e.g. provider_failure | emit_delta_failure | execution_failure | method_flaw")
    sp.add_argument("--symptom", required=True)
    sp.add_argument("--root-cause", dest="root_cause", default="")
    sp.add_argument("--prevention-rule", dest="prevention_rule", default="")
    sp.add_argument("--severity", default="warn",
                    choices=pl.VALID_SEVERITIES)
    sp.add_argument("--evidence", default="", help="path to log/trace/file")
    sp.add_argument("--provider", default="unknown")
    sp.add_argument("--status", default="draft", choices=pl.VALID_STATUSES,
                    help="default draft; only L8 Curie confirms")
    sp.add_argument("--scope", default="project", choices=["project", "global"],
                    help="project ledger (default) or the shared global ledger")
    sp.add_argument("--error-class", dest="error_class", default="agent",
                    choices=pl.VALID_ERROR_CLASSES,
                    help="agent (model/LLM issue) or system (platform/toolchain)")
    sp.set_defaults(func=cmd_record_pitfall)

    sp = sub.add_parser("list-pitfalls", help="list pitfalls (optionally filtered)")
    sp.add_argument("project_dir")
    sp.add_argument("--status", choices=pl.VALID_STATUSES)
    sp.add_argument("--node")
    sp.add_argument("--category")
    sp.add_argument("--severity", choices=pl.VALID_SEVERITIES)
    sp.add_argument("--global", dest="global_", action="store_true",
                    help="list the shared global ledger instead of this project's")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list_pitfalls)

    sp = sub.add_parser("pitfall-scan",
                        help="scan confirmed/promoted pitfalls relevant to a node")
    sp.add_argument("project_dir")
    sp.add_argument("--node")
    sp.add_argument("--category")
    sp.add_argument("--provider")
    sp.add_argument("--gate", action="store_true",
                    help="hard_stop gate: non-zero exit if a hard_stop applies")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_pitfall_scan)

    sp = sub.add_parser("pitfall-status",
                        help="L8 Curie: confirm / false_positive / obsolete a pitfall")
    sp.add_argument("project_dir")
    sp.add_argument("id")
    sp.add_argument("--status", required=True,
                    choices=["confirmed", "false_positive", "obsolete"])
    sp.add_argument("--by", default="Curie")
    sp.set_defaults(func=cmd_pitfall_status)

    sp = sub.add_parser("promote-pitfall",
                        help="promote a confirmed pitfall to a durable rule")
    sp.add_argument("project_dir")
    sp.add_argument("id")
    sp.add_argument("--to", required=True, choices=pl.VALID_PROMOTIONS)
    sp.add_argument("--scope", default="project", choices=["project", "global"],
                    help="project ledger (default) or global (protects all projects)")
    sp.set_defaults(func=cmd_promote_pitfall)

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



