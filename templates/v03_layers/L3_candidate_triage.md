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
python research_loop_v03.py triage-idea PROJECT_DIR CAND --decision select|reject --reason "..."
```


---

## v0.3 DAG Dependencies

- **Node:** L3_oppenheimer (L3)
- **Persona:** Oppenheimer (isolated subagent)
- **Input deltas:** L1 delta, L2 delta
- **Isolated from:** L4 and beyond

In v0.3 this layer runs as a subagent that receives only the deltas above
as embedded context (Path B). It does not access the filesystem. It emits a
single delta JSON instead of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Oppenheimer/L3_oppenheimer_delta.json`:

```json
{
  "selected": list,
  "rejected": list,
  "reason": str,
  "route_to": str
}
```