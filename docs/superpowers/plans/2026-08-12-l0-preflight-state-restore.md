# L0 Pre-flight + State Restore Implementation Plan

> **For agentic workers:** execute this plan task-by-task. TDD is mandatory for behavior changes. Do not expand into literature-transport implementation or L4 changes.

**Goal:** Make the single formal L0 node a deterministic pre-flight + previous-round evidence restore boundary, with one authoritative round-finalization path and component-specific failures.

**Base:** `e669ca3bc5229deabf46e89ca353fde510de5f98`

## Architecture review — 2026-08-12

This plan was re-audited before continuing implementation. The audit applies three rules to every change:

1. **One owner per concern.** Do not keep two independent implementations of the same check/finalization path.
2. **Dependency → consumer closure.** A blocking dependency must have a real downstream consumer in the current codebase.
3. **Scope discipline.** Only changes required to complete the L0 evidence/state contract belong in PR #15.

### Audit findings

1. `l0_preflight.py` is now the intended owner of framework readiness probes, but `cmd_preflight` and `cmd_check_deps` still repeat the Academic Research runtime check. This duplicates authority and must be removed.
2. PubMed MCP and Zotero readiness probes are useful, but their actual literature consumers are not yet wired in the canonical RLR path. They must be reported as **target-required / non-blocking readiness** in this PR, not falsely treated as closed blocking dependencies. They become blocking only in the later literature-transport integration that actually consumes them.
3. Obsidian already has a real L10c consumer. If it is blocking at L0, L10c sync failure cannot remain a warning. Finalization must fail closed.
4. Round manifest creation currently has two owners (`aggregate-report` and `emit-loop-memory`). This violates single ownership. L10c finalization must own manifest creation; loop-memory may only consume an already-frozen manifest.
5. The manifest currently captures source files, L7 script outputs, reports, literature JSON and run receipts, but not all authoritative result/audit artifacts. It must include explicit L7 result artifact refs and candidate delta/audit artifacts without broad directory guessing.
6. Continuation restore is enforced by the L0 context gate, but `run_loop.py` still performs provider readiness/main-agent handoff before a runner-level restore guard. A continuation must fail before provider setup/handoff.
7. `L0 contract CI` tests are green, but its whitespace step fails because shallow checkout does not contain the PR base commit. This is CI plumbing, not a product failure; fix by fetching sufficient history, not by weakening `git diff --check`.

### Explicitly out of scope

- Actual PubMed MCP search/full-text consumer implementation.
- Zotero item/PDF registration adapter.
- Any L4A→L4B, L4C, or L4.5 changes.
- New evidence database or duplicate artifact store.
- L7 workspace redesign.
- New formal DAG nodes.
- Automatic merge of PR #15.

---

## Task 1 — Preflight authority and enforcement semantics

**Files**
- Modify: `src/research_loop/l0_preflight.py`
- Modify: `src/research_loop/common.py`
- Modify: `src/research_loop/commands/lifecycle.py`
- Modify: `tests/test_l0_preflight_probes.py`

**Contract**
- `l0_preflight.py` is the sole framework-owned service-probe authority.
- Each `ProbeResult` states whether it is currently blocking.
- Current blocking probes: core Python/packages, filesystem, Academic Research, hypothesis ledger, evidence store, Obsidian.
- PubMed MCP and Zotero remain visible readiness probes but non-blocking until their real consumers are wired.
- `preflight_receipt.json` records both status and enforcement semantics.

**TDD**
- [ ] RED: failed non-blocking PubMed/Zotero probe does not make overall preflight fail.
- [ ] RED: failed blocking ARS/ledger/Obsidian probe does make overall preflight fail.
- [ ] RED: lifecycle commands do not execute a second ARS readiness check.
- [ ] Minimal implementation; no new generic dependency framework.

## Task 2 — Complete authoritative round evidence manifest

**Files**
- Modify: `src/research_loop/l0_state.py`
- Modify: `tests/test_l0_state_restore.py`

**Contract**
- One artifact path is registered once with the strongest appropriate class.
- Explicit authoritative sources only:
  - current L0 source contract;
  - L7 execution manifest outputs;
  - L7 `results[*].artifact_refs` as `result`;
  - candidate-scoped final reports;
  - candidate-owned literature evidence;
  - emitted candidate deltas/audit artifacts;
  - runtime receipts.
- No broad scan that invents evidence ownership.
- L7 output records link to the existing execution manifest as producer receipt where known.

**TDD**
- [ ] RED: L7 result artifact refs are persisted as `result`.
- [ ] RED: a path present as both L7 output and result is not duplicated.
- [ ] RED: candidate delta/audit evidence is registered.
- [ ] RED: tampering remains fail-closed.

## Task 3 — Single L10c finalization owner

**Files**
- Modify: `src/research_loop/commands/reporting.py`
- Modify: `src/research_loop/commands/continuation.py`
- Modify: `src/run_loop.py`
- Modify: `tests/test_cross_round_e2e.py`
- Modify: `tests/test_run_loop_guards.py`

**Contract**
- `aggregate-report`/L10c owns round finalization:
  1. generate candidate-scoped reports;
  2. run required Obsidian projection;
  3. freeze round evidence manifest only after sync succeeds.
- `run_loop.py` must not run a second independent Obsidian path.
- `emit-loop-memory` requires an existing valid round manifest and only links it by path/hash; it never creates/rebuilds the manifest.
- A failed Obsidian sync leaves no frozen round manifest.

**TDD**
- [ ] RED: Obsidian sync failure makes L10c fail and no manifest is frozen.
- [ ] RED: runner checks aggregate-report return code and does not claim completion on failure.
- [ ] RED: `emit-loop-memory` fails if L10c manifest is absent.
- [ ] RED: successful L10c leaves a manifest consumable by continuation.

## Task 4 — Earliest runner restore guard

**Files**
- Modify: `src/run_loop.py`
- Modify: `tests/test_run_loop_guards.py`

**Contract**
- After component dependency checks, but before provider readiness or main-agent handoff, call the same `restore_previous_round()` authority used by the L0 context gate.
- Initial round remains `NOT_APPLICABLE` and unchanged.
- Continuation failure logs the exact `L0_RESTORE_*` code and returns hard-stop code 3.

**TDD**
- [ ] RED: bad continuation manifest prevents `preflight_providers()` from being called.
- [ ] RED: bad continuation manifest prevents main-agent handoff.
- [ ] RED: initial round still reaches existing provider logic.

## Task 5 — CI and documentation closure

**Files**
- Modify: `.github/workflows/l0-contract.yml`
- Modify: `docs/DAG_TOPOLOGY.md`
- Update: this plan/spec only where behavior changed.

**Contract**
- Keep `git diff --check` meaningful; fetch PR base history instead of removing the check.
- Document one L0 node, round evidence restore, current blocking vs future literature-transport readiness, and required Obsidian finalization.

## Task 6 — Verification

No new production scope unless a failing test proves a contract defect.

- [ ] L0 targeted tests GREEN.
- [ ] Provider runtime tests GREEN.
- [ ] L4/L4.5 regression tests GREEN.
- [ ] Full suite GREEN.
- [ ] `git diff --check` GREEN.
- [ ] PR #15 diff reviewed for accidental L4/literature-transport expansion.
- [ ] PR #15 remains draft until local real-environment pilot is performed.

## Completion boundary

GitHub-side work is complete only when all repository tests/checks are green and no known L0 contract bug remains. The final real environment acceptance is separate and must be run locally because it requires the user's actual Academic Research runtime, PubMed MCP, Zotero Desktop, Obsidian vault, and cross-round filesystem state.