# DAG Topology — RLR V0.7

`research_loop/topology.py` is the executable source of truth for node order,
allowed inputs, personas, state transitions, and delta schemas. This document
is a reader-facing overview; it does not define commands or schemas.

RLR has 15 nodes. L9a and L9b run in parallel; L7 is the only execution node.
The current sequence is:

```
L0 -> L1 -> L2 -> L3 -> L4 -> L5 -> L6 -> L7 -> L8 -> L8.5
   -> { L9a || L9b } -> L10a -> L10b -> L10c
```

| Node | Persona | Responsibility | Formal effect |
| --- | --- | --- | --- |
| L0 | Linnaeus | Verify normalized input, dependencies, and capabilities | Stops on missing required inputs or dependencies |
| L1 | Einstein | Generate testable hypotheses from verified evidence | Hypothesis delta |
| L2 | Feynman | Falsify hypotheses and identify confounders | Critique delta |
| L3 | Oppenheimer | Triage candidate hypotheses | `triage-idea`; optional advisory ranking afterward |
| L4 | Fisher | Propose evidence-grounded methods | Method delta |
| L5 | Tukey | Falsify method assumptions and QC plan | Method critique |
| L6 | Oppenheimer | Approve, revise, or reject the analysis plan | `triage-method` |
| L7 | Turing | Execute only the approved plan in an isolated workspace | Execution artifact |
| L8 | Curie | Audit execution evidence and reproducibility | Evidence audit |
| L8.5 | Curie | Verify audited results against located literature evidence | Literature verification |
| L9a | Feynman | Falsify result-level claims | Parallel result critique |
| L9b | Darwin | Produce bounded biological interpretation | Parallel interpretation |
| L10a | Jobs | Assess scientific and practical value | Value assessment |
| L10b | Oppenheimer | Make the final formal decision | `KEEP` / `REVISE` / `DOWNGRADE` / `DROP`; optional advisory ranking afterward |
| L10c | Linnaeus | Aggregate the audit trail into final reports | Aggregate report |

## Evidence and isolation

- Before L1, L4, and L8.5, the Deep Research adapter obtains and validates a
  source-located evidence pack. L1 requires Results/Discussion/Conclusion;
  L4 requires primary-study Methods plus a review-search receipt; L8.5 checks
  result consistency with literature.
- Cognitive nodes receive only the context assembled for their allowed inputs.
  L7 alone receives a controlled execution workspace.
- L3 and L10b can emit ranking shadow artifacts after their own deltas are
  written. Ranking is advisory and never changes a formal transition.

## Template behavior

The default `contract` template mode injects the generated node contract. The
optional `full` mode additionally injects the node and persona templates from
`templates/layers/` and `templates/personas/`; these templates supplement the
contract and never replace its dynamic schema or runtime instructions.
