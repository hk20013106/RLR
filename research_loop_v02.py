#!/usr/bin/env python3
"""Research Loop Room v0.2-scaffold — gated multi-loop scientific council.

v0.2 turns the v0.1 state/log manager into a *gated* research workflow. It is
still a minimal, dependency-free file/structure manager: it does NOT drive
agents automatically and does NOT call external CLIs/APIs. Each persona (a
human, Hermes, Codex, or Claude Code) reads the persona/layer template, fills
in the note, and calls this tool to persist decisions.

Hard invariants enforced structurally:
  * Only Oppenheimer changes candidate status (decision / triage / gate cmds).
  * Only Turing executes code (execution is gated; no code runs in this tool).
  * Execution is REJECTED unless skill_use_plan + input_manifest exist and the
    candidate holds an approved analysis plan (status METHOD_APPROVED).

v0.1 compatibility: research_loop.py and any project it created are untouched
and keep working. v0.2 writes an extended directory layout (00_Preflight/,
07_Obsidian_Sync/, 10 persona note dirs) into new projects.

Usage:
    python research_loop_v02.py --help
    python research_loop_v02.py demo                  # full 10-persona walk
    python research_loop_v02.py new-project NAME [TOPIC]
    python research_loop_v02.py preflight PROJECT_DIR
    python research_loop_v02.py new-candidate PROJECT_DIR --title T --input I --claim C
    python research_loop_v02.py route PROJECT_DIR CAND_ID --to PERSONA --reason R
    python research_loop_v02.py note PROJECT_DIR CAND_ID --agent PERSONA --text T [--file PATH]
    python research_loop_v02.py triage-idea PROJECT_DIR CAND_ID --decision select|reject --reason R
    python research_loop_v02.py triage-method PROJECT_DIR CAND_ID --decision approve|reject --reason R
    python research_loop_v02.py execution-gate PROJECT_DIR CAND_ID
    python research_loop_v02.py decision PROJECT_DIR CAND_ID --status S --reason R [--route PERSONA]
    python research_loop_v02.py obsidian-sync PROJECT_DIR
    python research_loop_v02.py list PROJECT_DIR
    python research_loop_v02.py show PROJECT_DIR CAND_ID
"""

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

__version__ = "0.2.0"

# --- invariants -------------------------------------------------------------

# Ten v0.2 personas (the scientific council), in council order.
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

# Only Oppenheimer may move a candidate between these (via decision/triage/gate).
VALID_STATUSES = [
    "NEW",
    "IDEA_PROPOSED", "IDEA_REJECTED", "IDEA_SELECTED",
    "METHOD_PROPOSED", "METHOD_REJECTED", "METHOD_APPROVED",
    "NEEDS_EXECUTION", "EXECUTED", "UNDER_REVIEW",
    "KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED",
]
FINAL_STATUSES = {"KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED"}

# Persona who owns each layer (used by templates + index reference).
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
    ("L9",  "Result Falsification + Biology",       "Feynman/Darwin"),
    ("L10", "Value + Final Decision + Memory",      "Jobs/Oppenheimer/Linnaeus"),
]

# Files Linnaeus produces in 00_Preflight/ (the boot gate).
PREFLIGHT_FILES = [
    "skill_use_plan.md", "input_manifest.md",
    "output_manifest.md", "forbidden_shortcuts.md",
]

# --- small helpers ----------------------------------------------------------

def _now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def _stamp():
    # microsecond-resolution stamp -> unique note/handoff ids within one second.
    return _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")

def _date():
    return _dt.datetime.now().strftime("%Y-%m-%d")

def _slug(s):
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"^_+|_+$", "", s) or "candidate"

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

def _yaml_value(v):
    """Render a scalar value as a safe single-line YAML string."""
    if v is None:
        v = ""
    v = str(v).replace("\n", " ").strip()
    if v == "" or re.search(r"[:#{}\[\],&*!|>'\"%@`]|^-| $", v):
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return v

def _candidate_file(project_dir, cand_id):
    return Path(project_dir) / "01_Candidates" / f"{cand_id}.md"

def _next_seq(project_dir, prefix):
    # decision-log files are named "<prefix><NNNN>_<cand_id>.md" (e.g. D0007_C...).
    # Match the zero-padded counter right after the prefix.
    d = Path(project_dir) / "05_Decision_Log"
    n = 0
    if d.exists():
        for f in d.glob(f"{prefix}[0-9]*.md"):
            m = re.match(rf"^{re.escape(prefix)}(\d+)", f.stem)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1

def _replace_field(path, key, value):
    text = path.read_text(encoding="utf-8")
    pat = re.compile(rf"^{re.escape(key)}: .*$", re.M)
    new = f"{key}: {_yaml_value(value)}"
    if pat.search(text):
        text = pat.sub(lambda m: new, text, count=1)
    else:
        text = text.replace("---\n", "---\n" + new + "\n", 1)
    path.write_text(text, encoding="utf-8")

def _mkdirs(project_dir):
    """v0.2 directory layout (superset of v0.1)."""
    p = Path(project_dir)
    for sub in ["00_Preflight", "01_Candidates", "03_Handoffs",
                "04_Analysis_Outputs", "05_Decision_Log",
                "06_Manuscript_Direction", "07_Obsidian_Sync", "99_Archive"]:
        (p / sub).mkdir(parents=True, exist_ok=True)
    for agent in AGENTS:
        (p / "02_Agent_Notes" / agent).mkdir(parents=True, exist_ok=True)
    return p

# --- templates --------------------------------------------------------------

def _candidate_template(cand_id, title, source_input, claim):
    return f"""---
candidate_id: {_yaml_value(cand_id)}
title: {_yaml_value(title)}
source_input: {_yaml_value(source_input)}
claim_or_question: {_yaml_value(claim)}
current_status: NEW
current_owner: Oppenheimer
idea_summary: ""
weakness_summary: ""
method_summary: ""
evidence_level: ""
biology_summary: ""
value_summary: ""
analysis_needed: ""
latest_handoff: ""
final_decision: ""
created_at: {_yaml_value(_now())}
updated_at: {_yaml_value(_now())}
---

# {title}

## Claim / Question

{claim}

## Source Input

{source_input}

## Idea Summary (L1 Einstein / L2 Feynman)

_append via Einstein + Feynman notes_

## Method Summary (L4 Fisher / L5 Tukey)

_append via Fisher + Tukey notes_

## Evidence Summary (L8 Curie)

_append via Curie notes; level = STRONG | MODERATE | WEAK | INVALID_

## Weakness Summary (L2 / L9 Feynman)

_append via Feynman notes_

## Biology Summary (L9 Darwin)

_append via Darwin notes_

## Value / Manuscript (L10 Jobs)

_append via Jobs notes_

## Analysis Needed

_filled by Oppenheimer when approving a plan_

## Decision History

_append-only log of status changes (Oppenheimer only)_

## Latest Handoff

_updated on each route_

## Final Decision

_filled only when a terminal status is reached_
"""

def _index_template(name, topic):
    layers = "\n".join(f"- **{lid} {ltitle}** — {owner}"
                       for lid, ltitle, owner in LAYERS)
    personas = ", ".join(f"{p}｜{PERSONA_TITLE[p]}" for p in AGENTS)
    return f"""---
project_name: {_yaml_value(name)}
topic: {_yaml_value(topic)}
version: {_yaml_value(__version__)}
framework: gated-multi-loop-council
created_at: {_yaml_value(_now())}
---

# {name} — Research Loop Room v0.2 Index

Topic: {topic}

## Council (10 personas)

{personas}

## Gated Loop (Layers 0–10)

{layers}

## Statuses

{", ".join(VALID_STATUSES)}

## Hard Invariants

- Only **Oppenheimer** changes candidate status.
- Only **Turing** executes code, and only after the Execution Gate passes.
- Execution Gate requires: `00_Preflight/skill_use_plan.md`,
  `00_Preflight/input_manifest.md`, and an approved plan (status METHOD_APPROVED).
- **Linnaeus** runs first (L0 boot gate); no route to Execution before L0 + L6.
- Agent notes are append-only and auditable; no hidden chain-of-thought.

## Boot Gate (00_Preflight/)

Run `preflight` before any candidate work: creates skill_use_plan.md,
input_manifest.md, output_manifest.md, forbidden_shortcuts.md.

## Obsidian

Run `obsidian-sync` to (re)build `07_Obsidian_Sync/00_Obsidian_Index.md`,
which links to outputs rather than duplicating them.
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

- **From:** {frm} ({PERSONA_TITLE.get(frm, '?')})
- **To:** {to} ({PERSONA_TITLE.get(to, '?')})
- **Candidate:** {cand_id}
- **Reason:** {reason}

## Required Action

{action}

## Input Files

{inputs or '_none_'}

## Constraints

{constraints or '_none_'}

## Expected Output

{expected or '_none_'}

## Stop Condition

{stop or '_none_'}
"""

def _note_template(project_name, cand_id, agent, text):
    return f"""---
project: {_yaml_value(project_name)}
candidate_id: {_yaml_value(cand_id)}
agent: {_yaml_value(agent)}
title: {_yaml_value(PERSONA_TITLE.get(agent, ''))}
created_at: {_yaml_value(_now())}
---

# {agent}｜{PERSONA_TITLE.get(agent, '')} — Note on {cand_id}

{text}
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
route_to: {_yaml_value(route_to or '')}
created_at: {_yaml_value(_now())}
---

# Decision D{seq:04d} — {cand_id}

- **Kind:** {kind}
- **Decided by:** {agent}
- **From:** {frm_status}
- **To:** {to_status}
- **Reason:** {reason}
- **Next route:** {route_to or '_none (terminal or pending)_'}
"""

def _preflight_template(name, fname):
    title = fname.replace(".md", "").replace("_", " ").title()
    common_head = f"""---
project_name: {_yaml_value(name)}
preflight_file: {_yaml_value(fname)}
owner: Linnaeus
created_at: {_yaml_value(_now())}
---

# {title} — {name}

> Maintained by **Linnaeus｜Catalog Master** (L0 boot gate). Linnaeus organizes
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
| _e.g. raw fastq_ | reads | forbidden | do not touch raw |

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

_Turing updates this via output_manifest_update on execution._
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

def _execution_report_template(project_name, cand_id, inputs, actions,
                               outputs, warnings, failures, next_route):
    eid = "X" + _stamp()
    return f"""---
report_id: {_yaml_value(eid)}
project: {_yaml_value(project_name)}
candidate_id: {_yaml_value(cand_id)}
agent: Turing
created_at: {_yaml_value(_now())}
---

# Execution Report {eid} — {cand_id}

> Written by **Turing｜Execution Engine**. Turing reports exactly what happened
> and draws no scientific conclusion.

## Input Files

{inputs or '_none_'}

## Actions

{actions or '_none_'}

## Output Files

{outputs or '_none_'}

## Warnings

{warnings or '_none_'}

## Failures

{failures or '_none_'}

## Recommended Next Route

{next_route}
"""

# --- core mutators ----------------------------------------------------------

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

def _set_status(project_dir, cand_id, new_status, owner=None):
    cf = _candidate_file(project_dir, cand_id)
    _replace_field(cf, "current_status", new_status)
    if owner:
        _replace_field(cf, "current_owner", owner)
    _replace_field(cf, "updated_at", _now())

# --- commands ---------------------------------------------------------------

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
        _index_template(name, topic), encoding="utf-8")
    print(f"Created v0.2 project: {project_dir.resolve()}")
    print("Next: run `preflight` (Linnaeus L0) before any candidate work.")
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
    print(f"Preflight (Linnaeus L0) for {name}:")
    for f in created:
        print(f"  created  00_Preflight/{f}")
    for f in skipped:
        print(f"  skipped  00_Preflight/{f} (exists; use --force to overwrite)")
    return 0

def cmd_new_candidate(args):
    project_dir = Path(args.project_dir)
    idx = project_dir / "00_Project_Index.md"
    if not idx.exists():
        print(f"ERROR: not a project dir (no 00_Project_Index.md): {project_dir}",
              file=sys.stderr)
        return 2
    cand_id = "C" + _stamp()
    body = _candidate_template(cand_id, args.title, args.input, args.claim)
    cf = _candidate_file(project_dir, cand_id)
    cf.write_text(body, encoding="utf-8")
    _append_decision(project_dir, cand_id, "-", "NEW", "candidate created",
                     agent="Oppenheimer", kind="seed")
    print(cand_id)
    print(f"  -> {cf}")
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

def _require_status(fm, cand_id, expected):
    cur = fm.get("current_status", "?")
    if cur != expected:
        print(f"ERROR: {cand_id} is {cur}, expected {expected} for this triage.",
              file=sys.stderr)
        return False
    return True

def cmd_triage_idea(args):
    """L3 — Oppenheimer: IDEA_PROPOSED -> IDEA_SELECTED | IDEA_REJECTED."""
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
        to, owner = "IDEA_REJECTED", "Oppenheimer"
    seq = _append_decision(project_dir, args.cand_id, frm, to, args.reason,
                           route_to=owner, agent="Oppenheimer",
                           kind="candidate_triage")
    # dedicated triage decision artefact
    (project_dir / "05_Decision_Log" /
     f"candidate_triage_decision_{args.cand_id}.md").write_text(
        _decision_log_template(seq, args.cand_id, frm, to, args.reason, owner,
                               agent="Oppenheimer", kind="candidate_triage"),
        encoding="utf-8")
    _set_status(project_dir, args.cand_id, to, owner)
    print(f"candidate_triage: {frm} -> {to} (route: {owner})")
    return 0

def cmd_triage_method(args):
    """L6 — Oppenheimer: METHOD_PROPOSED -> METHOD_APPROVED | METHOD_REJECTED."""
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
        to, owner = "METHOD_REJECTED", "Fisher"
    seq = _append_decision(project_dir, args.cand_id, frm, to, args.reason,
                           route_to=owner, agent="Oppenheimer",
                           kind="analysis_plan")
    (project_dir / "05_Decision_Log" /
     f"analysis_plan_decision_{args.cand_id}.md").write_text(
        _decision_log_template(seq, args.cand_id, frm, to, args.reason, owner,
                               agent="Oppenheimer", kind="analysis_plan"),
        encoding="utf-8")
    _set_status(project_dir, args.cand_id, to, owner)
    if args.decision == "approve" and args.analysis_needed:
        _replace_field(cf, "analysis_needed", args.analysis_needed)
    print(f"analysis_plan: {frm} -> {to} (route: {owner})")
    if to == "METHOD_APPROVED":
        print("  approved plan recorded; run `execution-gate` before Turing.")
    return 0

def cmd_execution_gate(args):
    """Reject Execution unless preflight files + approved plan exist."""
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
    # gate passes -> Oppenheimer advances to NEEDS_EXECUTION, hands to Turing
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

def cmd_decision(args):
    """Generic Oppenheimer status change (used for EXECUTED/UNDER_REVIEW/final)."""
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
    seq = _append_decision(project_dir, args.cand_id, frm, args.status,
                           args.reason, args.route or "", agent="Oppenheimer",
                           kind="decision")
    _set_status(project_dir, args.cand_id, args.status, args.route or "Oppenheimer")
    if args.status in FINAL_STATUSES:
        _replace_field(cf, "final_decision", f"{args.status}: {args.reason}")
        # mirror final decision artefact
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

def cmd_obsidian_sync(args):
    """Sync project artefacts to Obsidian vault and build a navigable index.

    Copies all .md files from the project into
    <vault>/ResearchLoop/<project_name>/  and writes 00_Obsidian_Index.md
    with vault-internal wikilinks so [[links]] resolve inside Obsidian.
    """
    import shutil

    project_dir = Path(args.project_dir)
    idx = project_dir / "00_Project_Index.md"
    if not idx.exists():
        print(f"ERROR: not a project dir: {project_dir}", file=sys.stderr)
        return 2
    name = _load_yaml_front(idx).get("project_name", project_dir.name)

    # Determine vault path
    vault_str = getattr(args, "vault", None) or r"C:\Users\hk200\Documents\Obsidian Vault"
    vault = Path(vault_str)
    if not vault.exists():
        print(f"WARNING: vault not found: {vault} — writing index only (no copy)", file=sys.stderr)
        vault = None

    # Local sync dir (always created)
    sync = project_dir / "07_Obsidian_Sync"
    sync.mkdir(parents=True, exist_ok=True)

    # Collect all .md files to sync
    sync_subdirs = [
        "00_Preflight", "01_Candidates", "02_Agent_Notes",
        "03_Handoffs", "04_Analysis_Outputs", "05_Decision_Log",
        "06_Manuscript_Direction",
    ]

    # Build vault destination
    vault_dest = None
    copied = 0
    if vault:
        vault_dest = vault / "ResearchLoop" / name
        vault_dest.mkdir(parents=True, exist_ok=True)

    # Copy files preserving subdirectory structure
    for sub in sync_subdirs:
        src_dir = project_dir / sub
        if not src_dir.exists():
            continue
        if vault_dest:
            dst_dir = vault_dest / sub
            dst_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(src_dir.glob("*.md")):
            if vault_dest:
                dst = vault_dest / sub / f.name
                shutil.copy2(f, dst)
                copied += 1

    # Also copy 00_Project_Index.md
    if vault_dest:
        shutil.copy2(idx, vault_dest / "00_Project_Index.md")
        copied += 1

    # Build wikilink index using vault-internal paths
    def _vault_links(subdir):
        src_dir = project_dir / subdir
        if not src_dir.exists():
            return ["_none_"]
        items = sorted(src_dir.glob("*.md"))
        if not items:
            return ["_none_"]
        return [f"- [[{subdir}/{f.stem}|{f.stem}]]" for f in items]

    cand_lines = []
    cdir = project_dir / "01_Candidates"
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            fm = _load_yaml_front(f)
            cand_lines.append(
                f"- [[01_Candidates/{f.stem}|{fm.get('candidate_id', f.stem)}]] "
                f"— **{fm.get('current_status', '?')}** "
                f"(owner {fm.get('current_owner', '?')}) — {fm.get('title', '')}")
    if not cand_lines:
        cand_lines = ["_none_"]

    sections = [
        f"---\nproject_name: {_yaml_value(name)}\nkind: obsidian_index\n"
        f"synced_at: {_yaml_value(_now())}\n---\n",
        f"# {name} — Obsidian Index\n",
        "> Synced to vault. Wikilinks resolve inside Obsidian.\n",
        "## Project\n\n- [[00_Project_Index|Project Index]]\n",
        "## Preflight (L0)\n\n" + "\n".join(_vault_links("00_Preflight")) + "\n",
        "## Candidates\n\n" + "\n".join(cand_lines) + "\n",
        "## Decision Log\n\n" + "\n".join(_vault_links("05_Decision_Log")) + "\n",
        "## Analysis Outputs\n\n" + "\n".join(_vault_links("04_Analysis_Outputs")) + "\n",
        "## Handoffs\n\n" + "\n".join(_vault_links("03_Handoffs")) + "\n",
        "## Manuscript Direction\n\n" + "\n".join(_vault_links("06_Manuscript_Direction")) + "\n",
        "## Agent Notes\n",
    ]
    # Add per-persona note links
    notes_dir = project_dir / "02_Agent_Notes"
    if notes_dir.exists():
        for persona in sorted(d.name for d in notes_dir.iterdir() if d.is_dir()):
            plinks = _vault_links(f"02_Agent_Notes/{persona}")
            if plinks != ["_none_"]:
                sections.append(f"### {persona}\n\n" + "\n".join(plinks) + "\n")

    index_text = "\n".join(sections)

    # Write index to both local sync dir and vault
    out_local = sync / "00_Obsidian_Index.md"
    out_local.write_text(index_text, encoding="utf-8")

    if vault_dest:
        out_vault = vault_dest / "00_Obsidian_Index.md"
        out_vault.write_text(index_text, encoding="utf-8")
        print(f"Obsidian sync -> {out_vault} ({copied} files copied)")
    else:
        print(f"Obsidian sync (index only) -> {out_local}")
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

# --- demo -------------------------------------------------------------------

DEMO_NOTES = {
    "Linnaeus": ("L0 boot gate. Project classified: WGCNA co-expression on "
                 "length-scaled bulk RNA-seq (Rn/Sk/Sm, atrium/ventricle). "
                 "Skills inventory checked; reuse single-cell/bulk QC + WGCNA "
                 "skill/code patterns. Obsidian project folder confirmed. "
                 "Inputs registered: length_scaled_counts.csv = primary, "
                 "sample_metadata_checked.csv = primary, raw fastq = forbidden. "
                 "skill_use_plan + input/output manifests + forbidden_shortcuts "
                 "written. No interpretation performed."),
    "Einstein": ("L1 idea divergence. Deeper question: is there a co-expression "
                 "module whose eigengene tracks the high-heart-rate species "
                 "contrast (Sk/Sm vs Rn) independent of chamber? Candidate "
                 "hypotheses: (a) a conserved 'high-rate' metabolic module; "
                 "(b) chamber-shared remodeling module; (c) species-private "
                 "module. Each is testable via module-trait correlation."),
    "Feynman_idea": ("L2 idea falsification. Risk: module-trait correlation with "
                     "binary species traits is circular if traits encode the same "
                     "grouping used in filtering. Demand: define traits before "
                     "seeing modules; check that 'high-rate' module is not just "
                     "the largest-variance batch axis. Testable with current data "
                     "— yes, but guard against confounding with batch/sex."),
    "Fisher": ("L4 method brainstorm. Plan A: signed-hybrid WGCNA, power by "
               "scale-free fit, module-trait Pearson to species/chamber traits. "
               "Plan B: unsigned WGCNA power=4 (prior verified) + kME hub genes. "
               "Plan C: simple limma DE + GSEA (cheaper diagnostic). Plan B best "
               "tests the module-trait hypothesis and reuses existing code."),
    "Tukey": ("L5 method falsification / QC. n=71 (Rn24/Sk23/Sm24) ok for WGCNA. "
              "Check: batch vs species confound, sex balance, animal_id "
              "pseudoreplication, all-NA binary trait columns (Sk_vs_Rn NA for "
              "Sm). QC checkpoints: soft-threshold plot, sample dendrogram "
              "outliers, module count sanity. Failure-stop: max 2 retries per "
              "script/debug method; split monolithic script into stepA-D."),
    "Turing": ("L7 execution (STUB). Would run stepA_build_network -> "
               "stepB_trait_correlation -> stepC_hub_genes -> stepD_heatmaps "
               "using the approved unsigned/power=4 plan and registered primary "
               "inputs. Modular scripts, checkpoint logs. NOTE: no real run in "
               "scaffold; reports inputs/actions/outputs placeholders only."),
    "Curie": ("L8 evidence audit. Checked: sample filtering (include flag, "
              "AV_group), TMM+voom normalization, top-5000 MAD gene filter, "
              "module eigengenes, NA->0 trait fix. Outputs internally "
              "consistent. The analysis does test the candidate (module-trait "
              "correlation). Evidence level: MODERATE (single cohort, "
              "correlation only)."),
    "Feynman_result": ("L9 result falsification. The 'high-rate' module r with "
                       "high_heart_rate is strong, but species and chamber are "
                       "partially collinear. Requested diagnostic: partial "
                       "correlation controlling for chamber; permutation null "
                       "for module-trait r. Not a false positive on its face, "
                       "but causal language is unwarranted."),
    "Darwin": ("L9 biology. A high-rate metabolic/ECM module tracking Sk/Sm is "
               "biologically plausible (cardiac workload), and consistent with "
               "comparative physiology. Mark as plausible, NOT proven adaptive: "
               "conservation/adaptation claims need >1 contrast and ideally a "
               "third lineage. Enrichment != mechanism."),
    "Jobs": ("L10 value. If MODERATE evidence holds after partial-correlation "
             "diagnostic, this is a supporting main-figure (module-trait "
             "heatmap + hub genes), not a headline adaptation claim. Writing "
             "direction: 'a co-expression module tracks the high-rate species "
             "contrast', framed as hypothesis-generating. Do not overstate."),
}

def cmd_demo(args):
    pd = Path("DemoProject_v02")
    if pd.exists():
        print(f"ERROR: {pd} already exists; remove it first.", file=sys.stderr)
        return 2
    _mkdirs(pd)
    name = "DemoProject_v02"
    (pd / "00_Project_Index.md").write_text(
        _index_template(name, "Yigene WGCNA module-trait scaffold demo"),
        encoding="utf-8")

    # L0 — Linnaeus preflight (boot gate)
    pf = pd / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        (pf / fname).write_text(_preflight_template(name, fname), encoding="utf-8")

    def note(cand, agent, key):
        nid = agent + _stamp()
        (pd / "02_Agent_Notes" / agent / f"{nid}_{cand}.md").write_text(
            _note_template(name, cand, agent, DEMO_NOTES[key]), encoding="utf-8")

    # dummy candidate
    c1 = "C" + _stamp()
    (pd / "01_Candidates" / f"{c1}.md").write_text(
        _candidate_template(
            c1,
            "High-rate co-expression module tracks Sk/Sm vs Rn",
            "length_scaled_counts.csv (primary); sample_metadata_checked.csv (primary)",
            "A WGCNA module eigengene correlates with the high-heart-rate "
            "species contrast (Sk/Sm vs Rn) independent of chamber."),
        encoding="utf-8")
    _append_decision(pd, c1, "-", "NEW", "candidate created",
                     agent="Oppenheimer", kind="seed")

    # L0 Linnaeus note
    note(c1, "Linnaeus", "Linnaeus")

    # Phase 1 — Idea Loop: Einstein -> Feynman -> Oppenheimer triage
    note(c1, "Einstein", "Einstein")
    _append_decision(pd, c1, "NEW", "IDEA_PROPOSED",
                     "Einstein proposed testable module-trait hypotheses",
                     route_to="Feynman", agent="Oppenheimer", kind="decision")
    _set_status(pd, c1, "IDEA_PROPOSED", "Feynman")
    note(c1, "Feynman", "Feynman_idea")
    # Oppenheimer triage-idea -> select
    seq = _append_decision(pd, c1, "IDEA_PROPOSED", "IDEA_SELECTED",
                           "Idea testable with current data after confound guards; select",
                           route_to="Fisher", agent="Oppenheimer",
                           kind="candidate_triage")
    (pd / "05_Decision_Log" / f"candidate_triage_decision_{c1}.md").write_text(
        _decision_log_template(seq, c1, "IDEA_PROPOSED", "IDEA_SELECTED",
                               "Idea testable; select for method loop", "Fisher",
                               agent="Oppenheimer", kind="candidate_triage"),
        encoding="utf-8")
    _set_status(pd, c1, "IDEA_SELECTED", "Fisher")

    # Phase 2 — Method Loop: Fisher -> Tukey -> Oppenheimer triage
    note(c1, "Fisher", "Fisher")
    _append_decision(pd, c1, "IDEA_SELECTED", "METHOD_PROPOSED",
                     "Fisher proposed plans A/B/C; B (unsigned, power=4) preferred",
                     route_to="Tukey", agent="Oppenheimer", kind="decision")
    _set_status(pd, c1, "METHOD_PROPOSED", "Tukey")
    note(c1, "Tukey", "Tukey")
    seq = _append_decision(pd, c1, "METHOD_PROPOSED", "METHOD_APPROVED",
                           "Plan B approved with QC checkpoints + failure-stop rules",
                           route_to="Oppenheimer", agent="Oppenheimer",
                           kind="analysis_plan")
    (pd / "05_Decision_Log" / f"analysis_plan_decision_{c1}.md").write_text(
        _decision_log_template(seq, c1, "METHOD_PROPOSED", "METHOD_APPROVED",
                               "Plan B (unsigned WGCNA, power=4, kME hubs) approved",
                               "Oppenheimer", agent="Oppenheimer",
                               kind="analysis_plan"),
        encoding="utf-8")
    _set_status(pd, c1, "METHOD_APPROVED", "Oppenheimer")
    _replace_field(_candidate_file(pd, c1), "analysis_needed",
                   "Unsigned WGCNA power=4; module-trait Pearson; kME hub genes; "
                   "partial-correlation diagnostic vs chamber.")

    # Phase 3 — Execution Gate then Turing
    pf_ok = ((pf / "skill_use_plan.md").exists() and
             (pf / "input_manifest.md").exists())
    if pf_ok and _load_yaml_front(_candidate_file(pd, c1)).get("current_status") == "METHOD_APPROVED":
        _append_decision(pd, c1, "METHOD_APPROVED", "NEEDS_EXECUTION",
                         "execution gate passed: preflight + approved plan present",
                         route_to="Turing", agent="Oppenheimer",
                         kind="execution_gate")
        _set_status(pd, c1, "NEEDS_EXECUTION", "Turing")
    note(c1, "Turing", "Turing")
    er = _execution_report_template(
        name, c1,
        inputs="length_scaled_counts.csv (primary); sample_metadata_checked.csv (primary)",
        actions=DEMO_NOTES["Turing"],
        outputs="(scaffold stub - no real outputs)",
        warnings="v0.2 scaffold: Turing did not run real WGCNA.",
        failures="",
        next_route="Oppenheimer -> UNDER_REVIEW (Curie/Feynman/Darwin/Jobs)")
    (pd / "04_Analysis_Outputs" / f"X{_stamp()}_{c1}_execution_report.md").write_text(
        er, encoding="utf-8")
    _append_decision(pd, c1, "NEEDS_EXECUTION", "EXECUTED",
                     "Turing reported execution (stub); route to review",
                     route_to="Curie", agent="Oppenheimer", kind="decision")
    _set_status(pd, c1, "EXECUTED", "Curie")

    # Phase 4 — Review Loop: Curie -> Feynman -> Darwin -> Jobs -> Oppenheimer
    _append_decision(pd, c1, "EXECUTED", "UNDER_REVIEW",
                     "result review loop opened", route_to="Curie",
                     agent="Oppenheimer", kind="decision")
    _set_status(pd, c1, "UNDER_REVIEW", "Curie")
    note(c1, "Curie", "Curie")
    note(c1, "Feynman", "Feynman_result")
    note(c1, "Darwin", "Darwin")
    note(c1, "Jobs", "Jobs")
    # manuscript-direction artefact (Jobs)
    (pd / "06_Manuscript_Direction" / f"value_assessment_{c1}.md").write_text(
        _note_template(name, c1, "Jobs", DEMO_NOTES["Jobs"]), encoding="utf-8")

    # Oppenheimer final decision
    seq = _append_decision(pd, c1, "UNDER_REVIEW", "KEEP",
                           "MODERATE evidence; keep as supporting main-figure "
                           "pending partial-correlation diagnostic",
                           route_to="Linnaeus", agent="Oppenheimer",
                           kind="final_decision")
    (pd / "05_Decision_Log" / f"final_decision_{c1}.md").write_text(
        _decision_log_template(seq, c1, "UNDER_REVIEW", "KEEP",
                               "MODERATE evidence; supporting main-figure",
                               "Linnaeus", agent="Oppenheimer",
                               kind="final_decision"),
        encoding="utf-8")
    _set_status(pd, c1, "KEEP", "Linnaeus")
    _replace_field(_candidate_file(pd, c1), "final_decision",
                   "KEEP: MODERATE evidence; supporting main-figure pending diagnostic")
    _replace_field(_candidate_file(pd, c1), "evidence_level", "MODERATE")

    # L10 — Linnaeus syncs to Obsidian
    class _A:  # tiny shim to reuse cmd_obsidian_sync
        project_dir = str(pd)
    cmd_obsidian_sync(_A())

    print("\nDemo v0.2 project created at:", pd.resolve())
    print(f"  candidate: {c1}")
    print("  walk: Linnaeus -> Einstein -> Feynman -> Oppenheimer(triage-idea)")
    print("        -> Fisher -> Tukey -> Oppenheimer(triage-method)")
    print("        -> [execution-gate] -> Turing -> Oppenheimer(EXECUTED)")
    print("        -> Curie -> Feynman -> Darwin -> Jobs -> Oppenheimer(KEEP)")
    print("        -> Linnaeus(obsidian-sync)")
    print(f"\nRun: python research_loop_v02.py list {pd}")
    print(f"     python research_loop_v02.py show {pd} {c1}")
    return 0

# --- cli --------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="research_loop_v02.py",
        description="Research Loop Room v0.2-scaffold — gated multi-loop "
                    "scientific council (10 personas, Layers 0-10).")
    p.add_argument("--version", action="version", version=f"v{__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("demo", help="generate a full 10-persona demo project")
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("new-project", help="create a new v0.2 project folder")
    sp.add_argument("name")
    sp.add_argument("topic", nargs="?", default="")
    sp.set_defaults(func=cmd_new_project)

    sp = sub.add_parser("preflight", help="L0 Linnaeus boot gate (00_Preflight/)")
    sp.add_argument("project_dir")
    sp.add_argument("--force", action="store_true", help="overwrite existing files")
    sp.set_defaults(func=cmd_preflight)

    sp = sub.add_parser("new-candidate", help="create a candidate file")
    sp.add_argument("project_dir")
    sp.add_argument("--title", required=True)
    sp.add_argument("--input", required=True, help="source_input")
    sp.add_argument("--claim", required=True)
    sp.set_defaults(func=cmd_new_candidate)

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

    sp = sub.add_parser("note", help="append a persona note")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--agent", required=True, choices=AGENTS)
    sp.add_argument("--text")
    sp.add_argument("--file", help="read note body from a file")
    sp.set_defaults(func=cmd_note)

    sp = sub.add_parser("triage-idea",
                        help="L3 Oppenheimer: IDEA_PROPOSED -> SELECTED/REJECTED")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--decision", required=True, choices=["select", "reject"])
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=cmd_triage_idea)

    sp = sub.add_parser("triage-method",
                        help="L6 Oppenheimer: METHOD_PROPOSED -> APPROVED/REJECTED")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--decision", required=True, choices=["approve", "reject"])
    sp.add_argument("--reason", required=True)
    sp.add_argument("--analysis-needed", dest="analysis_needed",
                    help="recorded on the candidate when approving")
    sp.set_defaults(func=cmd_triage_method)

    sp = sub.add_parser("execution-gate",
                        help="reject Execution unless preflight + approved plan exist")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_execution_gate)

    sp = sub.add_parser("decision", help="Oppenheimer status change (final/intermediate)")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.add_argument("--status", required=True, choices=VALID_STATUSES)
    sp.add_argument("--reason", required=True)
    sp.add_argument("--route", help="next owner persona")
    sp.set_defaults(func=cmd_decision)

    sp = sub.add_parser("obsidian-sync", help="sync project to Obsidian vault")
    sp.add_argument("project_dir")
    sp.add_argument("--vault", help="Obsidian vault root path (default: C:\\Users\\hk200\\Documents\\Obsidian Vault)")
    sp.set_defaults(func=cmd_obsidian_sync)

    sp = sub.add_parser("list", help="list candidates")
    sp.add_argument("project_dir")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="show a candidate file")
    sp.add_argument("project_dir")
    sp.add_argument("cand_id")
    sp.set_defaults(func=cmd_show)

    return p

def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
