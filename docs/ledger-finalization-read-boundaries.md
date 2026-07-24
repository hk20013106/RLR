# Implementation Plan: Ledger Finalization Read-Boundary Enforcement

> Scope: close the crash-window correctness gap found in code review of branch
> `codex/hypothesis-ledger-cutover`. Plan only - no production code is modified
> by this document. Do **not** reorder commit/finalize, and do **not** split
> `engine.py` here - that is **Plan 2**,
> [`engine-modular-extraction.md`](./engine-modular-extraction.md), sequenced
> after this fix lands.
>
> **This plan is now split into two independent work packages (1A and 1B).**
> They share the same correctness context but must be separately reviewed,
> tested, and committed.

## Execution sequence

```text
Plan 1A (finalization read-boundary correctness) -> Plan 1B (native-v2 gate coverage)
```

Plan 1B depends on Plan 1A's `commit_finalized()` helper but does not depend
on the finalized-predicate SQL. Both must land before Plan 2 Batch C.

---

## Plan 1A: Finalization Read-Boundary Correctness

### Task Type

- [x] Backend (SQLite ledger read paths + tests)
- [ ] Frontend

### Problem (verified against current working tree, 2026-07-24)

An emission (one committed delta) is only *consumable* once a marker row exists
in `committed_emissions`. The artifact resolver enforces this
(`delta.py:47-58`, `_v2_commit_valid`); three ledger read paths do not, so a
crash between `commit_delta` and `finalize_emission` leaves an **orphan**
emission that the resolver hides but context injection, ranking, and verify all
treat as valid.

Root cause: `engine.py:_emit_delta_v2` (L1577-1625) performs the only feasible
ordering: `commit_delta` → write artifact → write receipt →
`finalize_emission`. A crash between `commit_delta` and `finalize_emission`
creates an orphan. This is **unavoidable** when SQLite and the filesystem are
separate durability domains; the fix is fail-closed filtering at the read
boundaries.

**Plan 1A does NOT modify `engine.py` or `_emit_delta_v2`.** The crash window
is inherent in the two-phase write protocol. Adding `try/except` cleanup would
not help (process termination cannot be caught) and deleting committed events
would violate append-only semantics. The fix is purely in
`hypothesis_ledger.py` consumer queries.

| Location | Behavior | Status |
| --- | --- | --- |
| `engine.py:1577-1625` (`_emit_delta_v2`) | `commit_delta` → write artifact → write receipt → `finalize_emission`. Crash window. | root cause (do not modify) |
| `delta.py:47-58` (`_v2_commit_valid`) | Joins `emissions e JOIN committed_emissions c` - fail-closed, correct. | reference pattern |
| `hypothesis_ledger.py:943-950` (`ranking_inputs`, proposal query) | `events JOIN versions JOIN emissions`, **no** marker join. | BUG |
| `hypothesis_ledger.py:969-974` (`ranking_inputs`, decision query) | selects decision event with **no** marker join - an orphan L3/L10b decision flips `formal_decision`. | BUG |
| `hypothesis_ledger.py:999` (`verify`) | only `events LEFT JOIN emissions`; never asserts finalization -> never flags orphans. | BUG |
| `hypothesis_ledger.py:1114-1130` (`materialize_authorized_context`) | default cursor `MAX(commit_seq)` and event select, **no** marker join -> orphan event injected into a downstream node's authorized snapshot. | BUG |
| `hypothesis_ledger.py:1001-1021` (`verify` rebuild replay) | projection replay reads raw `events` -> would replay an orphan as authoritative. | BUG |

### Scope

- Add one private `FINALIZED_EMISSION_PREDICATE` SQL constant in `hypothesis_ledger.py`.
- Apply it to every **consumptive** query in `ranking_inputs`,
  `materialize_authorized_context`, `verify`, and **`snapshot_candidate`**.
- Use its negation for orphan diagnostics in `verify`.
- Gate the `verify(rebuild=True)` projection replay to finalized events only.
- Add `commit_finalized()` test helper.
- Add crash-window tests.
- Bypass audit: enumerate every `events`/`emissions` read in the four methods.

### Out of scope (explicitly)

- `engine.py` / `_emit_delta_v2` - no modification.
- Database schema changes, index additions, or migrations.
- Projection protocol hardening (commit_delta writes projections before
  finalization; later commit_delta reads them). H0 verdict: real but
  self-healing on retry, limited to same candidate/round, detectable by
  `verify(rebuild=True)` after Plan 1A. No Plan 1C needed at this stage.
  Recorded as known limitation.
- Automatic orphan deletion, repair, or finalization.

### Technical Solution

```sql
-- one definition, emission aliased as m in every consumptive query
FINALIZED_EMISSION_PREDICATE =
    "EXISTS (SELECT 1 FROM committed_emissions c WHERE c.delta_hash = m.delta_hash)"
```

**Query changes required:**

1. **Proposal query** (L943-950): already joins `emissions m` - add
   `AND FINALIZED_EMISSION_PREDICATE` to the WHERE clause.
2. **Decision query** (L969-974): currently reads only `events`. Must add
   `JOIN emissions m ON m.commit_seq = e.commit_seq` then apply the predicate.
3. **Default cursor** (L932-934, `ranking_inputs`): change
   `MAX(commit_seq) FROM events` to `MAX(e.commit_seq) FROM events e JOIN
   emissions m ON m.commit_seq=e.commit_seq WHERE FINALIZED_EMISSION_PREDICATE`.
4. **`materialize_authorized_context` cursor** (L1114-1118): same pattern as
   above.
5. **`materialize_authorized_context` event select** (L1124-1130): add
   `JOIN emissions m ON m.commit_seq = e.commit_seq` and
   `AND FINALIZED_EMISSION_PREDICATE`.
6. **`verify` orphan detection** (L999): add
   `SELECT m.delta_hash FROM emissions m WHERE NOT FINALIZED_EMISSION_PREDICATE`
   as orphan diagnostics (stable prefix
   `orphan emission missing finalization marker:`).
7. **`verify(rebuild=True)` replay** (L1020-1021): filter
   `events e JOIN emissions m ON m.commit_seq=e.commit_seq WHERE
   FINALIZED_EMISSION_PREDICATE`.

**SQLite correctness:** `committed_emissions.delta_hash` is a primary key, so
the `EXISTS` subquery uses an indexed lookup. `EXISTS` is preferred over a
direct `JOIN` because it states a Boolean authorization condition, cannot alter
result cardinality, and its negation cleanly defines orphan detection.

**Performance:** No concern at current ledger scale. Do not add indexes
speculatively. If future scale demands it, candidate indexes are
`events(commit_seq)`, `events(project_id, candidate_id, round_id, commit_seq)`,
and `events(occurrence_id, commit_seq)` - but those need compatibility and
migration consideration and are out of scope.

### Cursor semantics (verified)

- **Default `MAX(commit_seq)`** (L932-934): currently reads from raw `events`.
  After Plan 1A, it reads from `events e JOIN emissions m WHERE
  FINALIZED_EMISSION_PREDICATE`, so the cursor is based on **finalized history
  only**.
- **Explicit `as_of`**: when `as_of` points to an orphan's `commit_seq`, the
  orphan is still excluded because the predicate filters by emission marker,
  not by `commit_seq` range. When `as_of` exceeds the finalized history, the
  cursor returns the latest finalized `commit_seq` (the predicate filters
  non-finalized rows). The `as_of` validation in
  `materialize_authorized_context` (L1120) checks `cursor < 0 or cursor >
  int(latest)` - after Plan 1A, `latest` is the finalized max, so an `as_of`
  pointing at an orphan will fail the range check.
- **Ranking proposal and decision**: both use the same `cursor` value, so they
  see the **same finalized snapshot**. This is already the case in the current
  code (both use the `cursor` variable); Plan 1A only changes what `cursor`
  resolves to.
- **Rebuild replay**: filters by `FINALIZED_EMISSION_PREDICATE`, so orphans are
  not replayed as authoritative. An orphan's events exist in the `events` table
  but are skipped during projection rebuild.

### Forensic vs. consumptive API boundary

| API | Classification | Treatment |
| --- | --- | --- |
| `ranking_inputs` (proposal + decision queries) | **Consumptive** | Filter orphans |
| `materialize_authorized_context` (cursor + event select) | **Consumptive** | Filter orphans |
| `verify` (orphan diagnostics) | **Forensic** | Observe and report orphans (negation of predicate) |
| `verify(rebuild=True)` (projection replay) | **Consumptive** | Filter orphans from replay |
| `graph` (L877-902) | **Forensic** (hypothesis-scoped history) | Unchanged this phase |
| `history` (L904-912) | **Forensic** (event log) | Unchanged this phase |
| `search` (L914-920) | **Forensic** (statement search) | Unchanged this phase |
| `snapshot_candidate` (L1062-1081) | **Consumptive** (loop memory -> next candidate) | **Included in Plan 1A** (H0 verdict: orphan enters loop memory -> next candidate context) |
| `commit_delta` internal reads (projections, occurrences) | **Write prerequisite** | **Known gap** - protocol hardening, separate plan |

### Implementation Steps (TDD order)

1. **Baseline** - capture branch/status/diff for target files, run the narrow
   suites, and separate real failures from the known 61.74% coverage-gate
   failure. Deliverable: recorded baseline; no edits.

2. **Add `commit_finalized()` test helper** (extend `tests/native_v2_helpers.py`)
   that runs the full production sequence: `commit_delta` -> write canonical
   artifact bytes -> write receipt -> `finalize_emission`. This is distinct
   from the existing `commit_v2()` helper (L18-44) which already does the full
   sequence - **verify whether `commit_v2()` already serves this purpose**.
   If `commit_v2()` is sufficient, add a thin alias `commit_finalized =
   commit_v2` for clarity. If not, extend it. Migrate ordinary fixtures in
   `tests/test_hypothesis_ledger.py` and `tests/test_ranking_cli.py` to it.
   Bare `commit_delta` stays **only** in deliberate crash-window tests.
   Deliverable: normal lifecycle/ranking tests still green *before* the filter
   lands.

3. **Add failing crash-window tests** (`tests/test_hypothesis_ledger.py`):
   - orphan L1 hidden from `ranking_inputs` until finalized;
   - orphan L3/L10b decision keeps `formal_decision == "UNAVAILABLE"` until
     finalized;
   - orphan event absent from `materialize_authorized_context` (empty events,
     cursor 0) until finalized;
   - `verify()` emits exactly one orphan diagnostic (stable prefix
     `orphan emission missing finalization marker:`) that clears on finalize.
   Deliverable: these fail for the right reason.

4. **Add the predicate** - one private module-level constant in
   `hypothesis_ledger.py`. Private, no caller-supplied aliases, no user data
   interpolation, schema/triggers/`_v2_commit_valid` untouched.

5. **`ranking_inputs`** - apply predicate to (a) the default-cursor
   `MAX(commit_seq)`, (b) the proposal query (L943-950), and
   **(c) the decision query** (L969-974). (c) requires adding a
   `JOIN emissions m ON m.commit_seq = e.commit_seq` to the decision query
   before the predicate can be applied.

6. **`materialize_authorized_context`** - apply predicate to the default
   `latest` cursor (L1114-1118) and the event select (L1124-1130).
   Preserve DAG `allowed_nodes`, L9a/L9b mutual invisibility, snapshot hashing,
   append-only collision checks, and explicit `as_of` validation (now measured
   against finalized history).

7. **`verify`** - add orphan detection
   (`emissions m WHERE NOT FINALIZED_EMISSION_PREDICATE`) as deterministic
   diagnostics, and gate the `rebuild=True` projection replay (L1020-1021) to
   finalized events only. Never delete/repair/finalize orphans inside `verify`.

8. **Bypass audit** - enumerate every `events`/`emissions` read inside the three
   methods; each consumptive query uses the predicate, each orphan diagnostic
   uses its negation. Leave forensic/history APIs (`graph`, `history`,
   `search`) outside these three boundaries unchanged this phase. Record
   `snapshot_candidate` as a known consumptive gap for follow-up.

### Key Files

| File | Operation | Description |
| --- | --- | --- |
| `src/research_loop/hypothesis_ledger.py` | Modify | Add `FINALIZED_EMISSION_PREDICATE`; apply in `ranking_inputs` (cursor+proposal+decision), `materialize_authorized_context` (cursor+select), `verify` (orphan detect + rebuild replay). |
| `tests/native_v2_helpers.py` | Modify | Verify/extend `commit_finalized()` full-sequence helper (may already be `commit_v2`). |
| `tests/test_hypothesis_ledger.py` | Modify | Migrate fixtures; add 4 crash-window tests. |
| `tests/test_ranking_cli.py` | Modify | Migrate fixtures to finalized emissions. |
| `src/research_loop/engine.py` | **Do NOT modify** | Plan 1A is purely in ledger read paths. |
| `src/research_loop/gates.py` | **Do NOT modify** | Gate logic is unaffected. |

### Risks and Mitigation

| Risk | Mitigation |
| --- | --- |
| Predicate duplicated/subtly divergent across 3 methods | One private constant; step 8 bypass audit. |
| Orphan decision still flips ranking if only proposal filtered | Step 5(c) filters the decision query too. |
| `verify(rebuild)` replays orphan as authoritative | Step 7 filters the replay select. |
| Existing tests relied on visibility right after bare `commit_delta` | Step 2 fixture migration to `commit_finalized`/`commit_v2`. |
| `as_of` validation breaks when cursor is finalized-only | Step 6 updates `latest` to finalized max; explicit `as_of` range check still works. |
| `snapshot_candidate()` consumes orphans (known gap) | Documented as out of scope; follow-up audit. |
| Projection/write-path contamination (broader protocol) | Documented as out of scope; separate protocol-hardening plan. |
| SQL injection via predicate | Static private fragment; all values stay bound parameters. |

### Definition of Done (Plan 1A)

- Crash-window tests pass (4 new tests).
- Orphan emissions invisible to `ranking_inputs`, `materialize_authorized_context`,
  and `verify(rebuild=True)`.
- `verify()` stably reports orphan diagnostics with prefix
  `orphan emission missing finalization marker:`.
- Orphan diagnostic clears after `finalize_emission`.
- No schema/protocol change.
- No modification to `engine.py`.
- Full pytest summary + coverage number recorded exactly; `git diff --check`
  and `run_loop.py --help` pass.
- Reviewer approval.

### Commit boundary

```text
commit: fix(ledger): finalized read-boundary correctness (Plan 1A)

- Add FINALIZED_EMISSION_PREDICATE in hypothesis_ledger.py
- Filter orphans in ranking_inputs, materialize_authorized_context, verify
- Add orphan diagnostics in verify
- Add crash-window tests
- Add commit_finalized test helper
```

---

## Plan 1B: Restore Native-v2 Gate Coverage

### Problem (verified against `tests/test_v06_divergence.py`, 445 lines)

~8 gate tests (L4/L6/L7/L10b) were rewritten so a formerly positive-path
assertion (`returncode == 0`) or a specific-reject reason (`"method_card"`,
`"grounding"`, `"branch"`, `"literature_changed_direction"`) now asserts only
the generic v1 cutover block `"only committed delta v2"`.

**Root cause verified:** The `_emit_l4`, `_emit_l6`, `_emit_l10b` test helpers
(L64-102) write raw v1-shape JSON and call `emit-delta` without
`schema_version: "2.0"` in the delta. The `cmd_emit_delta` function
(engine.py:1649-1654) checks `data.get("schema_version") == DELTA_SCHEMA_VERSION`
and routes to `_emit_delta_v2`; if it's not v2, and a binding exists, it rejects
with `"only committed delta v2"`.

So **all 10 gate tests hit the v1 guard before reaching any gate logic**. Both
accept and specific-reject coverage is gone. `test_l7_manifest_written_on_valid`
also deleted the only manifest-content assertions.

Additionally, `test_branch_gate_requires_prior_unexplored_statused` (L390-400)
inverted `assert ok is False and "b_atrial" in reason` -> `assert ok is True`.
This calls `_audit_branch_coverage` directly (gates.py:39-52), **not** via the
v1 guard. Verified: `_audit_branch_coverage` returns `True, ""` when
`from_memory` is true and `loop_type` is `divergent` but no prior branches are
recorded (because `_prior_unexplored_ids` returns empty for a fresh seed). So
the assertion `ok is True` is **correct for the current seed** - the test name
is misleading, not the assertion. The seed (`seed_revise_continuation`) does not
record any unexplored branches, so there is nothing to require.

### Scope

- Rewrite L4/L6/L7/L10b test helpers (`_emit_l4`, `_emit_l6`, `_emit_l10b`) to
  produce finalized v2 deltas using `commit_finalized()` from
  `native_v2_helpers.py`, so each test reaches its real gate.
- Restore specific reject reasons on bad input.
- Restore positive-path and manifest-content assertions on good input.
- Resolve the `test_branch_gate_requires_prior_unexplored_statused` semantic
  inversion: either seed an unexplored branch so the gate genuinely rejects, or
  rename the test to reflect what it actually verifies.

### Out of scope

- Plan 1A's finalized predicate (1B only needs the `commit_finalized` helper).
- Gate logic changes in `gates.py` or `hypothesis_contracts.py`.
- Coverage threshold fixes.

### CLI test boundary rules

Plan 1B must distinguish:

```text
upstream prerequisite state  vs.  target emission under test
```

1. `commit_finalized()` (or existing `commit_v2()`) may be used to build
   **upstream** finalized prerequisite state (e.g. seed an L1 hypothesis so
   L4 can reference it).
2. The **target** L4/L6/L7/L10b emission under test must go through the
   production CLI path:
   ```text
   schema_version=2.0 delta -> cmd_emit_delta / run_loop.py emit-delta -> real gate
   ```
3. Tests must NOT use helpers to write the target emission directly, as that
   bypasses the gate.
4. Reject tests must prove no finalization marker was created for the target.
5. Positive tests must prove artifact, receipt, marker, and necessary manifest
   content exist for the target.

### Implementation Steps

1. **Audit weakened gate tests** - enumerate every test in
   `test_v06_divergence.py` that asserts `"only committed delta v2"`. For each,
   determine: (a) what gate it was supposed to test, (b) what specific reject
   reason or positive assertion it should have, (c) what v2 fixture shape is
   needed to reach the gate.

2. **Resolve branch-gate semantic inversion** - trace
   `_audit_branch_coverage` (gates.py:39-52) and `_prior_unexplored_ids`. The
   current seed has no prior unexplored branches, so `ok is True` is correct.
   Either: (a) seed an unexplored branch in the prior candidate's
   `08_Audit/branch_ledger.json` so the gate genuinely rejects, and restore the
   `assert ok is False` assertion; or (b) if the gate was intentionally relaxed
   for seeds without prior branches, rename the test to
   `test_branch_gate_noop_when_no_prior_branches` and document why.

3. **Restore native-v2 per-gate coverage** - rewrite `_emit_l4`, `_emit_l6`,
   `_emit_l10b` helpers to use `commit_finalized()` and seed finalized v2
   upstream artifacts. For each L4/L6/L7/L10b test:
   - Assert the **specific** reject reason on bad input (and that no marker was
     created).
   - Assert success on good input (artifact + marker both exist).
   - Keep the generic `"only committed delta v2"` assertion **only** in the one
     test (`test_legacy_delta_without_new_fields_is_blocked_after_cutover`,
     L433-445) whose purpose is rejecting a legacy v1 delta file.

4. **Restore manifest assertions** - in `test_l7_manifest_written_on_valid`,
   assert the manifest content (script names, branch IDs, output hashes) after
   a successful v2 emission, not just `returncode != 0`.

### Key Files

| File | Operation | Description |
| --- | --- | --- |
| `tests/test_v06_divergence.py` | Modify | Rewrite v2 helpers; restore per-gate coverage; resolve branch-gate inversion. |
| `tests/native_v2_helpers.py` | Modify (via Plan 1A) | `commit_finalized()` helper. |
| `src/research_loop/gates.py` | Inspect (modify only if a confirmed v2 shape mismatch is found) | Referenced by step 2 gate tracing. |
| `src/research_loop/hypothesis_contracts.py` | Inspect | Referenced by step 3 for v2 delta shapes. |

### Risks and Mitigation

| Risk | Mitigation |
| --- | --- |
| Branch-gate inversion masks a real regression | Step 2 traces the gate before touching the assertion. |
| v2 fixture shape doesn't match gate expectations | Step 3 uses `commit_finalized` which produces real v2 deltas. |
| Gate tests still hit v1 guard if schema_version is missing | Verify `commit_finalized` sets `schema_version: "2.0"`. |
| Manifest assertions too strict | Assert only load-bearing fields (script name, branch_id, output hashes). |

### Definition of Done (Plan 1B)

- L4/L6/L7/L10b specific reject tests restored (assert specific reason, not
  generic v1 block).
- Positive-path tests restored (assert artifact + marker exist).
- Manifest content assertions restored in `test_l7_manifest_written_on_valid`.
- Branch-gate test either meaningfully asserts `False` first (with a seeded
  prior branch), or is renamed with rationale.
- Generic `"only committed delta v2"` assertion remains only in the legacy v1
  rejection test.
- Reviewer approval.

### Commit boundary

```text
commit: test(v06): restore native-v2 gate coverage (Plan 1B)

- Rewrite L4/L6/L7/L10b helpers to produce finalized v2 deltas
- Restore specific reject reasons and positive-path assertions
- Restore manifest content assertions
- Resolve branch-gate semantic inversion
```

---

## Relationship to Plan 2

Plan 2 Batch C (ledger CLI extraction) waits for Plan 1A because ledger/emit
extraction is **semantically coupled** to finalization and idempotency. The
sequencing is required even if the plans do not modify the same physical lines:
Plan 1A establishes the finalized read-boundary contract that Plan 2 Batch C
must preserve verbatim during extraction.

```text
                     ┌─ Plan 1A -> Plan 1B ─────────┐
H3 -> P2-PRE ────────┤                              ├─ SYNC BARRIER
                     └─ Plan 2 Batch A ─────────────┘
                                                       ↓
                                          Plan 2 Batch B -> C -> D -> E
```

Plan 1A/1B and Batch A may run in parallel after P2-PRE. Batch B does NOT
parallel Plan 1 (test fixture coupling). See
[`hermes-multi-agent-ledger-engine-plan.md`](./hermes-multi-agent-ledger-engine-plan.md)
§5 for the full dependency graph.
