# Layer 2 — Idea Falsification

- **Phase:** 1 — Idea Loop
- **Owner:** Feynman｜Reality Checker
- **Status effect:** none (Feynman attacks; Oppenheimer decides at L3)

## Purpose

Attack each candidate idea before any effort is spent. Determine whether it is
testable with current/plannable data, and surface circular reasoning, vague
claims, unfalsifiable hypotheses, and overfitting risk.

## Entry condition

L1 candidates exist (`candidate_questions.md`, `hypothesis_options.md`).

## Activities

1. For each candidate: is it testable with current data? How?
2. Identify circular reasoning / unfalsifiable framing / overfitting.
3. Propose a concrete diagnostic for every criticism (no vague attacks).

## Required outputs

- `idea_falsification.md`
- `diagnostic_tests_requested.md`

## Exit condition

Each candidate has a verdict + diagnostic. Route to **L3 (Oppenheimer)**.

## Forbidden

No veto, no vague criticism without a diagnostic, no direct code execution.


---

## v0.3 DAG Dependencies

- **Node:** L2_feynman (L2)
- **Persona:** Feynman (isolated subagent)
- **Input deltas:** candidate_frontmatter, L1 delta
- **Isolated from:** L3 and beyond

In v0.3 this layer runs as a subagent that receives only the deltas above
as embedded context (Path B). It does not access the filesystem. It emits a
single delta JSON instead of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Feynman/L2_feynman_delta.json`:

```json
{
  "attacks": [{"hypothesis_id": str, "severity": str, "text": str}],
  "confounders": [{"name": str, "severity": str, "text": str}],
  "diagnostic_tests": [{"name": str, "text": str}],
  "verdict": str
}
```