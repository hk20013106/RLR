# RLR v0.9.2 canonical continuation data authorization

## Goal

Repair the native Round N -> Round N+1 creation path so a continuation made by
`StopPolicy -> run_loop.create_child() -> new-candidate --from-memory` emits a
schema 1.1 L0 contract with explicit, hash-bound inherited scientific source
selectors. Preserve the existing CurrentRoundDataBinding and L7 fail-closed
boundaries, make deterministic child retries idempotent, and provide an
explicit auditable recovery operation for an unstarted defective continuation.
Release the bounded repair as v0.9.2 without touching the dirty source
worktree, the live real-data project, or scientific source files.

## Boundaries and authority

- Work only in `D:\\rlr-v0.9.2-work-20260816`, branched from merged main
  `07d1d2dddeb3d48db54a368bbe771c45f0a58310`.
- `L0InputContract` remains the declaration authority.
- The prior `Round Manifest` plus `L0EvidenceBinding/v1` remains the verified
  artifact authority.
- `CurrentRoundDataBinding/v1` remains the only L7 input authority.
- Loop memory carries continuation identity and intent only; it does not gain a
  file catalog.
- Automatically projected inherited selectors are limited to source files
  explicitly declared by the previous candidate's `source_input` and matched
  by exact path plus SHA-256 against the verified prior manifest. Their role is
  taken from the prior file manifest when available, otherwise a deterministic
  `inherited_source` role is used; every selector receives a reuse reason.
- Previous intermediate/result artifacts remain opt-in selectors; audit,
  literature, receipt, report, and manifest artifacts are never projected by
  the same-dataset source rule.

## Phase 1 — baseline and RED evidence

1. Add one vertical regression fixture to the existing cross-round integration
   module. Seed a real file-backed Round 1 through the normal CLI, finalize its
   real manifest, emit real loop memory, and call the imported production
   `run_loop.create_child()` function with a committed L10b REVISE proposal.
2. Do not edit the child contract in the test. Assert the v0.9.2 behavior
   required by the task: schema 1.1, explicit inherited selectors, and a
   non-empty binding containing the source file. On baseline v0.9.1 this test
   must fail because the child is inline/schema 1.0 and has zero authorized
   files.
3. Run and record the exact RED command and failure, then checkpoint the test
   only. No production code is changed before this observation.

## Phase 2 — canonical contract and selector projection

1. Add a narrow L0 state helper that verifies the memory-referenced prior
   manifest and exact hash, loads the parent L0 contract, and projects only
   source entries declared by that contract into selector records. Fail closed
   when the memory/manifest identity, source declaration, artifact class, or
   hash relationship is invalid.
2. Add a single current-schema promotion helper in `l0_contract` and use it at
   the native continuation intake boundary so newly created continuations
   carry schema 1.1 and an explicit `inherited_inputs` list while historical
   low-level builder compatibility remains readable.
3. Add an explicit `--inherit-previous-source` option to `new-candidate` and
   pass it from `run_loop.create_child()`. The canonical path therefore
   requests source projection explicitly. A supplied `--source-input-file`
   without this option remains new-only; with the option it becomes
   inherited-plus-new. This preserves explicit selectivity.
4. Keep selector validation in `l0_contract` and physical verification in
   `l0_data`; do not add a second registry or bypass `L0EvidenceBinding`.

## Phase 3 — deterministic creation safety and explicit recovery

1. Move all contract writes after the existing-candidate identity check.
2. For an existing deterministic child, return success only when the
   frontmatter identity and canonical contract bytes already match. Otherwise
   fail closed without writing the sidecar.
3. Add an explicit `--recover-defective-continuation` mode on the same
   `new-candidate` command. It may upgrade only a candidate whose exact memory
   and successor hypothesis identity match, whose status is still `NEW`, whose
   old contract is demonstrably the data-less inline/schema 1.0 form, and
   whose candidate has no cognitive or execution deltas/workspace/receipt
   progress. It regenerates the canonical contract from verified parent state,
   updates the frontmatter hash coherently, refreshes only the derived empty
   CurrentRoundDataBinding when present, and writes one append-only recovery
   audit record. Any mismatch or progressed candidate is rejected.
4. Recovery is explicit and never part of ordinary idempotent retry. Ledger
   history is preserved; no candidate YAML/Markdown is hand-edited by tests or
   the release process.

## Phase 4 — regression matrix and version

Add or retain tests for:

- production `create_child()` schema 1.1 and inherited selector projection;
- inherited-only, new-only, and inherited-plus-new bindings;
- exact L7 staging and exclusion of unselected results/intermediates plus
  literature/audit/receipt/report/manifest artifacts;
- inherited hash mismatch fail-closed behavior;
- idempotent retry with unchanged contract/hash;
- same-memory invalid-contract refusal and explicit pristine recovery;
- progressed-candidate recovery refusal;
- relevant Hypothesis Ledger continuation behavior;
- `VERSION == "0.9.2"` while historical release tags remain untouched.

Run the narrow tests first, then the full suite, and capture exact exit status
and observed output for every verification command.

## Phase 5 — integration and release

Before every remote mutation, re-fetch and verify branch/commit/tree lineage.
Review the bounded diff and run `git diff --check`. Commit only source, tests,
design/plan or release documentation, and the version source. Push the feature
branch, open a PR to `main`, wait for required CI, merge only after CI passes,
verify the merged main commit, create annotated tag `v0.9.2`, and publish concise
release notes describing canonical continuation data authorization and
deterministic child creation safety. Do not claim the real scientific loop was
resumed or completed.

## Validation commands

```powershell
python -m pytest tests/test_cross_round_e2e.py -q
python -m pytest tests/test_round_data_cross_round_e2e.py tests/test_round_data_binding.py tests/test_round_data_execution.py -q
python -m pytest tests/test_l0_input_contract.py tests/test_l0_intake.py tests/test_hypothesis_ledger.py tests/test_version.py -q
python -m pytest -q
git diff --check
```

## Rollback

Before release, stop at the local or PR boundary if any required check fails.
Do not alter the live project. If a release mutation fails, preserve the
existing v0.9.1 tag and main, report the exact remote state, and leave the
repair branch available for review rather than rewriting history.
