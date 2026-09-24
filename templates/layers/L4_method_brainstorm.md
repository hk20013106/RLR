# L4 — Fisher Method Design

## Purpose

Design a comparison pool of feasible analysis or experimental methods for the selected hypotheses. L4C/Fisher does not approve the final method: L5 critiques candidates and L6 selects the executable strategy.

The authorized L4 evidence context now contains:

- a method inventory produced by L4A;
- accepted `evidence_cards` produced deterministically by L4B;
- unresolved `evidence_gaps` produced deterministically by L4B.

L4B has not defined method components, candidates, eligibility, or required execution paths. Those judgments belong here.

## Required structure

Define the method components needed by the study. For every serious method candidate, state:

1. stable `method_id` and the component/hypotheses addressed;
2. analytical purpose;
3. required input type and data representation;
4. prerequisites and main implementation steps;
5. statistical, biological, and computational assumptions;
6. expected outputs;
7. strengths for this project;
8. limitations and failure modes;
9. feasible alternatives;
10. status — one of the four decision outcomes defined by the live provider
    schema (`eligible`, `ineligible`, `needs_user_source`, `needs_user_data`);
11. `execution_required`: whether this candidate is a Fisher-declared implementation path needed to cover a required component;
12. `evidence_card_handles` (for example `E1`) supporting the candidate;
13. `evidence_gap_handles` (for example `G1`) relevant to the candidate;
14. `method_anchor_handles` (for example `A1`) when available.

The authorized L4B context gives local reference handles. Use only those
handles; the `emit-delta` commit boundary deterministically binds them to
canonical evidence IDs.
Always provide all three handle arrays, using `[]` when none applies.

A method name plus a citation is not a sufficient method description.

## Evidence boundary

- Treat only an L4B card with `status: accepted` as strong method evidence.
- An evidence gap is not an anchor and must never be presented as accepted evidence.
- An eligible candidate with `execution_required: true` must reference at least one accepted evidence card.
- Optional alternatives may remain in the comparison catalog without an accepted card, but their evidence gaps and limitations must be explicit.
- Do not mark every plausible alternative as execution-required.
- Reviews, abstracts, table mentions, placeholders, and unlocated summaries do not become method evidence merely because they are relevant.
- Keep raw excerpts in the evidence store and reference card/anchor IDs instead of copying large passages into the method plan.

## Source-blocked candidates

Use `needs_user_source` only when a genuinely necessary candidate cannot be audited from the exact sources already attempted by L4B. State which evidence gap or legally obtained local source is needed. Registration alone never satisfies the gate; a later L4B run must produce an accepted evidence card.

## Data-blocked candidates

Use `needs_user_data` only when an otherwise executable candidate lacks required user data (inputs, measurements, or annotations not present in the authorized data binding). List every unavailable input in `missing_inputs`.

`needs_user_source` and `needs_user_data` are orthogonal blockers: the first means exact method evidence is missing, the second means executable data is missing. A candidate may carry both when both hold; a source-blocked candidate must never carry `missing_inputs` (that conflation belongs to `needs_user_data`). The live provider schema is authoritative for the exact fields each status requires.

## Handoff

Provide the complete candidate catalog and evidence references for L5. Do not silently delete alternatives, approve a final plan, run code, or imply that a proposed method has succeeded.

## Full-mode role

The current dynamic contract is authoritative for inputs, output schema, state changes, and runtime commands.
