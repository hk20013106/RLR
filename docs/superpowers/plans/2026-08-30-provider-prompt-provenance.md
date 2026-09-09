# Provider Prompt Provenance Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure `ProviderRuntimeReceipt/v1.prompt_hash` is derived from the exact prompt value actually passed across the provider process boundary, including L4A method-inventory execution.

**Architecture:** Keep `provider_runtime_observability` as the sole owner of runtime receipt finalization and keep all L4 scientific wrappers delegated to the existing canonical provider executor. Derive the observed prompt at the execution boundary from the actual stdin prompt when present, otherwise from the prompt argument already present in the executed Codex command; do not rebuild a scientific prompt and do not add an L4-specific branch.

**Tech Stack:** Python 3.13, pytest, existing `research_loop.deep_research`, `ProviderExecutor`, and provider runtime observability layer.

**Spec:** `docs/PROVIDER_RUNTIME_OBSERVABILITY.md`

## Global Constraints

- Preserve scientific/DAG behavior; this change is provenance-only.
- Do not change L4A/L4B/L4C responsibilities, provider timeout, search policy, schemas, or evidence gates.
- Keep one provider process owner and one runtime receipt owner.
- Hash the actually executed prompt value; never reconstruct an equivalent prompt for provenance.
- No L4-specific compatibility path or fallback.
- Run the narrow regression first, then the full CI regression suite.

---

### Task 1: Bind Runtime Receipt to the Executed Prompt

**Files:**
- Modify: `tests/test_provider_runtime_integration.py`
- Modify: `src/research_loop/provider_runtime_observability.py`

**Interfaces:**
- Consumes: `deep_research.execute_provider_invocation(execution_command, invocation_kwargs, timeout=...)`, `_ObservedExecutor.run(command, **kwargs)`, and `run_observed_provider(..., prompt=..., input_text=...)`.
- Produces: an unchanged `ProviderRuntimeReceipt/v1` schema whose existing `prompt_hash` now hashes the exact prompt value actually passed to the provider boundary.

- [ ] **Step 1: Write the failing boundary regression**

Extend `tests/test_provider_runtime_integration.py` with a test that sets `_CONTEXT["prompt"]` to a deliberately stale sentinel, invokes the canonical provider boundary with a different actual prompt, reads `runtime_receipt.json`, and asserts `prompt_hash == sha256(actual_prompt.encode("utf-8"))` and `prompt_hash != sha256(stale_prompt.encode("utf-8"))`. Cover both supported Codex invocation shapes: prompt supplied as `input_text`, and prompt appended as the final command argument.

- [ ] **Step 2: Run the regression and verify RED**

Run the targeted provider-runtime integration test. The new assertion must fail on the base implementation because `_ObservedExecutor` currently passes `context["prompt"]` into `run_observed_provider` even when the executed prompt differs.

- [ ] **Step 3: Implement the minimal generic boundary fix**

In `_ObservedExecutor.run`, choose the observed prompt from the actual process invocation: use `kwargs["input_text"]` when it is not `None`; otherwise use the final command argument for the existing Codex `subprocess_invocation` contract. Pass that single value to `run_observed_provider`. Do not modify L4 modules, prompt builders, timeout policy, or receipt schema.

- [ ] **Step 4: Run targeted verification**

Run `tests/test_provider_runtime_integration.py`, `tests/test_provider_runtime_observability.py`, and the existing Deep Research/L4 provider-boundary tests. Confirm the new regression and existing provider observability behavior pass.

- [ ] **Step 5: Search for duplicate provenance ownership**

Search the branch for `prompt_hash`, `ProviderRuntimeReceipt`, `_ObservedExecutor`, and `execute_provider_invocation`. Confirm runtime `prompt_hash` is finalized only by `provider_runtime_observability.py` and no L4-specific receipt path or second prompt authority was added.

- [ ] **Step 6: Run full regression and structural checks**

Run the repository CI/full pytest suite, `git diff --check`, and CLI import/help checks used by `.github/workflows/ci.yml`. Record exact pass/fail counts. Do not run a real scientific E2E.

- [ ] **Step 7: Stop after verification**

Report the final branch SHA, RED evidence, targeted/full regression results, changed files, and confirmation that the frozen Goal12 run, scientific logic, provider timeout, PR state, and merge state were not changed.
