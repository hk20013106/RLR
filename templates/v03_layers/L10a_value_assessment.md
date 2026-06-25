# Layer L10a - Value Assessment (Jobs)

- **Phase:** 4 - Result Review Loop
- **Owner:** Jobs | Story Strategist
- **Status effect:** none (Oppenheimer decides at L10b)

## Purpose

Evaluate manuscript value given evidence + falsification + biology, and frame
the writing direction without overstating.

## DAG dependencies (v0.3)

- candidate_frontmatter (read-only anchor)
- L8_curie_delta.json
- L9a_feynman_delta.json
- L9b_darwin_delta.json

**Isolated from:** L10b and beyond.

## Delta output

Emits `02_Agent_Notes/Jobs/L10a_jobs_delta.json`:

```json
{
  "value_assessment": str,
  "headline": str,
  "publishable_now": list,
  "needs_more_work": list,
  "manuscript_framing": str
}
```

## Exit condition

Value + framing recorded. Route to L10b (Oppenheimer).

## Forbidden

No inflating weak evidence, no overriding Curie/Darwin, no final status.
