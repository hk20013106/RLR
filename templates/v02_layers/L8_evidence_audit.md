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
