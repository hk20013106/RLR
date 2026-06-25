# Layer 4 — Method Brainstorm

- **Phase:** 2 — Method Loop
- **Owner:** Fisher｜Design Architect
- **Status effect:** `IDEA_SELECTED` → (proposed via Oppenheimer) `METHOD_PROPOSED`

## Purpose

Turn a selected candidate into several analyzable designs and recommend the one
that best tests it — reusing existing skills/code where possible.

## Entry condition

Candidate is `IDEA_SELECTED`; preflight skill-use plan available.

## Activities

1. Propose multiple analysis plans (never a single default).
2. Define inputs, transformations, models, filters, traits, contrasts, outputs.
3. Check whether local skills/code already implement the workflow (reuse-first).
4. Identify the plan that best tests the candidate.

## Required outputs

- `method_options.md`
- `analysis_design.md`
- `required_inputs_for_execution.md`

## Exit condition

Methods proposed. Route to **L5 (Tukey)**.

## Forbidden

No execution, no single method without alternatives, no ignoring skill-use plan,
no overcomplicated design when a simpler diagnostic suffices.
