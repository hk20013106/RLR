# Hermes Multi-Agent Coordination Plan: Ledger Finalization + Engine Extraction

> **Revision 2 (2026-07-24):** Execution-readiness audit applied. H0-H3 states
> redefined, dependency graph updated with limited dual-track parallelism,
> micro-tasks merged into batch tasks, git/worktree protocol added, agent
> launch contracts verified, reviewer hierarchy clarified, circuit-breaker
> and coverage policies established, orphan residual paths adjudicated.

## 1. Phase state (H0-H3)

```text
H0 = Execution-readiness audit (COMPLETED - this revision)
H1 = Plan 1 draft completed, validated by H0 (COMPLETED)
H2 = Plan 2 draft completed, validated by H0 (COMPLETED)
H3 = Apply H0 corrections and freeze canonical plans (COMPLETED by this revision)
```

All three canonical plans are now frozen at their current revision. H0 found
no issue requiring Plan 1 or Plan 2 to be reopened from scratch. Corrections
were applied as targeted edits (see §10 Orphan Residual-Path Verdict and
Plan 1B CLI-boundary rules).

## 2. Platform capability verification (verified 2026-07-24)

### Hermes

| Capability | Status | Evidence |
| --- | --- | --- |
| Orchestration (delegate_task) | verified | `delegate_task` tool, `max_concurrent_children=3` |
| Plan/handoff file management | verified | `write_file`, `read_file`, `patch` tools |
| Terminal/test execution | verified | `terminal` tool, foreground/background |
| Codebase-wide search | verified | `search_files` tool |

### Codex (0.144.5)

| Capability | Status | Evidence |
| --- | --- | --- |
| TDD implementation | verified | `codex e --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check` |
| Test execution | verified | codex session 019f945e completed successfully |
| Session resume | verified | `codex exec resume <session-id>` |

### Claude (2.1.218)

| Capability | Status | Evidence |
| --- | --- | --- |
| Architecture review | verified | `claude -p --output-format text` |
| Code review | verified | ECC `code-review` skill available |

### Antigravity (1.1.6)

| Capability | Status | Evidence |
| --- | --- | --- |
| Code analysis | verified | `agy -p --print` |
| Adversarial review | verified | `agy -p --dangerously-skip-permissions` |
| Test execution | verified | `agy -p` can run shell commands |

## 3. Agent Launch Contract

### Codex

```text
Command:     codex e --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C "<workdir>" --json -
Input:       stdin (prompt with ROLE_FILE header)
Workdir:     Windows absolute path (e.g. D:\research_loop\research_loop)
Resume:      codex exec resume <session-id> -C "<workdir>"
Timeout:     600000ms (10 min)
Log:         codeagent-wrapper writes to %TEMP%\codeagent-wrapper-<pid>.log
Success:     exit_code=0, SESSION_ID in output
Failure:     exit_code!=0, check log for details
Environment: must use Windows paths, NOT MSYS /d/... paths
```

### Claude

```text
Command:     claude -p --output-format text "<prompt>" --add-dir "<workdir>"
Input:       command-line argument or stdin
Workdir:     current directory (cd first) or --add-dir
Timeout:     300000ms (5 min)
Success:     exit_code=0, response on stdout
Failure:     exit_code!=0, stderr has error
Note:        does not support session resume in -p mode
```

### Antigravity

```text
Command:     agy -p --print --dangerously-skip-permissions "<prompt>"
Input:       command-line argument
Workdir:     current directory (cd first)
Timeout:     300000ms (5 min)
Success:     response on stdout
Failure:     non-zero exit, stderr has error
Note:        does not support session resume
```

### Launch failure handling

- CLI startup failure (path error, auth error, missing binary) is
  **ENVIRONMENT_BLOCKED**, not an implementation failure.
- Do not count environment failures against the task retry limit.
- Environment failures have their own retry limit of 2.
- After 2 environment failures, mark `ENVIRONMENT_BLOCKED` and escalate.

## 4. Agent responsibility hierarchy

### Implementer (Codex)

- Writes code in an isolated worktree.
- Creates local commits per checkpoint/family.
- Runs family tests after each checkpoint.
- Generates one handoff per batch.

### Verifier (Antigravity, default for Batch A/B)

- Works on a **detached worktree at a fixed commit**.
- Runs: test suite, cycle audit, public API comparison, CLI snapshot,
  coverage evidence, duplicate-definition check.
- Returns: `PASS` / `FAIL` / `ENVIRONMENT_BLOCKED`.
- Does NOT modify any files.

### Semantic reviewer (Claude, default for Plan 1A/1B, Batch C, final Plan 2)

- Works on a **detached worktree at a fixed commit**.
- Reviews: SQL/read-boundary semantics, forensic vs. consumptive boundary,
  gate-test reachability, module boundary, public API contract, behavior
  preservation, architecture consistency.
- Returns structured review with findings.
- Does NOT modify any files.

### Hermes (gate keeper)

- Adjudicates reviewer verdicts.
- Decides gate passage.
- Manages retry cycles.
- Does NOT implement or review code.

### Default assignment

```text
Batch A/B:           Antigravity verifier only
Plan 1A/1B:          Claude semantic review
Batch C (C1, C2):    Claude semantic review
Batch D:             Antigravity verifier
Batch E:             Claude semantic review (final)
Final Plan 2:        Claude semantic review
```

## 5. Dependency graph (limited dual-track parallelism)

```text
                         ┌─ Plan 1A -> Plan 1B ─────────┐
H3 -> P2-PRE ────────────┤                              ├─ SYNC BARRIER
           (safety nets) └─ Plan 2 Batch A ─────────────┘
                                                           ↓
                                              Plan 2 Batch B
                                                           ↓
                                              Plan 2 Batch C
                                                           ↓
                                              Plan 2 Batch D
                                                           ↓
                                              Plan 2 Batch E
```

### Rules

1. **Plan 1A/1B and Batch A may run in parallel** after P2-PRE completes.
   - Plan 1A/1B touches `hypothesis_ledger.py` + test files.
   - Batch A touches `engine.py` + new leaf modules.
   - File sets are disjoint.
2. **Batch B does NOT parallel Plan 1.**
   - Ranking extraction shares `test_ranking_cli.py` fixture expectations with
     Plan 1A.
   - Plan 1B modifies CLI/gate test baselines.
3. **Batch C waits for**: Plan 1A pass, Plan 1B pass, Batch A pass, Batch B pass.
4. **Sync barrier**: after parallel tracks converge, run a **joint regression
   test on the merged snapshot** before releasing Batch B.
5. Only Hermes may release parallel tasks, and only when file sets, worktrees,
   and test responsibilities are fully independent.
6. **No unmeasured duration estimates.** Do not claim "30-40% faster" without
   task-timing data.

### P2-PRE split

```text
P2-PRE-TEST: fix test_no_cycles.py scan path (tests only, no production code)
P2-RANKING-BOUNDARY: decide _SyntheticPositionBiasedJudge ownership (separate commit)
```

See §8 for details.

## 6. Task matrix

| Task ID | Phase | Owner | Reviewer | Depends on | Files owned | Status |
| --- | --- | --- | --- | --- | --- | --- |
| H0 | Audit | Hermes | - | - | docs (read-only) | completed |
| H1 | Plan | Hermes | - | H0 | `docs/ledger-finalization-read-boundaries.md` | completed |
| H2 | Plan | Hermes | - | H0 | `docs/engine-modular-extraction.md` | completed |
| H3 | Freeze | Hermes | - | H1, H2 | `docs/hermes-multi-agent-ledger-engine-plan.md` | completed |
| P2-PRE-TEST | Safety net | Codex | Antigravity | H3 | `tests/test_no_cycles.py` | pending |
| P2-RANKING-BOUNDARY | Boundary audit | Codex | Claude | H3 | `src/research_loop/engine.py`, possibly `ranking.py` | pending |
| P1A | Correctness | Codex | Claude | H3 | `src/research_loop/hypothesis_ledger.py`, `tests/native_v2_helpers.py`, `tests/test_hypothesis_ledger.py`, `tests/test_ranking_cli.py` | pending |
| P1B | Test coverage | Codex | Claude | P1A | `tests/test_v06_divergence.py` | pending |
| P2-BATCH-A | Extraction | Codex | Antigravity | P2-PRE-TEST | `src/research_loop/common.py` or `commands/_helpers.py`, `templates.py`, `delta_render.py`, `engine.py` | pending |
| P2-BATCH-B | Extraction | Codex | Antigravity | P1A, P1B, P2-BATCH-A, SYNC | `commands/ranking.py`, `commands/pitfall.py`, `commands/reporting.py`, `engine.py` | pending |
| P2-C1 | Extraction | Codex | Claude | P2-BATCH-B | `commands/ledger.py`, `engine.py` | pending |
| P2-C2 | Extraction | Codex | Claude | P2-C1 | `commands/continuation.py`, `engine.py` | pending |
| P2-BATCH-D | Extraction | Codex | Antigravity | P2-C2 | `commands/lifecycle.py`, `commands/research.py`, `commands/execution.py`, `engine.py` | pending |
| P2-E1 | Extraction | Codex | Claude | P2-BATCH-D | `cli.py`, `engine.py` | pending |
| P2-E2 | Final verify | Codex | Antigravity | P2-E1 | read-only | pending |
| P2-R | Final review | Claude | Hermes | P2-E2 | read-only | pending |

### Parallel execution

- **P1A and P2-BATCH-A** may run in parallel after P2-PRE-TEST.
- All other tasks are serial.
- `engine.py` single-writer rule: **only one task may modify `engine.py` at any
  time.** P1A does not touch `engine.py`, so P1A + P2-BATCH-A parallel is safe.

## 7. Batch task definitions

### P2-BATCH-A (merged: helpers + templates + delta rendering)

- **Owner:** Codex, one session, one worktree.
- **Internal checkpoints (3 local commits):**
  1. helpers -> `common.py` extend or `commands/_helpers.py`
  2. templates -> `templates.py`
  3. delta rendering -> `delta_render.py`
- After each checkpoint: run family tests + Phase-0 nets.
- **One handoff** for the entire batch.
- **Antigravity** verifies the final batch commit.
- **Hermes** performs one batch gate.
- Any checkpoint may be independently rolled back.

### P2-BATCH-B (merged: ranking + pitfall + reporting)

- **Owner:** Codex, one session, one worktree.
- **Prerequisite:** P2-RANKING-BOUNDARY resolved.
- **Internal checkpoints (3 local commits):**
  1. ranking -> `commands/ranking.py`
  2. pitfall -> `commands/pitfall.py`
  3. reporting -> `commands/reporting.py`
- After each checkpoint: run family tests + Phase-0 nets.
- **One handoff** for the entire batch.
- **Antigravity** verifies.

### P2-C1 (ledger, independent)

- Finalization-sensitive. Separate task.
- Claude semantic review.

### P2-C2 (continuation, independent)

- Idempotency-sensitive. Separate task.
- Claude semantic review.

### P2-BATCH-D (merged: lifecycle + research + execution)

- **Decision:** These three families share helpers from Batch A and have
  non-overlapping symbols (verified by AST manifest). They can be extracted
  sequentially in one Codex session.
- **Internal checkpoints (3 local commits):**
  1. lifecycle -> `commands/lifecycle.py`
  2. research -> `commands/research.py`
  3. execution -> `commands/execution.py`
- **One handoff** for the entire batch.
- **Antigravity** verifies.
- **Rationale:** All three depend on the same leaf modules (`topology`,
  `context`, `gates`, `common`). No cross-family symbol dependencies exist.
  Shared test baseline risk is low because each family has its own test files.

### P2-E1 (dispatch, independent)

- Move `build_parser` + `main` to `cli.py`.
- Claude semantic review (terminal state).

## 8. P2-PRE split

### P2-PRE-TEST

- Fix `tests/test_no_cycles.py` `_local_module_files()` (L26-36) to scan
  `REPO / "src" / "research_loop"` in addition to `REPO / "research_loop"`.
- Verify the test discovers the actual package.
- **No production code modified.**
- Separate commit.

### P2-RANKING-BOUNDARY

- Audit `_SyntheticPositionBiasedJudge` (engine.py:4083).
- **Evidence:** Used only by `_ranking_accuracy` (L4103), `cmd_ranking_benchmark`
  (L4113, L4180). All callers are ranking CLI functions.
- **Decision criteria:**
  - If it is pure ranking algorithm logic (reusable outside CLI): move to
    `ranking.py` logic leaf.
  - If it is benchmark-specific test fixture logic: move with `commands/ranking.py`
    in Batch B.
- **Evidence-based assessment:** The class generates biased judge positions for
  benchmark testing. It is not used by the core ranking algorithm
  (`ranking.py:DeterministicFakeJudge` is the runtime judge). It is
  benchmark-specific. **Decision: move with `commands/ranking.py` in Batch B.**
- Do NOT move it to `ranking.py` logic leaf unless evidence shows reuse outside
  benchmark CLI.
- Separate commit from P2-PRE-TEST.

## 9. Git and Worktree Transaction Protocol

### Baseline

- **Base commit:** `1f75f91` on `codex/hypothesis-ledger-cutover`.
- H3 freeze records this as the canonical base.
- **Dirty working tree:** The current tree has 31 modified + 9 untracked files
  (pre-existing task work). All task worktrees branch from `1f75f91` with
  `git stash` or `git worktree add` to avoid conflicts.
- No agent may start from an uncertain working-tree state.

### Naming conventions

```text
Branch:           rlr/<task-id>           (e.g. rlr/p1a, rlr/p2-batch-a)
Implementer WT:   D:\research_loop\wt\<task-id>
Reviewer WT:      D:\research_loop\wt\<task-id>-review
Log:              D:\research_loop\wt\<task-id>\agent.log
Handoff:          docs/handoffs/<task-id>-handoff.md
```

### Implementer transaction

1. Hermes creates worktree: `git worktree add D:\research_loop\wt\<task-id> -b rlr/<task-id> 1f75f91`
2. Codex works in that worktree.
3. Each checkpoint creates a local commit: `git commit -m "<type>: <description>"`
4. No push without explicit authorization.
5. Test failures must not be handed to reviewer unless marked as diagnostic.
6. On completion, Codex writes handoff to `docs/handoffs/<task-id>-handoff.md`.

### Reviewer transaction

1. Hermes records the implementer's final commit hash.
2. Hermes creates a detached worktree: `git worktree add --detached D:\research_loop\wt\<task-id>-review <commit-hash>`
3. Reviewer runs in that worktree (read-only).
4. Reviewer writes structured report.
5. Hermes cleans up: `git worktree remove D:\research_loop\wt\<task-id>-review`
6. Reviewer never modifies the implementer's branch.

### Integration strategy

**Canonical: serial integration branch.** All tasks merge back to
`codex/hypothesis-ledger-cutover` via `git merge --no-ff` after gate passage.
No cherry-pick, no fast-forward. This preserves per-task commit history and
makes rollback granular.

```text
git checkout codex/hypothesis-ledger-cutover
git merge --no-ff rlr/<task-id> -m "merge: <task-id> (<description>)"
git worktree remove D:\research_loop\wt\<task-id>
git branch -d rlr/<task-id>
```

## 10. Orphan residual-path verdict (H0 highest priority)

### 1. snapshot_candidate() - VERDICT: CONSUMPTIVE, MUST BE INCLUDED IN PLAN 1A

**Evidence path:**
- `hypothesis_ledger.py:1062-1081`: `snapshot_candidate` reads
  `SELECT event_id,commit_seq,... FROM events WHERE project_id=? AND candidate_id=? AND round_id=?`
  with **no committed_emissions join**.
- Called by `_build_loop_memory` (`engine.py:3471`).
- `_build_loop_memory` called by `cmd_emit_loop_memory` (`engine.py:3564`).
- `cmd_emit_loop_memory` is a runtime command that creates loop memory for
  next-round candidate creation.
- Loop memory feeds into `new-candidate --from-memory`.

**Verdict:** `snapshot_candidate` is a **consumptive** API. Orphan events
enter loop memory and influence the next candidate's context. This must be
included in Plan 1A's finalized predicate scope.

**Action:** Plan 1A scope expanded to include `snapshot_candidate()`. Add
`JOIN emissions m ON m.commit_seq = e.commit_seq` and
`FINALIZED_EMISSION_PREDICATE` to the event query at L1068-1073.

### 2. Projection contamination - VERDICT: REAL BUT SELF-HEALING; NO PLAN 1C NEEDED

**Evidence path:**
- `commit_delta` (L457-836) writes `workflow_projection` (L450) and
  `epistemic_projection` (L455) **before** `finalize_emission`.
- Later `commit_delta` reads `workflow_projection` (L570, L760) and raw
  `events` (L565, L596, L604, L676, L740) without finalized marker.
- An orphan L1 creates occurrence + projection entries.
- Later L3 `commit_delta` sees orphan occurrence via `_existing_occurrences`
  (L396-398, queries `occurrences` table, not events).

**But:** The orphan's effect is **limited to the same candidate/round**. A
crash during L1 of candidate C1 round 1 does NOT affect candidate C2. If L1
crashes, L3 cannot be emitted (L3 needs L1's `hypothesis_id` from the
normalized delta). The operator re-runs `emit-delta` for L1, which is
idempotent (`commit_delta` returns prior emission on retry), and finalizes it.

The dangerous case: L1 commits but crashes, then L3 is emitted with L1's
hypothesis_id (available from the orphan's events). L3 commits and finalizes
normally. Later, re-running L1 returns the prior emission and finalizes it.
**Self-healing on retry.**

**`verify(rebuild=True)` detection:** After Plan 1A filters rebuild to
finalized-only, an orphan L1's PROPOSED event is excluded from rebuild. But
the finalized L3 event (which references the orphan occurrence) is included.
The rebuild hash would differ from stored projection -> `verify` reports
"projection rebuild differs from persisted projection". This is a
**detection mechanism**, not a data-loss mechanism.

**Verdict:** Real contamination exists but is:
- Temporary (self-heals on L1 retry).
- Limited to same candidate/round.
- Detectable by `verify(rebuild=True)` after Plan 1A.

**No Plan 1C (projection protocol hardening) needed at this stage.** If the
project later requires the stronger invariant ("orphans can never influence
later writes"), that is a separate protocol-hardening plan. Record as
**known limitation** in Plan 1A.

## 11. Plan 1B CLI test boundary rules

Plan 1B must distinguish:

```text
upstream prerequisite state  vs.  target emission under test
```

Rules (written into Plan 1B):

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

## 12. Coverage policy (three-layer guard)

### Layer 1: Global non-regression

- H0 records baseline: line coverage, branch coverage, covered statements,
  missed statements.
- Current baseline (from handoff): branch coverage `61.74%`.
- Each batch and final state compared to baseline.
- **Tolerance:** 0.2 percentage points for rounding/path changes.
- Beyond tolerance: gate blocks unless explicit explanation provided.

### Layer 2: Family execution evidence

- After each family extraction, run family tests and collect coverage on the
  new module.
- Prove: module is imported, `cmd_*` entry points are executed, new module is
  not 0% coverage, original key positive/reject paths still execute.

### Layer 3: Pre/post behavioral mapping

- Record: old `engine.py` family test -> new `commands/<family>.py` test.
- Acceptance: previously-executed behaviors are still executed after migration.
- This is **not** an arbitrary fixed percentage.

No new coverage tools installed without authorization. Use existing
`pytest-cov` output.

## 13. Retry and circuit-breaker policy

### Implementation retry

- Max 3 implement-review cycles per task.
- One cycle = owner submits fixed commit -> reviewer returns verdict.
- After 3rd failure: `BLOCKED_ESCALATION`.
- Hermes: stops auto-retry, freezes branch/worktree, summarizes 3 failures,
  distinguishes repeated vs. new issues, records owner/reviewer disagreement,
  submits human decision request.

### Environment retry

- Max 2 retries for environment failures (CLI startup, path error, dependency
  install, temporary process error).
- After 2nd failure: `ENVIRONMENT_BLOCKED`.
- Environment failures do NOT count against implementation retry limit.

## 14. Gate criteria

### Per-batch gate

- Fixed commit hash recorded.
- Implementer worktree tests pass.
- Detached reviewer worktree tests pass.
- `test_public_api_compat.py` green.
- `test_no_cycles.py` green (after P2-PRE-TEST fix).
- Family tests green.
- `test_gate_cli_snapshot.py` green (when applicable).
- Global coverage non-regression (Layer 1).
- Family execution evidence (Layer 2).
- No duplicate source of truth.
- No command module import of `engine`.
- Structured verifier report.
- Applicable semantic review (Claude for C1/C2/E, Antigravity for A/B/D).
- Retry count within limit.

### Sync barrier gate (after parallel P1A + Batch A)

- Joint regression: `pytest -q` on merged snapshot.
- Both P1A and Batch A individual gates pass.
- No file conflicts between the two tracks.

### Final gate

```powershell
rtk proxy python -m pytest tests\test_public_api_compat.py tests\test_no_cycles.py tests\test_engine_api.py tests\test_gate_cli_snapshot.py -q
rtk proxy python -m pytest tests\test_hypothesis_ledger.py tests\test_ranking_cli.py tests\test_cross_round_e2e.py tests\test_v06_divergence.py -q
rtk proxy python -m pytest -q
rtk proxy python -m pytest -q --cov=research_loop --cov=run_loop --cov-branch --cov-report=term-missing --cov-fail-under=80
rtk proxy python run_loop.py --help
rtk proxy python research_loop_v04.py --help
rtk git diff --check
```

If coverage baseline is below 80%, accurately distinguish:
```text
tests passed
coverage gate failed because baseline coverage remains below threshold
```

## 15. Handoff specification

Reduced from per-micro-task to per-batch:

| Task | Handoff count |
| --- | --- |
| P1A | 1 implementation handoff |
| P1B | 1 implementation handoff |
| P2-BATCH-A | 1 batch handoff |
| P2-BATCH-B | 1 batch handoff |
| P2-C1 | 1 handoff |
| P2-C2 | 1 handoff |
| P2-BATCH-D | 1 batch handoff |
| P2-E1 | 1 handoff |

Verifier/reviewer writes a **concise report** (not a full implementation handoff).

Handoff format:

```markdown
# Handoff: <task-id>

## Branch/worktree
## Files changed
## Exact commands run
## Test results (pass/fail/skip/error counts)
## Known baseline failures
## Unresolved issues
## Assumptions
## Public API changes (must be "None" unless authorized)
## Next task prerequisites
## Commit hash (if authorized)
## Diff summary
```

## 16. Bug discovery during extraction

1. Do NOT fix behavior bugs in the extraction commit.
2. Record in handoff under "Unresolved issues."
3. Hermes creates a separate issue/plan.
4. Extraction proceeds as verbatim move regardless.

## 17. File ownership rules (unchanged)

- One active task = one file write owner.
- `engine.py`: only one Codex extraction task at any time.
- Reviewer is read-only.
- No three agents produce competing versions of the same file.

## 18. Recommended first execution task

```text
P2-PRE-TEST: Fix test_no_cycles.py to scan src/research_loop.

Command for Codex:
  codex e --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
    -C "D:\research_loop\research_loop" --json -

Prompt: "Fix tests/test_no_cycles.py _local_module_files() to discover
src/research_loop/ in addition to research_loop/. Run the test to verify
it discovers the actual package. Do not modify production code."
```
