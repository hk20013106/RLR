# Layer 1 — Idea Divergence

- **Phase:** 1 — Idea Loop
- **Owner:** Einstein｜Conceptual Explorer
- **Status effect:** candidate `NEW` → (proposed via Oppenheimer) `IDEA_PROPOSED`

## Purpose

Generate multiple candidate questions/hypotheses and, for each, state why it
matters and what data could test it.

## Entry condition

L0 complete (preflight files exist).

## Activities

1. Read project context, prior results, memory index.
2. Use academic/deep-research skills where available.
3. Produce several candidate questions/hypotheses (divergent, not one).
4. For each: significance + what data could test it.

## Required outputs

- `candidate_questions.md`
- `hypothesis_options.md`
- `research_context.md`

## Exit condition

Candidates framed and testable. Route to **L2 (Feynman)**.

## Forbidden

No decision, no execution, no publishability claim, no literature-as-evidence.


---

## v0.3 DAG Dependencies

- **Node:** L1_einstein (L1)
- **Persona:** Einstein (isolated subagent)
- **Input deltas:** candidate_frontmatter, L0 delta
- **Isolated from:** L2 and beyond

In v0.3 this layer runs as a subagent that receives only the deltas above
as embedded context (Path B). It does not access the filesystem. It emits a
single delta JSON instead of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Einstein/L1_einstein_delta.json`:

```json
{
  "hypotheses": [{"id": str, "text": str, "testable": bool, "rationale": str}],
  "key_uncertainty": str,
  "primary_hypothesis": str
}
```