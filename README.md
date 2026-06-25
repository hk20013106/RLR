# Research Loop Room (RLR)

[English](README.md) | [中文](README_CN.md)

**RLR turns a single research question into a structured multi-agent debate.**

You give it a scientific question. RLR walks it through a 15-step pipeline (L0 → L10c) where 10 expert personas — each acting as an isolated subagent — generate hypotheses, critique them, design methods, execute code, audit evidence, verify against literature, and reach a final KEEP / REVISE / DROP decision. No single agent sees the full picture; each sees only what the DAG allows. This prevents bias contamination (e.g., the agent proposing a hypothesis never sees the critique of its own idea until a decision is made).

Three pre-research steps ground the work in real literature (PubMed, EuropePMC) and real code (GitHub, Bioconductor) before the agents run. A dependency gate at L0 stops the loop if required tools are missing.

> **Core principle:** cognitive agents are isolated by information invisibility (Path B). The execution agent (Turing) is isolated by a controlled workspace + command allowlist (Path A). We do not pretend `spawn_agent` is an OS sandbox.

**Current version: v0.4.5** (2026-06-26)

---

## Version history

### v0.4.5 — CURRENT (2026-06-26)

- **Added L8.5 literature-verification node.** After results are computed (L7) and audited (L8), Curie runs a second pass that searches PubMed/EuropePMC to verify findings against published literature, before falsification and interpretation begin.
- **Added L0 dependency gate (hard stop).** `preflight` / `check-deps` verify required dependencies (PyYAML, Academic Research skill, Zotero, Obsidian vault) and STOP the loop if any is missing — fail-closed, never skip.
- **Added growable literature database** (`manage_literature_db.py`). Papers found during pre-research and L8.5 are stored, deduplicated, and reused across rounds via Obsidian wikilinks.
- **Fixed** UTF-8 stdout so `assemble-context` never crashes on non-GBK characters.

### v0.4 — 2026-06-25

- **Added three pre-research steps** (no new DAG nodes): deep literature search before L1, method literature review before L4, code search before L7.
- **Fixed** pre-research injection — the initial build wrote summaries but never embedded them in `assemble-context` (the feature was inert). Pre-research is now grounded in the candidate's own question/claim.
- **Fixed** `sync_to_obsidian` — no longer creates junk directories when `$OBSIDIAN_VAULT` is unset (fails loud) and no longer hard-codes local paths.
- **Added** end-of-round Obsidian sync as an explicit, required loop step.

### v0.3 — SUPERSEDED (2026-06-24)

- **Did:** turned every persona into an isolated subagent over a 14-node DAG (L0–L10c; L9a/L9b parallel).
- **Fixed vs v0.2:** eliminated single-shared-context contamination. Each node now sees only its DAG-allowed inputs.
- **Added:** `next-step` / `assemble-context` / `emit-delta` / `prepare-turing-workspace` commands; structured delta JSON with recursive schema validation; audit trail (context manifests + run receipts with hashes); loop runner (`run_loop.py`) with main-agent / headless / manual modes and hybrid StopPolicy; bilingual FINAL_REPORT.
- Preserved for reference: `research_loop_v03.py`, [DAG_TOPOLOGY.md](DAG_TOPOLOGY.md).

### v0.2 — DEPRECATED (2026-06-23)

- **Did:** reworked the loop into a gated 10-persona council with a decision log and Obsidian sync.
- **Fixed vs v0.1:** added gates — L0 skill/preflight gate, candidate triage, method triage, execution gate (only Turing runs code, only after the gate).
- **Still wrong:** all 10 personas shared one context window, so reasoning cross-contaminated.

### v0.1 — DELETED (2026-06-22)

- **Did:** a 7-agent linear loop with 9 statuses, all agents sharing one context.
- **Why removed:** no skill gate, no method triage, no execution safety, no context isolation. Architecture was judged unsound and deleted.

---

## How it works

### The DAG (15 nodes, L0 → L10c)

```
                    ┌─────────────────────────────────────────────────────┐
                    │              PRE-RESEARCH (before node)                │
                    │  L1: deep literature search    (Academic Research)     │
                    │  L4: method literature review (Academic Research)     │
                    │  L7: code search              (GitHub/Bioconductor)  │
                    └─────────────────────────────────────────────────────┘

 L0   Linnaeus  ──►  L1   Einstein  ──►  L2   Feynman  ──►  L3   Oppenheimer
 (gate)            (hypotheses)        (attack)            (triage)
   │
   └─►  L4   Fisher  ──►  L5   Tukey  ──►  L6   Oppenheimer  ──►  L7   Turing
        (method)          (QC)            (approve)             (execute)
                                                         │
   L8   Curie  ──►  L8.5 Curie  ──►  ┌─ L9a  Feynman  ──┐  ──►  L10a  Jobs
   (audit)          (lit-verify)     │   (falsify)        │       (value)
                                     └─ L9b  Darwin  ────┘  ──►  L10b  Oppenheimer
                                        (biology)                 (decide)
                                                                   │
                                                                   └─► L10c Linnaeus
                                                                       (report)
```

- **L0** is a boot gate + dependency gate. If a required dependency is missing, the loop STOPS.
- **L7 (Turing)** is the only node that runs code. All others are cognitive.
- **L8.5** verifies computed results against published literature.
- **L9a and L9b** run in parallel and cannot see each other.
- **L10c** aggregates everything into a final report.

### What is isolation and why does it matter?

In a normal AI conversation, one agent sees everything — the hypothesis, the critique, the method, the results. This causes bias: if you wrote the hypothesis, you're predisposed to defend it when you see the critique.

RLR solves this with two isolation mechanisms:

**Path B — context invisibility (cognitive agents).** Before each agent runs, the controller calls `assemble-context` to build a plain-text block containing only the deltas the DAG allows for that node. The agent sees only this text. It has no filesystem access and no visibility into other nodes' work. For example, Einstein (L1) never sees Feynman's critique (L2) — only Oppenheimer (L3) sees both, and only after Einstein has already committed its hypotheses.

**Path A — controlled workspace (Turing only).** Turing needs to run code, so it can't be fully isolated by context alone. Instead, the controller copies allowlisted files via `shutil.copy2` into a temporary directory on the same disk. Turing executes R/Python scripts there. Results are collected and packaged into an L7 delta JSON. Turing never touches the project directory directly.

The key insight: **Path B isolates by making information invisible; Path A isolates by constraining the workspace.** Neither pretends that `spawn_agent` is an operating-system sandbox.

### Personas

| Node | Persona | Role | Isolation |
|------|---------|------|-----------|
| L0 | Linnaeus | Preflight: verify dependencies, scan skills, check input data | Path B |
| L1 | Einstein | Generate scientific hypotheses from the research question | Path B |
| L2 | Feynman | Blind-critique L1 hypotheses: find flaws, confounders, missing controls | Path B |
| L3 | Oppenheimer | Triage: select testable hypotheses, reject weak ones | Path B |
| L4 | Fisher | Design analysis strategies and scripts | Path B |
| L5 | Tukey | Critique method design from EDA/QC perspective | Path B |
| L6 | Oppenheimer | Approve or reject the analysis plan | Path B |
| L7 | Turing | Execute approved scripts in a controlled workspace | **Path A** |
| L8 | Curie | Audit execution results, verify reproducibility | Path B |
| L8.5 | Curie | Verify L7/L8 results against PubMed/EuropePMC | Path B |
| L9a | Feynman | Hard falsification of results (statistical/logical) | Path B (parallel) |
| L9b | Darwin | Biological interpretation of results | Path B (parallel) |
| L10a | Jobs | Assess value, frame manuscript direction | Path B |
| L10b | Oppenheimer | Final decision: KEEP / REVISE / DOWNGRADE / DROP | Path B |
| L10c | Linnaeus | Aggregate all deltas into FINAL_REPORT | Reads all deltas |

### State transfer: delta JSON

Agents don't share a context window or filesystem. The only way state moves between them is through structured delta JSON files. The candidate file stays read-only throughout.

Each agent outputs a delta with a strict schema (validated by `emit-delta` before writing). Example — Einstein's delta:

```json
{
  "hypotheses": [{"id": "H1", "text": "...", "testable": true, "rationale": "..."}],
  "key_uncertainty": "...",
  "primary_hypothesis": "H1"
}
```

Schemas are hardcoded in `research_loop_v04.py` — no external JSON Schema library needed.

### Memory layers

1. **Delta JSON** — primary state transfer between agents, project-internal.
2. **Candidate frontmatter** — read-only anchor (question, claim) embedded in every agent's context.
3. **Literature database** — cross-round, papers found during pre-research and L8.5, deduplicated and reused.
4. **EverOS** — optional cross-session durable memory for technical facts (not project state).

---

## Commands

| Command | Description |
|---------|-------------|
| `demo` | Generate a demo project walking all 15 nodes |
| `new-project` | Create a project folder |
| `new-candidate` | Create a candidate with split frontmatter |
| `preflight` | L0 boot gate + dependency gate (STOPS if deps missing) |
| `check-deps` | Standalone dependency check |
| `next-step` | Get next DAG node (JSON) |
| `pre-research` | Print pre-research prompt for L1/L4/L7 |
| `assemble-context` | Build isolated context for a node (Path B) |
| `emit-delta` | Validate and save a delta JSON |
| `triage-idea` | L3: select/reject hypotheses |
| `triage-method` | L6: approve/reject analysis plan |
| `execution-gate` | Reject execution unless preflight + approved plan exist |
| `prepare-turing-workspace` | Build isolated workspace for L7 (Path A) |
| `decision` | Oppenheimer status change |
| `aggregate-report` | L10c: generate FINAL_REPORT (EN + CN) |
| `obsidian-sync` | Sync to Obsidian vault |
| `list` / `show` | List candidates / show a candidate |

---

## Quick start

```bash
# 1. Create a project
python research_loop_v04.py new-project MyProject

# 2. Create a candidate (your research question)
python research_loop_v04.py new-candidate MyProject --title "..." --question "..." --claim "..."

# 3. Run preflight (L0 gate — stops if deps missing)
python research_loop_v04.py preflight MyProject <CAND_ID>

# 4. Run the loop (main-agent mode)
python run_loop.py print-main-agent-prompt MyProject <CAND_ID>
# Paste the output into your host agent (Claude Code / Codex / etc.)
```

See [MAIN_AGENT_RUN.md](MAIN_AGENT_RUN.md) and [MAIN_AGENT_PROMPT.md](MAIN_AGENT_PROMPT.md) for the full orchestration protocol.

---

## File structure

```
research_loop/
├── research_loop_v04.py          # Main controller (v0.4.5)
├── run_loop.py                   # Loop runner (main-agent / headless / manual)
├── orchestrator.py               # Provider abstraction
├── manage_literature_db.py       # Growable literature database
├── sync_to_obsidian.py           # End-of-round Obsidian sync
├── templates/                    # Layer + persona templates
├── MAIN_AGENT_RUN.md             # Main-agent execution protocol
├── MAIN_AGENT_PROMPT.md          # Paste-ready startup prompt
├── RUNNER.md                     # Runner modes + StopPolicy
├── DAG_TOPOLOGY.md               # Full DAG dependency table
└── DemoProject_v03/              # Tracked example (one full walk)
```

Live research projects are gitignored (generated output, not source).

---

## Hard invariants

- **L0 dependency gate: missing dependency STOPS the loop — never skip.**
- Only Oppenheimer changes candidate status.
- Only Turing executes code, only after the execution gate passes.
- Candidate file is read-only; state flows only through delta JSON.
- L9a and L9b are mutually invisible.
- End-of-round Obsidian sync is required.
