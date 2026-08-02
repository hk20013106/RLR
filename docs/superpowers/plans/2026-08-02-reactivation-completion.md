# Historical Hypothesis Reactivation Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete only the already-approved `NEW / REACTIVATE / REVISE / DERIVE` lifecycle and L3 blocker review, without expanding reopening, export, semantic search, or unrelated ledger behavior.

**Architecture:** Keep the existing `HypothesisLedger.commit_delta()` transaction as the authoritative persistence path. Add focused extension modules that validate reactivation provenance before L1 commit, normalize `origin`, and transform only the L1 lifecycle event emitted by the existing transaction. Extend v2.1 JSON Schemas after the existing method-contract extension, then add narrow cross-delta checks for source recall and L3 blocker decisions.

**Tech Stack:** Python 3.11/3.12, SQLite, `jsonschema`, pytest, GitHub Actions on Windows.

## Global Constraints

- Do not rewrite or delete any historical family, version, occurrence, event, workflow state, or epistemic state.
- Do not change legacy v2.0 behavior.
- Do not implement formal reopening of `FALSIFIED` hypotheses in this plan.
- Do not implement export, snapshot, embedding search, or unrelated CLI changes.
- `REACTIVATE` must reuse the exact prior `hypothesis_id` and create a new occurrence.
- `REVISE` must create a new version in the same family.
- `DERIVE` must create a new family/version linked to recalled parents.
- Omitted `origin` must persist as `NEW`.
- A non-`NEW` source must occur in the exact recall artifact bound to the current candidate and round.
- Only one GitHub CI run is triggered after all code, tests, and documentation changes are complete.

---

## Pre-implementation review findings

1. The existing L1 transaction already derives stable IDs from the exact definition. This means the correct identity behavior can be retained without replacing the transaction:
   - unchanged definition naturally reuses `hypothesis_id`;
   - changed definition with unchanged statement naturally creates a new version in the same family;
   - changed statement naturally creates a new family.
2. The missing behavior is concentrated at the extension boundary:
   - schema does not define origin/source fields;
   - source and recall provenance are not checked before the transaction;
   - the base L1 event is always `PROPOSED` rather than `REPROPOSED`, `REVISED`, or `DERIVED`;
   - L3 does not require blocker assessment or obligations.
3. Replacing or copying the full `commit_delta()` transaction would be a high-risk bug source. The implementation will wrap the existing L1 path and alter only its event metadata through a scoped transaction-local context.
4. Contract installation order is a real bug risk. `method_contracts.install()` rebuilds persisted v2.1 schemas, so reactivation contracts must install after method contracts and rebuild persisted v2.1 schemas once more.
5. Recall validation must use the immutable artifact cursor. Checking only that a source exists in the live ledger would allow post-recall facts to leak into L1.
6. `FALSIFIED` must remain blocked. The existing L9a reopening behavior is not reused as an implicit L1 reopening shortcut.

---

### Task 1: Extend v2.1 L1 and L3 contracts

**Files:**
- Create: `src/research_loop/hypothesis_reactivation_contracts.py`
- Modify: `src/research_loop/__init__.py`
- Test: `tests/test_hypothesis_reactivation_contracts.py`

**Interfaces:**
- `install(contracts_module) -> None`
- L1 hypothesis fields: `origin`, `source_hypothesis_id`, `source_occurrence_id`, `parent_hypothesis_ids`, `change_summary`, `reactivation_basis`.
- L3 fields: `reactivation_assessment`, `downstream_obligations`.

- [ ] Add conditional JSON Schema rules for `NEW`, `REACTIVATE`, `REVISE`, and `DERIVE`.
- [ ] Keep submission compatibility when `origin` is omitted.
- [ ] Require persisted L1 hypotheses to contain normalized `origin`.
- [ ] Reject `SELECTED + UNRESOLVED` at schema level.
- [ ] Require at least one downstream obligation for `SELECTED + PARTIALLY_RESOLVED`.
- [ ] Rebuild persisted v2.1 schemas after installation.

### Task 2: Validate source identity and normalize L1 origins

**Files:**
- Create: `src/research_loop/hypothesis_reactivation.py`
- Modify: `src/research_loop/__init__.py`
- Extend tests: `tests/test_hypothesis_reactivation.py`

**Interfaces:**
- `install(ledger_module) -> None`
- The wrapper normalizes every native v2.1 L1 item to explicit `origin` before delegating to the existing transaction.

- [ ] Load and authenticate the current candidate/round recall artifact.
- [ ] Require every non-`NEW` source hypothesis and source occurrence to appear in the artifact.
- [ ] Reject duplicate target definitions in one L1 submission.
- [ ] `REACTIVATE`: require exact statement, operationalization, and falsification criteria match; require basis when eligibility is not `ELIGIBLE`; reject `BLOCKED_FALSIFIED`.
- [ ] `REVISE`: require the same normalized statement and a changed definition.
- [ ] `DERIVE`: require at least one recalled parent and a different normalized statement from every parent.
- [ ] `NEW`: reject source/parent fields.

### Task 3: Preserve the base transaction and emit correct lifecycle events

**Files:**
- Modify: `src/research_loop/hypothesis_reactivation.py`
- Extend tests: `tests/test_hypothesis_reactivation.py`

**Interfaces:**
- Scope event transformation to the active L1 commit only.
- Transform the base L1 event by `proposal_key`:
  - `NEW` → `PROPOSED`
  - `REACTIVATE` → `REPROPOSED`
  - `REVISE` → `REVISED`
  - `DERIVE` → `DERIVED`

- [ ] Preserve the original transaction, finalization callback, idempotency, and workflow projection.
- [ ] Add source IDs, recall hash/cursor, change summary, basis, and parents to event payloads.
- [ ] Verify unchanged reactivation reuses the old `hypothesis_id` but creates a distinct `occurrence_id`.
- [ ] Verify the historical rejected occurrence remains `REJECTED`.
- [ ] Verify revision retains family ID and derivation changes family ID.

### Task 4: L3 blocker review and obligations

**Files:**
- Create: `src/research_loop/hypothesis_reactivation_constraints.py`
- Modify: `src/research_loop/__init__.py`
- Extend tests: `tests/test_hypothesis_reactivation.py`

**Interfaces:**
- Install a narrow wrapper around finalized-upstream validation for L1/L3 only.

- [ ] Require L3 reactivation assessment for every non-`NEW` current occurrence.
- [ ] Require `prior_blocking_event_ids` to be drawn from the recalled historical blockers.
- [ ] Reject selecting `UNRESOLVED` reactivations.
- [ ] Require obligation IDs for partially resolved selected reactivations.
- [ ] Record `REACTIVATION_REVIEWED` as the L3 event type while preserving workflow status from disposition.

### Task 5: End-to-end regression and documentation

**Files:**
- Create: `tests/test_hypothesis_reactivation_e2e.py`
- Create: `docs/HYPOTHESIS_POOL.md`
- Modify: `README.md`
- Restore: `.github/workflows/ci.yml` to the repository's standard full matrix; remove all temporary targeted-CI behavior.

- [ ] End-to-end case: Round 1 proposed → attacked → rejected; Round 2 recall → reactivated → selected.
- [ ] Assert old rejection and attacks remain intact.
- [ ] Assert new occurrence and `REPROPOSED` event are appended.
- [ ] Add revision and derivation end-to-end cases.
- [ ] Document user-visible JSON examples and the distinction between rejection, reactivation, revision, derivation, and falsification.
- [ ] Perform static review for unbounded/generalized changes.
- [ ] Open PR once and run one final Python 3.11/3.12 full CI matrix.
- [ ] Fix only failures caused by this focused change; do not broaden scope.

## Self-review

- Spec coverage: Covers the approved Milestone 1 identity/provenance and L3 blocker-review requirements. Formal reopening and export remain explicitly excluded.
- Placeholder scan: No TBD or unspecified implementation steps remain.
- Type consistency: Uses existing IDs (`H:`, `HF:`, `HO:`, `HE:`), existing `HypothesisRecall/v1`, and existing v2.1 persisted-schema rebuilding pattern.
- Risk control: Reuses the existing transaction rather than cloning it; installs contracts after method contracts; validates recall at its fixed cursor; triggers GitHub CI only once after completion.
