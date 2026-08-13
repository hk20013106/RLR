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
| L0 | Linnaeus | Verify current input/readiness, restore prior-round evidence, and freeze the current-round scientific-data authorization | Fails closed on blocking readiness/input/restore/data-binding errors |
| L1 | Einstein | Generate testable hypotheses from verified evidence | Hypothesis delta |
| L2 | Feynman | Falsify hypotheses and identify confounders | Critique delta |
| L3 | Oppenheimer | Triage candidate hypotheses | `triage-idea`; optional advisory ranking afterward |
| L4 | Fisher | Propose evidence-grounded methods | Method delta |
| L5 | Tukey | Falsify method assumptions and QC plan | Method critique |
| L6 | Oppenheimer | Approve, revise, or reject the analysis plan | `triage-method` |
| L7 | Turing | Execute only the approved plan against data staged from the verified current-round binding | Execution artifact |
| L8 | Tukey (native v2.1) / Curie (historical) | Audit execution evidence and reproducibility | Evidence audit |
| L8.5 | Curie | Verify audited results against located literature evidence | Literature verification |
| L9a | Feynman | Falsify result-level claims | Native serial first stage |
| L9b | Darwin | Produce bounded biological interpretation | Native serial stage; authorized finalized L9a snapshot only |
| L10a | Jobs | Assess scientific and practical value | Value assessment |
| L10b | Oppenheimer | Make the final formal decision | `KEEP` / `REVISE` / `DOWNGRADE` / `DROP`; optional advisory ranking afterward |
| L10c | Linnaeus | Aggregate reports, complete required Obsidian projection, then freeze round evidence | Round finalization boundary |

## L0 pre-flight + state restore + current-round data binding

The formal DAG still contains one `L0` node. Its internal work is deterministic
and split by responsibility rather than by additional DAG nodes:

```
current machine/project                    previous round
        |                                        |
        v                                        v
component pre-flight                    round manifest restore
                                                 |
                                                 v
                                        L0EvidenceBinding
                                                 |
current l0_input declaration -------------------+-- selected inherited_inputs
        |                                        |
        +-------------------+--------------------+
                            v
                 CurrentRoundDataBinding
                            |
                  +---------+---------+
                  |                   |
                  v                   v
            cognitive DAG        L7 staging gate
                                      |
                                      v
                              Turing workspace
```

The two bindings have different jobs and are not competing registries.
`L0EvidenceBinding/v1` represents the verified previous-round evidence universe
for a continuation. `CurrentRoundDataBinding/v1` is the exact, deterministic
projection of scientific inputs authorized for the current round: selected
verified inherited artifacts plus current `l0_input` declarations. Only the
current-round binding is execution authority for L7.

`l0_input.yaml` remains the declaration authority. Native writers emit schema
1.1 so continuation rounds can carry explicit `inherited_inputs`; historical
1.0 contracts remain readable. Inherited selectors are exact path + SHA-256
references and may target only prior `source`, `intermediate`, or `result`
artifacts. Literature, audit, and receipt artifacts cannot silently become
scientific inputs.

Current local files are also hash-bound. Legal non-file declarations such as a
remote dataset or inline/other source remain representable in the current-round
binding, but they do not become executable files. L7 requires scientific data
to be materialized as verified local files before execution.

`00_Preflight/input_manifest.md` may remain as a human-facing/preflight
projection for existing project layouts, but it is not a machine authorization
source. `input_alias` likewise does not grant access. L7 never expands authority
from either of them, and an explicit `--file` may only refer to a file already
present in `CurrentRoundDataBinding`; it cannot add a new scientific input.

Before creating a Turing workspace, L7 revalidates the current binding, the L0
contract hash, any bound previous-evidence receipt, and each authorized file's
path/SHA. A changed or missing bound input fails closed before a workspace is
created. The workspace receives only those verified files plus the DAG-allowed
plan/support artifacts.

Framework-owned static/service probes have one authority,
`research_loop/l0_preflight.py`. Current blocking probes correspond to real
consumers: core Python/packages and filesystem, Academic Research, the
hypothesis ledger, the evidence store, and Obsidian. PubMed MCP and Zotero are
reported as readiness-only until the planned literature-transport and
reference-management consumers are actually wired; they are not heavy base
dependencies in this PR. Provider/main-agent readiness is runner-bound because
the active runner config is known only at invocation time. L7 workspace/runtime
checks remain deferred to the existing L7 execution gate.

For continuation rounds, L0 restores the prior physical evidence state from
`RLRRoundEvidenceManifest/v1`, verifies manifest identity/hash and every
registered artifact path/hash, and writes `L0EvidenceBinding/v1`. It then
verifies the continuation's selected `inherited_inputs` together with any new
current-round source declaration and freezes `CurrentRoundDataBinding/v1`.
Initial rounds skip previous-round restore but still freeze the same
current-round binding before downstream use.

Evidence is immutable by registered path + SHA-256 rather than by copying large
scientific files. Round manifests use explicit sources only: the L0 source
contract, L7 execution outputs, explicit L7 result artifact refs,
candidate-scoped reports, candidate-owned literature evidence, candidate
delta/audit artifacts, and runtime receipts. No broad directory scan silently
invents inherited evidence.

L10c is the single round-finalization owner: it generates candidate-scoped
reports, completes the required Obsidian projection, and freezes the round
manifest only after projection succeeds. `emit-loop-memory` owns semantic
continuation state only; it consumes and verifies the already-frozen manifest
and records its path/hash. It never creates a replacement manifest.

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
an explicit consumer boundary; a planned adapter is not made a blocking base
dependency before that consumer exists.

## Evidence and isolation

- Before L1, L4, and L8.5, the Deep Research adapter obtains and validates a
  source-located evidence pack. L1 requires Results/Discussion/Conclusion;
  staged L4 binds a metadata discovery manifest to primary-study Methods and a
  review-search receipt; L8.5 checks result consistency with literature.
- Cognitive nodes receive only the context assembled for their allowed inputs.
  L7 alone receives a controlled execution workspace.
- Cross-round physical evidence is exposed only after L0 verifies the prior
  manifest. Current-round scientific-data permission is narrower: only items
  selected into `CurrentRoundDataBinding` are authorized for execution.
  Cognitive nodes do not independently walk previous-round directories.
- L3 and L10b can emit ranking shadow artifacts after their own deltas are
  written. Ranking is advisory and never changes a formal transition.

## Template behavior

The default `contract` template mode injects the generated node contract. The
optional `full` mode additionally injects the node and persona templates from
`templates/layers/` and `templates/personas/`; these templates supplement the
contract and never replace its dynamic schema or runtime instructions.