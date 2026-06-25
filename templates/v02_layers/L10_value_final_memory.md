# Layer 10 — Value + Final Decision + Memory Integration

- **Phase:** 4 — Result Review Loop
- **Owners:** Jobs｜Story Strategist (value) → Oppenheimer｜Cold Director (final) → Linnaeus｜Catalog Master (memory)
- **Status effect:** `UNDER_REVIEW` → `KEEP | REVISE | DOWNGRADE | DROP | ARCHIVED`

## Purpose

Decide the manuscript value, make the final decision, and integrate everything
into project memory / Obsidian.

## Entry condition

Curie (L8) support level + Feynman/Darwin (L9) outputs present.

## Activities — Jobs

1. Evaluate value given evidence + falsification + biology.
2. Choose position: main figure / supplementary / discussion hypothesis / archive.
3. Suggest figure logic and writing direction without overstating.

## Activities — Oppenheimer

1. Make the final decision (no KEEP without Curie's audit).
2. Write `final_decision.md` + decision-log entry.

## Activities — Linnaeus

1. Sync candidate state, decisions, handoffs, output manifests to Obsidian.

## Required outputs

- `value_assessment.md`, `manuscript_position.md`, `figure_priority.md`,
  `writing_direction.md` (Jobs)
- `final_decision.md` (Oppenheimer)
- `07_Obsidian_Sync/00_Obsidian_Index.md` (Linnaeus)

## Commands

```
python research_loop_v02.py decision PROJECT_DIR CAND --status KEEP --reason "..." --route Linnaeus
python research_loop_v02.py obsidian-sync PROJECT_DIR
```

## Forbidden

Jobs: no inflating weak evidence, no overriding Curie/Darwin, no final status.
Oppenheimer: no KEEP without evidence audit.
