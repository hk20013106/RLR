# Meta-RLR Phase 2 — Local One-Turn Host Implementation Plan

Date: 2026-08-13
Design: `docs/superpowers/specs/2026-08-13-meta-rlr-phase2-local-host-design.md`

## Goal

Implement the smallest local Windows-oriented host that executes exactly one LoopX-governed Meta-RLR maintenance turn using the existing Phase 1 observation and verification boundary.

The implementation must reuse LoopX Path A, native Git worktrees, Codex CLI, and existing RLR verification profiles. It must not add a scheduler, database, scientific DAG node, LoopX internal dependency, GitHub runtime controller, automatic merge, or compatibility fallback.

## Inputs

- Current RLR `main` lineage after PR #19 and documentation-only follow-ups.
- Existing `src/rlr_maintenance/{contracts,observer,profiles,verification,loopx_cli}.py`.
- LoopX fork pinned qualification baseline `80877982216577174e3e7c7cca9804c5a3a3148b` / 0.4.5.
- LoopX Path A custom-runtime protocol.
- Current Codex CLI non-interactive `exec` interface.

## Constraints

1. RLR scientific DAG and `src/research_loop/` business logic are out of scope.
2. LoopX remains the only durable maintenance state owner.
3. Git/GitHub remains the only source/PR authority.
4. The host owns no durable state and runs one turn only.
5. Event revision and repair worktree base must match exactly.
6. All subprocesses use argv arrays with `shell=False` and explicit UTF-8.
7. Codex cannot be accepted as proof; verification reads the real repaired repository.
8. Verification failure cannot complete a todo, spend quota, or publish.
9. No dangerous Codex sandbox bypass.
10. No auto-merge.
11. Production changes require targeted tests then full regression.

## Phase A — Ground and freeze the contracts

### Task A1: Confirm baseline and callers

Inspect:

- `AGENTS.md`
- `docs/AGENT_CONTEXT.md`
- Phase 1 Meta-RLR design and tests
- `contracts.py`
- `observer.py`
- `profiles.py`
- `verification.py`
- `loopx_cli.py`
- current root CLI patterns

Done when the new host can be added without changing `src/research_loop/` or duplicating a validator/profile registry.

Validation: repository compare confirms post-promotion changes are documentation-only or otherwise explicitly reviewed.

### Task A2: Reuse survey

Confirm from pinned LoopX docs that Path A owns durable quota/todo/claim/writeback semantics and that direct CLI is the compatibility baseline. Confirm Codex CLI supports non-interactive exec, explicit cwd, sandbox selection, ephemeral sessions, and structured final output.

Done when no external orchestrator is necessary.

Validation: design records selected/rejected alternatives and exact responsibility owners.

## Phase B — RED tests for boundaries

Create tests before production implementation.

### Task B1: LoopX lifecycle adapter tests

Extend `tests/test_meta_rlr_loopx_cli.py` to require wrappers for:

- status
- todo claim
- todo update/block writeback
- todo complete
- refresh-state
- quota spend-slot

Required assertions:

- documented argv order/arguments;
- optional registry remains explicit;
- JSON parsing remains fail-closed;
- non-zero exit never synthesizes state;
- evidence passed to LoopX is bounded/public-safe.

Expected RED: missing lifecycle methods.

### Task B2: Codex adapter tests

Add `tests/test_meta_rlr_codex_cli.py`.

Test with a fake executable that records argv/stdin/cwd and emits a structured final-result file.

Required assertions:

- uses `codex exec`;
- exact `-C`/working root points to repair worktree;
- `--sandbox workspace-write` is present;
- `--ephemeral` is present;
- dangerous sandbox-bypass flag is absent;
- output schema is explicit;
- non-zero exit fails closed;
- malformed/missing structured final result fails closed;
- raw stdout/stderr are not returned as durable result fields.

Expected RED: `codex_cli.py` absent.

### Task B3: Git workspace tests

Add `tests/test_meta_rlr_workspace.py` using temporary Git repositories.

Required assertions:

- exact base SHA resolution;
- worktree is created from event revision, not ambient HEAD;
- pre-existing target path/branch collision fails closed;
- changed paths are read from Git, not worker claims;
- no destructive cleanup of pre-existing worktree/branch;
- branch/worktree identity is derived from bounded event/todo identity rather than private paths.

Expected RED: `workspace.py` absent.

### Task B4: One-turn host tests

Add `tests/test_meta_rlr_host.py` using fakes for LoopX, Codex, workspace, verifier, and optional publisher.

Required scenarios:

1. quota `should_run=false` → no claim/workspace/Codex/verify/spend;
2. single runnable todo → exact claim then execute;
3. multiple runnable candidates require an explicit steering selection and selected id must be in fresh candidate set;
4. claim failure → no workspace/Codex;
5. event revision mismatch/unresolvable → fail before Codex;
6. Codex failure → no complete/spend;
7. verification failure → no complete/spend/publish;
8. success order = claim → workspace → Codex → real-state inspection → verify → complete → refresh → spend → optional publish;
9. LoopX completion/writeback failure → no spend;
10. refresh failure → no spend;
11. publisher failure does not rewrite local verification truth;
12. no host-owned persistent state file is created.

Expected RED: `host.py` absent.

### Task B5: Architecture tests

Extend architecture coverage to prohibit:

- `research_loop` importing `rlr_maintenance`;
- RLR importing LoopX Python internals;
- Phase 2 adding a daemon/scheduler/database/state store;
- host importing scientific engine internals when existing boundary APIs suffice;
- GitHub Actions workflow as Meta-RLR runtime owner.

Expected RED only for newly required module inventory/contracts, not by weakening existing tests.

## Phase C — Minimal framework implementation

Implement only enough structure to satisfy the RED contracts.

### Task C1: Extend `LoopXCli`

Add thin documented wrappers; keep `run_json()` as the only subprocess/JSON parsing implementation.

No LoopX schema reimplementation beyond extracting explicitly required fields at the host boundary.

### Task C2: Add `CodexCli`

Create a narrow external process adapter.

Responsibilities:

- construct safe argv;
- write a temporary JSON schema/output target outside tracked repository files where practical;
- invoke `codex exec` with explicit repair worktree root and `workspace-write` sandbox;
- parse only the final structured result;
- return bounded metadata/digests, never raw transcript as durable evidence.

No LoopX writes and no Git publication.

### Task C3: Add `GitWorkspace`

Responsibilities:

- resolve revision;
- create isolated repair branch/worktree;
- inspect HEAD/status/changed paths;
- expose the facts the host needs for independent validation.

Do not add generic Git abstraction or destructive cleanup framework.

### Task C4: Add `MetaRLRHost`

Implement dependency-injected one-turn sequencing.

The host must:

- validate event;
- derive verification profile through `profile_for_event`;
- obtain fresh quota;
- stop quietly on no-run decisions;
- resolve/validate selected todo;
- claim before write-capable execution;
- create exact-revision worktree;
- invoke Codex;
- inspect real Git state;
- run profile verifier;
- write compact success/block evidence to LoopX;
- refresh then spend only after validated durable writeback;
- optionally publish a Draft PR through an injected publisher after local success.

The host returns an in-memory structured turn result. It does not persist that result as an independent state store.

### Task C5: Add thin local CLI

Add `meta_rlr.py` or the narrowest repository-consistent entry point.

Initial command surface should be explicit and small, for example:

```powershell
python meta_rlr.py run-once `
  --event <event.json> `
  --repo <RLR checkout> `
  --loopx-project <control root> `
  --goal-id <goal> `
  --agent-id <agent> `
  --workspace-parent <path> `
  [--registry <path>]
```

The CLI does not run a permanent loop and does not imply GitHub Actions scheduling.

## Phase D — GREEN verification

### Task D1: Targeted tests

Run:

```powershell
python -m pytest tests/test_meta_rlr_loopx_cli.py tests/test_meta_rlr_codex_cli.py tests/test_meta_rlr_workspace.py tests/test_meta_rlr_host.py tests/test_meta_rlr_architecture.py -q
```

Done when all targeted Phase 2 tests pass without test weakening.

### Task D2: Existing Meta-RLR suite

Run:

```powershell
python -m pytest tests/test_meta_rlr_*.py -q
```

Done when Phase 1 behavior remains intact.

### Task D3: Full regression

Run:

```powershell
python -m pytest -q
python run_loop.py --help
python meta_rlr.py --help
```

Done when full RLR regression is green and public RLR CLI behavior remains unchanged.

### Task D4: Diff/architecture review

Review exact diff for:

- no `src/research_loop/**` business-logic changes unless a proven canonical-owner issue unexpectedly requires redesign;
- no LoopX vendoring/imports;
- no scheduler/database/daemon;
- no GitHub runtime workflow;
- no auto-merge;
- no compatibility fallback;
- no unrelated refactor.

If any appears, stop and redesign rather than justify it post hoc.

## Phase E — Draft PR qualification

Create a Draft PR from `feat/meta-rlr-phase2-local-host` to `main` only after local/static targeted tests are coherent enough for review.

PR must state:

- local-Windows runtime is authoritative;
- GitHub CI is development verification only;
- no automatic merge;
- LoopX pin/Path A assumptions;
- remaining real-local acceptance required before merge approval.

Wait for repository CI. Investigate failures by root cause; do not patch tests or validators merely to make the PR green.

## Phase F — Real Windows acceptance (post-code, pre-merge approval)

After code/CI closure, run on native Windows with the pinned LoopX CLI and real Codex CLI.

Minimum pilot:

1. Use an isolated RLR checkout and a controlled synthetic software failure derived from an existing historical regression fixture, not scientific data.
2. Materialize a valid `RLRMaintenanceEvent/v1` bound to the failing revision.
3. Seed/connect a LoopX maintenance goal using documented CLI.
4. Run `meta_rlr.py run-once` once.
5. Prove LoopX authorizes and claims exactly one todo.
6. Prove Codex modifies only the isolated repair worktree.
7. Prove RLR verification runs independently.
8. Prove failed verification cannot complete/spend.
9. Prove a successful repair writes back, refreshes, spends exactly once, and stops.
10. If Draft PR publication is enabled in this phase, prove it stops at Draft and does not merge.
11. Restart from fresh process state and prove no host transcript/session database is required.

This real Windows pilot is required evidence before recommending merge. GitHub CI alone cannot substitute for it.

## Completion gate

Phase 2 is eligible for merge review only when:

- design and implementation remain coherent;
- targeted Phase 2 tests pass;
- all existing Meta-RLR tests pass;
- full RLR regression passes;
- GitHub CI passes;
- native Windows real LoopX + Codex + RLR one-turn acceptance passes;
- no production code was changed merely to satisfy compatibility with a stale path;
- no automatic merge authority was introduced.
