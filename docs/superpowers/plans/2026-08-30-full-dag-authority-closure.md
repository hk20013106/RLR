# Full DAG Authority & Contract Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every native L0→L10 required authority, artifact, provider contract, and execution-provenance dependency statically auditable before another real E2E run.

**Architecture:** Keep `context_inputs` as the existing upstream-delta visibility policy and add an orthogonal typed-authority layer owned by topology plus a narrow resolver/projector module. `CurrentRoundDataBinding` remains L0-owned; L4 consumes its compact verified projection while L7 consumes the same authority through its execution boundary. A separate deterministic closure validator audits topology reachability, authority ownership, provider→binder→persisted contracts, and receipt/recovery invariants without running a provider.

**Tech Stack:** Python 3.13, dataclasses, JSON/JSON Schema, pytest, existing RLR topology/context/ledger modules, GitHub Actions Windows CI.

**Spec:** Goal 11 — GitHub Full-DAG Authority & Contract Closure (user-authorized task, 2026-08-30).

## Global Constraints

- Base SHA is exactly `403a3070deb5d49d5f147adb12f676b9078b53ba`.
- Work only on `codex/full-dag-authority-closure`; never force-push unrelated history.
- Do not run real L0→L10, Fisher, or Deep Research.
- Preserve `SINGLE OWNER`, `HASH EXACT CANONICAL BYTES`, `NO SECOND SOURCE OF TRUTH`, `STDOUT IS NOT AN ARTIFACT BUS`, and fail-closed behavior.
- Do not hard-code MC1 or a candidate path; Goal 10 is only the regression case.
- Preserve least-authority/least-context; never render large scientific matrices into cognitive prompts.
- Native v2.1 is the new-run target; legacy v2.0 stays isolated/read-only.

---

### Task 1: Architecture RED tests

**Files:**
- Create: `tests/test_full_dag_authority_closure.py`

**Interfaces:**
- Consumes: existing `topology_for_profile`, `CurrentRoundDataBinding/v1`, provider/persisted schema registries, `RunReceipt`.
- Produces: executable regression expectations for the authority and closure APIs introduced in Tasks 2–3.

- [ ] **Step 1: Write failing tests** proving: native L4 declares `current_round_data_binding`; L7 uses the same authority under an execution mode; a verified small `*Binding/v1` input can be projected compactly with hash/schema/semantic facts; every native node has a static closure row; provider/persisted contracts and receipt execution fields are reported CLOSED.
- [ ] **Step 2: Push test-only commit and inspect GitHub Actions.** Expected result: FAIL because the typed-authority/closure modules and declarations do not yet exist. This is the RED gate.

### Task 2: Typed authority declaration, resolver, and context projection

**Files:**
- Create: `src/research_loop/authority.py`
- Modify: `src/research_loop/topology.py`
- Modify: `src/research_loop/context.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Test: `tests/test_full_dag_authority_closure.py`

**Interfaces:**
- Consumes: `verify_current_round_data_binding(project_dir, cand_id) -> dict`.
- Produces:
  - `AUTHORITY_REGISTRY`
  - `authority_requirements(node_info) -> tuple[str, ...]`
  - `resolve_authority(project_dir, cand_id, authority_name, *, mode) -> ResolvedAuthority`
  - `project_context_authorities(project_dir, cand_id, node_info) -> tuple[list[str], list[dict]]`

- [ ] **Step 1: Add topology declarations.** L0 produces `current_round_data_binding`; L4 requires it for cognitive context; L7 requires the same authority for execution. Do not add it to unrelated nodes.
- [ ] **Step 2: Implement the narrow authority registry/resolver.** `current_round_data_binding` has exactly one canonical producer (`L0`) and separate allowed consumption modes (`context` for L4, `execution` for L7). Resolution calls the existing L0 validator rather than copying it.
- [ ] **Step 3: Implement deterministic compact context projection.** Render artifact identity, binding SHA/schema, authorized-input role/origin/path/hash/size/reason, and for small JSON binding artifacts a bounded scalar semantic projection. Never load tabular/raw matrix content into context.
- [ ] **Step 4: Integrate with `cmd_assemble_context`.** Keep `allowed_inputs` unchanged for DAG-delta isolation. Add manifest fields `required_authorities` and `injected_authorities`; add the authority projection before the provider contract. Fail closed if a required authority cannot resolve.
- [ ] **Step 5: Surface authority requirements in `next-step` scheduling packets** without changing routing semantics.
- [ ] **Step 6: Run targeted tests until GREEN.** Goal 10 regression must show `CurrentRoundDataBinding → generic resolver → L4 provider-visible context` and L7 must point to the same authority definition.

### Task 3: Full native static closure validator

**Files:**
- Create: `src/research_loop/pre_e2e_closure.py`
- Modify only if required by proven contract gaps: `src/research_loop/hypothesis_contracts.py`, `src/research_loop/method_contracts.py`
- Test: `tests/test_full_dag_authority_closure.py`

**Interfaces:**
- Consumes: native topology, authority registry, provider schema registry, submission/persisted schema registry, `RunReceipt` dataclass, existing L4 handle binder declaration.
- Produces:
  - closure statuses `CLOSED`, `NO_PRODUCER`, `UNBOUND`, `UNAUTHORIZED`, `UNREACHABLE`, `TYPE_MISMATCH`, `AMBIGUOUS_OWNER`, `CONTRACT_MISMATCH`
  - `audit_static_closure(profile_id) -> dict`
  - optional project-level `audit_project_authorities(project_dir, cand_id, profile_id) -> dict`
  - machine-readable `e2e_start_allowed` boolean.

- [ ] **Step 1: Audit every native topology node.** Verify each declared delta dependency refers to a reachable node/special source and each required typed authority has one owner, an allowed consumer mode, and a resolver/projector.
- [ ] **Step 2: Audit provider→canonical contract closure.** For all ledger nodes, require a provider schema and persisted schema. Native L4 explicitly declares the handle→ID field transformation; all other nodes are identity wire mappings. Provider-required fields must be representable in canonical submission schema after transformation, and persisted schema must contain the canonical submission contract plus ledger-owned identities.
- [ ] **Step 3: Audit execution provenance.** Confirm `RunReceipt` contains `exit_code`, `timed_out`, `terminal_state`, `execution_status` and that native emission validation still binds exact context/provider artifacts.
- [ ] **Step 4: Audit state/recovery ownership statically.** Confirm committed artifacts are resolved through committed ledger emissions and that the existing recovery path does not define a second provider-output owner. Report provable gaps rather than adding speculative telemetry.
- [ ] **Step 5: Emit a complete L0→L10 closure matrix.** L4 staged internals are represented in L4 contract subchecks (L4A/L4B/L4C/L4.5). Any required non-CLOSED result forces `e2e_start_allowed=false`.
- [ ] **Step 6: Run targeted closure tests.** All native required rows must be CLOSED.

### Task 4: Documentation and fresh verification

**Files:**
- Create: `docs/architecture/FULL_DAG_AUTHORITY_CLOSURE.md`
- Modify only if executable behavior changed and documentation is stale: `docs/AGENT_CONTEXT.md`

**Interfaces:**
- Consumes: closure report generated by Task 3.
- Produces: human-readable dependency/ownership/propagation/contract/execution matrices matching executable declarations.

- [ ] **Step 1: Document the five graphs** (node dependencies, artifact ownership, authority propagation, contract transformations, execution/receipt/recovery) and explain the Goal 10 regression.
- [ ] **Step 2: Verify targeted suites on GitHub Actions.** Authority/context/provider/ledger/recovery tests must pass.
- [ ] **Step 3: Verify full GitHub Actions CI.** Windows Python 3.13 full pytest/coverage job must pass on the final branch head.
- [ ] **Step 4: Inspect final branch diff and remote ref.** No PR/merge; remote `codex/full-dag-authority-closure` must point at the verified repair SHA.
- [ ] **Step 5: Final status.** Return `READY_FOR_ONE_FINAL_CLEAN_E2E` only if the closure validator reports no unresolved required path and fresh CI is green; otherwise return `NOT_READY` with exact unresolved rows.
