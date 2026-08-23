# L0.5 Dynamic Research and Provider Executor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Curie literature discovery an explicit L0.5 DAG node, remove active hardcoded pre-research queries, and standardize external provider/research subprocess execution behind ProviderExecutor.

**Architecture:** L0 remains the sole semantic authority. L0.5 is a non-delta research node whose completion artifact is an immutable ResearchSeed-to-EvidencePack binding; L1 consumes that frozen evidence only. Query strings are runtime-derived from authoritative state. ProviderExecutor is the single process-execution boundary for external provider/research CLIs while existing RunReceipt/v1 remains the durable receipt.

**Tech Stack:** Python stdlib, pytest, existing RLR topology/Deep Research/provider modules, GitHub Actions Windows Python 3.13.

**Spec:** `docs/superpowers/specs/2026-08-24-l0-5-dynamic-research-provider-executor-design.md`

## Global Constraints

- Do not change candidate status vocabulary.
- Do not give Einstein/L1 direct Knowledge Base authority.
- Do not duplicate the L0 scientific question/hypothesis as a second semantic authority.
- Do not add project-specific query literals to runtime configuration.
- Preserve `RunReceipt/v1` and existing provider public imports.
- Keep LoopX untouched.
- Fail closed on ResearchSeed/evidence drift and provider execution errors.

---

### Task 1: RED architecture contracts

**Files:**
- Modify: `tests/test_l1_research_seed_authority.py`
- Create: `tests/test_l0_5_research_node.py`
- Create: `tests/test_provider_executor.py`

**Interfaces:**
- Consumes: current topology, PRE_RESEARCH_MAP, Deep Research stage dispatch, provider runtime.
- Produces: failing contracts for explicit L0.5, dynamic-query policy, and ProviderExecutor.

- [ ] **Step 1: Write failing topology tests**

Assert native topology sequence contains `L0`, `L0.5`, `L1` consecutively; L0.5 persona is Curie, `node_kind == "research"`, `research_required is True`, and L1 no longer owns `pre_research`.

- [ ] **Step 2: Write failing dynamic-query tests**

Assert every active PRE_RESEARCH_MAP entry has `queries == []`; serialized active map contains none of `heart rate`, `cardiac`, `wgcna`, `bat`, `shrew`, `ecm`, `module preservation`.

- [ ] **Step 3: Write failing ProviderExecutor tests**

Import `ProviderExecutor`, `ProviderExecutionError`, and `ProviderExecutionResult`; verify a trivial Python child succeeds with captured text, non-zero exit produces normalized error detail, and timeout produces normalized timeout detail.

- [ ] **Step 4: Push RED and verify CI fails for the intended missing contracts**

Expected: existing suite remains green except new architecture tests.

---

### Task 2: Explicit L0.5 topology and routing

**Files:**
- Modify: `src/research_loop/topology.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Modify: `src/run_loop.py`
- Modify: `src/research_loop/deep_research.py`
- Modify: `src/research_loop/commands/research.py`
- Modify: `src/research_loop/research_seed.py`
- Modify: `src/research_loop/hypothesis_recall_context.py`
- Test: `tests/test_l0_5_research_node.py`
- Test: `tests/test_l1_research_seed_authority.py`

**Interfaces:**
- Produces topology node `L0.5` and canonical new Deep Research stage identity `L0.5`.
- Produces exact ResearchSeed -> L0.5 evidence binding used by L1.

- [ ] **Step 1: Add L0.5 topology entry and sequence position**

L0.5 is Curie/research-only, status_before IDEA_PROPOSED, no status advance, KB read-write. Remove pre-research ownership from L1.

- [ ] **Step 2: Make next-step completion artifact-aware**

When status is IDEA_PROPOSED, route to L0.5 until the current ResearchSeed has one valid exact L0.5 evidence binding; once valid, route to L1. Do not create a fake L0.5 delta.

- [ ] **Step 3: Move native discovery stage from L1 to L0.5**

Deep Research `_STAGES` and stage instruction accept L0.5. `cmd_deep_research_run --node L0.5` loads canonical L0 ResearchSeed and persists evidence under L0.5. Preserve legacy L1 read compatibility where required but do not create new native L1 research runs.

- [ ] **Step 4: Bind exact L0.5 run to ResearchSeed**

Generalize the existing binding helpers so their canonical target stage is L0.5 and context/receipt validation for L1 checks that exact L0.5 artifact hash.

- [ ] **Step 5: Teach run_loop to execute research nodes without cognitive deltas**

When next-step returns L0.5, run/validate Deep Research and continue; do not invoke an Einstein-style provider or emit-delta for L0.5. Store the exact run id for subsequent L1 context assembly.

- [ ] **Step 6: Run targeted topology/L0.5/L1 evidence tests**

Expected: all targeted tests pass.

---

### Task 3: Remove all active hardcoded pre-research queries

**Files:**
- Modify: `src/research_loop/preresearch.py`
- Modify: `src/research_loop/commands/research.py`
- Test: `tests/test_l0_5_research_node.py`
- Test: `tests/test_l1_research_seed_authority.py`

**Interfaces:**
- PRE_RESEARCH_MAP remains policy metadata with empty query lists.
- Prompt generation derives search intent from current authoritative artifacts.

- [ ] **Step 1: Empty all active query lists and generalize descriptions**

L0.5/L4/L7/L8.5 entries contain no domain examples.

- [ ] **Step 2: L0.5 prompt derivation**

Derive actual literature queries from canonical L0 scientific question and current-round hypothesis; require actual queries in Query log.

- [ ] **Step 3: L4 prompt derivation**

Use canonical question plus selected hypotheses/method-design objective and instruct Curie to derive methodology search queries; no fixed package/method names.

- [ ] **Step 4: L7 prompt derivation**

Ground code search in approved L6 strategy/scripts_needed and instruct derivation of repository/package queries; no WGCNA/clusterProfiler/ECM literals.

- [ ] **Step 5: L8.5 prompt derivation**

Ground verification in concrete L7/L8 findings and instruct derivation of support/contradiction queries; no cardiac/bat/shrew literals.

- [ ] **Step 6: Run dynamic-query regressions**

Expected: active runtime config/prompt tests pass.

---

### Task 4: ProviderExecutor process boundary

**Files:**
- Create: `src/research_loop/providers/executor.py`
- Modify: `src/research_loop/providers/__init__.py`
- Modify: `src/research_loop/providers/base.py`
- Modify: `src/research_loop/deep_research.py`
- Modify: `src/orchestrator.py`
- Test: `tests/test_provider_executor.py`
- Test: `tests/test_provider_dispatch.py`
- Test: `tests/test_deep_research.py`

**Interfaces:**
- `ProviderExecutor.run(command, *, timeout=None, shell=False, cwd=None, env=None, input_text=None, check=True) -> ProviderExecutionResult`
- `ProviderExecutionResult`: immutable args/returncode/stdout/stderr.
- `ProviderExecutionError`: normalized launch/timeout/non-zero error.

- [ ] **Step 1: Implement minimal executor**

Use one stdlib subprocess call internally with text stdout/stderr capture and explicit timeout. Normalize timeout, CalledProcessError/non-zero, and launch errors.

- [ ] **Step 2: Export executor through providers package and orchestrator compatibility shim**

Do not change existing RunReceipt/v1 schema.

- [ ] **Step 3: Route command/headless providers through ProviderExecutor**

Replace direct subprocess.run in provider base helpers.

- [ ] **Step 4: Route Deep Research CLI through ProviderExecutor**

Preserve Windows `.cmd` stdin behavior, model/provider isolation, timeout, and JSON output validation.

- [ ] **Step 5: Add source-level guard for core external paths**

Regression asserts provider base and Deep Research modules do not directly call `subprocess.run` outside executor.py.

- [ ] **Step 6: Run provider/deep-research targeted tests**

Expected: all pass.

---

### Task 5: Integrated runner/context regression and final verification

**Files:**
- Modify tests only as required for new canonical node name.
- Update docs that explicitly say Deep Research runs before L1 rather than at L0.5.

**Interfaces:**
- End-to-end native flow: L0 -> L0.5 evidence -> L1.

- [ ] **Step 1: Update main-agent/run-loop instructions to name L0.5 explicitly**

- [ ] **Step 2: Run targeted suites**

Run topology/L0.5/L1 authority, deep_research, provider dispatch/executor, run_loop guards, context/receipt, L4 evidence tests.

- [ ] **Step 3: Run full regression suite**

`python -m pytest -q`

- [ ] **Step 4: Run whitespace check**

`git diff --check main...HEAD`

- [ ] **Step 5: Verify PR diff scope and no LoopX changes**

Expected: only RLR core/tests/docs for these three tasks.
