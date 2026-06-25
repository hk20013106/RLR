# DAG Topology - Research Loop Room v0.3

This document is the canonical reference for the v0.3 subagent DAG. There are
14 nodes (L0-L10c). L9a/L9b run in parallel; L7 is the only execution node.

Each node is executed by a separate subagent with physical context isolation
(Path B for cognitive agents; Path A workspace isolation for Turing). A
subagent sees ONLY the delta files listed in its "Input Files" column. Anything
not listed is physically absent from its context.

## Topology table

| Node | Persona | Input Files | Isolated From | Output |
| ---- | ------- | ----------- | ------------- | ------ |
| L0 | Linnaeus | AGENTS.md, skills_inventory, data paths | all exec notes | L0_linnaeus_delta.json |
| L1 | Einstein | candidate_frontmatter, L0 delta | L2+ | L1_einstein_delta.json |
| L2 | Feynman | candidate_frontmatter, L1 delta | L3+ | L2_feynman_delta.json |
| L3 | Oppenheimer | L1 delta, L2 delta | L4+ | L3_oppenheimer_delta.json |
| L4 | Fisher | L1 delta, L3 delta, L2 delta | L5+ | L4_fisher_delta.json |
| L5 | Tukey | L4 delta, L2 delta (ref) | L6+ | L5_tukey_delta.json |
| L6 | Oppenheimer | L4 delta, L5 delta | L7+ | L6_oppenheimer_delta.json |
| L7 | Turing | L6 delta, L0 delta, skill_plan (Path A) | L1-L5 history | L7_turing_delta.json |
| L8 | Curie | L7 delta, L6 delta, candidate_frontmatter | L9+ | L8_curie_delta.json |
| L9a | Feynman (2nd) | L1 delta, L7 delta, L8 delta | L9b, L10 | L9a_feynman_delta.json |
| L9b | Darwin (2nd) | L1 delta, L7 delta, L8 delta | L9a, L10 | L9b_darwin_delta.json |
| L10a | Jobs | candidate_frontmatter, L8, L9a, L9b deltas | L10b+ | L10a_jobs_delta.json |
| L10b | Oppenheimer (3rd) | L10a, L8, L9a, L9b deltas | - | L10b_oppenheimer_delta.json |
| L10c | Linnaeus (2nd) | ALL delta files | - | FINAL_REPORT.md + FINAL_REPORT_CN.md |

## DAG order

```
L0 -> L1 -> L2 -> L3 -> L4 -> L5 -> L6 -> L7 -> L8
     -> { L9a || L9b } -> L10a -> L10b -> L10c
```

## Notes

- "candidate_frontmatter" = stripped YAML metadata (candidate_id, title,
  question, claim). The candidate body is never passed to subagents.
- L2 Feynman and L9a Feynman are DIFFERENT subagent instances. Same persona,
  independent context. L9a does not see L2's note.
- L3/L6/L10b Oppenheimer are also separate instances.
- L7 Turing is the only node using Path A (workspace + command allowlist). All
  others use Path B (context embedded as text; no filesystem access).
- Delta files live at `02_Agent_Notes/<persona>/<node>_<persona>_delta.json`.
- Terminal status reached after L10c (report generated). Statuses KEEP/DROP/
  ARCHIVED end the loop earlier if set by L10b.
