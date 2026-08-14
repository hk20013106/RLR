# Meta-RLR Phase 2 — Local One-Turn Host Implementation Plan

Date: 2026-08-13
Design: `docs/superpowers/specs/2026-08-13-meta-rlr-phase2-local-host-design.md`

## Goal

Implement the smallest local Windows-oriented Host that executes exactly one LoopX-governed Meta-RLR software-maintenance turn using the existing Phase 1 observation and verification boundary.

Reuse LoopX Path A, native Git worktrees, Codex CLI, and existing RLR verification profiles. Do not add a scheduler, database, scientific DAG node, LoopX-internal dependency, GitHub runtime controller, automatic merge, or compatibility fallback.

## Frozen architectural constraints

1. RLR scientific DAG and `src/research_loop/` business logic are out of scope.
2. LoopX remains the only durable maintenance lifecycle/writeback/settlement owner.
3. Git/GitHub remain source/PR authorities; GitHub is not the runtime scheduler.
4. The Host is one-shot and owns no durable state.
5. Event revision and repair worktree base must match exactly.
6. Codex cannot commit, push, merge, mutate LoopX, or count its own output as verification.
7. Independent RLR verification is required before success settlement.
8. LoopX pinned commit `80877982216577174e3e7c7cca9804c5a3a3148b` is the CLI contract authority.
9. Fresh execution uses two-stage quota authorization: unscoped frontier first, then scoped `turn_instance_id`.
10. Canonical successful settlement is `todo complete(turn_id) → refresh-state(turn_id, outcome_progress, repair worktree) → quota spend-slot(turn_id)`.
11. `refresh-state` is the durable writeback required by LoopX before turn-scoped spend; it must not be bypassed or emulated in Meta-RLR.
12. Crash recovery reuses Git verified-commit provenance plus LoopX native idempotent completion/refresh/spend replay; no Host journal/database is allowed.
13. Production changes require RED tests, minimal GREEN implementation, targeted verification, then full regression.
14. No auto-merge.

## Phase A — Ground contracts and reuse

### A1. Baseline review

Inspect `AGENTS.md`, current `main`, Phase 1 Meta-RLR code/tests, existing verification profiles, and root CLI conventions.

Acceptance:

- no scientific/runtime authority moves;
- Phase 2 remains under `src/rlr_maintenance/`;
- no duplicate validator/profile/state registry is introduced.

### A2. Reuse survey

Confirm pinned LoopX direct CLI Path A is the compatibility baseline and already owns todo, quota, claim, completion, refresh writeback, and spend.

Confirm Codex CLI provides bounded non-interactive execution.

Reject third-party orchestrators that duplicate LoopX lifecycle state or Git worktree authority.

### A3. Verify settlement from source, not draft assumptions

Pinned LoopX source/docs prove:

- `refresh-state` is a registered production CLI command;
- custom-runner Path A requires writeback then refresh then spend;
- turn-scoped `refresh-state` requires an accountable `delivery_outcome`;
- accountable outcomes are `outcome_progress` and `primary_goal_outcome`;
- Meta-RLR uses `outcome_progress` for one verified software repair;
- `quota spend-slot` requires the matching accountable refresh-state writeback/receipt;
- completion, refresh writeback, and spend are replayable under the same settlement identity.

Any earlier Phase 2 draft claiming that `refresh-state` does not exist is superseded.

## Phase B — TDD contracts

### B1. LoopX external boundary

Tests require wrappers for:

- `quota should-run` with and without `turn_instance_id`;
- `todo add`;
- `todo claim`;
- blocked `todo update`;
- `todo complete(turn_instance_id)`;
- `refresh-state(todo_id, turn_instance_id, delivery_outcome, delivery_workspace_path)`;
- `quota spend-slot(turn_instance_id)`.

Assertions:

- argv list + `shell=False`;
- explicit registry remains supported;
- malformed/non-object/non-zero output fails closed;
- no LoopX Python internals are imported;
- turn-scoped refresh accepts only accountable delivery outcomes;
- the same turn id crosses complete, refresh, and spend.

### B2. Codex adapter

Require:

- `codex exec`;
- exact repair-worktree cwd;
- workspace-write sandbox;
- ephemeral/non-interactive execution;
- structured bounded final result;
- no dangerous sandbox bypass;
- no raw transcript as maintenance truth.

### B3. Git workspace and recovery

Require:

- exact event revision;
- deterministic event/todo worktree identity;
- collision fail-closed behavior;
- changed paths derived from Git;
- Host commits exactly the verified path set;
- commit includes public Meta-RLR provenance trailers;
- commit is immediately read back through the recovery parser;
- recovery accepts only one clean commit directly above the event base;
- dirty/ambiguous/wrong-parent/wrong-provenance state fails closed.

### B4. Host frontier

Require:

1. recovery probe before fresh todo creation;
2. idempotent LoopX todo add if no recovery exists;
3. first quota read unscoped;
4. no-run stops before claim/Codex;
5. different frontier defers;
6. only matching event todo permits deterministic turn creation;
7. second quota read uses that turn id and must preserve the same frontier;
8. only then may claim occur.

### B5. Host success/failure order

Fresh success:

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
→ refresh-state(turn_id, outcome_progress, repair worktree)
→ quota spend-slot(turn_id)
```

Failure gates:

- claim/worktree failure → no Codex;
- Codex failure → no success settlement;
- worker HEAD movement/empty diff → blocked;
- verification failure → no verified commit/complete/refresh/spend;
- post-verification diff mutation → blocked;
- commit/readback failure → no complete/refresh/spend;
- completion failure → no refresh/spend;
- refresh failure → no spend.

### B6. Crash recovery

Represent the post-verification crash window:

```text
scoped LoopX turn exists
+ exact provenance-bound verified Git commit exists
+ process crashed before/during settlement
```

Require:

- no Codex rerun;
- event/profile/base/todo/turn provenance matches current facts;
- recovered commit is independently reverified;
- fresh verification PASS replays `complete → refresh → spend` under the same turn id;
- same repair worktree is supplied as delivery workspace;
- no Host journal/database is consulted.

### B7. Architecture guards

Prohibit:

- `research_loop → rlr_maintenance` reverse dependency;
- LoopX Python internal imports;
- daemon/scheduler/database/state-store modules;
- GitHub workflow as Meta-RLR runtime owner;
- automatic merge;
- duplicate state/provenance authority.

## Phase C — Minimal implementation

### C1. `LoopXCli`

Keep `run_json()` as the only subprocess/JSON parser. Add only pinned direct-CLI lifecycle wrappers, including accountable `refresh_state()`.

### C2. `CodexCli`

External worker adapter only. It builds safe argv, runs in the isolated worktree, parses bounded output, and persists no raw transcript as truth.

### C3. `GitWorkspace`

Own only Git mechanics: exact base, worktree, inspection, exact verified staging, provenance-bound commit, and verified-commit recovery readback.

### C4. `MetaRLRHost`

Own sequencing only: validate event, route profile, recovery probe, fresh frontier, claim, Codex, independent RLR verification, verified commit, complete, refresh, spend.

The Host persists no state.

### C5. Local CLI

Expose one explicit command only:

```powershell
python meta_rlr.py run-once `
  --event <event.json> `
  --repo <RLR checkout> `
  --loopx-project <LoopX control root> `
  --goal-id <goal> `
  --agent-id <agent> `
  --workspace-parent <path> `
  [--registry <path>]
```

`--loopx-project` is a CLI working/control root, not authority to override LoopX's registered goal project. `refresh-state` therefore lets LoopX resolve its project from the registry and separately receives the repair worktree as `delivery_workspace_path`.

No permanent loop or GitHub wake controller is introduced.

## Phase D — Automated qualification

### D1. Targeted Phase 2 tests

Run relevant `tests/test_meta_rlr_*` for LoopX, Codex, Host/frontier, workspace/recovery, and architecture.

### D2. Existing Meta-RLR regression

```powershell
python -m pytest tests/test_meta_rlr_*.py -q
```

### D3. Full RLR regression

```powershell
python -m pytest -q
python run_loop.py --help
python meta_rlr.py --help
```

No completion claim until the exact PR head passes.

### D4. Diff/coherence review

Verify no:

- `src/research_loop/**` business-logic changes;
- LoopX vendoring;
- second scheduler/database;
- GitHub runtime workflow;
- automatic merge;
- compatibility fallback;
- unrelated refactor.

If found, redesign instead of rationalizing the drift.

## Phase E — Draft PR qualification

Keep PR #25 Draft through automated qualification.

PR evidence must state:

- local Windows runtime is authoritative;
- GitHub CI is development verification only;
- pinned LoopX direct CLI is the integration contract;
- real settlement includes accountable refresh-state before spend;
- crash recovery uses Git provenance + LoopX idempotent settlement;
- no automatic merge;
- native Windows acceptance remains required.

## Phase F — Native Windows real acceptance

After an exact Phase 2 code head is GREEN, run the real pinned LoopX + Codex + Git + RLR path on native Windows.

Minimum acceptance:

1. controlled failing RLR revision;
2. valid event bound to that exact revision;
3. real pinned LoopX goal/agent;
4. one fresh `meta_rlr.py run-once` repair;
5. prove unscoped then scoped quota and one claim;
6. prove Codex edits only the repair worktree;
7. prove independent RLR verification;
8. prove failed verification cannot commit/complete/refresh/spend;
9. prove success creates one provenance-bound verified commit;
10. prove completion uses the scoped turn id;
11. prove `refresh-state` creates the accountable writeback for the same todo/turn and repair worktree;
12. prove spend succeeds only after that refresh;
13. simulate crash after verified commit at settlement boundaries;
14. fresh process re-verifies, skips Codex, and safely replays complete/refresh/spend;
15. repeated replay does not duplicate effects/quota;
16. prove no Host-owned session database or transcript is required.

## Completion gate

Phase 2 is eligible for merge review only when:

- design and implementation are coherent with pinned LoopX source;
- exact PR head Meta-RLR tests pass;
- full RLR regression passes;
- GitHub CI passes;
- native Windows real fresh-turn + crash-recovery acceptance passes;
- no production code was changed for stale compatibility;
- no second authority or automatic merge was introduced.
