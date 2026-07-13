<!-- Generated: 2026-07-07 | Project: Research Loop Room v0.6 | Files scanned: 95 | Token estimate: ~900 -->

# Architecture - Research Loop Room (RLR) v0.6

## Project Type

**Multi-Agent Research Orchestration Engine** - DAG-based research automation with isolated cognitive agents, divergence-contract hardening, and controlled execution workspace.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Entry: run_loop.py (Loop Orchestrator)                     │
│  - Drives research_loop_v04.py (v0.6 engine, filename kept) │
│  - Round execution, StopPolicy, provider dispatch            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  research_loop_v04.py (v0.6 Divergence-Contract Engine)     │
│  - DAG state machine L0->L10c (15 nodes, 10 personas)       │
│  - Pre-research gate (fail-closed rc=3)                     │
│  - v0.6 gates: divergence, branch, method, traceability     │
│  - Loop memory: emit-loop-memory -> next_loop_memory.json   │
│  - ARS card adapter (token firewall)                        │
│  - Ledgers: branch + modality                               │
└─────────────────────────────────────────────────────────────┘
        ↓                    ↓                      ↓
┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐
│orchestrator  │  │pitfall_ledger.py │  │ars_card_adapter.py │
│(provider)    │  │(audit trail)     │  │(paper/method cards)│
└──────────────┘  └──────────────────┘  └────────────────────┘
        ↓
   Per-Node Subagent Execution (Path B: context isolation)
   L0 Linnaeus (gate) -> L1 Einstein -> ... -> L10c Linnaeus (report)
   L7 Turing (Path A: workspace isolation, only code executor)
```

---

## v0.6 Key Additions (over v0.5)

| Feature | Gate/Command | Purpose |
|---------|-------------|---------|
| Loop memory | `emit-loop-memory` | Structured cross-round state (no agent-memory leakage) |
| Divergence gate | `_audit_divergence` | ≥2 new query families required for divergent loops |
| Branch ledger | `branch-status` | Every prior unexplored branch must be statused |
| Modality ledger | `modality-scan` | Track data modalities used vs available-unused |
| L4 method gate | `_audit_l4_methods` | Scripts need method_card(full_text) or internally_motivated |
| L6 traceability | `_audit_l6_traceability` | Every script needs valid grounding ref |
| L7 manifest | `_audit_l7_manifest` | Every output maps to L6 script + branch + method |
| L10b decision | `_audit_l10_traceability` | literature_changed_direction + decision_grounding |
| ARS card adapter | `ars_card_adapter.py` | ARS output -> compact card JSON, strips prose |
| Report no-clobber | `cmd_aggregate_report` | FINAL_REPORT_<cand>.md, no silent overwrite |

---

## Data Flow (3 paths)

### Path A: Execution (Turing, L7 only)
```
L6 delta (approved) -> prepare-turing-workspace -> subprocess (allowlisted)
  -> result artifact -> L7_turing_delta.json + _exec_manifest/<cand>_L7.json
```

### Path B: Cognitive (L0-L6, L8-L10c)
```
assemble-context(node, persona) -> DAG-allowed deltas as text
  -> subagent via provider -> delta JSON -> emit-delta (schema validated)
```

### Path C: Cross-Round Memory (v0.6)
```
L10b delta + ledgers -> emit-loop-memory -> next_loop_memory.json
  -> new-candidate --from-memory --loop-type divergent
  -> L0 prior_loop_memory gate (hash verified) -> L1 divergence gate
```

---

## Core Modules

| Module | File | LOC | Purpose |
|--------|------|-----|---------|
| Engine | `research_loop_v04.py` | 4843 | DAG, gates, CLI, context assembly, schemas |
| Runner | `run_loop.py` | 863 | Loop orchestration, StopPolicy, provider |
| Orchestrator | `orchestrator.py` | 399 | Provider abstraction (main_agent/command/manual/headless) |
| Pitfall Ledger | `pitfall_ledger.py` | 448 | Failure audit trail, draft->confirmed |
| ARS Adapter | `ars_card_adapter.py` | 79 | Token firewall: ARS->paper/method cards |
| Literature DB | `manage_literature_db.py` | 243 | Cross-round paper dedup + reuse |
| Obsidian Sync | `sync_to_obsidian.py` | 555 | End-of-round vault sync |
| Legacy | `rlr_v05b.py` | 559 | v0.5b prototype (superseded, gate promoted to engine) |
| Historical (removed) | `research_loop_v03.py` | 2433 (historical count) | v0.3 engine; removed from the standalone tree, recoverable from Git history |

---

## DAG Topology (15 nodes)

```
L0 Linnaeus → L1 Einstein → L2 Feynman → L3 Oppenheimer
(gate)        (hypotheses)   (attack)      (triage)
                                                    │
L4 Fisher → L5 Tukey → L6 Oppenheimer → L7 Turing → L8 Curie → L8.5 Curie
(method)    (QC)      (approve)         (execute)   (audit)    (lit-verify)
                                                                        │
                   ┌─ L9a Feynman ─┐ → L10a Jobs → L10b Oppenheimer → L10c Linnaeus
                   │  (falsify)    │    (value)     (decide)            (report)
                   └─ L9b Darwin ──┘
                      (biology)
```

L9a/L9b parallel, mutually invisible. Only L10c sees all deltas.

---

## Dependencies

- Python 3.13 (stdlib: json, hashlib, pathlib, argparse, subprocess, re)
- PyYAML (candidate/config parsing)
- pytest 9.1 (test suite: 25 tests in tests/test_v06_divergence.py)
- External: Academic Research skill, PubMed/EuropePMC API, Obsidian vault, GitHub API
- ARS agents: synthesis_agent (L1), research_architect_agent (L4)

---

## Test Coverage

| Suite | Tests | Covers |
|-------|-------|--------|
| `tests/test_v06_divergence.py` | 25 | All v0.6 gates: loop-memory, divergence, branch, method, traceability, manifest, no-clobber |
| Root `test_*.py` | ~12 | Legacy: run guards, template contract, v05 gate, provenance, turing hydration |

---

## Hard Invariants

1. L0 dependency gate: missing dep STOPS loop
2. Only Turing executes code, only after execution gate
3. Candidate file read-only; state via delta JSON only
4. L9a/L9b mutually invisible
5. v0.6: divergent loops require ≥2 new query families + all branches statused
6. v0.6: no delta carries full paper/method text (card IDs + hashes only)
7. v0.6: next_loop_memory.json is deterministic, regenerable, no hidden state
