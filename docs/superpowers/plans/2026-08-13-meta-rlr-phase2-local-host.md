# Meta-RLR Phase 2 — Local One-Turn Host Implementation Plan

Date: 2026-08-13
Design: `docs/superpowers/specs/2026-08-13-meta-rlr-phase2-local-host-design.md`

## Goal

Implement the smallest local Windows-oriented host that executes exactly one LoopX-governed Meta-RLR maintenance turn using the existing Phase 1 observation and verification boundary.

The implementation reuses LoopX Path A, native Git worktrees, Codex CLI, and existing RLR verification profiles. It must not add a scheduler, database, scientific DAG node, LoopX internal dependency, GitHub runtime controller, automatic merge, or compatibility fallback.

## Frozen architectural constraints

1. RLR scientific DAG and `src/research_loop/` business logic are out of scope.
2. LoopX remains the only durable maintenance state owner.
3. Git/GitHub remains source/PR authority; GitHub is not the runtime scheduler.
4. The Host owns no durable state and runs one bounded turn only.
5. Event revision and repair worktree base must match exactly.
6. Codex cannot commit, push, merge, mutate LoopX, or count its own output as verification.
7. Independent RLR verification is required before any success settlement.
8. Verification failure cannot complete a todo, write the durable refresh receipt, spend quota, or publish.
9. LoopX 0.4.5 pinned source is the CLI contract authority.
10. The canonical settlement is `todo complete(turn_id) → refresh-state(turn_id) → quota spend-slot(turn_id)`. `refresh-state` is LoopX-owned durable settlement writeback, not a Host scheduler or second state authority.
11. The Host must use two-stage quota authorization: unscoped frontier read first, scoped `turn_instance_id` read second.
12. Crash recovery reuses Git verified-commit provenance plus LoopX native idempotent settlement; no Host journal/database is allowed.
13. Production changes require RED tests, targeted verification, then full regression.
14. No auto-merge.

## Phase A — Ground and freeze contracts

### A1. Baseline review

Inspect `AGENTS.md`, Phase 1 Meta-RLR contracts/tests, current `main`, `loopx_cli.py`, RLR verification profiles, and root CLI conventions.

Acceptance:

- no scientific/runtime authority needs to move;
- Phase 2 can remain under `src/rlr_maintenance/`;
- no duplicate validator/profile registry is needed.

### A2. Reuse survey

Confirm from pinned LoopX 0.4.5 source/docs that direct CLI Path A is the compatibility baseline and already owns todo/quota/claim/completion/settlement state.

Confirm Codex CLI provides non-interactive bounded execution.

Reject third-party orchestrators that duplicate LoopX scheduling/todo/session state or Git worktree authority.

### A3. Correct the early settlement assumption

Verify the real pinned LoopX CLI rather than relying on draft documentation.

Result:

- `refresh-state` accepts the same settlement identity and writes the required durable receipt;
- `todo complete` accepts the settlement turn identity without terminal no-follow-up closure during settlement;
- `quota spend-slot` accepts the same turn identity and must run from the verified delivery worktree;
- completion, durable writeback, and spend support idempotent replay for the same identity.

This correction restores the authoritative sequence `complete(turn_id) → durable refresh-state writeback(turn_id) → spend(turn_id)`.

## Phase B — TDD contracts

### B1. LoopX external boundary tests

Require only documented direct-CLI wrappers:

- `quota should-run` with and without `turn_instance_id`;
- `todo add`;
- `todo claim`;
- blocked todo update;
- `todo complete(turn_instance_id)`;
- `quota spend-slot(turn_instance_id)`.

Assertions:

- argv uses lists and `shell=False`;
- registry remains explicit;
- malformed/non-object/non-zero output fails closed;
- no LoopX Python internals are imported;
- the wrapper issues explicit classification, delivery scale, outcome, worktree provenance, and capability arguments for `refresh-state`.

### B2. Codex adapter tests

Require:

- `codex exec`;
- exact worktree cwd;
- workspace-write sandbox;
- ephemeral/non-interactive execution;
- structured bounded final result;
- no dangerous sandbox bypass;
- no raw transcript persisted as maintenance truth.

### B3. Git workspace tests

Require:

- exact event revision resolution;
- deterministic event/todo branch/worktree identity;
- collision fail-closed behavior;
- changed paths derived from Git;
- verified commit created only from the independently verified path set;
- verified commit carries public Meta-RLR provenance trailers;
- the production commit is immediately read back through the same recovery parser;
- recovery accepts only one clean commit directly above the event base revision;
- dirty, ambiguous, wrong-parent, wrong-provenance state fails closed.

### B4. Host frontier tests

Require:

1. recovery probe occurs before creating a new maintenance todo;
2. if there is no recoverable commit, LoopX idempotent `todo add` returns the event-bound todo;
3. first `quota should-run` is unscoped;
4. no-run stops without claim/Codex/spend;
5. a different frontier todo causes defer with no write-capable action;
6. only after the event todo is selected does the Host derive `turn_instance_id`;
7. second `quota should-run(turn_id)` must still select the same todo;
8. only then may claim occur.

### B5. Host success/failure tests

Fresh success order:

```text
recovery probe
→ todo add
→ unscoped quota
→ scoped quota(turn_id)
→ claim
→ worktree
→ Codex
→ Git inspection
→ RLR verification
→ Git re-inspection
→ provenance-bound verified commit
→ todo complete(turn_id)
→ quota spend-slot(turn_id)
```

Failure assertions:

- claim failure → no Codex;
- worktree failure → no Codex;
- Codex failure → no complete/refresh/spend;
- worker-changed HEAD → no verification success;
- empty diff → blocked;
- verification fail → no verified commit/complete/refresh/spend;
- post-verification diff mutation → blocked;
- commit/readback fail → no complete/refresh/spend;
- completion or refresh failure → no later settlement step.

### B6. Crash-recovery tests

Construct a recovery state representing:

```text
scoped LoopX turn already authorized
+ exact verified Git commit already created
+ process crashed before/during settlement
```

Require:

- Host does not call Codex;
- commit event id matches the current maintenance event;
- commit profile id matches current `profile_for_event()`;
- commit todo id is a valid LoopX todo id;
- commit turn id equals the deterministic current event/todo turn id;
- recovered commit is reverified by RLR;
- only a fresh verification PASS allows `complete(turn_id) → refresh-state(turn_id) → spend(turn_id)` replay;
- no Host database/journal is consulted.

### B7. Architecture tests

Prohibit:

- `research_loop → rlr_maintenance` reverse dependency;
- LoopX Python internal imports;
- daemon/scheduler/database/state-store modules;
- GitHub workflow as Meta-RLR runtime owner;
- automatic merge authority;
- duplicate state/provenance authority.

## Phase C — Minimal implementation

### C1. `LoopXCli`

Keep `run_json()` as the only subprocess/JSON parser. Add only pinned Path A lifecycle wrappers.

### C2. `CodexCli`

External process adapter only. It constructs safe argv, runs Codex in the repair worktree, parses the bounded final result, and returns no durable raw transcript.

### C3. `GitWorkspace`

Own only Git mechanics:

- exact base resolution;
- create isolated repair worktree;
- inspect real HEAD/diff;
- stage exactly verified paths;
- create provenance-bound verified commit;
- read and validate a recoverable verified commit.

### C4. `MetaRLRHost`

Own only sequencing:

- validate event;
- route to existing verification profile;
- recovery probe;
- fresh todo/frontier flow when no recovery exists;
- two-stage quota binding;
- claim;
- Codex;
- independent RLR verification;
- verified commit;
- LoopX settlement.

The Host persists no state.

### C5. Local CLI

Provide only an explicit one-shot command:

```powershell
python meta_rlr.py run-once `
  --event <event.json> `
  --repo <RLR checkout> `
  --loopx-project <control root> `
  --goal-id <goal> `
  --agent-id <agent> `
  --workspace-parent <path> `
  [--registry <path>] `
  --quota-scan-root <public-safe-root>
```

The local host passes the pinned LoopX runtime profile `outer_controller` by
default. The quota scan root is deliberately required from the caller: LoopX
defines its implicit default as the LoopX installation root, while a real RLR
checkout or control project may contain private state and must not be guessed
as a public-safe scan root.

No permanent loop or GitHub wake controller is introduced.

## Phase D — Automated verification

### D1. Targeted Phase 2 tests

Run all `tests/test_meta_rlr_*` relevant to:

- LoopX CLI;
- Codex CLI;
- workspace/recovery;
- Host/frontier;
- architecture.

RED failures must correspond to missing/incorrect Phase 2 behavior, not test defects.

### D2. Existing Meta-RLR regression

Run:

```powershell
python -m pytest tests/test_meta_rlr_*.py -q
```

Phase 1 must remain intact.

### D3. Full RLR regression

Run:

```powershell
python -m pytest -q
python run_loop.py --help
python meta_rlr.py --help
```

No product claim is made until the exact PR head passes.

### D4. Diff/architecture review

Verify exact PR diff contains no:

- `src/research_loop/**` business-logic change;
- LoopX vendoring;
- second scheduler/database;
- GitHub runtime workflow;
- auto-merge;
- compatibility fallback;
- unrelated refactor.

If found, redesign rather than justify afterward.

## Phase E — Draft PR qualification

Keep PR #25 Draft through automated code qualification.

The PR must state:

- local Windows runtime is authoritative;
- GitHub CI is development verification only;
- LoopX direct CLI pin assumptions;
- crash recovery uses Git + LoopX native idempotency;
- no automatic merge;
- real Windows acceptance remains required.

## Phase F — Native Windows real acceptance

After the exact code head is GREEN in GitHub CI, run the real pinned LoopX + Codex + Git + RLR path on native Windows.

Minimum acceptance:

1. isolated RLR checkout at a controlled failing revision;
2. valid `RLRMaintenanceEvent/v1` bound to that revision;
3. real LoopX maintenance goal/agent using pinned direct CLI;
4. one `meta_rlr.py run-once` fresh repair;
5. prove unscoped frontier then scoped turn binding then one claim;
6. prove Codex modifies only the isolated worktree;
7. prove RLR verification is independent;
8. prove failed verification cannot commit/complete/refresh/spend;
9. prove success creates exactly one provenance-bound verified commit;
10. prove success completes, writes durable refresh-state, and spends under the same turn id;
11. simulate process interruption after verified commit but before settlement;
12. invoke a fresh process and prove recovery re-verifies the commit, skips Codex, and safely replays complete/refresh/spend under the same turn id;
13. prove repeated settlement does not double-complete/double-spend;
14. prove no Host-owned session database or transcript is required.

Draft PR publication, if later enabled, remains a separate downstream boundary and must stop before merge.

## Completion gate

Phase 2 becomes eligible for merge review only when:

- design and implementation are coherent;
- exact PR head targeted tests pass;
- all Meta-RLR tests pass;
- full RLR regression passes;
- GitHub CI passes;
- native Windows real LoopX + Codex + RLR fresh-turn and crash-recovery acceptance passes;
- no production code was changed merely for stale compatibility;
- no second authority or automatic merge was introduced.
