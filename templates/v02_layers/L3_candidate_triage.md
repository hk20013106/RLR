# Layer 3 — Candidate Triage Decision

- **Phase:** 1 — Idea Loop
- **Owner:** Oppenheimer｜Cold Director
- **Status effect:** `IDEA_PROPOSED` → `IDEA_SELECTED` | `IDEA_REJECTED`

## Purpose

Decide which candidate ideas are worth method design. Only selected candidates
move to the Method Loop.

## Entry condition

L1 (Einstein) + L2 (Feynman) outputs present; candidate is `IDEA_PROPOSED`.

## Activities

1. Weigh significance vs. testability vs. effort.
2. Select or reject each candidate, with a recorded reason.
3. Write the candidate triage decision artefact + decision-log entry.

## Required outputs

- `candidate_triage_decision.md`
- `05_Decision_Log/` entry

## Exit condition

- `IDEA_SELECTED` → route to **L4 (Fisher)**.
- `IDEA_REJECTED` → stop / archive.

## Command

```
python research_loop_v02.py triage-idea PROJECT_DIR CAND --decision select|reject --reason "..."
```
