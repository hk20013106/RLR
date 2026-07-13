<!-- Generated: 2026-07-07 | Project: Research Loop Room v0.6 | Files scanned: 95 | Token estimate: ~950 -->

# Backend Architecture - Research Loop Room (RLR) v0.6

## Project Type

**Multi-Agent Orchestration Engine** - DAG-based research automation with v0.6 divergence-contract hardening, isolated cognitive agents, and controlled execution workspace.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Entry Point: run_loop.py (Loop Orchestrator)               │
│  - Drives research_loop_v04.py (v0.6 engine, filename kept) │
│  - Round execution, StopPolicy, provider dispatch            │
│  - Modes: main_agent / command / headless / manual           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  research_loop_v04.py (v0.6 Divergence-Contract Engine)     │
│  - DAG state machine L0->L10c (15 nodes, 10 personas)       │
│  - Pre-research gate (fail-closed rc=3 for L1/L4)           │
│  - Delta emit + context assembly (Path B isolation)          │
│  - v0.6: loop memory, divergence/branch/method gates        │
│  - Obsidian sync + reporting                                 │
└─────────────────────────────────────────────────────────────┘
        ↓                    ↓                      ↓
┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐
│orchestrator  │  │pitfall_ledger.py │  │ars_card_adapter.py │
│(provider)    │  │(audit trail)     │  │(token firewall)    │
└──────────────┘  └──────────────────┘  └────────────────────┘
```

---

## Core Modules

| Module | File | LOC | Purpose | Coupling |
|--------|------|-----|---------|----------|
| **v0.6 Engine** | `research_loop_v04.py` | 4843 | DAG, gates, CLI, context assembly, schemas | pitfall_ledger, ars_card_adapter |
| **Loop Runner** | `run_loop.py` | 863 | CLI entry, round loop, StopPolicy, provider | research_loop_v04, orchestrator |
| **Orchestrator** | `orchestrator.py` | 399 | Provider abstraction (4 modes) | (none) |
| **Pitfall Ledger** | `pitfall_ledger.py` | 448 | Failure audit, draft->confirmed | (none) |
| **ARS Adapter** | `ars_card_adapter.py` | 79 | ARS output -> paper/method card JSON | research_loop_v04 |
| **Literature DB** | `manage_literature_db.py` | 243 | Cross-round paper dedup + reuse | (none) |
| **Obsidian Sync** | `sync_to_obsidian.py` | 555 | End-of-round vault sync + wikilinks | (none) |
| **Legacy** | `rlr_v05b.py` | 559 | v0.5b prototype (superseded) | (none) |
| **Historical (removed)** | `research_loop_v03.py` | 2433 (historical count) | v0.3 engine; removed from the standalone tree | (none) |

---

## CLI Commands (v0.6)

| Command | Purpose |
|---------|---------|
| `new-project` / `new-candidate` | Create project/candidate |
| `new-candidate --from-memory --loop-type` | v0.6: create from loop-memory seed |
| `preflight` / `check-deps` | L0 boot gate + dependency check |
| `next-step` | Get next DAG node (JSON) |
| `assemble-context` | Build isolated context for a node (Path B) |
| `emit-delta` | Validate + save delta JSON |
| `emit-loop-memory` | v0.6: assemble next_loop_memory.json+md from deltas |
| `branch-status` | v0.6: branch ledger query |
| `modality-scan` | v0.6: modality ledger query |
| `triage-idea` / `triage-method` | L3/L6: select/reject |
| `execution-gate` | Reject execution unless preflight+approved plan |
| `prepare-turing-workspace` | Build isolated workspace (Path A) |
| `aggregate-report` | L10c: FINAL_REPORT_<cand>.md (no clobber) |
| `obsidian-sync` | Sync to Obsidian vault |
| `record-pitfall` / `list-pitfalls` / `pitfall-scan` | Pitfall ledger ops |

---

## v0.6 Gate Functions

| Gate | Function | Line | Triggers On |
|------|----------|------|-------------|
| Pre-research | `_audit_pre_research` | 888 | L1/L4 missing/empty artifact -> rc=3 |
| L0 memory | `_audit_l0_memory` | 4237 | from_memory candidate, hash mismatch |
| L1 divergence | `_audit_divergence` | 4061 | <2 new query families (divergent type) |
| Branch coverage | `_audit_branch_coverage` | 3968 | Prior unexplored branch not statused |
| L4 method | `_audit_l4_methods` | 4208 | Script without method_card grounding |
| L6 traceability | `_audit_l6_traceability` | 4174 | Script without valid grounding ref |
| L7 manifest | `_audit_l7_manifest` | 4126 | Output not mapping to L6 script+branch |
| L10b decision | `_audit_l10_traceability` | 4095 | Missing literature_changed_direction |

---

## Data Flow

### Path A: Execution (Turing, L7 only)
```
L6 delta (approved) -> prepare-turing-workspace (allowlisted files)
  -> subprocess.run (bounded commands) -> L7_turing_delta.json
  -> _exec_manifest/<cand>_L7.json (output hashes)
```

### Path B: Cognitive Agents (L0-L6, L8-L10c)
```
assemble-context(node, persona)
  -> candidate_frontmatter + DAG-allowed deltas (text only)
  -> subagent via provider -> delta JSON
  -> emit-delta (schema validated) -> 02_Agent_Notes/<persona>/
```

### Path C: Cross-Round Memory (v0.6)
```
emit-loop-memory(cand) -> next_loop_memory.json (from L1/L8/L9/L10b + ledgers)
  -> new-candidate --from-memory seed.json --loop-type divergent
  -> L0 prior_loop_memory (hash gate) -> L1 divergence gate (≥2 new families)
  -> branch ledger (all prior branches statused) -> modality ledger
```

---

## Key Data Structures

### Delta JSON (per node, schema-validated)
```json
{"node": "L1", "persona": "Einstein", "candidate_id": "C...",
 "hypotheses": [{"id": "H1", "text": "...", "testable": true}],
 "candidate_branches": [{"id": "b1", "description": "..."}]}
```

### Loop Memory Seed (v0.6, deterministic)
```json
{"source_candidate_id": "...", "terminal_decision": "DOWNGRADE",
 "next_round_hypothesis": "...", "required_new_search_directions": [...],
 "unexplored_branches": [...], "data_modalities_available_unused": [...],
 "paper_card_ids": [...], "method_card_ids": [...], "hashes": {}}
```

### Paper Card (v0.6, token-firewall output)
```json
{"id": "<sha1[:12]>", "pmid": "...", "doi": "...", "title": "...",
 "one_line": "...", "claims_used": [...], "query_family_id": "...", "hash": "..."}
```

### Method Card (v0.6)
```json
{"id": "<sha1[:12]>", "source_paper_card_id": "...", "method_name": "...",
 "data_modality": "...", "key_parameters": {...}, "extracted_from": "full_text"}
```

---

## DAG Topology (15 nodes, L0->L10c)

| Stage | Node | Persona | Role | Isolation |
|-------|------|---------|------|-----------|
| Boot | L0 | Linnaeus | Dependency + memory gate | Path B |
| Hypotheses | L1 | Einstein | Deep lit search + divergence | Path B |
| Attack | L2 | Feynman | Critique hypotheses | Path B |
| Triage | L3 | Oppenheimer | Accept/reject | Path B |
| Design | L4 | Fisher | Method lit review + cards | Path B |
| QC | L5 | Tukey | Data quality check | Path B |
| Approve | L6 | Oppenheimer | Method approval + traceability | Path B |
| Execute | L7 | Turing | Run code (Path A) | **Path A** |
| Audit | L8 | Curie | Results audit | Path B |
| Lit-Verify | L8.5 | Curie | PubMed/EuropePMC verify | Path B |
| Falsify | L9a | Feynman | Statistical falsification | Path B (parallel) |
| Biology | L9b | Darwin | Biological interpretation | Path B (parallel) |
| Value | L10a | Jobs | Manuscript direction | Path B |
| Decide | L10b | Oppenheimer | KEEP/REVISE/DOWNGRADE/DROP | Path B |
| Report | L10c | Linnaeus | Aggregate FINAL_REPORT | Reads all |

---

## Dependencies

- **Python 3.13** (stdlib: json, hashlib, pathlib, argparse, subprocess, re, shutil)
- **PyYAML** (candidate/config parsing)
- **pytest 9.1** (25 tests in tests/test_v06_divergence.py)
- **Academic Research skill** (L1/L4 pre-research)
- **PubMed/EuropePMC API** (L1/L4/L8.5)
- **GitHub API** (L7 code search)
- **Obsidian vault** (sync, wikilinks, literature DB)
- **ARS agents** (synthesis_agent, research_architect_agent)

---

## Execution Modes

| Mode | Entry | Provider | Use Case |
|------|-------|----------|----------|
| main_agent | run_loop.py | Current session (Claude Code/Codex/Hermes) | Interactive |
| command | run_loop.py | External CLI | Batch/automated |
| headless | run_loop.py | Subprocess script | Unattended |
| manual | run_loop.py --provider manual | User stdin | Debug/testing |

---

## Isolation Strategy

**Path B (Cognitive):** Context isolation via DAG-allowed deltas only. No filesystem, no subprocess. Agent sees only what assemble-context provides.

**Path A (Turing):** Controlled temp directory, command allowlist, resource bounds. Results collected as artifacts.

**Information invisibility:** L2 doesn't see L1 until committed. L9a/L9b mutually blind. Only L10c sees everything.

---

## Hard Invariants

1. Missing dependency STOPS loop (L0 gate, never skip)
2. Only Oppenheimer changes candidate status
3. Only Turing executes code, only after gate
4. Candidate file read-only; state via delta JSON only
5. L9a/L9b mutually invisible
6. End-of-round Obsidian sync required
7. v0.6: No delta carries full paper text (card IDs + hashes only)
8. v0.6: next_loop_memory.json deterministic, regenerable
9. v0.6: Divergent loops require ≥2 new query families + all branches statused
10. v0.6: All new schema fields optional; hard-fail only when from_memory=true
