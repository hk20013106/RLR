# Native Curie → Einstein Handoff and Gap Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make native v2.1 L1 consume a directly bound frozen Curie EvidencePack and implement a bounded EvidenceGapRequest → Curie retry → versioned EvidencePack loop.

**Architecture:** Add a native evidence binding that does not depend on legacy Deep Research run artifacts, then change native L1 context assembly to use that binding as its sole evidence authority. Add an explicit gap-loop runtime that validates the exact parent pack/request lineage and permits at most three acquisition rounds while preserving all prior frozen packs.

**Tech Stack:** Python 3.13, stdlib JSON/hashlib/pathlib, existing RLR v2.1 contracts and L0.5 Curie store, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-24-l05-curie-einstein-phases3-8-design.md`

## Global Constraints

- Curie is the only acquisition authority; Einstein cannot search or retrieve.
- Native v2.1 must not require `deep_research.evidence_artifact_manifest()` for L1 evidence binding.
- Frozen EvidencePacks are immutable and revalidated at L1 use.
- EvidenceGapRequest is the only authorized path back to Curie.
- Maximum three acquisition rounds per ResearchSeed.
- Historical v2.0 compatibility behavior remains unchanged.
- No candidate workflow status mutation is introduced by the evidence loop.

---

### Task 1: Native frozen-pack binding contract

**Files:**
- Create: `tests/test_l05_native_evidence_binding.py`
- Modify: `src/research_loop/research_seed.py`

**Interfaces:**
- Consumes: `research_seed.load_l1_research_seed()`, `l05_curie.load_frozen_evidence_pack()`.
- Produces: `write_l1_native_evidence_binding(project_dir, seed, pack_manifest, acquisition_run_id) -> dict`, `load_l1_native_evidence_binding(project_dir, seed) -> dict`, `native_evidence_binding_manifest_entry(project_dir, seed) -> dict`.

- [ ] **Step 1: Write failing tests** proving a native binding can be written from a frozen pack without any legacy Deep Research run file; loading revalidates pack hash/identity; tampering fails closed; replacing an already-bound different pack without an explicit advancement API fails.
- [ ] **Step 2: Run the targeted test in CI and verify RED** with missing native binding APIs.
- [ ] **Step 3: Implement the minimal native binding** under `08_Audit/research_seed_bindings/`, schema-versioned separately from the legacy v2 bridge. Persist ResearchSeed receipt, frozen pack manifest, acquisition run ID, active pack version and lineage.
- [ ] **Step 4: Run targeted tests and existing `test_l1_research_seed_authority.py` / `test_l05_curie_l1_bridge.py`; verify GREEN.**

### Task 2: Native L1 consumes native binding, not legacy pre-research provenance

**Files:**
- Create: `tests/test_l05_native_l1_handoff.py`
- Modify: `src/research_loop/l05_context.py`

**Interfaces:**
- Consumes: `load_l1_native_evidence_binding()` and frozen EvidencePack renderer.
- Produces: native v2.1 L1 context injection whose manifest records `injected_mode = l05_native_frozen_pack` and exact binding/pack receipt.

- [ ] **Step 1: Write failing sentinel tests** proving native L1 succeeds with a valid native binding even when no legacy Deep Research run exists; proving native L1 fails closed when the binding is missing/tampered; proving v2.0 path remains unchanged.
- [ ] **Step 2: Verify RED** because current code requires `pre_research.evidence_run_id` and `load_l1_evidence_binding()`.
- [ ] **Step 3: Modify only native v2.1 path** to load the native binding directly. Do not infer a pack from filesystem order. Preserve the original legacy context path for v2.0.
- [ ] **Step 4: Run targeted context/isolation tests and verify GREEN.**

### Task 3: EvidenceGapRequest persistence and exact parent authorization

**Files:**
- Create: `src/research_loop/l05_curie/gap_loop.py`
- Create: `tests/test_l05_curie_gap_loop.py`
- Modify: `src/research_loop/l05_curie/__init__.py`

**Interfaces:**
- Consumes: `build_gap_request()`, `validate_gap_request()`, native evidence binding, frozen EvidencePack manifest.
- Produces: `open_gap_request(...) -> dict`, `load_open_gap_request(...) -> dict`, `authorize_retry(...) -> dict`.

- [ ] **Step 1: Write failing tests** for append-only request persistence, exact candidate/round/seed/parent-pack matching, one OPEN request per active pack, and rejection of request reuse or forged parent hashes.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement minimal append-only request receipts** under `08_Audit/l05_gap_requests/<candidate>/`. Authorization returns the next evidence version and exact `source_gap_request_id`; it does not perform acquisition itself.
- [ ] **Step 4: Run targeted contract/store tests and verify GREEN.**

### Task 4: Versioned Curie retry runtime and binding advancement

**Files:**
- Create: `src/research_loop/l05_curie/native_runtime.py`
- Create: `tests/test_l05_curie_native_runtime.py`
- Modify: `src/research_loop/research_seed.py`
- Modify: `src/research_loop/l05_curie/__init__.py`

**Interfaces:**
- Consumes: an acquisition callable returning a validated frozen pack manifest, `authorize_retry()`, native binding APIs.
- Produces: `bind_initial_curie_pack(...)`, `run_authorized_retry(...)`, and an explicit append-only `advance_l1_native_evidence_binding(...)`.

- [ ] **Step 1: Write failing tests** for v1 initial binding, v2/v3 advancement with exact parent hash and gap request ID, preservation of prior packs, rejection of skipped versions, and no v4 authorization.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement the minimum orchestration** without provider-specific logic. Require the returned pack to match candidate/round/seed/version/parent/request before advancing the active binding.
- [ ] **Step 4: Run targeted runtime tests and verify GREEN.**

### Task 5: CLI/runtime integration and regression gate

**Files:**
- Create: `src/research_loop/l05_gap_cli.py`
- Create: `tests/test_l05_gap_cli.py`
- Modify: `src/research_loop/__init__.py`
- Modify: `.github/workflows/l05-curie-ci.yml`

**Interfaces:**
- Produces thin commands to inspect/open a gap request and bind/advance a native frozen pack without giving L1 search authority.

- [ ] **Step 1: Write failing CLI registration tests.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Add thin CLI adapters and focused CI coverage.**
- [ ] **Step 4: Run L0.5 focused CI, L1 context tests, main full suite, and `git diff --check`; verify no failures.**
- [ ] **Step 5: Open/update Draft PR A with exact verification evidence.**