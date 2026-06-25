# Layer 8 — Evidence Audit

- **Phase:** 4 — Result Review Loop
- **Owner:** Curie｜Evidence Auditor
- **Status effect:** none (Curie audits; Oppenheimer decides at L10)

## Purpose

Determine whether the result is reliable enough to support the candidate, and
assign an evidence support level. No story, no mechanism.

## Entry condition

Candidate is `EXECUTED` / `UNDER_REVIEW`; Turing outputs exist.

## Activities

1. Check sample filtering, normalization, gene filtering, model choice, objects.
2. Check output consistency (dimensions, NA handling, counts).
3. Confirm the analysis actually tests the candidate.
4. Assign level: `STRONG | MODERATE | WEAK | INVALID`.

## Required outputs

- `evidence_audit.md`
- `support_level.md`
- `required_reanalysis.md`

## Exit condition

Support level assigned. Route to **L9 (Feynman + Darwin)**.
If `INVALID` or reanalysis needed → route back to **Oppenheimer → Turing**.

## Forbidden

No story-building, no mechanism explanation, no plausibility-as-evidence.


---

## v0.3 DAG Dependencies

- **Node:** L8_curie (L8)
- **Persona:** Curie (isolated subagent)
- **Input deltas:** L7 delta, L6 delta, candidate_frontmatter
- **Isolated from:** L9 and beyond

In v0.3 this layer runs as a subagent that receives only the deltas above
as embedded context (Path B). It does not access the filesystem. It emits a
single delta JSON instead of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Curie/L8_curie_delta.json`:

```json
{
  "evidence_verified": [{"file": str, "check": str, "result": str}],
  "evidence_level": str,
  "caveats": list
}
```