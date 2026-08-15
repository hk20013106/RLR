# Meta-RLR Phase 3 Auto-Wakeup Implementation Plan

Base: `3b3de53f4d51f6a2bf7b915532d15a91f5892c50`
Branch: `phase3/auto-maintenance-wakeup`

## Scope

Implement only the automatic bridge described in the companion design spec. Preserve Phase 2 ownership and settlement semantics.

## Sequence

1. Add focused tests for a new provider-runtime verification profile and bridge behavior. Tests must fail before implementation.
2. Add `provider_runtime_execution_integrity` to a single `provider_runtime_integrity` verification profile. Reuse the existing profile catalog/verifier.
3. Add a small `rlr_maintenance.autowake` module that:
   - loads explicit opt-in config;
   - classifies only already-observed runtime terminal states;
   - normalizes/persists/reuses `RLRMaintenanceEvent/v1`;
   - invokes the existing `meta_rlr.py run-once` CLI;
   - accepts resume handoff only for `verified` or `recovered` outcomes.
4. Extend `MetaRLRTurnResult` minimally with `worktree_path` so Phase 3 can activate the verified code without touching the original checkout.
5. Integrate the bridge at the detached worker non-zero boundary before generic failure finalization.
6. On a verified handoff, run exactly one fresh `_deep-research-worker` process from the verified worktree against the same project/task request. Guard the retry against recursive repair.
7. Review the diff for architecture drift, duplicated scheduling/state, data mutation, verification shortcuts, or LoopX-version coupling.
8. Run focused tests first, then Phase 2 maintenance tests/provider-runtime tests, then the repository CI/full regression.
9. Fix only root causes that violate the Phase 3 design; do not expand scope to unrelated failures.

## Targeted validation

Focused:

```text
tests/test_meta_rlr_autowake.py
tests/test_meta_rlr_profiles.py
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