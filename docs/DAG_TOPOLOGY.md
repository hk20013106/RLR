# DAG Topology — RLR V0.9

`research_loop/topology.py` is the executable source of truth for node order,
allowed inputs, personas, state transitions, and delta schemas. This document
is a reader-facing overview; it does not define commands or schemas.

RLR has 15 formal nodes and L7 is the only execution node. Native v2.1 projects
use the current sequence below; historical v2.0 projects retain parallel
L9a/L9b.

```
L0 -> L1 -> L2 -> L3 -> L4 -> L5 -> L6 -> L7 -> L8 -> L8.5
   -> L9a -> finalized L9a snapshot -> L9b -> L10a -> L10b -> L10c
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
| L8 | Tukey (native v2.1) / Curie (historical) | Audit execution evidence and reproducibility | Evidence audit |
| L8.5 | Curie | Verify audited results against located literature evidence | Literature verification |
| L9a | Feynman | Falsify result-level claims | Native serial first stage |
| L9b | Darwin | Produce bounded biological interpretation | Native serial stage; authorized finalized L9a snapshot only |
| L10a | Jobs | Assess scientific and practical value | Value assessment |
| L10b | Oppenheimer | Make the final formal decision | `KEEP` / `REVISE` / `DOWNGRADE` / `DROP`; optional advisory ranking afterward |
| L10c | Linnaeus | Aggregate the audit trail into final reports | Aggregate report |

## Internal L4 method-planning pipeline

The formal DAG still contains one `L4` node and retains the `L4_fisher` storage
key. Internally, L4 is divided into four auditable stages:

```
L3 selected hypotheses
        |
        v
L4A Literature Discovery
        |  L4ADiscoveryManifest/v1
        v
L4B Evidence Construction
        |  existing strict ARS method-evidence pack
        v
L4C Fisher Method Design
        |  L4_fisher delta
        v
L4.5 Deterministic Commit
        |
        v
L5 Tukey
```

- **L4A** performs query planning, metadata discovery, identifier-first
  deduplication, relevance selection, and full-text availability recording. It
  is metadata-only and cannot create method anchors.
- **L4B** consumes the frozen L4A selection and delegates full-text retrieval,
  Methods extraction, source-payload retention, anchor verification, and method
  candidate construction to the existing Academic Research Skills and RLR
  method-evidence stack.
- **L4C** is the existing Fisher cognitive node. It retains the formal
  `L4_fisher` delta and the existing state transition to `METHOD_PROPOSED`.
- **L4.5** is deterministic and non-cognitive. It revalidates the exact L4A
  manifest, L4B evidence files, and persisted L4C delta hash before committing
  the method projection. A failure aborts the native L4 persistence boundary.

L4A, L4B, L4C, and L4.5 do not add formal DAG nodes, do not introduce L3.5,
and do not renumber L5-L10.

## Reuse-first adapter boundary

RLR does not reimplement mature retrieval and parsing systems. Academic
Research Skills, the existing `deep_research.py` runtime, method evidence
validators, registered user sources, context manifests, and the hypothesis
ledger remain the default implementation. Literature-search MCP, Zotero,
GROBID, Docling, PaperQA2, or another parser/retriever may be attached behind
L4A or L4B adapters; none is required as a heavy base dependency.

## Evidence and isolation

- Before L1, L4, and L8.5, the Deep Research adapter obtains and validates a
  source-located evidence pack. L1 requires Results/Discussion/Conclusion;
  staged L4 binds a metadata discovery manifest to primary-study Methods and a
  review-search receipt; L8.5 checks result consistency with literature.
- Cognitive nodes receive only the context assembled for their allowed inputs.
  L7 alone receives a controlled execution workspace.
- L3 and L10b can emit ranking shadow artifacts after their own deltas are
  written. Ranking is advisory and never changes a formal transition.

## Template behavior

The default `contract` template mode injects the generated node contract. The
optional `full` mode additionally injects the node and persona templates from
`templates/layers/` and `templates/personas/`; these templates supplement the
contract and never replace its dynamic schema or runtime instructions.
