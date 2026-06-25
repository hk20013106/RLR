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
python research_loop_v03.py triage-method PROJECT_DIR CAND --decision approve|reject \
    --reason "..." [--analysis-needed "..."]
```

> After approval, the gate (`execution-gate`) is the only path to Turing.


---

## v0.3 DAG Dependencies

- **Node:** L6_oppenheimer (L6)
- **Persona:** Oppenheimer (isolated subagent)
- **Input deltas:** L4 delta, L5 delta
- **Isolated from:** L7 and beyond

In v0.3 this layer runs as a subagent that receives only the deltas above
as embedded context (Path B). It does not access the filesystem. It emits a
single delta JSON instead of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Oppenheimer/L6_oppenheimer_delta.json`:

```json
{
  "approved_strategy": str,
  "modifications": list,
  "reason": str,
  "analysis_plan": {"scripts": list, "parameters": dict, "outputs": list}
}
```