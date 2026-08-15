# Meta-RLR Phase 2 — Local One-Turn Host Design

Date: 2026-08-13
Status: implementation design, corrected against pinned LoopX 0.4.5

## 1. Purpose

RLR is the scientific object plane. It owns the research DAG, scientific state, evidence contracts, provider boundaries, controlled execution, and native verification. Meta-RLR exists only to maintain the RLR software system itself: diagnose software/runtime/contract/test failures, make bounded source repairs, verify them against RLR-owned invariants, and preserve maintenance continuity across sessions.

Phase 1 established two provider-neutral contracts under `src/rlr_maintenance/`:

1. Observe authoritative RLR/runtime facts as `RLRMaintenanceEvent/v1`.
2. Verify repairs through immutable `RLRVerificationProfile/v1` profiles and structured receipts.

Phase 2 closes the missing execution gap between those contracts and LoopX. It adds a thin **local one-turn host** that can execute exactly one bounded maintenance turn on the authoritative Windows runtime.

The goal is not to create another agent framework, scheduler, database, or scientific node. The host is a disposable transaction coordinator around existing owners.

## 2. Runtime and development boundary

Development happens in GitHub: source control, code review, ordinary CI, and Draft PRs.

Formal Meta-RLR execution happens locally on Windows. GitHub Actions is not a maintenance scheduler and does not own the loop lifecycle. A local invocation may later publish a verified Draft PR to GitHub, but GitHub is not required to decide whether a local maintenance turn should run.

```text
GitHub                       Local Windows runtime
source / PR / CI             ---------------------
        │                    LoopX durable state
        │                           │
        └──── source checkout ──────┼──── Meta-RLR one-turn host
                                    │        │
                                    │        ├─ Codex CLI
                                    │        ├─ git worktree
                                    │        └─ RLR verification
                                    │
                                    └─ next local wake reads fresh state
```

## 3. Authority model

- **RLR** owns scientific truth and software verification contracts.
- **LoopX** owns maintenance goal/todo/claim/quota/history/settlement state.
- **Codex** owns semantic diagnosis and bounded code editing only.
- **Git** owns source identity, branches, commits, and worktrees.
- **GitHub** owns remote repository/PR/CI/merge state when publication is requested.
- **Meta-RLR Host** owns only local sequencing and fail-closed boundary checks.

The host owns no durable state.

## 4. Reuse decision

Phase 2 reuses the pinned LoopX 0.4.5 direct-CLI Path A surface. It does not adopt a second orchestrator and does not import LoopX Python internals.

Reused wheels:

- LoopX JSON CLI for todo/quota/claim/completion/settlement;
- native `git worktree` and Git commit identity;
- Codex CLI `exec` for bounded coding work;
- existing `RLRMaintenanceEvent/v1` validation;
- existing verification profile routing and `run_profile()`.

Rejected:

- another scheduler/state database;
- GitHub Actions as runtime controller;
- a permanent local daemon with its own timing policy;
- a third-party agent orchestrator that duplicates LoopX/Git authority;
- LoopX experimental typed Turn in parallel with the already-qualified direct CLI path;
- automatic merge or automatic scientific-contract changes.

## 5. Corrected LoopX Path A settlement contract

Pinned LoopX 0.4.5 source is the authority for the CLI contract.

`refresh-state` is part of the pinned production interface. In a turn-scoped settlement it is LoopX's durable settlement writeback receipt, not a second scheduler and not Host-owned state.

The settlement sequence is:

```text
quota should-run without turn id
        ↓
confirm current frontier todo
        ↓
derive deterministic turn_instance_id
        ↓
quota should-run with the same turn id
        ↓
confirm the same frontier todo again
        ↓
claim
        ↓
bounded repair + independent verification
        ↓
todo complete(turn_instance_id)
        ↓
refresh-state(turn_instance_id, accountable delivery outcome, verified repair worktree)
        ↓
quota spend-slot(turn_instance_id)
```

The first unscoped quota read prevents the host from creating a settlement identity for an unrelated frontier todo. The second scoped quota call binds the exact event/todo turn to LoopX's native heartbeat settlement identity before write-capable execution begins.

The completion must not assert terminal `--no-follow-up`: terminal closure would make the subsequent quota spend invalid. The Host invokes the spend from the verified delivery worktree and supplies the configured scan root only to quota commands; it supplies neither a runtime profile nor a scan root to `refresh-state`.

LoopX 0.4.5 natively supports idempotent replay for all settlement steps:

- completing an already-completed todo under the same completion turn key is an idempotent replay;
- writing back an already-recorded accountable refresh-state receipt under the same identity is an idempotent replay;
- spending a slot under an already-settled identical heartbeat identity is an idempotent replay.

Meta-RLR therefore must not create its own settlement journal.

## 6. One-turn host model

The host is one-shot and stateless. One invocation processes at most one maintenance event/todo.

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
        ├─ fail → blocked writeback; no complete/refresh/spend
        ↓ pass
Host creates one verified Git commit with machine-readable provenance
        ↓
todo complete(turn id)
        ↓
durable refresh-state writeback(turn id, verified repair worktree)
        ↓
quota spend-slot(turn id)
        ↓
exit
```

There is no `while True` loop. A later local wake starts from fresh LoopX and Git facts.

## 7. Event-bound todo identity

The host creates a stable, public-safe todo text from:

- `dedup_fingerprint` prefix;
- component;
- expected contract.

LoopX `todo add` remains the todo identity/dedup authority. Pinned LoopX returns the existing active todo when the normalized text already exists; Meta-RLR does not implement a parallel todo registry.

After `todo add`, the host accepts execution only when LoopX's fresh quota frontier selects exactly that returned `todo_id`.

## 8. Deterministic turn identity

The host derives one deterministic settlement id from the maintenance event id and LoopX todo id. The same id is used for:

- scoped `quota should-run`;
- verified Git commit provenance;
- `todo complete`;
- `refresh-state` durable writeback;
- `quota spend-slot`;
- crash recovery replay.

The host never invents a new turn id when recovering the same verified repair.

## 9. Local storage boundaries

Three filesystem roles remain distinct:

1. **Source checkout** — normal RLR Git checkout used to resolve the event revision.
2. **LoopX control project/root** — LoopX-owned durable registry/state/history.
3. **Repair worktree** — isolated Git worktree rooted at the exact observed RLR revision.

LoopX state is not copied into RLR worktrees and is not committed to RLR. The host does not create its own database, queue, transaction journal, or cached quota packet store.

## 10. Codex boundary

Codex is an external coding worker, not a state owner.

The worker receives only:

- one bounded objective/todo;
- validated maintenance event facts;
- expected RLR contract;
- verification profile id and forbidden shortcuts;
- the isolated worktree root;
- repository architecture rules already present in `AGENTS.md`.

Codex may edit the worktree. It may not:

- commit;
- push;
- merge;
- modify LoopX state;
- mark a todo complete;
- spend quota;
- weaken tests or scientific policy to manufacture success.

Model completion text is advisory only. Git diff and RLR verification remain authoritative.

## 11. Git workspace contract

`GitWorkspace` owns Git mechanics only:

- resolve the exact event revision;
- create deterministic event/todo repair branch and worktree;
- inspect real HEAD, changed paths, and dirty paths;
- stage exactly the verified path set;
- create the verified commit after verification;
- read a recoverable verified commit on a later process invocation.

It does not edit LoopX state and does not decide whether verification passed.

## 12. Verified commit provenance

A successful Host-created repair commit contains public machine-readable trailers:

```text
Meta-RLR-Repair-Key: <dedup prefix>
Meta-RLR-Event-ID: <event id>
Meta-RLR-Todo-ID: <LoopX todo id>
Meta-RLR-Turn-ID: <deterministic turn instance id>
Meta-RLR-Profile-ID: <verification profile id>
```

These trailers bind source state to a maintenance turn. They are **not proof that the repair is still valid**.

Before returning success, `GitWorkspace.commit_verified()` reads the commit back through the same recovery parser and verifies that the commit identity, changed-path set, event, todo, turn, and profile match what the Host intended to commit.

## 13. Crash recovery contract

Phase 2 recovery deliberately covers the trustworthy post-verification crash window:

```text
RLR verification PASS
        ↓
verified commit created
        ↓
process crashes before/during LoopX settlement
```

On the next invocation for the same event, before creating/claiming a new todo, the Host searches only the deterministic repair-worktree namespace for that event repair key.

A recoverable commit must satisfy all of the following:

1. exactly one matching repair worktree exists;
2. worktree branch identity matches Meta-RLR naming;
3. worktree is clean;
4. HEAD is exactly one commit above the event base revision;
5. commit parent equals the exact event revision;
6. required Meta-RLR trailers are present and unique;
7. trailer event id equals the current event;
8. trailer profile id equals current `profile_for_event()` routing;
9. trailer todo id is a valid LoopX todo id;
10. trailer turn id equals the Host's deterministic event/todo turn id;
11. changed-path set is non-empty.

Even after all provenance checks pass, the Host **reruns the RLR verification profile** against the recovered worktree. Only a fresh verification PASS allows settlement replay.

Recovery then performs:

```text
todo complete(same turn id)
        ↓
refresh-state(same turn id, recovered verified worktree)
        ↓
quota spend-slot(same turn id)
```

LoopX's native idempotency makes this safe whether the prior process crashed before completion, after completion, or after spend receipt creation.

If an existing worktree is dirty, has multiple commits, has wrong provenance, or otherwise cannot be proven to be the exact verified repair, Phase 2 fails closed. It does not resume an ambiguous Codex editing session.

## 14. Verification and success

Fresh repair success requires:

1. event validation passes;
2. unscoped LoopX frontier selects the event-bound todo;
3. scoped LoopX frontier under the deterministic turn id still selects the same todo;
4. exact todo claim succeeds;
5. worktree base equals the event revision;
6. Codex completes without host-level failure;
7. real Git diff exists and Codex did not move HEAD;
8. the RLR verification profile passes;
9. changed paths remain identical after verification;
10. Host creates and reads back the provenance-bound verified commit;
11. LoopX `todo complete` succeeds under the same turn id;
12. LoopX `quota spend-slot` succeeds under the same turn id.

A Codex `status=changed` response alone is never success evidence.

## 15. Failure semantics

- Recovery provenance cannot be proven → fail closed; do not settle.
- Recovery re-verification fails → do not settle.
- Unscoped quota says no run → no claim/Codex/spend.
- Unscoped quota selects another todo → defer with no write-capable action.
- Scoped quota says no run or changes frontier → no claim/Codex/spend.
- Claim fails → no Codex call.
- Worktree creation fails → no Codex call.
- Codex fails → no completion/spend.
- Verification fails → no completion/spend/publication.
- Verified commit creation/readback fails → no completion/spend.
- Todo completion fails → no spend.
- Spend fails after completion → report accounting failure; never fabricate success.

Raw stdout/stderr, credentials, private paths, and full Codex transcripts are not maintenance truth.

## 16. Publication boundary

GitHub publication is optional and downstream of local verification. It is not required for the Phase 2a local one-turn host.

A later narrow publisher may push an already-verified repair branch and create a **Draft PR**. It must never merge, force-push `main`, or become the loop scheduler/state owner.

## 17. Module boundaries

```text
src/rlr_maintenance/
├── contracts.py       # existing event authority
├── observer.py        # existing observation authority
├── profiles.py        # existing profile/routing authority
├── verification.py    # existing independent verifier
├── loopx_cli.py       # external pinned LoopX CLI boundary
├── codex_cli.py       # external Codex adapter
├── workspace.py       # Git worktree + verified-commit/recovery boundary
└── host.py            # stateless one-turn coordinator

meta_rlr.py            # thin local CLI entry point
```

No daemon, scheduler, database, or second state store is added.

## 18. Phase 2 scope

In scope:

- local one-turn coordinator;
- LoopX todo/frontier/claim/completion/spend lifecycle;
- two-stage quota binding;
- isolated exact-revision repair worktree;
- non-interactive bounded Codex worker;
- existing verification profile routing/execution;
- Host-created provenance-bound verified commit;
- post-verification crash recovery and idempotent LoopX settlement replay;
- thin local CLI;
- fail-closed architecture and regression tests.

Out of scope:

- GitHub-driven wake/scheduling;
- continuous daemon;
- automatic merge;
- automatic RLR scientific DAG changes;
- automatic contract-policy changes;
- LoopX source modification;
- second maintenance state store or transaction journal;
- stale-event auto-rebase;
- resume of ambiguous pre-verification Codex sessions;
- unrelated literature/fetch-tool redesign.

## 19. Acceptance criteria

Phase 2 code is ready for a real local pilot only when automated tests prove:

1. No `research_loop → rlr_maintenance` or LoopX-internal dependency is introduced.
2. A recoverable verified commit is reverified and settled without rerunning Codex.
3. Invalid/dirty/ambiguous recovery state fails closed.
4. A no-run unscoped quota packet causes zero Codex invocations and zero spend.
5. The Host creates no settlement turn until the unscoped frontier selects the event-bound todo.
6. The scoped quota call uses a deterministic turn id and must still select the same todo.
7. Worktree base equals the event's exact RLR revision.
8. Codex is invoked only after claim and cannot commit/push/merge.
9. Verification failure prevents verified commit, complete, refresh, and spend.
10. Successful verification is followed by a provenance-bound local commit, then `complete(turn id) → durable refresh-state writeback(turn id) → spend(turn id)`.
11. The verified commit is read back through the recovery parser before success.
12. No raw transcript/private path becomes LoopX maintenance truth.
13. Full RLR regression remains green.
14. GitHub CI is green on the Draft PR.
15. Native Windows acceptance proves the real pinned LoopX CLI + real Codex CLI + real RLR verification + crash-recovery settlement path before merge approval.

## 20. Coherence check

The design preserves Phase 1 rather than replacing it. The only new responsibility is local sequencing across already-owned boundaries. LoopX remains the sole maintenance lifecycle authority, Git remains source/recovery authority, RLR remains verification authority, and the Host remains disposable. Crash recovery reuses Git provenance plus LoopX's native idempotent settlement instead of introducing a Meta-RLR state database or compatibility patch stack.
