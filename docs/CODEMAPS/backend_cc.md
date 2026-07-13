<!-- Generated: 2026-07-07 | Project: Research Loop Room v0.6 | Token estimate: ~900 -->

# Component Coupling Analysis - Research Loop Room (RLR)

## Executive Summary

RLR v0.6 exhibits **moderate structural coupling** with clear architectural boundaries. The DAG-based isolation design prevents global coupling contamination, but the orchestration layer (`run_loop.py` ↔ `research_loop_v04.py`) forms a tight coupling hotspot that could limit versioning flexibility.

---

## Coupling Matrix

### Tight Coupling (≥2 strong dependencies)

| Module A | Module B | Type | Strength | Impact | Mitigation |
|----------|----------|------|----------|--------|------------|
| `run_loop.py` | `research_loop_v04.py` | Direct import + subprocess | **CRITICAL** | Provider dispatch, round control; both fail if one changes CLI | Abstract provider interface; version negotiation |
| `research_loop_v04.py` | `pitfall_ledger.py` | Direct import (audit trail) | **HIGH** | Ledger writes after every node; sync failure blocks loop | Async ledger; non-blocking retry |
| `research_loop_v04.py` | Delta JSON schema | Implicit contract | **HIGH** | All 15 agents must emit compatible JSON; breaking schema blocks loop | Versioned schema (delta_version field); compat layer |
| `assemble-context()` | Filesystem I/O | File system coupling | **MEDIUM** | Reads candidate YAML, delta files; path errors fail context | Fallback candidate frontmatter; virtual filesystem abstraction |
| `prepare-turing-workspace()` | Command allowlist config | Hardcoded or env-dependent | **MEDIUM** | L7 execution depends on config availability; missing config → exec failure | Embedded default allowlist; env override |

### Loose Coupling (1 dependency, orthogonal)

| Module A | Module B | Type | Strength | Cohesion |
|----------|----------|------|----------|----------|
| `orchestrator.py` | Provider impls | Abstraction | **LOW** | Clean interface; multiple providers can coexist |
| `deep_extract_deltas.py` | Delta files | Post-hoc reader | **LOW** | Additive; no effect on loop runtime |
| `manage_literature_db.py` | Obsidian vault | External tool | **LOW** | Optional; loop succeeds without it |
| `ars_card_adapter.py` | ARS agents | Bridge/adapter | **LOW** | Wraps external service; no core loop dependency |

---

## Dependency Graph

```
┌──────────────────────────────────────────────────────────────┐
│ ENTRY & CONTROL LAYER                                        │
├──────────────────────────────────────────────────────────────┤
│ run_loop.py (orchestrator)                                   │
│   ↓ imports & drives                                         │
│   research_loop_v04.py (DAG state machine)                   │
│       ↓ imports                                              │
│       pitfall_ledger.py (audit trail)                        │
│       ↓ calls (per-node)                                     │
│       assemble-context(node) → delta files from FS           │
│       ↓ I/O                                                  │
│       emit-delta(persona, delta_json)                        │
│       ↓ validation                                           │
│       validate_delta_schema() [implicit contract]            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ EXECUTION LAYER (Path A)                                     │
├──────────────────────────────────────────────────────────────┤
│ prepare-turing-workspace(cand, skill_plan)                   │
│   ↓ filesystem + env                                         │
│   workspace (temp dir) + command_allowlist.yaml              │
│   ↓ subprocess (isolated)                                    │
│   L7 Turing executes (bounded by allowlist + timeout)        │
│   ↓ artifact → delta                                         │
│   L7_turing_delta.json                                       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ COGNITIVE LAYER (Path B, per-node)                           │
├──────────────────────────────────────────────────────────────┤
│ L0-L6, L8-L10c Subagents (isolated by DAG)                   │
│   ↓ via orchestrator.py (provider dispatch)                  │
│   Provider: main_agent | command | headless | manual         │
│   ↓ input                                                    │
│   assemble-context(node, persona) [DAG-filtered]             │
│   ↓ output                                                   │
│   emit-delta(node, persona, delta_json)                      │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ UTILITIES & POST-HOC                                         │
├──────────────────────────────────────────────────────────────┤
│ deep_extract_deltas.py (optional post-hoc mining)            │
│ rebuild_deltas.py (recovery)                                 │
│ manage_literature_db.py (lit DB, optional)                   │
│ ars_card_adapter.py (ARS bridge, optional)                   │
└──────────────────────────────────────────────────────────────┘
```

---

## Circular Dependencies

**NONE detected.** The DAG enforces a strict partial order (L0 → L10c), preventing circular coupling.

Proof:
- Input dependencies form a DAG (see DAG_TOPOLOGY.md)
- No backward edges (L_n never depends on L_m where m > n)
- Utilities are post-hoc readers (no effect on forward execution)

---

## Shared Data Structures

### Candidate YAML (Immutable Reference)

```yaml
candidate_id: C20260625112755162852
title: "..."
question: "..."
claim: "..."
topic_hints: []
```

**Accessed by:** all 15 nodes via `assemble-context()`  
**Mutation:** None (read-only throughout)  
**Risk:** Very Low (immutability enforced)

### Delta JSON Schema (Implicit Contract)

```json
{
  "delta_version": "0.6",
  "node": "L1",
  "persona": "Einstein",
  "timestamp": "ISO8601",
  "hypotheses": [...],
  "methods": [...],
  "results": [...],
  "routing": null,
  "status": "IDEA_PROPOSED",
  "metadata": {}
}
```

**Accessed by:** all 15 agents (emit) + L10c Linnaeus (aggregate)  
**Mutation:** None per agent (write-once per node)  
**Contract Risk:** **HIGH** — Breaking schema changes block entire loop  
**Mitigation:** Add `delta_version` field; v0.6 → v0.7 compat layer reads v0.6 deltas

### Pitfall Ledger (Append-Only)

```jsonl
{"node": "L7", "category": "execution_error", "severity": "warn", "status": "draft"}
```

**Accessed by:** `research_loop_v04.py` (auto-record), L8 Curie (confirm)  
**Mutation:** Append-only; status field transitions (draft → confirmed)  
**Risk:** Low (immutable commit history)

### Pre-Research Artifacts

```
01_Candidates/<cand_id>/pre_research_L1.json
01_Candidates/<cand_id>/pre_research_L4.json
01_Candidates/<cand_id>/pre_research_L7.json
```

**Accessed by:** `assemble-context()` for L1, L4, L7  
**Mutation:** None (generated before loop, read-only during)  
**Gate Risk:** **HIGH** — L1/L4 fail closed (rc=3) if missing/empty

---

## Communication Patterns

### Pattern 1: File-Based Sequential (Primary)

```
L_n emits delta_n.json → filesystem → L_(n+1) reads delta_n.json
```

**Latency:** O(file I/O)  
**Coupling:** File format (delta JSON schema)  
**Scalability:** Sequential; ~1-2 min per node

### Pattern 2: DAG Filtering (Information Isolation)

```
assemble-context(node=L5, persona=Tukey)
  → read only DAG-allowed files (L2, L4 deltas + candidate)
  → other files physically absent from context
```

**Coupling:** None (read-only projection)  
**Isolation:** **Enforced** (information invisibility by physical absence)

### Pattern 3: Decision Routing (Conditional Branch)

```
L3 Oppenheimer emits: status: "IDEA_REJECTED" + routing: {persona: L4_fisher}
  → run_loop.py reads routing → JUMP to L4 or DROP
```

**Coupling:** Status enum + routing schema  
**Risk:** Undefined routing target breaks loop

---

## Hot Spots & Refactoring Candidates

### 1. research_loop_v04.py (1500 lines, GOD MODULE)

**Responsibilities:**
- DAG state machine + topology
- Context assembly (path filtering)
- Delta validation
- Status transitions
- Obsidian sync
- Pitfall ledger integration
- Pre-research gates
- CLI dispatch

**Risk:** Single point of failure for state machine

**Refactoring Plan (v0.7):**
- Extract `DAGTopology` class (immutable, testable)
- Extract `ContextAssembler` (pure function, path filtering)
- Extract `DeltaValidator` (schema + versioning)
- Extract `ObsidianSync` (optional module)

**Estimated Effort:** ~400 lines → 4 × 100-line modules

### 2. run_loop.py ↔ research_loop_v04.py CLI Contract

**Current Contract:**
```
research_loop_v04.py assemble-context PROJECT CAND --node L5
research_loop_v04.py emit-delta PROJECT CAND --node L5 --persona Tukey --file delta.json
```

**Risk:** Subprocess communication brittle; shell escaping, encoding mismatches

**Mitigation (v0.7):**
- Add JSON-RPC layer
- Keep CLI for backward compat
- Versioned protocol

---

## Decoupling Opportunities

### Opportunity 1: Delta Schema Versioning

```json
{
  "delta_version": "0.6",
  ...
}
```

Add `DeltaValidator(version)` that applies migration rules (v0.5 → v0.6).

### Opportunity 2: Provider Interface Formalization

```python
class Provider(ABC):
    def run(self, prompt: str, node: str, persona: str) -> Dict:
        pass
```

Implement: `MainAgentProvider`, `CommandProvider`, `HeadlessProvider`, `MockProvider`

### Opportunity 3: Extract Obsidian Sync

Move to optional plugin pattern:
```
plugins/obsidian_sync.py → def sync(project, cand) → bool
```

Loop loads plugin if available; silently skips if not.

---

## Refactoring Roadmap

| Phase | Target | Effort | Impact |
|-------|--------|--------|--------|
| **v0.6** | Baseline | — | — |
| **v0.7** | Extract DAGTopology, ContextAssembler, DeltaValidator | 3-4 days | 60% reduction in research_loop_v04.py |
| **v0.7** | Formalize Provider interface + JSON-RPC bridge | 2-3 days | Decouple run_loop.py; enable provider testing |
| **v0.8** | Delta schema versioning + compat layer | 1-2 days | Enable non-breaking schema evolution |
| **v0.8** | Extract Obsidian sync as optional plugin | 1 day | Obsidian failures no longer block loop |
| **v1.0** | Async/await refactor (optional) | 5-7 days | Parallel round execution |

---

## Testing Gaps

| Layer | Coverage | Tests |
|-------|----------|-------|
| DAG topology | ✓ | test_v05_gate.py |
| Delta emit | ✓ | test_template_contract.py |
| Status transitions | ✓ | test_run_loop_guards.py |
| Pre-research gate | ✓ | test_v05_gate.py |
| Provider dispatch | ✗ | **MISSING** |
| Context assembly | Partial | **NEEDS EXPANSION** |
| Obsidian sync | ✗ | **MISSING** |

---

## Coupling Score Summary

| Metric | Score | Assessment |
|--------|-------|------------|
| **Cyclomatic Coupling** | 0 | ✓ No cycles |
| **Efferent Coupling** | 5 | Moderate (depends on 5 external modules) |
| **Afferent Coupling** | 15 | High (all 15 agents depend on delta schema) |
| **Abstractness** | 0.3 | Low (few abstractions) |
| **Instability** | 0.6 | Moderate (fragile CLI contract) |

**Overall:** **MODERATE COUPLING with CRITICAL HOTSPOTS** — Proceed with v0.7 extraction roadmap.

