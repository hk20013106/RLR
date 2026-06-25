# Research Loop Room (RLR)

A gated multi-loop scientific council framework. Each research question walks
through a 14-node DAG (L0-L10c), each node run by a named persona acting as an
independent subagent with physical context isolation.

> Core principle: cognitive agents are isolated by information invisibility
> (Path B). The execution agent (Turing) is isolated by workspace + command
> allowlist (Path A). We do not pretend spawn_agent is an OS sandbox.

**Current version: v0.3.0** (2026-06-25)

---

## Version history

| Version | Status | Description |
|----------|--------|-------------|
| v0.1 | **DELETED** | 7-agent linear loop (Idea, Value, Evidence, Falsification, Biology, Decision, Execution) with 9 statuses. Lacked skill gates, method triage, execution safety. Architecture deemed unreasonable; removed. |
| v0.2 | **DEPRECATED** | 10-persona single-context council with gates and Obsidian sync. Still works; `research_loop_v02.py` and existing v0.2 projects preserved untouched. See [README_v0.2.md](README_v0.2.md). |
| v0.3 | **CURRENT** | Subagent physical isolation architecture. 14-node DAG, delta JSON, Path A/B isolation, L9a/L9b parallel. See [README_v0.3.md](README_v0.3.md) and [DAG_TOPOLOGY.md](DAG_TOPOLOGY.md). |

---

## v0.3 Architecture

### DAG topology (14 nodes)

```
L0 Linnaeus -> L1 Einstein -> L2 Feynman -> L3 Oppenheimer
  -> L4 Fisher -> L5 Tukey -> L6 Oppenheimer -> L7 Turing
  -> L8 Curie -> { L9a Feynman || L9b Darwin } -> L10a Jobs
  -> L10b Oppenheimer -> L10c Linnaeus
```

L9a and L9b run in parallel and cannot see each other. L7 (Turing) is the only
execution node. All other nodes are cognitive (no code execution).

### 10 Personas and their roles

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
| L9a | `L9a_feynman_delta.json` | falsification_risks[], survives[], falsified[] |
| L9b | `L9b_darwin_delta.json` | module_interpretations[], convergent_evolution, limitations[] |
| L10a | `L10a_jobs_delta.json` | value_assessment, headline, publishable_now[], manuscript_framing |
| L10b | `L10b_oppenheimer_delta.json` | decision, evidence_level, reason, next_steps[] |

Schemas are hardcoded in `research_loop_v03.py` (no external JSON Schema
library). `emit-delta` validates structure before writing.

### Memory sharing (3 layers)

1. **Delta JSON** (primary, project-internal): the only way project state flows
   between subagents.
2. **Candidate frontmatter** (read-only anchor): candidate_id, title, question,
   claim are stripped and embedded in every subagent context. The candidate
   body (status/history) is never passed to subagents.
3. **EverOS** (cross-session, optional): durable technical facts at
   http://localhost:9000 (configurable). A subagent MAY search EverOS at startup. EverOS does
   NOT store project state.

Not a memory mechanism: no shared context window, no shared variables, no
filesystem access for cognitive agents, no candidate body access.

---

## Commands

| Command | Description |
|---------|-------------|
| `demo` | Generate a demo project walking all 14 nodes |
| `new-project` | Create a v0.3 project folder |
| `preflight` | L0 Linnaeus boot gate (creates 00_Preflight/) |
| `new-candidate` | Create a candidate with split frontmatter (question/claim) |
| `next-step` | Get next DAG node scheduling packet (JSON) |
| `assemble-context` | Build isolated context text for a node (Path B) |
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
step = next-step(PROJECT, CAND)
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
# repeat until L10c -> aggregate-report -> done
```

---

## Hard invariants

- Only Oppenheimer changes candidate status (via decision/triage commands).
- Only Turing executes code, and only after the execution gate passes.
- Linnaeus runs first (L0); no execution before L0 + L6 complete.
- Candidate file is read-only; state flows only through delta JSON.
- All deltas are append-only and auditable.
- L9a and L9b are mutually invisible.

---

## File structure

```
research_loop/
|-- research_loop_v03.py          # Main script (v0.3.0, dependency-free)
|-- research_loop_v02.py          # Preserved (deprecated)
|-- README_v0.3.md                # Detailed v0.3 documentation
|-- README_v0.2.md                # v0.2 documentation
|-- DAG_TOPOLOGY.md               # Full DAG dependency table
|-- HANDOFF_V03_SUBAGENT_ARCHITECTURE.md
|-- templates/
|   |-- v03_personas/             # 10 persona templates
   `-- v03_layers/               # 14 layer templates (L0-L10c)
|-- DemoProject_v03/              # Demo walking all 14 nodes
|-- Yigene_WGCNA_v03/             # Real WGCNA project (status=KEEP)
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

