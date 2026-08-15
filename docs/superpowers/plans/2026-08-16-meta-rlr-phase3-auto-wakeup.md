# Meta-RLR Phase 3 Auto-Wakeup Implementation Plan

Base: `3b3de53f4d51f6a2bf7b915532d15a91f5892c50`
Branch: `phase3/auto-maintenance-wakeup`

## Scope

Implement only the automatic bridge described in the companion design spec. Preserve Phase 2 ownership, settlement semantics, and the hard dependency rule that `src/research_loop` does not depend on Meta-RLR or LoopX.

## Sequence

1. Add focused tests for a new provider-runtime verification profile and bridge behavior. Tests must fail before implementation.
2. Add `provider_runtime_execution_integrity` to a single `provider_runtime_integrity` verification profile. Reuse the existing profile catalog/verifier.
3. Add a small `rlr_maintenance.autowake` module that:
   - loads explicit opt-in config;
   - classifies only already-observed runtime terminal states;
   - normalizes through the existing maintenance observer and persists/reuses `RLRMaintenanceEvent/v1`;
   - invokes the existing `meta_rlr.py run-once` CLI;
   - accepts resume handoff only for `verified` or `recovered` outcomes.
4. Reuse `GitWorkspace.find_existing` + `read_verified_commit` to resolve the independently verified repair worktree from Phase 2 provenance. Do not add a second worktree registry or change `MetaRLRTurnResult` solely for Phase 3.
5. Implement the wake/resume wrapper in `rlr_maintenance.autowake_adapter`, not in the scientific `research_loop` package.
6. Use repository-root `research_loop_v04.py` as the outer composition point: initialize RLR normally, then install the maintenance adapter onto the existing detached-task module after provider observability is in place.
7. On a verified handoff, run exactly one fresh `_deep-research-worker` process from the verified worktree against the same project/task request. Guard both the Meta-RLR child process tree and the repaired retry against recursive repair.
8. Fail closed if the running RLR code checkout is dirty, because Phase 2 repair provenance is commit-based and cannot verify an uncommitted runtime variant.
9. Review the diff for architecture drift, duplicated scheduling/state, data mutation, verification shortcuts, reverse dependencies, or LoopX-version coupling.
10. Run focused bridge/architecture tests first, then Phase 2 maintenance tests/provider-runtime tests, then the repository CI/full regression.
11. Fix only root causes that violate the Phase 3 design; do not expand scope to unrelated failures.

## Root-cause corrections found during implementation

- Direct event construction was moved back through the existing maintenance observer so there is still one normalization boundary.
- Dirty runtime code is rejected rather than pretending a repair against `HEAD` represents uncommitted code.
- Meta-RLR and verifier children inherit a non-reentrant guard so verification cannot recursively wake another maintenance turn.
- Full regression exposed an illegal `research_loop -> rlr_maintenance` import. The bridge was moved outward to `rlr_maintenance`, and `research_loop_v04.py` now composes the two systems. The architecture test remains strict; it was not weakened.

## Targeted validation

Focused:

```text
tests/test_meta_rlr_autowake.py
tests/test_maintenance_autowake_adapter.py
tests/test_meta_rlr_observer.py
tests/test_meta_rlr_profiles.py
tests/test_meta_rlr_architecture.py
tests/test_provider_runtime_observability.py
relevant detached Deep Research worker tests
```

Regression:

```text
tests/test_meta_rlr_*.py
full pytest suite via existing GitHub Actions CI
```

## Rollback

Phase 3 is opt-in via `RLR_META_RLR_AUTOWAKE_CONFIG`. Removing/unsetting it restores the pre-Phase-3 failure path. Code rollback is the normal branch/PR revert; no runtime database migration exists.
