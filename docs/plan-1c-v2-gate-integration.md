# Plan 1C: V2 Gate Integration

> Scope: wire the L4/L6/L7/L10b gate checks into the v2 emission path so
> that v2 deltas are validated against the same traceability gates as v1.
> This unblocks Plan 1B (test-only gate coverage restoration).

## Problem

`_emit_delta_v2()` (engine.py:988-1036) calls `ledger.commit_delta()` -> writes
artifact -> `finalize_emission()`, but **never invokes any gate functions**.
The v1 path in `cmd_emit_delta` (engine.py:~1160-1200) calls:
- `_audit_l4_methods` for L4
- `_audit_l6_traceability` for L6
- `_audit_l7_manifest` for L7
- `_audit_l10_traceability` + `_audit_l10_evidence` for L10b

Additionally, gate functions in `gates.py` expect `analysis_plan` as a dict
with `.get("scripts")`, but the v2 schema defines `analysis_plan` as a list
of strategy objects (each containing `scripts`).

## Scope

### Files to modify
- `src/research_loop/engine.py` -- add gate calls in `_emit_delta_v2`
- `src/research_loop/gates.py` -- make `_audit_l6_traceability` and
  `_l6_script_branches` handle both dict and list `analysis_plan`

### Files NOT to modify
- `src/research_loop/hypothesis_ledger.py`
- `src/research_loop/hypothesis_contracts.py`
- Any test file (Plan 1B territory)
- Any commands/ module

## Implementation steps

### Step 1: Fix gate functions to handle v2 list `analysis_plan`

In `gates.py`:

1. `_l6_script_branches` (L120-131): currently `(json.loads(...).get("analysis_plan") or {}).get("scripts", [])`.
   Change to handle both:
   - dict: `.get("scripts", [])` (v1)
   - list: iterate each strategy, collect `strategy.get("scripts", [])` (v2)

2. `_audit_l6_traceability` (L166-198): currently `(delta.get("analysis_plan") or {}).get("scripts", [])`.
   Same fix: handle both dict and list.

### Step 2: Add gate calls in `_emit_delta_v2`

After `ledger.commit_delta` succeeds but BEFORE writing the artifact, add the
same gate checks that the v1 path uses:

```python
# Gate checks (same as v1 path)
errors = []
if args.node == "L4":
    ok_m, m_reason = _audit_l4_methods(project_dir, args.cand_id, data)
    if not ok_m:
        errors.append(m_reason)
if args.node == "L6":
    ok_l6, l6_reason = _audit_l6_traceability(project_dir, args.cand_id, data)
    if not ok_l6:
        errors.append(l6_reason)
if args.node == "L7":
    ok_l7, l7_reason = _audit_l7_manifest(project_dir, args.cand_id, data)
    if not ok_l7:
        errors.append(l7_reason)
if args.node == "L10b":
    ok_l10, l10_reason = _audit_l10_traceability(project_dir, args.cand_id, data)
    if not ok_l10:
        errors.append(l10_reason)
    ok_evidence, evidence_reason = _audit_l10_evidence(project_dir, args.cand_id, data)
    if not ok_evidence:
        errors.append(evidence_reason)
if errors:
    print("DELTA V2 VALIDATION: REJECT", file=sys.stderr)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    return 1
```

Place gate checks AFTER `commit_delta` (which validates schema) but BEFORE
writing the artifact file. If gates fail, the ledger transaction has already
committed, but the emission is not finalized (no artifact, no marker), so it
becomes an orphan -- which Plan 1A's finalized predicate correctly hides from
consumptive reads. This is the correct behavior: a gate-rejected delta should
not be consumable.

### Step 3: Verification

```bash
python -m pytest tests/test_public_api_compat.py tests/test_no_cycles.py tests/test_engine_api.py -q
python -m pytest tests/test_hypothesis_ledger.py tests/test_ranking_cli.py tests/test_cross_round_e2e.py -q
python -m pytest tests/test_v06_divergence.py -q
python research_loop_v04.py --help
```

## Risks

| Risk | Mitigation |
| --- | --- |
| Gate check after commit_delta creates orphan on rejection | Plan 1A predicate hides orphans from consumptive reads; re-running emit-delta with corrected data creates a new finalized emission |
| Existing v2 tests don't expect gate calls | Gates are no-op for non-from_memory candidates; only from_memory + divergent candidates trigger gates |
| analysis_plan shape change breaks existing v1 code | Handle both dict and list; v1 path unchanged |

## Definition of Done

- `_emit_delta_v2` calls L4/L6/L7/L10b gates for the corresponding nodes
- `gates.py` handles both dict and list `analysis_plan`
- All existing tests pass
- `test_v06_divergence.py` still has the same pass/fail count (P1B will fix the tests)
