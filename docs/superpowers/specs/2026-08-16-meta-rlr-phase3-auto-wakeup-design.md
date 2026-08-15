# Meta-RLR Phase 3: Automatic Runtime-Failure Wakeup and Safe Resume

Date: 2026-08-16
Base: `3b3de53f4d51f6a2bf7b915532d15a91f5892c50` (RLR v0.9.0 Phase 2)
LoopX compatibility target: v0.4.5, `80877982216577174e3e7c7cca9804c5a3a3148b`

## Goal

Close exactly one missing control-flow gap:

```text
RLR provider/runtime failure
-> canonical RLRMaintenanceEvent/v1
-> existing Meta-RLR Phase 2 host
-> LoopX authorization
-> Codex repair in isolated worktree
-> independent RLR verification
-> verified repair commit + settlement
-> fresh worker from the verified repair worktree
-> resume the same detached scientific task request
```

Phase 3 is an ignition/bridge layer. It is not a second scheduler, a replacement for LoopX, a new repair engine, or a new scientific decision layer.

## Architectural ownership

Unchanged from Phase 2:

- RLR owns scientific execution and independent verification of a repair.
- LoopX owns todo/turn/quota/settlement/authorization.
- Codex edits code only inside the isolated repair worktree.
- Meta-RLR Host coordinates LoopX, Codex, Git, and RLR verification.
- Git owns code isolation and repair provenance.
- GitHub remains remote code/PR/CI; it is not the runtime scheduler.

Phase 3 adds only:

1. failure classification at an existing RLR runtime boundary;
2. event persistence using the existing `RLRMaintenanceEvent/v1` contract;
3. one-shot invocation of the existing `meta_rlr.py run-once` entry point;
4. safe handoff to a fresh worker process using the independently verified repair worktree.

## Reuse-first decisions

### Existing RLR surfaces reused directly

- `provider_runtime_observability.py` is the sensor. It already distinguishes terminal provider conditions such as provider failure, timeout, dead process, transport loss, successful completion, and explicit stop. Phase 3 does not add a second watchdog daemon.
- `rlr_maintenance.contracts` remains the only maintenance-event schema authority.
- `rlr_maintenance.observer` remains the normalization boundary, including the provider-runtime event projection added by Phase 3.
- `MetaRLRHost` remains the only repair coordinator.
- `LoopXCli` remains the LoopX v0.4.5 integration surface.
- `GitWorkspace` remains the worktree/provenance authority and is reused to resolve the verified repair worktree after Phase 2 returns a verified commit SHA.
- verification profiles remain the only route from a failure contract to acceptance tests.

### External designs used as patterns, not imported subsystems

- OpenAI Symphony: borrow the idempotent reconcile/watchdog pattern — observe current state, act only on eligible stalled/failed states, and restart work in a fresh workspace/process.
- Dagger self-healing CI: borrow the failure -> repair -> independent test -> retry boundary.
- Newer LoopX session-adapter/worker-bridge documentation reinforces a thin-host-adapter design and avoiding a second event store. Those newer surfaces are not assumed to exist in the pinned v0.4.5 SHA, so Phase 3 continues to use the already-proven v0.4.5 CLI boundary from Phase 2.

No external runtime framework is vendored. Importing Symphony/Dagger/Conductor would duplicate scheduler/control-plane responsibilities already owned by RLR + LoopX + Meta-RLR.

## Trigger boundary

The detached Deep Research worker is the first concrete integration point because it already has:

- a durable task request;
- a durable provider-runtime status/receipt;
- the project and candidate identity;
- the failed node;
- a clean process boundary for restart.

When the synchronous handler exits non-zero, the adapter inspects the durable provider-runtime state after the existing observability wrapper has finalized it.

Only these provider/runtime states are repair-eligible:

- `provider_failed` with an infrastructure/runtime termination reason;
- `provider_dead`;
- `transport_lost`;
- `job_timed_out`;
- `inactivity_timed_out`.

Explicit stop, successful provider execution followed by scientific/validation rejection, malformed scientific evidence, or an unclassified failure are not auto-repaired. They fail closed through the existing path.

## Runtime verification contract

A provider/runtime software failure must not be falsely labelled as an L4 scientific-contract violation. Add one infrastructure contract owned by one verification profile:

- contract: `provider_runtime_execution_integrity`
- profile: `provider_runtime_integrity`

The profile includes focused runtime/maintenance tests and the full regression suite. It does not weaken existing L0/L4/L10C profiles.

## Configuration and enablement

Automatic repair is opt-in through one explicit JSON configuration file referenced by:

```text
RLR_META_RLR_AUTOWAKE_CONFIG
```

The file contains the runtime-specific Phase 2 parameters already required by `meta_rlr.py run-once`: LoopX project/goal/agent, LoopX executable and registry, explicit quota scan root/profile, Codex executable, workspace parent, and capabilities.

The repository path is derived from the running RLR code. The event directory is inside the existing project audit tree. No Host database, queue, or journal is added.

Automatic repair requires the running RLR code checkout to be clean. Phase 2 provenance is commit-based; if uncommitted code is executing, a repair based only on `HEAD` would not be verifiably repairing the code that actually failed. Dirty code therefore fails closed. This does not mutate or clean an existing dirty checkout; such a checkout simply is not an eligible Phase 3 runtime source.

If configuration is absent/invalid, the code checkout is dirty, LoopX/Codex is unavailable, or Meta-RLR returns a non-verified outcome, the original RLR failure remains a failure. Phase 3 never converts repair-infrastructure failure into scientific success.

## Event idempotence

The canonical event builder supplies `dedup_fingerprint`. Before creating a new occurrence, the bridge scans only the existing maintenance-event directory for a valid event with the same fingerprint and reuses it. This prevents a repeated observation of the same underlying detached-task failure from producing a second repair identity.

This directory is the canonical Phase 2 event bridge, not a second state store.

## Repair activation and resume

A verified repair commit cannot be hot-loaded into the already-running Python process. Phase 3 also MUST NOT merge, reset, clean, stash, or overwrite another checkout to activate the fix.

Instead:

1. `meta_rlr.py run-once` returns the existing Phase 2 result, including the verified repair commit SHA.
2. Phase 3 reuses `GitWorkspace.find_existing` and `read_verified_commit` to resolve the single repair worktree and verify that its commit/event/profile provenance matches the Phase 2 result. No second worktree registry is introduced.
3. The failed detached worker starts a fresh Python process using `<verified_worktree>/research_loop_v04.py`.
4. The new process executes `_deep-research-worker` against the same project directory and task ID, so it consumes the same durable task request and writes the normal task result/status artifacts.
5. A transient environment guard marks this as the single post-repair retry. If the fresh worker fails, no recursive auto-repair is attempted by that retry; the task remains failed for later diagnosis/escalation.

This activates independently verified code without mutating the original checkout.

## Non-goals

Phase 3 does not:

- add a scheduler or service daemon;
- poll GitHub for runtime state;
- change LoopX version or semantics;
- allow Codex to commit/push/merge;
- change scientific results or data;
- manufacture production failures;
- auto-repair scientific/validation failures merely because a command returned non-zero;
- implement arbitrary retry loops;
- alter Phase 2 settlement order (`complete -> refresh-state -> spend-slot`).

## Acceptance invariants

A Phase 3 implementation is acceptable only if tests demonstrate:

1. repairable provider/runtime state emits/reuses a valid `RLRMaintenanceEvent/v1`;
2. non-repairable states do not wake Meta-RLR;
3. the bridge invokes the existing `meta_rlr.py run-once` rather than duplicating Host logic;
4. only `verified`/`recovered` Meta-RLR outcomes with matching Git provenance can produce a resume handoff;
5. dirty RLR code checkouts fail closed;
6. resume uses a fresh worker from the verified repair worktree;
7. the original checkout is not modified by the resume path;
8. recursive post-repair repair is blocked;
9. existing Phase 2 recovery and settlement tests remain green;
10. full repository regression remains green.
