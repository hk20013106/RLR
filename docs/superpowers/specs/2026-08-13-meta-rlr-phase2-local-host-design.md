# Meta-RLR Phase 2 — Local One-Turn Host Design

Date: 2026-08-13
Status: implementation design, corrected against pinned LoopX 0.4.5 source

## 1. Purpose

RLR is the scientific object plane. It owns the research DAG, scientific state, evidence contracts, provider boundaries, controlled execution, and native verification. Meta-RLR exists only to maintain the RLR software system itself: diagnose software/runtime/contract/test failures, make bounded source repairs, verify them against RLR-owned invariants, and preserve maintenance continuity across sessions.

Phase 1 established two provider-neutral contracts under `src/rlr_maintenance/`:

1. observe authoritative RLR/runtime facts as `RLRMaintenanceEvent/v1`;
2. verify repairs through immutable `RLRVerificationProfile/v1` profiles and structured receipts.

Phase 2 closes the execution gap between those contracts and LoopX. It adds a thin **local one-turn host** that can execute exactly one bounded maintenance turn on the authoritative Windows runtime.

The Host is not another agent framework, scheduler, database, or scientific DAG node. It is a disposable coordinator across existing authorities.

## 2. Runtime and development boundary

Development happens in GitHub: source control, code review, ordinary CI, and Draft PRs.

Formal Meta-RLR execution happens locally on Windows. GitHub Actions is not the maintenance scheduler and does not own the runtime loop.

```text
GitHub                       Local Windows runtime
source / PR / CI             ---------------------
        │                    LoopX durable state
        │                           │
        └──── source checkout ──────┼──── Meta-RLR one-turn Host
                                    │        │
                                    │        ├─ Codex CLI
                                    │        ├─ Git repair worktree
                                    │        └─ RLR verification
                                    │
                                    └─ next local wake reads fresh state
```

## 3. Authority model

- **RLR** owns scientific truth and software verification contracts.
- **LoopX** owns maintenance goal/todo/claim/quota/history/writeback/settlement state.
- **Codex** owns semantic diagnosis and bounded code editing only.
- **Git** owns source identity, branches, commits, and worktrees.
- **GitHub** owns remote repository/PR/CI/merge state when publication is requested.
- **Meta-RLR Host** owns only local sequencing and fail-closed boundary checks.

The Host owns no durable state.

## 4. Reuse decision

Phase 2 reuses the pinned LoopX 0.4.5 direct-CLI Path A surface. It does not adopt a second orchestrator and does not import LoopX Python internals.

Reused wheels:

- LoopX JSON CLI for todo/quota/claim/completion/refresh/settlement;
- native Git worktrees and Git commit identity;
- Codex CLI `exec` for bounded coding work;
- existing `RLRMaintenanceEvent/v1` validation;
- existing verification profile routing and `run_profile()`.

Rejected:

- another scheduler/state database;
- GitHub Actions as runtime controller;
- a permanent local daemon with its own timing policy;
- third-party orchestration that duplicates LoopX or Git authority;
- LoopX experimental typed Turn in parallel with the already-qualified direct CLI path;
- automatic merge or automatic scientific-contract changes.

## 5. Pinned LoopX Path A contract

Pinned LoopX commit `80877982216577174e3e7c7cca9804c5a3a3148b` is the authority for the integration surface.

The shipped CLI explicitly registers `refresh-state`. Its custom-runner guide defines the bounded turn as:

```text
quota decision
→ claim
→ bounded execution
→ independent validation
→ todo/evidence writeback
→ refresh-state
→ quota spend-slot
```

For turn-scoped heartbeat settlement, Phase 2 adds a stricter binding around that baseline:

```text
quota should-run without turn id
        ↓
confirm current frontier todo
        ↓
derive deterministic turn_instance_id
        ↓
quota should-run with that turn id
        ↓
confirm the same frontier todo again
        ↓
claim
        ↓
bounded repair + independent verification
        ↓
Host creates provenance-bound verified Git commit
        ↓
todo complete(turn_instance_id)
        ↓
refresh-state(
  todo_id,
  turn_instance_id,
  delivery_outcome=outcome_progress,
  delivery_workspace_path=repair worktree
)
        ↓
quota spend-slot(turn_instance_id)
```

The first unscoped quota read prevents Meta-RLR from creating a settlement identity for an unrelated frontier. The scoped read binds one exact event/todo turn before write-capable work.

`refresh-state` is not optional bookkeeping. In pinned LoopX, `quota spend-slot` requires a matching accountable refresh-state writeback/receipt for the original settlement identity. A todo completion receipt alone is insufficient.

`outcome_progress` is used because a verified RLR software repair is accountable progress in the long-running maintenance goal but does not imply the entire maintenance goal has reached its primary terminal outcome.

The Host does not pass a `--project` override to `refresh-state`; LoopX remains the authority for resolving the goal project from its registry. The repair worktree is supplied separately as `--delivery-workspace-path` so LoopX can validate delivery-workspace causality.

## 6. One-turn Host model

The Host is one-shot and stateless. One invocation processes at most one maintenance event/todo.

Fresh path:

```text
validated maintenance event
        ↓
probe for recoverable verified Git commit
        ↓ none
idempotent LoopX todo add
        ↓
unscoped quota should-run
        ├─ no run → NOOP
        ├─ different todo → DEFER
        ↓ exact event todo selected
derive deterministic turn id
        ↓
scoped quota should-run(turn id)
        ├─ no run → NOOP
        ├─ frontier changed → DEFER
        ↓ same todo selected
claim exact todo
        ↓
create isolated worktree at exact event revision
        ↓
Codex bounded edit
        ↓
inspect real Git diff
        ↓
route event to existing RLR verification profile
        ↓
run independent RLR verification
        ├─ fail → blocked; no verified commit/settlement
        ↓ pass
Host creates one verified Git commit
        ↓
todo complete(turn id)
        ↓
refresh-state(turn id, outcome_progress, repair worktree)
        ↓
quota spend-slot(turn id)
        ↓
exit
```

There is no `while True` loop. A later local wake starts from fresh LoopX and Git facts.

## 7. Event-bound todo identity

The Host creates stable public-safe todo text from:

- `dedup_fingerprint` prefix;
- component;
- expected contract.

LoopX `todo add` remains todo identity/dedup authority. Pinned LoopX returns the existing active todo when normalized text already exists; Meta-RLR does not implement a parallel todo registry.

Execution is allowed only when fresh LoopX quota selects exactly the event-bound returned `todo_id`.

## 8. Deterministic turn identity

The Host derives one deterministic settlement id from maintenance event id and LoopX todo id. The same value is used for:

- scoped `quota should-run`;
- verified Git commit provenance;
- `todo complete`;
- `refresh-state`;
- `quota spend-slot`;
- crash-recovery replay.

The Host never invents a new turn id when recovering the same verified repair.

## 9. Local storage boundaries

Three filesystem roles remain distinct:

1. **RLR source checkout** — source/revision authority.
2. **LoopX control root** — LoopX-owned durable registry/state/history.
3. **Repair worktree** — isolated Git worktree rooted at the exact observed RLR revision.

LoopX state is not copied into RLR worktrees and is not committed to RLR. The Host does not create its own database, queue, settlement journal, or cached quota store.

## 10. Codex boundary

Codex is an external coding worker, not a maintenance state owner.

The worker receives only one bounded todo, validated event facts, expected RLR contract, verification profile/forbidden shortcuts, worktree root, and repository architecture rules.

Codex may edit the repair worktree. It may not:

- commit;
- push;
- merge;
- modify LoopX state;
- mark a todo complete;
- refresh LoopX state;
- spend quota;
- weaken tests or scientific policy to manufacture success.

Model completion text is advisory. Git diff and RLR verification are authoritative.

## 11. Git workspace contract

`GitWorkspace` owns Git mechanics only:

- resolve exact event revision;
- create deterministic event/todo repair worktree;
- inspect real HEAD/changed/dirty paths;
- stage exactly the independently verified path set;
- create the verified commit after verification;
- read and validate a recoverable verified commit.

It does not edit LoopX state and does not decide whether RLR verification passed.

## 12. Verified commit provenance

A successful Host-created repair commit contains public machine-readable trailers:

```text
Meta-RLR-Repair-Key: <dedup prefix>
Meta-RLR-Event-ID: <event id>
Meta-RLR-Todo-ID: <LoopX todo id>
Meta-RLR-Turn-ID: <deterministic turn instance id>
Meta-RLR-Profile-ID: <verification profile id>
```

These trailers bind source state to a maintenance turn. They are not proof that the repair remains valid.

Before success settlement, `commit_verified()` reads the commit back through the same recovery parser and verifies the commit, changed-path set, event, todo, turn, and profile bindings.

## 13. Crash recovery contract

Phase 2 recovery covers the trustworthy post-verification crash window:

```text
RLR verification PASS
→ verified commit created
→ process crashes before, during, or after LoopX settlement
```

On the next invocation for the same event, before creating/claiming a new todo, the Host probes only the deterministic repair-worktree namespace for that repair key.

A recoverable commit must prove:

1. exactly one matching worktree;
2. correct Meta-RLR branch identity;
3. clean worktree;
4. exactly one commit above event base;
5. exact event-base parent;
6. complete unique Meta-RLR trailers;
7. current event/profile match;
8. valid LoopX todo id;
9. deterministic turn-id match;
10. non-empty changed-path set.

Even after provenance passes, the Host reruns the RLR verification profile. Only a fresh PASS allows replay.

Recovery then unconditionally replays the same settlement identity:

```text
todo complete(same turn id)
→ refresh-state(same turn id, outcome_progress, same repair worktree)
→ quota spend-slot(same turn id)
```

Pinned LoopX makes completion, accountable refresh writeback, and spend replayable/idempotent under the same settlement identity. Therefore Meta-RLR does not need a transaction journal to guess where the previous process crashed.

Ambiguous/dirty/multi-commit/wrong-provenance worktrees fail closed. Phase 2 does not resume an ambiguous pre-verification Codex session.

## 14. Verification and success

Fresh repair success requires all of:

1. event validation;
2. unscoped frontier selects event-bound todo;
3. scoped frontier under deterministic turn id still selects it;
4. claim succeeds;
5. worktree base equals exact event revision;
6. Codex returns without host-level failure;
7. real non-empty Git diff and unchanged HEAD;
8. RLR verification profile PASS;
9. changed paths remain identical after verification;
10. provenance-bound verified commit creation + readback PASS;
11. `todo complete` PASS under the same turn id;
12. accountable `refresh-state` PASS under the same turn id and repair worktree;
13. `quota spend-slot` PASS under the same turn id.

Codex `status=changed` alone is never success evidence.

## 15. Failure semantics

- recovery provenance cannot be proven → fail closed;
- recovery re-verification fails → no settlement;
- quota no-run → no claim/Codex/spend;
- different frontier → defer;
- claim/worktree/Codex failure → no success settlement;
- verification failure → no verified commit/complete/refresh/spend;
- verified commit/readback failure → no complete/refresh/spend;
- todo completion failure → no refresh/spend;
- refresh failure → no spend;
- spend failure after durable writeback → report accounting failure; never fabricate success.

Raw stdout/stderr, credentials, private paths, and full Codex transcripts are not maintenance truth.

## 16. Publication boundary

GitHub publication is optional and downstream of local verification. It is not required for the Phase 2a one-turn Host.

A later narrow publisher may push an already-verified repair branch and create a **Draft PR**. It must never merge, force-push `main`, bypass failed verification, or become loop scheduler/state owner.

## 17. Module boundaries

```text
src/rlr_maintenance/
├── contracts.py       # existing event authority
├── observer.py        # existing observation authority
├── profiles.py        # existing profile/routing authority
├── verification.py    # existing independent verifier
├── loopx_cli.py       # external pinned LoopX CLI boundary
├── codex_cli.py       # external Codex adapter
├── workspace.py       # Git worktree + verified commit/recovery boundary
└── host.py            # stateless one-turn coordinator

meta_rlr.py            # thin local CLI entry point
```

No daemon, scheduler, database, or second state store is added.

## 18. Phase 2 scope

In scope:

- local one-turn coordinator;
- LoopX todo/frontier/claim/completion/refresh/spend lifecycle;
- two-stage quota binding;
- exact-revision isolated repair worktree;
- bounded Codex worker;
- existing RLR verification routing/execution;
- provenance-bound verified commit;
- post-verification crash recovery and idempotent settlement replay;
- thin local CLI;
- fail-closed architecture/regression tests.

Out of scope:

- GitHub-driven runtime wake/scheduling;
- continuous daemon;
- automatic merge;
- automatic RLR scientific DAG changes;
- automatic contract-policy changes;
- LoopX source modification;
- second maintenance state store/journal;
- stale-event auto-rebase;
- ambiguous pre-verification session resume;
- unrelated literature/fetch-tool redesign.

## 19. Acceptance criteria

Phase 2 is ready for a real local pilot only when automated tests prove:

1. no `research_loop → rlr_maintenance` or LoopX-internal dependency;
2. recoverable verified commit is reverified without rerunning Codex;
3. invalid recovery state fails closed;
4. no-run quota causes zero Codex and zero spend;
5. no settlement turn is created for an unrelated frontier todo;
6. scoped quota uses deterministic turn id and must preserve selected todo;
7. worktree base equals exact event revision;
8. Codex runs only after claim and cannot commit/push/merge;
9. verification failure prevents commit/complete/refresh/spend;
10. success ordering is verified commit → complete → accountable refresh → spend;
11. refresh uses the same todo/turn and actual repair worktree;
12. refresh failure prevents spend;
13. crash recovery replays complete/refresh/spend safely under the same identity;
14. full RLR regression remains green;
15. GitHub CI is green on the Draft PR;
16. native Windows acceptance proves the real pinned LoopX CLI + real Codex CLI + real Git + real RLR fresh-turn and crash-recovery paths before merge review.

## 20. Coherence check

The design preserves Phase 1 instead of replacing it. LoopX remains the sole maintenance lifecycle/writeback/settlement authority; Git remains source and recovery authority; RLR remains verification authority; the Host remains disposable. The corrected design uses LoopX's real `refresh-state` durable-writeback contract rather than bypassing it or emulating it in Meta-RLR.
