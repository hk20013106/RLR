# L6 — Final Method Selection and Analysis Plan

## Purpose

Select the executable method for every required L4 component after reading the complete L4 candidate catalog and all L5 critiques. L6 may approve one candidate or an explicit combined strategy; it must not collapse alternatives without an audit trail.

## Required selection for each component

Record in `selected_methods`:

- `component_id`;
- selected `method_id`, or an ordered list of method IDs for a combined strategy;
- decision rationale tied to the actual input and study design;
- rejected alternatives and specific reasons;
- final parameters and thresholds;
- software/package and version requirements;
- scripts required by L7;
- supporting method-anchor IDs;
- L5 QC requirements and stop rules that L7 must implement.

Every required component must have a selection. A candidate marked `needs_user_source` cannot be selected until its source has been registered, extracted, and accepted as a located method anchor.

## Reasoning boundary

- Require prespecified inputs, procedures, quality checks, outputs, and decision criteria.
- Prefer the simplest method that adequately answers the selected hypothesis.
- Treat executability as plan readiness, not evidence for the hypothesis.
- Keep the full L4 comparison record; do not rewrite history after selecting a method.

## Handoff

Only `selected_methods` and the approved `analysis_plan` become executable in L7. Reference raw Methods excerpts by anchor/evidence ID rather than copying large passages. Do not execute code, fabricate outputs, or select among scientific hypotheses.

## Full-mode role

The current dynamic contract is authoritative for inputs, output schema, state changes, and runtime commands.
