# L5 — Method Candidate Falsification

## Purpose

Critique every eligible L4 method candidate before any final method is selected. L5 must preserve the candidate catalog and bind each critique to a stable `method_id` and `component_id`.

## Required review for each candidate

Record:

- `method_id` and `component_id`;
- verdict: `ACCEPT`, `MODIFY`, or `REJECT`;
- compatibility with the actual input type and data representation;
- violated or fragile assumptions;
- threats from sample structure, measurement limits, leakage, confounding, and implementation choices;
- required EDA/QC diagnostics;
- failure modes and explicit stop rules;
- required modifications;
- whether a proposed alternative should replace or supplement the candidate.

Do not silently omit, merge, or delete an L4 candidate. An ineligible L4 candidate may be acknowledged briefly with its existing rejection reason; every eligible candidate requires an explicit critique.

## Evidence boundary

Use L4 method-anchor IDs to verify what the source actually supports. Do not treat a citation as proof that the method fits this project. Distinguish:

- evidence that a method exists or has been used;
- evidence that it is reproducible;
- evidence that its assumptions fit the current data;
- evidence that it is preferable to alternatives.

## Handoff

Return `method_critiques`, QC checkpoints, failure stop rules, and recommended modifications for L6. Do not approve execution, change candidate state, or claim an analysis result.

## Full-mode role

The current dynamic contract is authoritative for inputs, output schema, state changes, and runtime commands.
