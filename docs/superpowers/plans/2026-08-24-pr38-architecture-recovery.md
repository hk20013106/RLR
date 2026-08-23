# PR #38 Architecture Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Do not patch failing tests one-by-one. Every production change must remove or consolidate an authority boundary.

**Goal:** Finish the three P0 objectives—explicit L0.5 retrieval, zero project-specific hardcoded pre-research queries, and one external process-execution boundary—while reducing duplicate code and preserving one canonical owner for each scientific concept.

**Architecture:** Keep `L0 -> L0.5 (Curie research) -> L1 (Einstein reasoning)` as the native DAG. Collapse the current PR's install/compat wrappers back into existing canonical owners. Reuse the repository's mature bounded-process implementation as the process engine behind `ProviderExecutor`; do not maintain two subprocess implementations. Treat the 41 CI failures as evidence about migration boundaries, not as 41 independent bugs.

**Tech Stack:** Python 3.13, existing RLR topology/state machine, existing Deep Research EvidencePack machinery, existing `RunReceipt/v1`, existing bounded process implementation. No new runtime dependency in this recovery. Haystack is reserved for a future local hybrid-retrieval backend if/when L0.5 indexes the local literature corpus.

**Spec:** `docs/superpowers/specs/2026-08-24-l0-5-dynamic-research-provider-executor-design.md`

## Global Constraints

- One canonical owner per concept; compatibility aliases may delegate but may not reimplement behavior.
- Do not reintroduce active L1 pre-research ownership. Native flow is L0 -> L0.5 -> L1.
- No repository-embedded domain seed queries for L0.5, L4, L7, or L8.5.
- L0.5 must freeze one exact EvidencePack per canonical ResearchSeed and L1 must fail closed on missing/drifted binding.
- Preserve `RunReceipt/v1`; do not create a second provenance ledger.
- Do not add Prefect, LangChain, AnyIO, or another orchestration/runtime framework solely to make CI green.
- If local keyword+vector retrieval is implemented later, prefer a mature hybrid retriever (Haystack/OpenSearch/Qdrant) rather than hand-writing BM25/vector fusion.
- Historical tests are migrated only when the asserted behavior is intentionally superseded; production code is not bent to preserve obsolete native L1 pre-research semantics.

---

## Root-cause map for the 41 failures

### Group A — intentional DAG migration, not product regressions

Most failures still create or expect `L1_research.md`, call `deep-research-run --node L1`, or expect `next-step == L1` immediately after L0. These tests must move to L0.5 or seed a valid L0.5 EvidencePack before testing L1-only behavior.

Affected families include `test_cross_round_e2e.py`, `test_decision_cli.py`, `test_gate_cli_snapshot.py`, `test_hypothesis_reactivation.py`, `test_persona_prompt_injection.py`, `test_pr1_provenance.py`, `test_pr2_gate.py`, `test_pr3_templates.py`, `test_pr4_provenance_audit.py`, `test_template_contract.py`, and `test_v05_gate.py`.

### Group B — duplicated L0.5 implementation introduced by this PR

The new `l0_5_runtime.py`, `l0_5_context.py`, `l0_5_binding_compat.py`, `l0_5_deep_research.py`, `l0_5_cli.py`, `dynamic_preresearch.py`, and `provider_execution.py` install behavior dynamically through `research_loop.__init__`. This creates parallel owners and import-order coupling. These wrappers are the wrong long-term architecture even where their tests pass.

### Group C — duplicated process execution

`providers/executor.py` currently calls `subprocess.run()` while `rlr_maintenance/bounded_process.py` already provides timeout, bounded output, process-tree cleanup, and cross-platform handling. The new executor must reuse/move that implementation rather than become a second process runner.

### Group D — test mocking at the wrong boundary

Deep Research tests monkeypatch `deep_research.subprocess.run`; once execution is centralized, tests must inject/mock the canonical executor instead. Do not restore direct subprocess calls for test convenience.

---

## Task 1: Collapse evidence binding to one generic owner

**Files:**
- Modify: `src/research_loop/research_seed.py`
- Delete after migration: `src/research_loop/research_evidence_binding.py`
- Delete after migration: `src/research_loop/l0_5_binding_compat.py`
- Test: `tests/test_l0_5_research_node.py`
- Test fixtures: `tests/deep_research_fixtures.py`, `tests/hypothesis_recall_test_support.py`

**Interfaces:**
- Add one generic binding implementation parameterized by `target_node`.
- Active native use: `target_node="L0.5"`.
- If legacy L1 helper names must remain, they must be one-line delegates to the generic implementation, not duplicate persistence/validation logic.

- [ ] Add failing tests that a ResearchSeed binds immutably to exactly one L0.5 evidence run and rejects drift.
- [ ] Generalize the existing binding code in `research_seed.py`; preserve its canonical L0 validation and manifest hashing.
- [ ] Switch all new L0.5 runtime/context call sites to the generic owner.
- [ ] Delete `research_evidence_binding.py` and `l0_5_binding_compat.py` once no production import remains.
- [ ] Run targeted binding + seed tests.

**Acceptance:** one implementation contains binding path construction, evidence-run validation, persistence, load, and manifest generation.

---

## Task 2: Make L0.5 native in canonical lifecycle/research/context owners

**Files:**
- Modify: `src/research_loop/commands/lifecycle.py`
- Modify: `src/research_loop/commands/research.py`
- Modify: `src/research_loop/context.py`
- Modify: `src/research_loop/gates.py` only if gate logic already canonically lives there
- Keep/modify: `src/research_loop/topology_extensions.py`
- Delete after migration: `src/research_loop/l0_5_runtime.py`
- Delete after migration: `src/research_loop/l0_5_context.py`
- Delete after migration: `src/research_loop/l0_5_deep_research.py`
- Delete after migration: `src/research_loop/l0_5_cli.py`
- Modify: `src/research_loop/__init__.py` to remove the deleted installers

**Behavior:**
- `next-step` returns L0.5 when native L0 is complete and current ResearchSeed lacks a valid frozen L0.5 binding.
- `deep-research-run --node L0.5` is handled directly by the canonical research command.
- Once the binding is valid, `next-step` returns L1 and includes/references the exact L0.5 evidence run.
- `assemble-context --node L1` reloads canonical ResearchSeed, validates the bound L0.5 run, validates its EvidencePack, injects only that evidence, and fails closed on missing/drifted evidence.
- L1 has no direct knowledge-base or pre-research ownership.

- [ ] Write/adjust focused RED tests for next-step L0.5 -> L1 transition and L1 fail-closed binding.
- [ ] Move the minimal logic from the installer wrappers into canonical functions.
- [ ] Remove installer registrations from `research_loop.__init__`.
- [ ] Delete wrappers only after production searches show zero imports.
- [ ] Run lifecycle, context, research, hypothesis-recall, and persona-context tests.

**Acceptance:** importing `research_loop` is no longer required to monkeypatch L0.5 behavior into stable modules.

---

## Task 3: Remove hardcoded query ownership without inventing a query framework

**Files:**
- Modify: `src/research_loop/preresearch.py`
- Modify: `src/research_loop/commands/research.py`
- Delete after migration: `src/research_loop/dynamic_preresearch.py`
- Tests: `tests/test_l0_5_research_node.py` plus focused L4/L7/L8.5 tests

**Behavior:**
- `PRE_RESEARCH_MAP[*]["queries"] == []` for all active stages.
- The prompt receives authoritative state rather than repository-owned query literals:
  - L0.5: canonical question + current hypothesis.
  - L4: question/hypothesis + selected L3/method-design state.
  - L7: approved L6 strategy and required software/tasks.
  - L8.5: actual L7 results + L8 audit.
- Curie/research tooling derives the actual queries and records them in the query log.

This deliberately chooses the original requirement's "directly call the retrieval engine with current state" path rather than creating another query-generator subsystem.

- [ ] Add tests that active configs contain no domain examples and prompts contain the current authoritative state.
- [ ] Integrate dynamic prompt construction into the existing research command or a single pure helper in `preresearch.py`.
- [ ] Remove `dynamic_preresearch.install()` and delete the module.
- [ ] Search production code for the former WGCNA/cardiac/bat/shrew/ECM seed literals and verify none remain in active pre-research configuration.

**Acceptance:** query diversity is a runtime retrieval responsibility, not a static repository configuration responsibility.

---

## Task 4: Converge on one process engine and one ProviderExecutor contract

**Files:**
- Modify/move implementation from: `src/rlr_maintenance/bounded_process.py`
- Canonical owner: `src/research_loop/providers/executor.py`
- Modify: `src/research_loop/providers/base.py`
- Modify: `src/research_loop/deep_research.py`
- Modify additional production direct-call sites found by search
- Delete after migration: `src/research_loop/provider_execution.py`
- Make `src/rlr_maintenance/bounded_process.py` a compatibility re-export if maintenance imports require path stability
- Tests: `tests/test_provider_executor.py`, `tests/test_rlr_maintenance_bounded_process.py`, Deep Research runtime tests

**Implementation rule:** do not keep both `subprocess.run()` executor code and the bounded `Popen` implementation.

- [ ] First port the tested bounded-process semantics (hard timeout, output bounds, process-tree cleanup, Windows process-group handling) into the canonical executor owner without changing behavior.
- [ ] Extend only what providers require (`str | argv`, optional shell mode, optional stdin text); no retries/scheduler/state logic.
- [ ] Make `ProviderExecutor` delegate to that sole implementation and normalize nonzero/timeout/launch failures.
- [ ] Point maintenance callers at the same implementation through import/re-export.
- [ ] Point command/headless provider and Deep Research directly at the canonical executor; remove `provider_execution.install()`.
- [ ] Search all production `src/` for `subprocess.run(` / `subprocess.Popen(`. Each remaining call must either be the canonical executor itself or be explicitly justified as an unrelated process-lifecycle primitive; otherwise migrate it.
- [ ] Rewrite tests to inject/mock `ProviderExecutor`, not `deep_research.subprocess.run`.

**Acceptance:** there is one process-spawning implementation, one timeout/output/error contract, and `RunReceipt/v1` remains the provenance authority.

---

## Task 5: Migrate tests by scientific contract, not by filename

**Rules:**

1. Tests whose subject is pre-research provenance/gating move from `L1_research.md` to `L0.5_research.md` and the L0.5 EvidencePack/binding.
2. Tests whose subject is L1 reasoning/persona/hypothesis recall must create a valid L0.5 evidence fixture first, then test the L1 behavior.
3. `next-step` tests after L0 must expect L0.5 until evidence is frozen.
4. Native Deep Research CLI tests must invoke `--node L0.5`; legacy-profile tests may remain L1 only when they explicitly bind a historical profile.
5. Remove tests that exist only to guarantee placeholder-generation behavior if placeholder files are not part of the production architecture. Keep validation tests for malformed/missing evidence, retargeted to L0.5.
6. Never add a production compatibility branch solely to preserve an obsolete test expectation.

- [ ] Convert one family at a time and run its focused tests.
- [ ] Keep the RED->GREEN history meaningful: failures should disappear because fixtures now satisfy the new upstream contract, not because gates are weakened.

---

## Task 6: Decide external-framework adoption only at the actual retrieval boundary

**Current decision:** no new dependency in PR #38.

- AnyIO: reject for this PR because existing bounded-process code already solves the synchronous process-tree/timeout/output problem more directly.
- LangChain MultiQueryRetriever: reject for this PR because L0.5 is not primarily a vector-store retriever and adding LangChain only for query expansion duplicates the Academic Research agent's capability.
- Prefect: reject for this PR because it would create a second workflow/state authority beside RLR's scientific DAG.
- Haystack hybrid retrieval: approve as the preferred candidate for a future local-literature retrieval backend if the project requires BM25 + embedding retrieval. Do not implement a home-grown hybrid retriever.

**Future trigger for Haystack:** only when L0.5 is required to retrieve against a locally indexed corpus, not merely external PubMed/OpenAlex/web sources.

---

## Task 7: Verification and completion gate

- [ ] `pytest` focused: topology/L0.5, research seed/binding, pre-research, provider executor, Deep Research, L1 context/hypothesis recall.
- [ ] Full Windows/Python 3.13 suite passes.
- [ ] L4 evidence CI passes.
- [ ] Import check and CLI help pass.
- [ ] Search confirms active hardcoded domain query literals are absent.
- [ ] Search confirms no L0.5 install/compat wrapper remains as a second behavior owner.
- [ ] Search confirms production process spawning is centralized.
- [ ] PR diff is reviewed for net simplification: new wrapper files should be deleted/merged, not merely accompanied by more compatibility code.
- [ ] Update PR description from RED/TDD wording to the final architecture and exact verification evidence.

## Completion definition

PR #38 is complete only when all three P0 requirements are true at runtime, not merely represented by tests:

1. **Explicit L0.5:** native DAG and runtime enforce `L0 -> L0.5 -> L1`, with immutable ResearchSeed -> exact EvidencePack binding.
2. **Dynamic research:** no active project-specific hardcoded query seeds; each research stage is grounded in current authoritative state.
3. **Unified execution:** one process engine under `ProviderExecutor`, consistent timeout/output/error semantics, and no parallel subprocess implementation.

A green CI obtained by restoring native L1 pre-research, weakening L0.5 gates, or adding compatibility wrappers that duplicate behavior is explicitly NOT completion.
