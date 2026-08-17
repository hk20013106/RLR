# L6 Execution Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and verification-before-completion. Keep the patch minimal.

**Goal:** Reject `METHOD_APPROVED -> NEEDS_EXECUTION` when the L6-approved scripts are missing or ambiguous.

**Architecture:** Reuse the existing `_approved_execution_scripts()` resolver in `cmd_execution_gate`. Do not add a new resolver, state, rollback edge, recovery command, schema version, or script identity protocol.

**Tech Stack:** Python, pytest, existing RLR CLI/state machine.

## Global Constraints

- Base: RLR v0.9.4 / `fa9f69bf9547eb0155cce2f9b2b37b58ce114d96`.
- Do not touch real project data/candidates.
- Do not change L7 exact-name resolution semantics.
- Do not add historical recovery in this patch.
- Minimize CI: one RED branch run, one GREEN branch run; no PR until GREEN is verified.

### Task 1: RED regression

**Files:**
- Modify: `tests/test_round_data_execution.py`

- [ ] Add a test where CurrentRoundDataBinding and `skill_use_plan.md` are valid, candidate is `METHOD_APPROVED`, and `_approved_execution_scripts()` reports a missing approved script.
- [ ] Assert `cmd_execution_gate()` returns `1` and `_set_status()` is never called.
- [ ] Keep the existing legacy-input-manifest test focused by stubbing script resolution success.
- [ ] Push the RED commit and confirm the new test fails on v0.9.4 behavior.

### Task 2: Minimal production fix

**Files:**
- Modify: `src/research_loop/commands/execution.py`

- [ ] In `cmd_execution_gate`, when status is `METHOD_APPROVED`, call `_approved_execution_scripts(project_dir, cand_id)`.
- [ ] Append resolver errors to the existing `missing` list.
- [ ] Do not advance status when any script resolution error exists.
- [ ] Do not alter `_approved_execution_scripts()` or `cmd_prepare_turing_workspace()`.
- [ ] Push once and verify the full existing GitHub CI is green.

### Task 3: Stop for local validation

- [ ] Do not merge to `main` and do not tag/release v0.9.5 yet.
- [ ] Report branch/head SHA and GitHub CI result so the user can pull the branch for local real-data testing.
