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
python research_loop_v03.py execution-gate PROJECT_DIR CAND
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


---

## v0.3 DAG Dependencies

- **Node:** L7_turing (L7)
- **Persona:** Turing (isolated subagent)
- **Input deltas:** L6 delta, L0 delta, skill_plan (Path A workspace)
- **Isolated from:** L1-L5 history

In v0.3 this layer runs as an isolated subagent using **Path A** (workspace
isolation), not Path B. Turing receives the L6 and L0 deltas plus the preflight
files inside a dedicated `_turing_workspace_<ts>/` built by
`prepare-turing-workspace`, runs the approved scripts in `scripts/`, and
reads/writes only within that workspace. Turing is the one node that touches the
filesystem; all cognitive nodes use Path B. It emits a single delta JSON instead
of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Turing/L7_turing_delta.json`:

```json
{
  "scripts_run": [{"name": str, "exit_code": int, "output_files": list}],
  "key_results": dict,
  "warnings": list,
  "failures": list
}
```