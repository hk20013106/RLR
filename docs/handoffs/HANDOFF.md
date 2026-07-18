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
