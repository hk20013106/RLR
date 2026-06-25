# Layer L9b - Biology Interpretation (Darwin, separate instance)

- **Phase:** 4 - Result Review Loop (parallel with L9a)
- **Owner:** Darwin | Evolutionary Biologist (separate subagent instance)
- **Parallel:** runs in parallel with L9a (Feynman); neither sees the other's output

## Purpose

Interpret modules/pathways/tissues/species patterns biologically without
overreaching. Separate correlation, mechanism, adaptation, speculation.

## DAG dependencies (v0.3)

- L1_einstein_delta.json
- L7_turing_delta.json
- L8_curie_delta.json
- candidate_frontmatter (read-only anchor)

**Isolated from:** L9a (Feynman), L10.

## Delta output

Emits `02_Agent_Notes/Darwin/L9b_darwin_delta.json`:

```json
{
  "module_interpretations": [{"module": str, "meaning": str, "genes": list, "evidence": str}],
  "convergent_evolution": str,
  "limitations": list
}
```

## Exit condition

Biology interpretation recorded. Route to L10a (Jobs).

## Forbidden

No causation from correlation, no adaptation claim without adequate evidence,
no enrichment-as-mechanism, no replacing the evidence audit.
