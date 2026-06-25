# Research Loop Room (RLR)

A gated multi-loop scientific council framework. Each research question walks
through a **15-node DAG** (L0-L10c, including **L8.5**), each node run by a named
persona acting as an independent subagent with physical context isolation. Three
**pre-research steps** ground L1/L4/L7 in real literature/code before they run,
and **L0 is a hard dependency gate** that stops the loop if a required dependency
is missing.

> Core principle: cognitive agents are isolated by information invisibility
> (Path B). The execution agent (Turing) is isolated by workspace + command
> allowlist (Path A). We do not pretend spawn_agent is an OS sandbox.

**Current version: v0.4.5** (2026-06-26)

---

## Version history

Each version is described by **what it did**, **what it fixed** vs the prior
version, and **what it added**.

### v0.1 — DELETED
- **Did:** a 7-agent *linear* loop (Idea, Value, Evidence, Falsification,
  Biology, Decision, Execution) with 9 statuses, all agents sharing one context.
- **Why removed:** no skill gate, no method triage, no execution safety, and no
  context isolation. The architecture was judged unsound and deleted (not kept
  for reference).

### v0.2 — DEPRECATED (preserved, still runs)
- **Did:** reworked it into a **gated 10-persona council** (Linnaeus … Jobs) in a
  single shared context, with a decision log and Obsidian sync.
- **Fixed vs v0.1:** added the missing **gates** — L0 skill/preflight gate,
  candidate triage, method triage, and an execution gate (only Turing runs code,
  and only after the gate). Grew 7→10 personas and 9→15 statuses.
- **Added:** gated multi-loop flow, append-only decision log, Obsidian sync.
- **Still wrong:** all 10 personas shared **one context window**, so reasoning
  cross-contaminated (e.g. an idea's author saw the critique of its own idea).
- `research_loop_v02.py` and v0.2 projects are preserved untouched. See
  [README_v0.2.md](README_v0.2.md).

### v0.3 — SUPERSEDED (preserved for reference)
- **Did:** turned every persona into an **isolated subagent** over a **14-node
  DAG** (L0–L10c; L9a/L9b run in parallel).
- **Fixed vs v0.2:** the single-shared-context contamination. Each node now sees
  **only its DAG-allowed inputs** (Path B = context invisibility); execution is
  isolated to a workspace (Path A). Free-form notes were replaced by **structured
  delta JSON** with **recursive schema validation**.
- **Added:** the `next-step` / `assemble-context` / `emit-delta` /
  `prepare-turing-workspace` controller commands; **audit trail** (context
  manifests + run receipts with hashes); declared `tools_policy` +
  `everos_read_scopes`; graded input visibility (`input_alias`); a `decision`
  transition guard (with `--force`); the **loop runner** (`run_loop.py` +
  `orchestrator.py`) with **main-agent / headless / manual** modes, a hybrid
  **StopPolicy**, and child-candidate rounds; bilingual `FINAL_REPORT`; and the
  human-readable Obsidian sync (`sync_to_obsidian.py`). See
  [README_v0.3.md](README_v0.3.md) and [DAG_TOPOLOGY.md](DAG_TOPOLOGY.md).

### v0.4.x — CURRENT
- **Did:** added **three pre-research steps** to the protocol, run *before* their
  node, **without changing the 14-node DAG** — deep research before **L1**,
  method literature review before **L4**, code search before **L7**.
- **Fixed:** pre-research is now actually **injected into `assemble-context`**
  (the initial build wrote it but never embedded it — the feature was inert) and
  is **grounded in the candidate's own question/claim** (the initial build
  ignored the candidate and hard-coded one project's queries). `sync_to_obsidian`
  no longer creates junk directories when `$OBSIDIAN_VAULT` is unset (it now
  **fails loud**) and no longer hard-codes a local results path.
- **Added:** the `pre-research` command; pre-research summaries embedded in
  context and recorded in the manifest (`pre_research` field); run_loop triggers
  + updated main-agent protocol; **end-of-round Obsidian sync is now an explicit,
  required loop step**. `research_loop_v04.py`.
- **v0.4.5:** added the **L8.5 literature-verification node** (Curie-owned;
  verifies L7/L8 results against PubMed/EuropePMC after results exist) + a
  **growable literature database** (`manage_literature_db.py`, cited via Obsidian
  wikilinks); a UTF-8 stdout fix; and a hard **L0 dependency gate** — `preflight`
  / `check-deps` verify required dependencies (**PyYAML, Academic Research skill,
  Zotero, Obsidian vault**, plus per-project deps) and **STOP the loop if any is
  missing** (fail-closed; skills/apps attested via `RLR_*` env vars).

---

## Architecture (v0.4.5)

### DAG topology (15 nodes)

```
        [pre: deep research]   [pre: method review]    [pre: code search]
                v                       v                       v
L0* Linnaeus -> L1 Einstein -> L2 Feynman -> L3 Oppenheimer -> L4 Fisher
  -> L5 Tukey -> L6 Oppenheimer -> L7 Turing -> L8 Curie -> L8.5 Curie (lit-verify)
  -> { L9a Feynman || L9b Darwin } -> L10a Jobs -> L10b Oppenheimer -> L10c Linnaeus

  L0* = boot gate + DEPENDENCY GATE (STOPS the loop if a required dep is missing)
```

- **Pre-research** runs *before* L1/L4/L7 (it does **not** change the DAG; the
  result is embedded into that node's context). See below.
- **L8.5** (Curie's 2nd instance) verifies the computed L7/L8 results against
  **published literature** before falsification/interpretation.
- L9a/L9b run in parallel and cannot see each other. **L7 (Turing) is the only
  execution node** (Path A); all others are cognitive (Path B).
- Status flow adds `AUDITED`: `... EXECUTED --(L8)--> AUDITED --(L8.5)--> UNDER_REVIEW ...`.

### Pre-research (before L1 / L4 / L7) — v0.4

| Before | Step | What it does |
|--------|------|--------------|
| **L1** | deep research | real literature search on the candidate's question (Academic Research skill / PubMed / bioRxiv) → hypotheses are literature-grounded |
| **L4** | method literature review | how others ran similar analyses → method design is grounded |
| **L7** | code search | existing pipelines (GitHub / Bioconductor / CRAN) → reuse, don't rebuild |

`pre-research --node L1|L4|L7` prints a prompt grounded in the candidate's
question; the agent writes the summary to
`02_Agent_Notes/_pre_research/<node>_research.md`, which `assemble-context` embeds
into that node and records in the context manifest (`pre_research` field). Papers
found are added to a **growable literature database** (`manage_literature_db.py`,
`09_Literature_Database/`), cited via Obsidian wikilinks and reused across rounds.

### L0 dependency gate (hard stop) — v0.4.5

`preflight` / `check-deps` verify every required dependency and **STOP (non-zero
exit) if any is missing** — the loop must not proceed past L0, never skip.
Required (framework): **PyYAML**, the **Academic Research skill**, **Zotero**, and
an **Obsidian vault**. Things Python can't introspect (Claude skills, GUI apps)
are *fail-closed* and attested via `RLR_*` env vars (or auto-detected: Zotero
connector port `127.0.0.1:23119`, `$OBSIDIAN_VAULT` path). Projects declare extra
deps (e.g. `- command: Rscript`) in `00_Preflight/dependencies.md`.

### Personas (10 personas across 15 node instances)

| Node | Persona | Title | Role | Isolation |
|------|---------|-------|------|-----------|
| L0 | Linnaeus | Catalog Master | Preflight: scan skills, verify input data, create skill_use_plan | Path B |
| L1 | Einstein | Conceptual Explorer | Generate scientific hypotheses from the question | Path B |
| L2 | Feynman | Blind Critic | Attack L1 hypotheses; identify confounders, diagnostic tests | Path B |
| L3 | Oppenheimer | Decision Maker | Triage: select testable hypotheses, reject weak ones | Path B |
| L4 | Fisher | Method Designer | Design experimental/analysis strategies and scripts | Path B |
| L5 | Tukey | QC Auditor | Critique method design from EDA/QC perspective | Path B |
| L6 | Oppenheimer | Decision Maker | Approve or reject the analysis plan | Path B |
| L7 | Turing | Executor | Execute approved scripts in controlled workspace | **Path A** |
| L8 | Curie | Evidence Auditor | Audit execution results, verify reproducibility | Path B |
| **L8.5** | **Curie** | **Literature Verifier** | **Verify L7/L8 results against PubMed/EuropePMC; grow the literature DB** | Path B |
| L9a | Feynman | Falsifier | Hard falsification of results (statistical/logical) | Path B (parallel with L9b) |
| L9b | Darwin | Biologist | Biological interpretation of results | Path B (parallel with L9a) |
| L10a | Jobs | Value Assessor | Assess value, frame manuscript direction | Path B |
| L10b | Oppenheimer | Decision Maker | Final decision: KEEP / REVISE / DOWNGRADE / DROP | Path B |
| L10c | Linnaeus | Catalog Master | Aggregate all deltas into FINAL_REPORT | Reads all deltas |

### Two isolation paths

**Path B (cognitive agents):** Context embedding. The controller calls
`assemble-context` to build a plain-text block containing only the deltas the
DAG allows for that node, plus stripped candidate frontmatter. This text is
embedded as the `spawn_agent` message. The subagent sees only this text; it has
no filesystem access and no visibility into other nodes' deltas.

**Path A (Turing / execution):** Controlled workspace. The controller calls
`prepare-turing-workspace` to copy allowlisted files via `shutil.copy2` into a
same-disk temporary directory. Turing executes R/Python scripts there. Results
are collected and packaged into an L7 delta JSON.

### Delta JSON (state transfer)

Each subagent outputs a structured delta JSON. The candidate file stays
read-only throughout. State flows between subagents only through delta files.

| Node | Delta file | Key fields |
|------|-----------|------------|
| L0 | `L0_linnaeus_delta.json` | skills_found, input_verified, skill_use_plan, forbidden_shortcuts |
| L1 | `L1_einstein_delta.json` | hypotheses[], key_uncertainty, primary_hypothesis |
| L2 | `L2_feynman_delta.json` | attacks[], confounders[], diagnostic_tests[], verdict |
| L3 | `L3_oppenheimer_delta.json` | selected[], rejected[], reason, route_to |
| L4 | `L4_fisher_delta.json` | strategies[], recommended, scripts_needed[], key_decisions |
| L5 | `L5_tukey_delta.json` | attacks[], qc_checkpoints[], failure_stop_rules[] |
| L6 | `L6_oppenheimer_delta.json` | approved_strategy, analysis_plan{scripts, parameters, outputs} |
| L7 | `L7_turing_delta.json` | scripts_run[], key_results{}, warnings[], failures[] |
| L8 | `L8_curie_delta.json` | evidence_verified[], evidence_level, caveats[] |
| L8.5 | `L8.5_curie_delta.json` | searched_keywords[], papers[]{pmid,title,abstract,comparison,relevance}, summary |
| L9a | `L9a_feynman_delta.json` | falsification_risks[], survives[], falsified[] |
| L9b | `L9b_darwin_delta.json` | module_interpretations[], convergent_evolution, limitations[] |
| L10a | `L10a_jobs_delta.json` | value_assessment, headline, publishable_now[], manuscript_framing |
| L10b | `L10b_oppenheimer_delta.json` | decision, evidence_level, reason, next_steps[] |

Schemas are hardcoded in `research_loop_v04.py` (no external JSON Schema
library). `emit-delta` validates structure **recursively** (container types +
required keys of objects inside lists/dicts) before writing.

### Memory sharing (4 layers)

1. **Delta JSON** (primary, project-internal): the only way project state flows
   between subagents.
2. **Candidate frontmatter** (read-only anchor): candidate_id, title, question,
   claim are stripped and embedded in every subagent context (cognitive nodes
   see only `input_alias`, not the raw data path). The candidate body
   (status/history) is never passed to subagents.
3. **Literature database** (cross-round, project-internal) — `09_Literature_Database/`,
   managed by `manage_literature_db.py`: papers found during pre-research / L8.5,
   deduplicated and cited via Obsidian wikilinks, reused across rounds.
4. **EverOS** (cross-session, optional): durable technical facts (configurable
   endpoint). A subagent MAY search declared `everos_read_scopes` at startup;
   EverOS does NOT store project state.

Not a memory mechanism: no shared context window, no shared variables, no
filesystem access for cognitive agents, no candidate body access.

---

## Commands

| Command | Description |
|---------|-------------|
| `demo` | Generate a demo project walking all 15 nodes |
| `new-project` | Create a v0.4 project folder |
| `preflight` | L0 boot gate: create `00_Preflight/` **+ run the dependency gate (STOPS if a required dep is missing)** |
| `check-deps` | **(v0.4.5)** Standalone L0 dependency gate; non-zero exit = STOP |
| `new-candidate` | Create a candidate with split frontmatter (question/claim) |
| `next-step` | Get next DAG node scheduling packet (JSON) |
| `pre-research` | **(v0.4)** Print the pre-research prompt for L1/L4/L7 (deep research / method review / code search), grounded in the candidate's question |
| `assemble-context` | Build isolated context text for a node (Path B); embeds the pre-research summary for L1/L4/L7 |
| `emit-delta` | Validate and save a subagent's delta JSON |
| `route` | Hand a candidate to a persona |
| `note` | Append a persona note |
| `triage-idea` | L3: IDEA_PROPOSED -> IDEA_SELECTED/REJECTED |
| `triage-method` | L6: METHOD_PROPOSED -> METHOD_APPROVED/REJECTED |
| `execution-gate` | Reject execution unless preflight + approved plan exist |
| `decision` | Oppenheimer status change |
| `aggregate-report` | L10c: generate FINAL_REPORT.md + FINAL_REPORT_CN.md |
| `obsidian-sync` | Copy deltas + report to Obsidian vault |
| `list` | List candidates |
| `show` | Show a candidate file |

### Orchestration loop (for the controlling agent)

```
preflight(PROJECT)              # L0 DEPENDENCY GATE — if it exits non-zero, STOP (do not skip)
step = next-step(PROJECT, CAND)
if step.node in (L1, L4, L7):   # v0.4 pre-research, BEFORE the node
    pre-research(--node step.node)   # deep research / method review / code search
    # write 02_Agent_Notes/_pre_research/<node>_research.md; assemble-context embeds it
if step.node == L8.5:           # v0.4.5 literature verification (Curie)
    verify L7/L8 results vs PubMed/EuropePMC; add papers to the literature DB
if step.is_parallel:        # L9a + L9b
    ctx_a = assemble-context(--node L9a)
    ctx_b = assemble-context(--node L9b)
    spawn both, wait both, emit both deltas
elif step.is_execution:     # L7 Turing
    workspace = prepare-turing-workspace(allowlisted_files)
    result = exec_command("Rscript script.R", workdir=workspace)
    emit-delta(--node L7, delta from result)
else:                       # cognitive layer, Path B
    ctx = assemble-context(--node step.node)
    agent = spawn_agent(message=ctx)
    wait_agent(agent)
    emit-delta(--node step.node, --file agent_output)
# run step.advance_command (triage-idea / triage-method / execution-gate / decision)
# at L10c: aggregate-report  +  sync_to_obsidian (REQUIRED end-of-round step)
# then StopPolicy decides stop / open a child-candidate round (max_rounds)
```

---

## Hard invariants

- **L0 dependency gate: a missing required dependency STOPS the loop — never skip.**
- Only Oppenheimer changes candidate status (via decision/triage commands).
- Only Turing executes code, and only after the execution gate passes.
- Linnaeus runs first (L0); no execution before L0 + L6 complete.
- Candidate file is read-only; state flows only through delta JSON.
- All deltas are append-only and auditable.
- L9a and L9b are mutually invisible.
- Pre-research (L1/L4/L7) and L8.5 literature verification do **not** change the
  14-node decision DAG — they ground it in real literature/code.
- End-of-round Obsidian sync is a required step (it fails loud if no vault).

---

## File structure

```
research_loop/
|-- research_loop_v04.py          # Main controller (v0.4.0, dependency-free) + pre-research
|-- research_loop_v03.py          # Preserved for reference (v0.3.0)
|-- run_loop.py                   # Loop runner (main-agent / headless / manual)
|-- orchestrator.py               # Provider abstraction (headless / manual) + config
|-- MAIN_AGENT_RUN.md             # Main-agent execution protocol
|-- MAIN_AGENT_PROMPT.md          # Paste-ready main-agent startup prompt
|-- RUNNER.md                     # Runner modes + StopPolicy
|-- DAG_TOPOLOGY.md               # Full DAG dependency table (14 nodes, unchanged)
|-- templates/
|   |-- v03_personas/             # 10 persona templates
   `-- v03_layers/               # 14 layer templates (L0-L10c)
`-- ...
```

## Projects

| Project | Version | Status | Description |
|---------|---------|--------|-------------|
| DemoProject_v03 | v0.3 | COMPLETE | Demo walking all 14 DAG nodes |
| Yigene_WGCNA_v03 | v0.3 | KEEP | Convergent co-expression modules in bat + shrew |
| DemoProject_v02 | v0.2 | COMPLETE | v0.2 demo (preserved) |
| Yigene_WGCNA_v02 | v0.2 | KEEP | v0.2 WGCNA analysis (preserved) |

## Environment

- Python 3.13, R 4.6.0, Windows 11 / PowerShell
- Obsidian vault: `OBSIDIAN_VAULT env var`
- EverOS memory: http://localhost:9000 (configure via env vars)
| AGENTS.md: `AGENTS.md (local config)`

