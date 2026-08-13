# L0 — Skill, State & Data Preflight

## Purpose

Establish an auditable starting state before scientific reasoning begins. Verify required capabilities and the authoritative `l0_input` declaration, restore exact prior-round evidence when this is a continuation, and freeze the current round's scientific-data authorization before downstream use.

## Reasoning boundary

- Verify declared current inputs and prior evidence without inferring scientific meaning.
- For continuation rounds, restore the frozen previous-round manifest and verify only explicitly selected inherited path/SHA references.
- Treat `CurrentRoundDataBinding` as the deterministic current-round authorization projection; do not create a parallel data registry.
- Do not treat `input_manifest.md`, `input_alias`, or prose descriptions as machine authorization for scientific data.
- Distinguish an unavailable dependency from an unverified one; do not silently substitute either.
- Keep provenance compact and reproducible so downstream layers can identify what was actually available.

## Handoff

Hand forward the verified preflight/state record, explicit blockers, approved capabilities, and the frozen current-round data binding. Do not create hypotheses, decisions, execution outputs, or status claims.

## Full-mode role

This text supplements the current dynamic contract. The contract defines the authoritative inputs, outputs, schemas, state transitions, and commands for this run.
