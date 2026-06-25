# Layer L9a - Result Falsification (Feynman, second instance)

- **Phase:** 4 - Result Review Loop (parallel with L9b)
- **Owner:** Feynman | Reality Checker (separate subagent instance from L2)
- **Parallel:** runs in parallel with L9b (Darwin); neither sees the other's output

## Purpose

Attack the completed result for hidden confounders, false positives, and
falsification risks. This is a second, independent Feynman instance - it does
NOT inherit L2's earlier note.

## DAG dependencies (v0.3)

- L1_einstein_delta.json
- L7_turing_delta.json
- L8_curie_delta.json
- candidate_frontmatter (read-only anchor)

**Isolated from:** L9b (Darwin), L2 history, L10.

## Delta output

Emits `02_Agent_Notes/Feynman/L9a_feynman_delta.json`:

```json
{
  "falsification_risks": [{"name": str, "severity": str, "resolvable": bool, "text": str}],
  "survives": list,
  "falsified": list
}
```

## Exit condition

Falsification recorded. Route to L10a (Jobs).

## Forbidden

No veto, no vague criticism, no status change.
