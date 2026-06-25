# Layer 7 — Execution

- **Phase:** 3 — Execution
- **Owner:** Turing｜Execution Engine (the only persona who runs code)
- **Status effect:** `METHOD_APPROVED` → `NEEDS_EXECUTION` (gate) → `EXECUTED`

## Execution Gate (hard)

Execution is **REJECTED** unless all of:

1. `00_Preflight/skill_use_plan.md` exists,
2. `00_Preflight/input_manifest.md` exists,
3. the candidate holds an approved plan (status `METHOD_APPROVED`).

```
python research_loop_v02.py execution-gate PROJECT_DIR CAND
```

On PASS the candidate advances to `NEEDS_EXECUTION` and is handed to Turing.

## Purpose

Execute only the approved plan, reusing skills/code, in modular scripts with
checkpoints, and report exactly what happened.

## Activities

1. Read skill_use_plan, input_manifest, approved plan, qc_checkpoints.
2. Reuse existing skills/code patterns; write modular scripts.
3. Run; generate checkpoints, logs, figures, tables.
4. Update the output manifest.

## Required outputs

- `scripts/`, `results/`
- `execution_report.md`
- `crash_log.md`
- `output_manifest_update.md`

## Exit condition

- Success → Oppenheimer sets `EXECUTED`; route to **L8 (Curie)**.
- Failure → write crash log + failure report; route back to **Oppenheimer**.

## Forbidden

No scientific conclusion, no status change, no modifying raw inputs, no
from-scratch when a skill exists, no monolithic scripts, no >2 retries of the
same failed method (escalate / hand off instead).
