# Layer 6 — Analysis Plan Decision

- **Phase:** 2 — Method Loop
- **Owner:** Oppenheimer｜Cold Director
- **Status effect:** `METHOD_PROPOSED` → `METHOD_APPROVED` | `METHOD_REJECTED`

## Purpose

Approve exactly one analysis plan (or send it back). Only approved plans may
reach Execution — and only through the Execution Gate.

## Entry condition

L4 (Fisher) + L5 (Tukey) outputs present; candidate is `METHOD_PROPOSED`.

## Activities

1. Choose one plan; confirm it tests the candidate and respects QC/failure gates.
2. Record the approved plan (and `analysis_needed`) or reject with reasons.

## Required outputs

- `analysis_plan_decision.md`
- `05_Decision_Log/` entry

## Exit condition

- `METHOD_APPROVED` → **Execution Gate (L7 entry)**.
- `METHOD_REJECTED` → route back to **L4 (Fisher)**.

## Command

```
python research_loop_v02.py triage-method PROJECT_DIR CAND --decision approve|reject \
    --reason "..." [--analysis-needed "..."]
```

> After approval, the gate (`execution-gate`) is the only path to Turing.
