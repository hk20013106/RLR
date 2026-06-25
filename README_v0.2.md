# Research Loop Room v0.2-scaffold

A **gated multi-loop scientific council** for post-analysis reasoning. v0.2 turns
the v0.1 state/log manager into a workflow where ideas, methods, and execution
must pass explicit gates — so future analyses cannot skip skill discovery,
project memory, input manifests, idea/method triage, evidence audit, or decision
logging (the failures exposed by the first real WGCNA loop).

It is still a minimal, **dependency-free** file/structure manager. It does **not**
drive agents automatically and does **not** call external APIs or the Codex /
Claude Code CLIs. Each persona reads its template, fills in a note, and calls the
tool to persist the decision.

> Core principle: Research Loop Room does **not replace skills**. It **routes**
> tasks through skills, **enforces gates**, **records decisions**, and
> **preserves project memory**.

---

## What changed from v0.1

|           | v0.1                                                         | v0.2                                                                             |
| --------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| Script    | `research_loop.py`                                           | `research_loop_v02.py` (copy + extend)                                           |
| Roles     | 7 functional agents                                          | **10 named personas** (council)                                                  |
| Statuses  | 9                                                            | **15** (idea/method/execution/review phased)                                     |
| Structure | linear loop                                                  | **gated multi-loop** (Phases 0–4, Layers 0–10)                                   |
| Gates     | none                                                         | **Boot Gate (L0)** + **Execution Gate (L7)**                                     |
| Dirs      | —                                                            | `00_Preflight/`, `07_Obsidian_Sync/`, 10 persona note dirs                       |
| Commands  | demo/new-project/new-candidate/route/note/decision/list/show | + `preflight`, `triage-idea`, `triage-method`, `execution-gate`, `obsidian-sync` |

**v0.1 compatibility is preserved:** `research_loop.py` and every project it
created are untouched and keep working with the v0.1 commands. v0.2 lives in a
separate script and writes a *superset* directory layout for new projects. The
eight v0.1 command names (`new-project`, `new-candidate`, `route`, `note`,
`decision`, `list`, `show`, `demo`) still exist in v0.2 with the same shape.

---

## The 10 personas (council)

| #   | Persona         | Title                  | Layer(s)     | Can change status? | Can run code?  |
| --- | --------------- | ---------------------- | ------------ | ------------------ | -------------- |
| 1   | **Linnaeus**    | Catalog Master         | L0, L10 sync | no                 | no             |
| 2   | **Einstein**    | Conceptual Explorer    | L1           | no                 | no             |
| 3   | **Feynman**     | Reality Checker        | L2, L9       | no                 | no             |
| 4   | **Oppenheimer** | Cold Director          | L3, L6, L10  | **YES (only)**     | no             |
| 5   | **Fisher**      | Design Architect       | L4           | no                 | no             |
| 6   | **Tukey**       | EDA Scout              | L5           | no                 | no             |
| 7   | **Turing**      | Execution Engine       | L7           | no                 | **YES (only)** |
| 8   | **Curie**       | Evidence Auditor       | L8           | no                 | no             |
| 9   | **Darwin**      | Evolutionary Biologist | L9           | no                 | no             |
| 10  | **Jobs**        | Story Strategist       | L10          | no                 | no             |

Full role definitions (personality, inputs, allowed skills, forbidden actions,
outputs, handoff rules, stop conditions): `templates/v02_personas/`.

---

## The gated loop (Layers 0–10)

```
Phase 0 — Boot Gate
  L0  Skill & Memory Preflight ............ Linnaeus      [BOOT GATE]

Phase 1 — Idea Loop
  L1  Idea Divergence ..................... Einstein
  L2  Idea Falsification .................. Feynman
  L3  Candidate Triage Decision .......... Oppenheimer   (IDEA_SELECTED/REJECTED)

Phase 2 — Method Loop
  L4  Method Brainstorm ................... Fisher
  L5  Method Falsification / Skill Match .. Tukey
  L6  Analysis Plan Decision ............. Oppenheimer   (METHOD_APPROVED/REJECTED)

Phase 3 — Execution
  L7  Execution .......................... Turing        [EXECUTION GATE]

Phase 4 — Result Review Loop
  L8  Evidence Audit ..................... Curie         (STRONG/MODERATE/WEAK/INVALID)
  L9  Result Falsification + Biology ..... Feynman + Darwin
  L10 Value + Final Decision + Memory .... Jobs → Oppenheimer → Linnaeus
```

Layer definitions (entry/exit conditions, activities, outputs): `templates/v02_layers/`.

### Statuses

`NEW → IDEA_PROPOSED → IDEA_SELECTED → METHOD_PROPOSED → METHOD_APPROVED →
NEEDS_EXECUTION → EXECUTED → UNDER_REVIEW → KEEP | REVISE | DOWNGRADE | DROP →
ARCHIVED` (plus `IDEA_REJECTED`, `METHOD_REJECTED`).

---

## The two gates

### Boot Gate (L0 / Linnaeus)

No candidate may route to Execution until `00_Preflight/skill_use_plan.md` and
`00_Preflight/input_manifest.md` exist. Create them with:

```
python research_loop_v02.py preflight PROJECT_DIR
```

### Execution Gate (L7 / Oppenheimer enforces, Turing obeys)

`execution-gate` **rejects** (exit code 1) unless all three hold:

1. `00_Preflight/skill_use_plan.md` exists
2. `00_Preflight/input_manifest.md` exists
3. the candidate holds an approved plan (status `METHOD_APPROVED`)

On PASS the candidate advances to `NEEDS_EXECUTION` and is routed to Turing. This
is the structural fix for "execution jumped too early into writing code."

```
python research_loop_v02.py execution-gate PROJECT_DIR CAND_ID
```

---

## Hard invariants (enforced structurally)

- **Only Oppenheimer changes candidate status** — only `decision`, `triage-idea`,
  `triage-method`, and `execution-gate` mutate `current_status`, and all record
  `decided_by: Oppenheimer`.
- **Only Turing executes code** — execution is gated; no code runs in this tool.
- **Linnaeus runs first**; no Execution route before L0 and L6 are complete.
- Einstein proposes but cannot decide; Feynman attacks but cannot veto; Fisher
  designs but cannot execute; Tukey detects risk but cannot decide; Curie audits
  but writes no manuscript claims; Darwin interprets but cannot replace
  statistics; Jobs shapes presentation but cannot strengthen weak evidence.
- All notes are **append-only and auditable** — no hidden chain-of-thought.

---

## Obsidian sync

Each project has an Obsidian-compatible folder. Raw outputs stay in their results
directories; the sync index **links** to them (`[[../path|name]]`) rather than
duplicating large files. Rebuild any time:

```
python research_loop_v02.py obsidian-sync PROJECT_DIR
# -> 07_Obsidian_Sync/00_Obsidian_Index.md
```

---

## Failure-stop rules

Codified in `00_Preflight/forbidden_shortcuts.md` and Tukey's `failure_stop_rules.md`:
**max 2 retries on the same file-write/debug method**, split monolithic scripts
into modules, and escalate/hand off (e.g. to Claude Code) instead of looping.

---

## Directory layout (v0.2)

```
ResearchLoop_ProjectName/
├─ 00_Project_Index.md
├─ 00_Preflight/                 # L0 boot gate (Linnaeus)
│  ├─ skill_use_plan.md
│  ├─ input_manifest.md
│  ├─ output_manifest.md
│  └─ forbidden_shortcuts.md
├─ 01_Candidates/
├─ 02_Agent_Notes/               # one subdir per persona (10)
│  ├─ Linnaeus/ … ├─ Jobs/
├─ 03_Handoffs/
├─ 04_Analysis_Outputs/          # execution reports, results links
├─ 05_Decision_Log/              # D####_*, candidate_triage_*, analysis_plan_*, final_decision_*
├─ 06_Manuscript_Direction/      # Jobs value/figure/writing
├─ 07_Obsidian_Sync/             # link index (no duplication)
└─ 99_Archive/                   # dropped/archived candidates
```

---

## Commands

```
python research_loop_v02.py demo                          # full 10-persona walk
python research_loop_v02.py new-project NAME [TOPIC]
python research_loop_v02.py preflight PROJECT_DIR [--force]
python research_loop_v02.py new-candidate PROJECT_DIR --title T --input I --claim C
python research_loop_v02.py note PROJECT_DIR CAND --agent PERSONA --text "..."
python research_loop_v02.py route PROJECT_DIR CAND --to PERSONA --reason "..."
python research_loop_v02.py triage-idea PROJECT_DIR CAND --decision select|reject --reason "..."
python research_loop_v02.py triage-method PROJECT_DIR CAND --decision approve|reject --reason "..." [--analysis-needed "..."]
python research_loop_v02.py execution-gate PROJECT_DIR CAND
python research_loop_v02.py decision PROJECT_DIR CAND --status STATUS --reason "..." [--route PERSONA]
python research_loop_v02.py obsidian-sync PROJECT_DIR
python research_loop_v02.py list PROJECT_DIR
python research_loop_v02.py show PROJECT_DIR CAND
```

## Demo walk

`python research_loop_v02.py demo` creates `DemoProject_v02/` and walks one dummy
candidate through every persona:

```
Linnaeus → Einstein → Feynman → Oppenheimer(triage-idea: SELECTED)
  → Fisher → Tukey → Oppenheimer(triage-method: APPROVED)
  → [execution-gate: PASS] → Turing(EXECUTED)
  → Curie → Feynman → Darwin → Jobs → Oppenheimer(KEEP) → Linnaeus(obsidian-sync)
```

---

## Scope (not yet implemented — by design)

- No external APIs; no Codex/Claude Code CLI integration.
- No real WGCNA run — Turing's L7 is a scaffold stub.
- v0.1 is extended, not rewritten.

**Version:** 0.2.0 · scaffold · 2026-06-24
