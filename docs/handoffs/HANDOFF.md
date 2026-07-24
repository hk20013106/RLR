# RLR active handoff

## 2026-07-12 — Ranking reliability shadow MVP compact handoff

### Completed and verified

- Branch `ranking-reliability-shadow` contains and has pushed the ranking MVP:
  `3374516`, `eb6a80e`, and `2960f93`.
- The feature adds versioned ranking artifacts, fair A/B+B/A judging,
  deterministic Elo with validated checkpoint/replay, idempotent evidence
  events, synthetic benchmark/report commands, and L3/L10b-only fail-soft
  shadow integration. Formal RLR gates, candidate selection, and decisions are
  unchanged.
- The latest pre-documentation verification was `python -m pytest -q` with
  `285 passed`; `git diff --check` passed. Ranking artifacts are project-local
  at `08_Audit/ranking/` and use a validated completion marker for runner
  deduplication.

### Current documentation state

- `README.md` and `README_CN.md` document strict L0 intake and the advisory
  ranking interface, including the L3/L10b-only, fail-soft boundary. They now
  also document the V0.7 node-by-node contract, runtime module layers, four
  framework-level L0 dependencies, and the historical `research_loop_v04.py`
  compatibility shim. The documentation correction follows this handoff record
  on `ranking-reliability-shadow`.
- Do not stage or modify the pre-existing untracked local files shown by
  `git status` (for example `.claude/`, `.omm/`, `docs/CODEMAPS/`, and the
  Benchmate research note).

### Suggested next-session skill

- Use `verification-before-completion` before a documentation release claim;
  no implementation skill is needed unless the documented CLI changes.

## 2026-07-18 — Hypothesis ledger / knowledge-graph projection implementation pause

### Task and agreed architecture

- User asked to implement the “假说账本与知识图谱投影架构改造” end-to-end.
- Confirmed design decisions: a shared SQLite ledger is the canonical append-only
  source; JSON commit receipts are immutable audit exports; graph/current-state/
  ranking inputs are projections.  Identity is split into family, immutable
  version, and per-project/candidate/round occurrence.  L9a is the sole writer
  of the five-state epistemic projection; workflow state belongs to occurrences.
- Store access is explicit through `--knowledge-store` or
  `RLR_HYPOTHESIS_STORE`; a project binding records `store_id` and `project_id`.
  Do not add a fallback store path.
- The requested final design is in the user conversation; executable code and
  tests remain authoritative for current behavior.

### Implemented in this session

- Added `src/research_loop/hypothesis_ledger.py`.
  - SQLite WAL/foreign keys/busy timeout; append-only triggers for facts.
  - Family/version/occurrence/evidence/event/emission/projection/authorization
    tables; deterministic UUIDv5 identifiers; receipt and graph DTO helpers.
  - Draft 2020-12 `jsonschema` node submission schemas for L0–L10b and semantic
    gates currently covering the key L1/L3/L4/L6/L7/L8/L9a/L10b lifecycle.
  - L1 normalizes statements (NFC/trim/whitespace), deduplicates families and
    definitions, creates occurrences; L7 creates pending evidence; L8 exhausts
    L7 evidence; L9a requires verified evidence and contradictory evidence for
    FALSIFIED; reopening requires superseding the prior L9a event.
- Updated `requirements.txt` to add `jsonschema>=4.23`.
- Updated `src/research_loop/delta.py` so a project with a ledger binding only
  resolves receipt-backed, hash-matched `*_delta.v2.json` artifacts.
- Updated `src/research_loop/engine.py`.
  - v2 `emit-delta` calls the ledger then atomically writes canonical v2 delta
    bytes and an exclusive JSON commit receipt in `08_Audit/hypothesis_commits/`.
  - `new-project --knowledge-store` binds a project.
  - `triage-idea` / `triage-method` derive v2 outcomes from the committed delta.
  - Added `finalize-candidate` and `hypothesis-show`, `hypothesis-history`,
    `hypothesis-lineage`, `hypothesis-search`, `hypothesis-verify`, and
    `hypothesis-authorize-context` CLI commands.
  - v2 loop-memory includes fixed ledger cursor, authorized event refs and a
    projection hash; a bound continuation checks memory store identity and the
    immediate successor ID.
- Updated `src/run_loop.py` to use v2 provider schemas for bound projects and
  invoke derived triage/finalization paths rather than repeating decisions.
- Added `tests/test_hypothesis_ledger.py` for lifecycle/event replay,
  deterministic retry, semantic rejection, and CLI receipt persistence.

### Verified in this session

- `python -m pytest tests\test_hypothesis_ledger.py -q` → `3 passed`.
- `python -m pytest tests\test_engine_api.py tests\test_hypothesis_ledger.py -q`
  → `19 passed`.
- `python -m pytest tests\test_run_loop_guards.py tests\test_candidate_aware_next_step.py -q`
  → `8 passed`.
- `python research_loop_v04.py --help` and `python run_loop.py --help` passed.
- `git diff --check` passed, with only pre-existing/normal CRLF warnings.
- `python -m pytest -q` was launched and completed without reported failures,
  but the `rtk` output supplied only progress dots and no auditable test count;
  do not claim a full regression pass without rerunning it and capturing a
  normal summary.

### Important unfinished work / risks

- This is not the requested full Phase 1–4 delivery.  The following remain:
  1. Implement `hypothesis-migrate` with project-atomic dry-run/resolution/
     commit behavior and block unmigrated legacy projects at all formal entry
     points.  Do not infer missing L8/L9a hypothesis ownership or criteria.
  2. Complete strict v2 contracts and semantic gates for L2, L5, L8.5, L9b and
     L10a, including deep-research evidence-record binding.
  3. Physically inject only fixed, authorized ledger snapshots into context;
     preserve the L9a/L9b mutual invisibility invariant.
  4. Convert ranking into a read-only ledger-query consumer and migrate legacy
     ranking evidence only as advisory provenance.
  5. Change continuation runner flow to force `emit-loop-memory` before
     `new-candidate --from-memory --loop-type`; remove its current direct child
     frontmatter mutation path.
  6. Add transaction/crash recovery/migration/cross-project/reopen/context
     isolation end-to-end tests and capture full pytest plus coverage >=80%.
- Current compatibility compromise: unbound projects can still use legacy v1
  resolution.  Bound projects are v2-only.  The user requested an immediate
  strict cutover, so this must be eliminated only together with a safe migration
  path; do not silently break legacy projects beforehand.
- Review `HypothesisLedger.commit_delta` carefully before broad use. It handles
  deterministic L1 retry by rolling back speculative projection changes and
  returning the final-hash emission, but project-wide multi-delta atomic
  migration is not implemented.

### Workspace state

- Branch at session start: `main`.
- `AGENTS.md` had a pre-existing user modification. This session then added the
  ledger-specific fail-closed/projection/authority rules and changed its
  verification example to `rtk git diff --check`; review the combined diff
  before staging.
- Current task files are:
  `AGENTS.md`, `requirements.txt`, `src/research_loop/delta.py`,
  `src/research_loop/engine.py`, `src/run_loop.py`,
  `src/research_loop/hypothesis_ledger.py` (new), and
  `tests/test_hypothesis_ledger.py` (new).
- No commit, push, branch, or external state change was performed.

### Suggested next-session skills

- `karpathy-guidelines` before edits (required by project instructions).
- `codebase-design` to finish the migration/context/runner authority boundaries.
- `grill-me` only if product decisions around strict cutover or migration UX
  must be revisited; the main architectural decisions are already recorded
  above.
- `handoff` again before pausing a later implementation phase.

## 2026-07-22 — Hypothesis Ledger forced cutover integration handoff

### Task background

- The user authorized completion of the remaining Hypothesis Ledger cutover:
  project-atomic migration, strict v2 node contracts, fixed authorized context,
  read-only ranking, continuation ordering, and regression/coverage validation.
- The detailed implementation contract is in the user request and the current
  code/tests are the authoritative state; do not infer missing scientific
  provenance during migration.

### Completed in this session

- Added the focused modules `src/research_loop/hypothesis_contracts.py` and
  `src/research_loop/hypothesis_migration.py`; expanded `HypothesisLedger` with
  activation/migration/authorization, read-only query paths, projection rebuild,
  and continuation support.
- Added Draft 2020-12 submission/persisted schemas and semantic mappings for the
  remaining L2, L5, L8.5, L9b, and L10a nodes; updated context/provider/template
  paths to use v2 contracts for bound projects.
- Implemented migration dry-run/resolution/commit plumbing, v1 formal-entry
  activation gates, content/hash checks, and append-only committed-emission
  markers. A v2 resolver now requires a matching ledger emission, receipt, and
  finalized marker.
- Physically injected authorized ledger snapshots into context and closed the
  snapshot statement/event leakage path; ranking now consumes ledger DTOs rather
  than delta files. Runner continuation now emits loop-memory before creating a
  child and validates store/cursor/successor identity.
- Added and expanded migration, contract, ledger, context-isolation, ranking,
  cross-round, and crash/finalization tests. Added `pytest-cov` development
  dependency, `.coveragerc`, and subprocess coverage collection hooks.

### Verification observed

- `rtk proxy python -m pytest -q` completed with `324 passed in 303.44s`
  before the final committed-emission-marker test was added; that marker test
  currently passes independently (`1 passed in 2.03s`). Rerun the full suite to
  obtain the current final count.
- Targeted ledger/contracts/migration/cross-round/ranking suite: `32 passed`.
- `rtk git diff --check` passed.
- `rtk proxy python research_loop_v04.py --help` and
  `rtk proxy python run_loop.py --help` passed.
- Full coverage command ran all collected tests (`324 passed`) but failed the
  required threshold: branch coverage was `61.74%` versus `--cov-fail-under=80`.
  Coverage collection is now working across CLI subprocesses; the remaining
  gap is genuine untested legacy branches, concentrated in `engine.py`,
  `src/run_loop.py`, gates, and provider dispatch.

### Remaining work

1. Add direct contract/integration tests for the uncovered engine, runner, gate,
   provider, migration crash-point, and authorization branches until branch
   coverage reaches at least 80%; do not lower the threshold or omit modules.
2. Rerun the current full pytest suite and the required coverage command after
   the new marker test/configuration changes, then record exact summaries.
3. Perform final correctness/security review, especially migration transaction
   crash recovery and continuation idempotency, before any commit.
4. Review the complete diff and stage only task files. No commit or push has
   been made yet.

### Workspace state

- Branch: `codex/hypothesis-ledger-cutover`.
- Working tree is intentionally uncommitted and contains the task-related
  modifications listed by `rtk git status --short`, including the new ledger
  contract/migration modules, coverage configuration, and tests.
- Existing v1 artifacts remain preserved; do not delete or overwrite them.

### Suggested next-session skills

- `karpathy-guidelines` before any further edits.
- `code-review` and a security-focused review before committing persistence or
  migration changes.
- `verification-before-completion` (if available) for the final test/coverage
  and diff audit.
- `handoff` again if work pauses before the 80% coverage gate is satisfied.

## 2026-07-23 — Current state, problems, and continuation plan

### Background

- The active task is the Hypothesis Ledger forced cutover and its remaining
  integration work. The detailed architecture and acceptance criteria are in
  the user request; this handoff records executable state and the next actions.
- The user also asked whether the 4,768-line `src/research_loop/engine.py`
  should be split. The answer is yes, but only as a staged, behavior-preserving
  extraction after the current ledger cutover is stabilized.

### Current implementation state

- Branch: `codex/hypothesis-ledger-cutover`.
- The working tree is intentionally uncommitted. All current modifications are
  task-related; preserve existing v1 artifacts and do not reset or clean the
  tree.
- The ledger seam is implemented in `src/research_loop/hypothesis_ledger.py`,
  with focused contract and migration modules:
  `src/research_loop/hypothesis_contracts.py` and
  `src/research_loop/hypothesis_migration.py`.
- Bound projects use explicit store/project activation, v2 schemas, append-only
  SQLite facts, deterministic IDs, receipts, committed-emission markers, and
  fail-closed artifact/hash resolution.
- v2 contract and semantic paths now cover the remaining L2, L5, L8.5, L9b, and
  L10a flows in addition to the earlier L1/L3/L4/L6/L7/L8/L9a/L10b work.
- Migration dry-run/resolution/commit plumbing, activation gates, fixed
  authorized context snapshots, ledger-backed ranking DTOs, and
  `emit-loop-memory` before continuation child creation are present.
- Context leakage checks were tightened so unauthorized statements/events do
  not enter snapshots; L9a/L9b must remain mutually invisible.
- Tests were added or expanded for contracts, migration, ledger lifecycle,
  cross-round behavior, ranking, context isolation, and emission finalization.

### Verification observed

- `rtk proxy python -m pytest -q` completed with `324 passed in 303.44s`
  before the final committed-emission-marker test was added. The new marker
  test passes independently (`1 passed in 2.03s`); rerun the full suite for the
  current exact total.
- Targeted ledger/contracts/migration/cross-round/ranking tests: `32 passed`.
- `rtk git diff --check` passed.
- `rtk proxy python research_loop_v04.py --help` and
  `rtk proxy python run_loop.py --help` passed.

### Problems and risks

1. Coverage is below the required gate. The full coverage invocation collected
   and passed all 324 tests but reported branch coverage `61.74%`, failing
   `--cov-fail-under=80`. Subprocess collection is now wired through
   `.coveragerc`, `sitecustomize.py`, and `tests/conftest.py`, so this is a real
   test-gap rather than a missing-collection artifact. The largest uncovered
   areas are legacy branches in `src/research_loop/engine.py`, `src/run_loop.py`,
   gates, and provider dispatch.
2. The full suite has not been rerun after the latest marker test and coverage
   changes; no final regression count should be claimed yet.
3. Migration transaction crash-point behavior and continuation idempotency need
   a final adversarial review. In particular, verify that orphan files/receipts
   are invisible without activation and that retrying a memory/successor pair
   cannot create a second occurrence.
4. `engine.py` remains a large CLI god module (about 4,768 lines and 110
   functions). It mixes topology/constants, templates, preflight, lifecycle,
   ledger commands, execution workspace, continuation, reporting, pitfalls,
   ranking, and parser dispatch. Splitting it mechanically now would increase
   risk; leaving it permanently as the authority boundary would increase future
   drift and coverage cost.
5. No final code/security review or commit has been performed.

### Next-session plan

#### Phase 1 — Establish a fresh baseline

- Run the current targeted ledger/contract/migration/context/ranking/runner
  suites and then the complete pytest suite.
- Capture the current test count, failures, skipped tests, and coverage report
  before adding new tests.

#### Phase 2 — Raise coverage through real boundary tests

- Add tests for uncovered `engine.py` lifecycle/CLI branches, `src/run_loop.py`
  dispatch and stop-policy branches, gate rejection paths, provider dispatch,
  migration failure/rollback points, and authorization/as-of replay.
- Use native-v2 fixtures or explicit migration fixtures; do not weaken v2 gates
  or exclude production modules from coverage.
- After each group, rerun the narrow suite and inspect `term-missing` output.

#### Phase 3 — Staged `engine.py` extraction

- First extract low-coupling command families: ranking, pitfall, and reporting.
- Then extract ledger/migration/authorization commands and continuation logic.
- Then extract project/lifecycle and execution-workspace commands.
- Move argparse construction/dispatch into `cli.py`; retain `engine.py` as a
  compatibility facade exposing `main` and any legacy `cmd_*` names required by
  tests or public scripts.
- Keep schemas, topology, ledger facts, and event mappings in their existing
  focused modules. Do not create a second source of truth or introduce import
  cycles.

#### Phase 4 — Correctness/security review and final verification

- Review SQL parameterization, append-only triggers, store/project binding,
  artifact path normalization, receipt/hash matching, and fail-closed gates.
- Test projection clearing/rebuild, cross-project occurrence isolation,
  fixed-memory immutability, FALSIFIED reopen requirements, and L9a/L9b
  sentinel absence in context, manifests, prompts, and ledger snapshots.
- Run:
  `rtk proxy python -m pytest -q`
  and
  `rtk proxy python -m pytest -q --cov=research_loop --cov=run_loop --cov-branch --cov-report=term-missing --cov-fail-under=80`.
- Finish with `rtk git diff --check` and both public CLI `--help` checks.
- Only after all required checks pass, review the diff, stage task files, and
  create a conventional commit if explicitly authorized.

### Definition of success

- Current full pytest suite passes with an auditable summary.
- Branch coverage is at least 80% without exclusions or threshold reduction.
- Migration, context isolation, ranking read-only behavior, continuation order,
  and projection rebuild tests pass.
- `engine.py` is reduced to a compatibility facade or clearly bounded residual
  coordinator, with no duplicated contract/event logic.
- Security/correctness review finds no unresolved high-severity issue, and the
  worktree is only committed after explicit authorization.

### Suggested skills

- `karpathy-guidelines` before every code-edit phase.
- `code-review` and a security-focused review before commit.
- `codebase-design` for the staged `engine.py` extraction.
- `verification-before-completion` for the final pytest/coverage/diff audit.
- `handoff` again if the task pauses before the coverage and review gates pass.
