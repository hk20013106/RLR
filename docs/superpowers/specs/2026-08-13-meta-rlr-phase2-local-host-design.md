# Meta-RLR Phase 2 — Local One-Turn Host Design

Date: 2026-08-13
Status: implementation design

## 1. Purpose

RLR is the scientific object plane. It owns the research DAG, scientific state, evidence contracts, provider boundaries, controlled execution, and native verification. Meta-RLR exists only to maintain the RLR software system itself: diagnose software/runtime/contract/test failures, make bounded source repairs, verify them against RLR-owned invariants, and preserve maintenance continuity across sessions.

Phase 1 established two provider-neutral contracts under `src/rlr_maintenance/`:

1. Observe authoritative RLR/runtime facts as `RLRMaintenanceEvent/v1`.
2. Verify repairs through immutable `RLRVerificationProfile/v1` profiles and structured receipts.

Phase 2 closes the missing execution gap between those contracts and LoopX. It adds a thin **local one-turn host** that can execute exactly one bounded maintenance turn on the authoritative Windows runtime.

The goal is not to create another agent framework, scheduler, database, or scientific node. The host is a disposable transaction coordinator around existing owners.

## 2. Runtime and development boundary

Development happens in GitHub: source control, code review, ordinary CI, and Draft PRs.

Formal Meta-RLR execution happens locally on Windows. GitHub Actions is not a maintenance scheduler and does not own the loop lifecycle. A local invocation may publish a verified Draft PR to GitHub, but GitHub is not required to decide whether a local maintenance turn should run.

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

## 3. Architecture-first review

### 3.1 Why is Phase 2 necessary?

Phase 1 proved the semantic boundary but still required manual glue to perform a real repair sequence. The violated architectural invariant is continuity: maintenance state is durable in LoopX, but no RLR-owned adapter currently executes one fresh LoopX turn end-to-end. Without this host, each repair requires a human to reconstruct the same protocol manually.

### 3.2 Who owns each responsibility?

- RLR owns scientific truth and software verification contracts.
- LoopX owns maintenance goal/todo/claim/evidence/quota/history/replan state.
- Codex owns semantic diagnosis and bounded code editing.
- Git owns source identity, branches, commits, and worktrees.
- GitHub owns remote repository/PR/CI/merge state when publication is requested.
- The Phase 2 host owns only local sequencing and fail-closed boundary checks.

### 3.3 Is there a more fundamental reusable solution?

Yes: use LoopX's documented Path A custom-runtime protocol instead of creating a Meta-RLR scheduler/state machine. At pinned LoopX 0.4.5, the compatibility baseline is direct CLI orchestration:

```text
fresh quota decision
→ claim
→ bounded agent action
→ independent validation
→ todo writeback
→ refresh
→ spend
```

LoopX's experimental typed Turn adapter is deliberately not adopted in Phase 2 because the already-qualified direct CLI path is the compatibility baseline and avoids a new dependency on LoopX Python internals.

### 3.4 What existing wheels are reused?

- LoopX CLI JSON lifecycle and quota/todo/refresh/spend contracts.
- Native `git worktree` for source isolation.
- Codex CLI `exec` for non-interactive bounded coding work.
- Existing `RLRMaintenanceEvent/v1` validator and observers.
- Existing verification profiles and `run_profile()` executor.
- Git/GitHub for revision and Draft PR authority.

No third-party orchestrator is introduced. Products that already own session scheduling, todo state, worktree lifecycle, or PR automation would duplicate LoopX or Git authority.

## 4. Selected architecture

### 4.1 Host model

The Phase 2 host is **one-shot and stateless**. One invocation evaluates one fresh LoopX frontier and performs at most one executable maintenance todo.

```text
local wake
  ↓
preflight exact repo state + validated event
  ↓
LoopX quota should-run (fresh JSON)
  ├─ no execution obligation → NOOP / exit
  ↓
resolve one runnable todo without inventing policy
  ↓
claim exact todo
  ↓
create isolated git worktree from exact observed RLR revision
  ↓
Codex bounded repair
  ↓
inspect real git diff / changed paths
  ↓
route event → existing RLR verification profile
  ↓
run independent verification
  ├─ FAIL → LoopX blocked/update; never complete/spend/publish
  ↓ PASS
LoopX complete with compact evidence
  ↓
refresh-state
  ↓
quota spend-slot
  ↓
optional controlled Draft PR publication
  ↓
exit
```

There is no `while True` loop in the host. A later local wake starts from fresh LoopX state.

### 4.2 No new durable state

Forbidden host-owned persistence includes:

- `meta_rlr_state.json`
- host SQLite databases
- repair queues
- copied LoopX todo/history stores
- cached quota packets across invocations
- raw Codex transcripts as maintenance truth

Durable authority remains:

- LoopX: maintenance lifecycle.
- Git/GitHub: source and PR state.
- RLR: contract/verification truth.

A process crash must not require replaying model conversation state. The next wake reads LoopX and repository facts again.

## 5. Local storage boundaries

Three filesystem roles must remain distinct even when they live on one Windows machine:

1. **Source checkout** — normal RLR Git checkout used to identify the current authoritative revision.
2. **LoopX control project/root** — LoopX-owned local durable state and registry. It is not copied into repair worktrees or committed to RLR.
3. **Repair worktree** — disposable Git worktree rooted at the exact observed RLR revision and dedicated to one claimed maintenance todo.

The host must not solve state separation by inventing a second registry. It accepts explicit paths and passes the LoopX registry through the CLI's documented `--registry` argument.

## 6. Turn input contract

Phase 2 consumes an already-normalized `RLRMaintenanceEvent/v1`. Observation remains Phase 1 authority; the host does not scrape arbitrary logs or reinterpret scientific artifacts.

Required invocation facts:

- validated maintenance event;
- local RLR source repository root;
- LoopX project/control root;
- LoopX goal id;
- registered maintenance agent id;
- optional explicit LoopX registry path;
- workspace parent for repair worktrees;
- publication mode, default off.

### Revision binding

The first Phase 2 implementation is intentionally strict:

- the event's `rlr_revision` must resolve in the local repository;
- the repair worktree is created from that exact revision;
- the host never silently rebases a failure onto a newer revision;
- stale-event reconciliation is a later explicit workflow, not an implicit compatibility path.

This gives causal auditability: the code being repaired is exactly the code that emitted the failure event.

## 7. LoopX integration contract

The host consumes only documented external CLI JSON contracts. `research_loop` never imports LoopX; `rlr_maintenance` never imports LoopX Python internals.

`LoopXCli` is extended with narrow wrappers for the documented lifecycle only:

- `status`
- `quota should-run`
- `todo claim`
- `todo update` / blocked writeback when needed
- `todo complete`
- `refresh-state`
- `quota spend-slot`

Every write is bound to explicit `goal_id`, `todo_id`, and `agent_id`/`claimed_by` where the CLI contract requires them. Non-zero exits, malformed JSON, missing required fields, and ambiguous lifecycle facts fail closed.

### Todo selection

LoopX remains the work-frontier authority. The host must not invent project-specific priority policy.

- If the fresh quota packet identifies exactly one executable/runnable todo, that todo may be selected deterministically.
- If multiple runnable candidates exist, the maintenance agent may perform a read-only steering selection using a structured Codex response. The selected id must be a member of the fresh LoopX runnable set before claim.
- The host never converts array order into hidden business priority when LoopX explicitly leaves the final steering choice to the agent.
- No write-capable repair begins before successful claim.

## 8. Codex boundary

Codex is an external coding worker, not a maintenance state owner.

The Phase 2 adapter uses non-interactive `codex exec` in the repair worktree. The current upstream CLI supports an explicit working directory, sandbox selection, ephemeral sessions, output schema, and output-last-message file. The adapter must use a workspace-write sandbox and must never use the dangerous bypass-approvals-and-sandbox flag.

The worker receives only:

- compact current objective/todo;
- validated maintenance event facts;
- expected RLR contract;
- verification profile id and forbidden shortcuts;
- exact worktree root;
- repository architecture instructions already present in `AGENTS.md`.

The worker does not receive authority to mark LoopX todos complete, spend quota, or merge GitHub PRs. Model completion text is never success evidence.

### Structured worker result

The Codex final response is constrained to a small schema such as:

```json
{
  "status": "changed|no_change|blocked",
  "summary": "public-safe bounded summary",
  "tests_requested": ["..."],
  "blocker": null
}
```

This response is advisory. Git diff and RLR verification remain authoritative.

## 9. Worktree and source-isolation contract

`GitWorkspace` owns only Git mechanics:

- verify repository existence;
- resolve exact base SHA;
- create a deterministic-but-collision-safe repair branch name from event/todo identity;
- create a worktree outside the source checkout;
- record the start SHA;
- read changed paths and final HEAD/diff status;
- refuse destructive cleanup of pre-existing paths/branches.

It must not edit LoopX state or run RLR verification.

The initial implementation does not silently reuse an existing repair branch/worktree with ambiguous state. A collision is a fail-closed recovery condition to be inspected or handled by a later explicit resume contract.

## 10. Verification and success

The host calls `profile_for_event(event)` and then `run_profile(profile_id, repair_worktree)`.

Success requires all of the following:

1. Event validation passed.
2. LoopX authorized execution and exact todo claim succeeded.
3. Codex process completed without host-level failure.
4. Real repository state was inspected after Codex.
5. No forbidden host-owned paths or authority boundaries were violated.
6. The RLR verification profile passed.
7. LoopX completion/writeback succeeded.
8. State refresh succeeded.
9. Quota spend succeeded only after validated writeback.

A Codex `status=changed` response alone is not success. A clean diff may be valid only when the worker truthfully reports `no_change` and independent verification proves the event is already resolved; otherwise it is blocked/no-progress, not a completed repair.

## 11. Failure semantics

The host fails closed at each irreversible boundary.

- Quota says no run → no Codex call, no claim, no spend.
- Claim fails → no Codex call.
- Worktree creation fails → no Codex call.
- Codex fails → no todo completion, no spend.
- Verification fails → no todo completion, no spend, no publication.
- LoopX writeback fails → no spend, no publication.
- Refresh fails → no spend, no publication.
- Spend fails after completion → report accounting failure; do not fabricate success.
- Publication fails after verified completion → local repair remains verified, publication is a separate failed boundary and must not rewrite verification truth.

Raw stdout/stderr, credentials, private paths, and full transcripts are not copied into LoopX evidence. Existing digest/bounded evidence principles are preserved.

## 12. Publication boundary

GitHub publication is optional and downstream of local verification.

When enabled, a narrow publisher may:

- verify the repair branch and commit identity;
- push that branch;
- create a **Draft PR**;
- record the returned PR reference as compact evidence.

It must never:

- merge;
- force-push;
- update `main`;
- bypass failed verification;
- turn GitHub into the loop scheduler/state owner.

Phase 2 tests may use a fake publisher. Real GitHub publication is qualified separately on Windows after the local turn is proven.

## 13. Proposed module boundaries

```text
src/rlr_maintenance/
├── contracts.py       # existing event authority
├── observer.py        # existing observation authority
├── profiles.py        # existing profile/routing authority
├── verification.py    # existing independent verifier
├── loopx_cli.py       # extend documented lifecycle wrappers
├── codex_cli.py       # new external Codex adapter
├── workspace.py       # new Git worktree boundary
└── host.py            # new one-turn coordinator; no durable state

meta_rlr.py            # thin local CLI entry point
```

A publication adapter is added only if it stays narrow and independent; otherwise publication remains explicitly outside Phase 2a rather than being forced into `host.py`.

## 14. Rejected designs

### GitHub Actions as runtime controller
Rejected. Formal runtime is local Windows; GitHub is source/PR/CI authority, not maintenance scheduling authority.

### Permanent local daemon with its own timer
Rejected. LoopX already owns quota/scheduler hints. The host performs one turn and exits.

### New Meta-RLR database/queue
Rejected. Duplicates LoopX.

### LoopX Python imports
Rejected. Violates provider-neutral external boundary and pin portability.

### Experimental `loopx turn run-once` in Phase 2
Rejected for now. Direct CLI is the qualified compatibility baseline. The typed Turn path can be evaluated later as a deliberate replacement, never run in parallel with the direct sequence.

### Third-party agent orchestrator
Rejected. Existing orchestrators commonly duplicate session, scheduling, todo, worktree, or PR authority already owned by LoopX/Git.

### Automatic merge or automatic scientific-contract change
Rejected. Human approval remains required for merge and for intentional RLR DAG/contract policy changes.

## 15. Phase 2 scope

### In scope

- local one-turn coordinator;
- fresh LoopX quota/claim/writeback/refresh/spend flow;
- isolated repair worktree;
- non-interactive bounded Codex worker;
- exact event-revision binding;
- existing verification profile routing/execution;
- structured local turn receipt/result;
- thin local CLI;
- tests for all fail-closed boundaries;
- optional Draft PR publication only after verification if it remains architecturally narrow.

### Out of scope

- GitHub-driven wake/scheduling;
- continuous daemon;
- automatic merge;
- automatic RLR scientific DAG changes;
- automatic contract-policy changes;
- LoopX source modification;
- second maintenance state store;
- stale-event auto-rebase;
- automatic architecture-drift synthesis/dreaming policy;
- literature/fetch-tool redesign unrelated to the maintenance turn.

## 16. Acceptance criteria

Phase 2 code is ready for a real local pilot only when automated tests prove:

1. No `research_loop → rlr_maintenance` or LoopX internal dependency is introduced.
2. A no-run quota packet causes zero Codex invocations and zero writes/spend.
3. Exactly one runnable todo can be claimed and executed.
4. Multiple candidates cannot be silently auto-prioritized by host policy.
5. Claim failure prevents worktree/Codex execution.
6. Worktree base equals the event's exact RLR revision.
7. Codex is invoked with a bounded working root and without dangerous sandbox bypass.
8. Verification failure prevents complete/spend/publish.
9. Successful verification is followed by complete → refresh → spend in that order.
10. Raw logs/transcripts/private paths are not persisted as LoopX evidence.
11. Restarting the host requires no host-owned session database.
12. Full RLR regression remains green.
13. GitHub CI is green on the Draft PR.
14. A later Windows acceptance proves the real pinned LoopX CLI + real Codex CLI + real RLR verification path before merge approval.

## 17. Coherence check

The design preserves the Phase 1 authority model rather than replacing it. The only new responsibility is local sequencing across already-owned boundaries. Every durable fact has exactly one owner, every success claim is independently verified, and every downstream write is ordered after the prerequisite evidence. GitHub is deliberately absent from the core run loop, while local Windows remains the authoritative execution environment.
