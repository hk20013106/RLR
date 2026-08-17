# L6 Execution Readiness Design

## Goal

Prevent RLR from transitioning a candidate from `METHOD_APPROVED` to `NEEDS_EXECUTION` when the L6-approved execution scripts cannot actually be resolved.

## Architectural decision

Keep the DAG forward-only. Do not add `NEEDS_EXECUTION -> L6` rollback, plan supersession, or a new recovery state in this patch.

Reuse the existing L7 script authority: `_approved_execution_scripts(project_dir, cand_id)`. The execution gate must call the same resolver before it changes candidate status. Every declared L6 script must resolve to exactly one file using the existing search roots and exact-name semantics.

If resolution fails, `execution-gate` returns REJECT and leaves the candidate at `METHOD_APPROVED`. L7 remains execution-only and continues to fail closed independently.

## Why this boundary

L6 is documented as producing an executable analysis plan. L7 is documented as executing only the approved plan and not improvising. Therefore executability must be checked before the lifecycle enters `NEEDS_EXECUTION`, rather than adding a backward transition after failure.

## Scope

In scope:
- reuse `_approved_execution_scripts()` at the L6 -> execution boundary;
- fail closed for missing or ambiguous approved scripts;
- regression test that status is not advanced on resolution failure.

Out of scope:
- script-content SHA binding in L6;
- new script-generation phase;
- historical candidate recovery;
- lifecycle rollback/supersession;
- changes to L7 resolution semantics;
- changes to real scientific data or real candidates.

The historical stuck candidate `C0435E33DA217D4E6` is intentionally not mutated by this patch. Its recovery will be decided separately after this prevention fix is validated.
