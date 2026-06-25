# Layer 5 — Method Falsification / Skill Match

- **Phase:** 2 — Method Loop
- **Owner:** Tukey｜EDA Scout
- **Status effect:** none (Tukey attacks; Oppenheimer decides at L6)

## Purpose

Attack proposed methods and define QC/failure gates before execution, so the run
cannot spiral into ad-hoc debugging.

## Entry condition

L4 method options exist; candidate is `METHOD_PROPOSED`.

## Activities

1. Attack each method; check it does not needlessly repeat existing work.
2. Inspect data realities: sample size, grouping, missingness, outliers,
   confounders (batch, sex, animal_id, species/chamber).
3. Decide whether scripts should be modularized.
4. Define QC checkpoints and failure-stop rules (max 2 retries/method).

## Required outputs

- `method_falsification.md`
- `qc_checkpoints.md`
- `failure_stop_rules.md`

## Exit condition

QC + failure gates defined. Route to **L6 (Oppenheimer)**.

## Forbidden

No final decision, no manuscript conclusion, no retry loop without strategy change.


---

## v0.3 DAG Dependencies

- **Node:** L5_tukey (L5)
- **Persona:** Tukey (isolated subagent)
- **Input deltas:** L4 delta, L2 delta (reference)
- **Isolated from:** L6 and beyond

In v0.3 this layer runs as a subagent that receives only the deltas above
as embedded context (Path B). It does not access the filesystem. It emits a
single delta JSON instead of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Tukey/L5_tukey_delta.json`:

```json
{
  "attacks": [{"target": str, "severity": str, "text": str}],
  "qc_checkpoints": [{"name": str, "text": str}],
  "failure_stop_rules": [{"name": str, "text": str}]
}
```