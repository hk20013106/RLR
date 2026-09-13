# English Literature Query Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Keep scientific semantics multilingual while ensuring every English-literature retrieval/ranking query is validated English text.

**Architecture:** One shared English-query contract; stage-specific planners remain in L0.5, L4A and L8.5; downstream ranking and PaperQA2/SPECTER2 reuse validated queries instead of rebuilding them from raw scientific text.

**Tech Stack:** Python, pytest, existing structured-model runtime, Curie multisource, PaperQA2, SPECTER2.

**Spec:** `docs/superpowers/specs/2026-09-13-english-literature-query-boundary-design.md`

## Global Constraints

- No ResearchSeed schema change.
- No new retriever, identity/hash owner, evidence owner, retry owner, or DAG path.
- No EvidencePack redesign and no extra L4A model invocation.
- Preserve explicit English-query behavior.
- Reject CJK retrieval text before transport/PaperQA2/SPECTER2.

### Task 1: Shared contract

**Files:** `src/research_loop/l05_curie/contracts.py`, `src/research_loop/l05_curie/query_planner.py`, `tests/test_l05_curie_query_planning.py`

- [ ] RED: Chinese explicit QueryPlan is rejected.
- [ ] RED: non-English default seed cannot be reduced by the deterministic fallback.
- [ ] GREEN: add one shared English retrieval-query validator; remove project-specific Chinese lexicon; keep English deterministic planning.

### Task 2: L0.5 planning and reuse

**Files:** `src/run_loop.py`, `src/research_loop/l05_curie/europepmc_runtime.py`, related tests.

- [ ] RED: formal non-English seed uses the configured structured model to produce 3-6 English queries; explicit English queries bypass it.
- [ ] RED: selector and PaperQA2 never consume raw Chinese ResearchSeed text.
- [ ] GREEN: provider-aware planning outside Curie core; ranking and PaperQA2 reuse canonical QueryPlan text.

### Task 3: L4 reuse

**Files:** `src/research_loop/l4_inventory.py`, `src/research_loop/l4_contextual_literature.py`, `src/research_loop/l4_evidence_bundle.py`, related tests.

- [ ] RED: non-English canonical method name is rejected for native L4A.
- [ ] RED: SPECTER2 and L4B cannot receive Chinese method text.
- [ ] GREEN: require English canonical `method.name`; SPECTER2 uses contextual English query only; L4B uses contextual query when present, otherwise validated English method name. No new provider call.

### Task 4: L8.5 planning

**Files:** `src/research_loop/l85_literature_verification.py`, `src/research_loop/commands/research.py`, related tests.

- [ ] RED: pure-Chinese finding cannot be reduced to ASCII residues.
- [ ] RED: CJK/missing/duplicate finding-query mappings fail before transport.
- [ ] GREEN: existing structured-model runtime produces one validated English query per finding ID; native Curie discovery remains unchanged downstream.

### Task 5: Verification

- [ ] Cross-boundary Chinese ResearchSeed/method/finding regression.
- [ ] Targeted tests green.
- [ ] Full GitHub CI green.
- [ ] Final diff confirms no identity/hash/evidence/retry/DAG ownership drift.
