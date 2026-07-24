"""Markdown templates extracted from the runtime engine."""

from research_loop.common import (
    PERSONA_TITLE, _dep_fix_hint, _input_alias, _now, _render_extra_front,
)
from research_loop.topology import AGENTS, DAG_NODES
from research_loop.yamlio import _yaml_value


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
- Academic Research is verified from `deep_research_runtime.json` by checking
  the configured CLI plus its Codex skill or Claude plugin manifest; it has no
  environment-variable attestation path.
- Attestation env vars: RLR_ZOTERO, RLR_OBSIDIAN (set to 1 to attest), and
  OBSIDIAN_VAULT (path to your vault).
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


def _candidate_template(cand_id, title, source_input, question, claim,
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


def _index_template(name, topic):
    layers = "\n".join(f"- **{lid} {ltitle}** - {owner}"
                       for lid, ltitle, owner in LAYERS)
    personas = ", ".join(f"{p} | {PERSONA_TITLE[p]}" for p in AGENTS)
    return f"""---
project_name: {_yaml_value(name)}
topic: {_yaml_value(topic)}
version: {_yaml_value(__version__)}
framework: gated-multi-loop-council-v07
created_at: {_yaml_value(_now())}
---

# {name} - Research Loop Room V0.7 Index

Topic: {topic}

## Council (10 personas)

{personas}

## DAG Topology (15 nodes L0-L10c)

{layers}

## Statuses

{", ".join(VALID_STATUSES)}

## Hard Invariants

- Only **Oppenheimer** changes candidate status.
- Only **Turing** executes code, and only after the Execution Gate passes.
- Execution Gate requires: `00_Preflight/skill_use_plan.md`,
  `00_Preflight/input_manifest.md`, and an approved plan (status METHOD_APPROVED).
- Each persona runs as an isolated subagent under the V0.7 topology.
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
