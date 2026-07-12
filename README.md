# Research Loop Room (RLR)

[English](README.md) | [中文](README_CN.md)

**RLR turns a single research question into a structured multi-agent debate.**

You give it a scientific question. RLR walks it through a 15-step pipeline (L0 → L10c) where 10 expert personas — each acting as an isolated subagent — generate hypotheses, critique them, design methods, execute code, audit evidence, verify against literature, and reach a final KEEP / REVISE / DROP decision. No single agent sees the full picture; each sees only what the DAG allows. This prevents bias contamination (e.g., the agent proposing a hypothesis never sees the critique of its own idea until a decision is made).

L1, L4, and L8.5 run a verifiable Academic Research Skills (ARS) pass before their node; L7 separately searches reusable code. Each literature run stores a versioned evidence pack rather than trusting a prose summary.

> **Core principle:** cognitive agents are isolated by information invisibility (Path B). The execution agent (Turing) is isolated by a controlled workspace + command allowlist (Path A). We do not pretend `spawn_agent` is an OS sandbox.

**Current version: V0.7** (canonical gated runtime)

**Canonical runtime path:** `python run_loop.py run PROJECT CAND` drives the V0.7
engine (`research_loop_v04.py`, filename retained for import stability). As of
V0.7, `assemble-context` **enforces the deep-research gate** on the literature
deep-research stages **L1, L4, and L8.5**: they **fail closed (rc=3)** unless a
successful ARS CLI receipt, source-database metadata record, and required
located evidence sections are persisted under `09_Literature_Database/evidence_packs/`.
The runner re-raises this as a hard stop; it never treats a handwritten
pre-research note or an environment-variable attestation as proof. The old `rlr_v05b.py` prototype is **LEGACY** (its
gate was promoted into the canonical engine).

**Current additions:** L0 now accepts a strict, auditable normalized input
contract, and the optional Hypothesis Ranking Reliability Layer produces a
separate advisory ranking artifact. Neither addition changes an existing
formal gate or decision.

---

## Version history

### V0.7 — CURRENT (canonical gated runtime)

- **Added verifiable Deep Research evidence packs.** Codex explicitly invokes `$academic-research-suite`; Claude invokes the configured `academic-research-skills` plugin. L1 requires Results/Discussion/Conclusion, L4 requires Methods plus a review-search receipt, and L8.5 requires paper-based result verification. L10 receives located extracts and L10b cites evidence IDs.
- **Added strict L0 intake.** `normalize-l0-input` builds a validated, auditable contract from a request file and explicit data location without guessing paths, IDs, decisions, or conclusions.
- **Added the Hypothesis Ranking Reliability Layer (shadow mode).** It uses paired fair judgments, deterministic scheduling, checkpoints, evidence events, and disagreement reporting under `08_Audit/ranking/`; it never changes formal RLR decisions or gates.

### v0.4.5 — superseded by V0.7 (2026-06-26)

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
                    │  L1/L4/L8.5: ARS evidence packs (Codex or Claude)      │
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

### L0 dependency contract (V0.7)

L0 currently has **four framework-level required dependencies**. The gate is
fail-closed: one missing item stops the loop before L1.

| Dependency | Detection / attestation | Used for |
|------------|-------------------------|----------|
| PyYAML | Python import `yaml` | Contract, frontmatter, and literature-database I/O |
| Academic Research runtime | `00_Preflight/deep_research_runtime.json`: configured CLI + Codex skill manifest or Claude plugin manifest | L1/L4/L8.5 evidence acquisition |
| Zotero connector | `127.0.0.1:23119` or `RLR_ZOTERO` | Reference-manager and citation source |
| Obsidian vault | Existing `$OBSIDIAN_VAULT` path or `RLR_OBSIDIAN` | End-of-round human-readable sync |

Projects may add more required entries in
`00_Preflight/dependencies.md` using `- python:`, `- command:`, or `- env:`;
those entries are additive, not replacements for the four framework checks.

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

### V0.7 node-by-node contract

| Node | Reads | Produces | Formal effect |
|------|-------|----------|---------------|
| L0 Linnaeus | Candidate frontmatter + strict L0 contract | Input verification, skill plan, dependency/preflight audit | Stops on missing dependency or unverified input; advances to `IDEA_PROPOSED` |
| L1 Einstein | Candidate frontmatter + L0 + Results/Discussion/Conclusion evidence | Testable hypotheses and primary hypothesis | Generates the hypothesis delta |
| L2 Feynman | Candidate frontmatter + L1 | Blind attacks, confounders, diagnostic tests | No status change |
| L3 Oppenheimer | L1 + L2 | Selected/rejected hypotheses and rationale | `triage-idea`; optional shadow ranking runs after delta write only |
| L4 Fisher | L1 + L2 + L3 + Methods/review evidence | Strategies, scripts, parameters, outputs | Proposes the analysis plan |
| L5 Tukey | L4 + L2 | QC checkpoints, failure rules, method attacks | No status change |
| L6 Oppenheimer | L4 + L5 | Approved/rejected method plan and modifications | `triage-method`; not a ranking hook |
| L7 Turing | L6 + L0 + prepared allowlisted workspace | Script exit codes, output files, key results | Only node allowed to execute code; `execution-gate` precedes it |
| L8 Curie | L7 + L6 + frontmatter | Evidence audit, reproducibility checks, evidence level | Advances to `AUDITED` |
| L8.5 Curie | L7 + L8 + paper-based verification evidence | Confirmation/contradiction audit and literature records | Advances to review |
| L9a Feynman | L1 + L7 + L8 + L8.5 | Statistical/logical falsification | Parallel; cannot read L9b |
| L9b Darwin | L1 + L7 + L8 + L8.5 | Biological interpretation and limitations | Parallel; cannot read L9a |
| L10a Jobs | Frontmatter + L8/L8.5/L9a/L9b + located L1/L8.5 evidence | Value assessment and manuscript framing | No status change |
| L10b Oppenheimer | L10a + L8/L8.5/L9a/L9b + located evidence | Final decision and cited evidence IDs | `KEEP/REVISE/DOWNGRADE/DROP`; optional shadow ranking runs after delta write |
| L10c Linnaeus | All permitted deltas | English/Chinese FINAL_REPORT and sync inputs | Aggregates; does not execute code or choose a new winner |

The ranking layer is an advisory signal attached after successful L3/L10b delta
emission. It does not participate in `triage-idea`, `triage-method`, or
`decision` transition validation.

### V0.7 runtime layers

1. **Compatibility/dispatch:** `research_loop_v04.py` preserves the historical
   command/import path; `research_loop/cli.py` dispatches to the engine.
2. **DAG contract:** `topology.py` defines nodes, allowed inputs, statuses, and
   transitions; `delta.py` defines structured output schemas.
3. **Context and gates:** `context.py` builds Path B manifests; `gates.py`
   enforces L0 input, pre-research, execution, and traceability checks.
4. **Persistence:** `paths.py`, `yamlio.py`, `ledger.py`, and candidate-owned
   delta files provide isolated, hashable project artifacts.
5. **Execution/providers:** `providers/` selects main-agent, command,
   headless, or manual execution; `api.py` exposes the same operations in
   process; `run_loop.py` drives rounds and StopPolicy.
6. **Specialized layers:** `l0_contract.py`/`l0_intake.py` own strict L0
   normalization; `deep_research.py` owns ARS receipts and immutable paper evidence;
   `ranking.py` owns advisory ranking artifacts and never writes
   formal decision state.

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

Delta schemas live in `research_loop/delta.py` and are validated by the engine;
the historical shim only re-exports the same surface.

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
| `normalize-l0-input` | Normalize an explicit request and data location into the strict L0 contract |
| `check-deps` | Standalone dependency check |
| `next-step` | Get next DAG node (JSON) |
| `pre-research` | Print the legacy research prompt / L7 code-search prompt (literature stages use `deep-research-run`) |
| `deep-research-run` | Invoke configured Codex/Claude ARS and persist a verified evidence pack |
| `audit-literature-evidence` / `literature-report` | Fail-closed evidence audit / source-located report |
| `assemble-context` | Build isolated context for a node (Path B) |
| `emit-delta` | Validate and save a delta JSON |
| `triage-idea` | L3: select/reject hypotheses |
| `triage-method` | L6: approve/reject analysis plan |
| `execution-gate` | Reject execution unless preflight + approved plan exist |
| `prepare-turing-workspace` | Build isolated workspace for L7 (Path A) |
| `decision` | Oppenheimer status change |
| `aggregate-report` | L10c: generate FINAL_REPORT (EN + CN) |
| `obsidian-sync` | Sync to Obsidian vault |
| `ranking-shadow` | Run an isolated, advisory fair ranking for explicit candidates |
| `ranking-benchmark` | Run the free synthetic fair-vs-naive ranking benchmark |
| `ranking-report` | Render a shadow-ranking artifact as JSON or Markdown |
| `list` / `show` | List candidates / show a candidate |

---

## Strict L0 intake and advisory hypothesis ranking

`normalize-l0-input` converts a request file plus an explicit local path (or a
stable remote dataset locator) into a validated L0 contract. It does not infer
paths, IDs, decisions, or conclusions from prose. `--dry-run` writes nothing;
`--run-l0` stops the canonical runner at L0.

```bash
python research_loop_v04.py normalize-l0-input \
  --project MyProject --input request.md --data data_directory --dry-run
```

The **Hypothesis Ranking Reliability Layer** is shadow-only: it ranks an
explicit candidate set with paired A/B and B/A judgments, marks reversals as
`UNCERTAIN`, and writes versioned artifacts, checkpoints, reports, evidence
events, and formal-decision disagreement signals under
`08_Audit/ranking/`. It uses deterministic fake judges by default; a configured
RLR provider is opt-in. Its output never changes candidate selection, status,
or gate pass/fail.

```bash
# Run an isolated L3 or L10b shadow ranking.
python research_loop_v04.py ranking-shadow MyProject --stage L3 \
  --candidate C001 --candidate C002 --seed 7 --match-budget 10

# Exercise the free synthetic benchmark and render a saved artifact.
python research_loop_v04.py ranking-benchmark --gold gold.json --seeds 1,2,3 --match-budget 10
python research_loop_v04.py ranking-report MyProject --run <RUN_ID> --format markdown

# Opt in during a canonical run. L3/L10b only; L6 is deliberately excluded.
python run_loop.py run MyProject C001 --shadow-ranking \
  --shadow-candidate C002 --shadow-seed 7 --shadow-match-budget 10
```

Shadow failures, partial artifacts, and timeouts are audit-recorded and
fail-soft: the existing RLR decision path continues unchanged.

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
├── research_loop_v04.py          # Historical CLI/import compatibility shim
├── research_loop/
│   ├── cli.py                    # Stable CLI dispatch surface
│   ├── engine.py                 # Command handlers and orchestration operations
│   ├── api.py                    # In-process EngineAPI facade
│   ├── topology.py               # DAG nodes, transitions, visibility inputs
│   ├── context.py                # Path B context assembly and manifests
│   ├── gates.py                  # L0/L1/L7/L10 traceability and status gates
│   ├── delta.py                  # Delta schemas and candidate-owned resolution
│   ├── l0_contract.py            # L0 schema, validator, serializer, renderer
│   ├── l0_intake.py              # Rule-based request/data normalizer
│   ├── deep_research.py           # ARS runtime receipts, paper records, evidence packs
│   ├── providers/                # main-agent, command, headless, manual providers
│   ├── ranking.py                # Shadow fair judge, Elo, checkpoint, evidence
│   ├── paths.py / yamlio.py      # Safe paths and YAML/frontmatter I/O
│   ├── ledger.py / presearch.py  # Pitfall/evidence ledgers and pre-research
│   └── errors.py                 # Typed runtime errors
├── run_loop.py                   # Canonical multi-round runner and StopPolicy
├── manage_literature_db.py       # Growable literature database
├── sync_to_obsidian.py           # End-of-round Obsidian sync
├── templates/                    # Layer + persona templates
├── MAIN_AGENT_RUN.md             # Main-agent execution protocol
├── MAIN_AGENT_PROMPT.md          # Paste-ready startup prompt
├── RUNNER.md                     # Runner modes + StopPolicy
├── DAG_TOPOLOGY.md               # Full DAG dependency table
└── DemoProject_v03/              # Tracked example (one full walk)
```

`research_loop_v04.py` remains in the repository because tests and external
automation use its historical path. It delegates to `research_loop.cli` and
does not contain the current engine body; new code should import
`research_loop.engine`, `research_loop.cli`, or `research_loop.api` directly.

Live research projects are gitignored (generated output, not source).

---

## Hard invariants

- **L0 dependency gate: missing dependency STOPS the loop — never skip.**
- Only Oppenheimer changes candidate status.
- Only Turing executes code, only after the execution gate passes.
- Candidate file is read-only; state flows only through delta JSON.
- L9a and L9b are mutually invisible.
- End-of-round Obsidian sync is required.
