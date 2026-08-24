# L0.5 Curie → Einstein Phases 3–8 Design

## Goal

Complete the native L0 → L0.5 Curie → frozen EvidencePack → L1 Einstein evidence lifecycle without reintroducing hidden retrieval authority in Einstein. Extend Curie from the current Europe PMC vertical slice to multi-provider discovery, cognitive selection, PaperQA2-assisted retrieval, semantic verification, and a bounded evidence-gap loop.

## Architectural invariants

1. L0.5 remains a first-class staged phase but is not inserted into the status-bearing DAG. The status DAG remains L0 → L1.
2. Curie is the only evidence-acquisition authority. Einstein may consume only an immutable, validated frozen EvidencePack.
3. A frozen EvidencePack is content-addressed and immutable. Additional evidence creates a new version with `parent_pack_sha256`; an old pack is never mutated.
4. `EvidenceGapRequest` is the only authorized downstream-to-upstream request for additional evidence. Einstein may not call search providers, PaperQA2, or retrieval transports directly.
5. Evidence acquisition and evidence interpretation are separate authorities. Retriever output is never self-certified.
6. Provider-specific adapters normalize into one provider-neutral discovery record and one canonical paper identity layer.
7. Negative, ambiguous, and contradictory evidence must be preservable. Selector and verifier contracts may not force all evidence into supportive semantics.
8. Fail closed on malformed identity, provenance, source snapshots, hashes, version lineage, or authority violations.
9. The evidence-gap loop is bounded to three Curie acquisition rounds per ResearchSeed.
10. No legacy v2.0 data is silently admitted to the native v2.1 path.

## Delivery decomposition

### PR A — Phase 3 + Phase 8: native Curie → Einstein handoff and bounded gap loop

Replace the native v2.1 L1 binding dependency on a legacy Deep Research run with a direct binding to a frozen Curie EvidencePack. Keep legacy behavior only for historical v2.0 compatibility. Introduce an append-only native evidence binding that records ResearchSeed, exact frozen pack manifest, pack lineage, and acquisition run metadata without requiring `deep_research.evidence_artifact_manifest()`.

Add a bounded `EvidenceGapRequest` lifecycle. Einstein may emit a schema-validated request referencing the exact frozen pack hash. Curie may consume only an OPEN request whose candidate, round, seed hash, and parent pack hash match the active state. A retry creates EvidencePack v2/v3 with `parent_pack_sha256` and `source_gap_request_id`. Round 3 gaps terminate as `INSUFFICIENT_STOP`; no fourth acquisition round is authorized.

### PR B — Phase 4: provider-neutral multi-source discovery

Introduce provider-neutral discovery orchestration with adapters for Europe PMC, PubMed, OpenAlex, Crossref, and Semantic Scholar. Each adapter has deterministic request/response receipts and normalizes records into the same canonical discovery schema. Canonical identity merges DOI, PMID, PMCID, OpenAlex ID, Semantic Scholar corpus/paper ID, and Crossref DOI metadata without allowing conflicting stable identifiers to bridge distinct papers.

No provider-specific record may bypass canonicalization, selector decisions, retrieval verification, or EvidencePack provenance.

### PR C — Phase 5 + Phase 6: cognitive Selector and PaperQA2 retrieval/reranking

Upgrade Selector decisions to a versioned `SelectorDecision` contract containing at minimum:

- `paper_id`
- `decision` (`INCLUDE`, `EXCLUDE`, `RESERVE`)
- `relevance`
- `directness`
- `methodological_value`
- `contradiction_value`
- `evidence_diversity`
- `originating_query_ids`
- `reason`

Deterministic eligibility gates remain authoritative for hard exclusions. Cognitive scoring is advisory within valid candidates and must be fully persisted.

PaperQA2 is an optional retrieval/reranking backend under Curie. It may produce evidence candidates with source locators and provenance, but may not certify evidence, change candidate status, emit hypotheses, or bypass the independent verifier. Absence or failure of PaperQA2 must not silently degrade provenance; the runtime either uses another declared retrieval route or reports insufficient evidence.

### PR D — Phase 7 + integration hardening: semantic verifier and full-cycle validation

Add a semantic verification contract distinct from deterministic source fidelity. Deterministic verification first establishes exact source bytes, hash, locator, and text. Semantic verification then records:

- `evidence_id`
- `source_fidelity`
- `entailment`
- `scope_match`
- `context_preserved`
- `qualification_preserved`
- `verdict`
- `reason`

Only evidence that passes deterministic verification and satisfies the semantic policy is admitted as reasoning-authorized evidence. Ambiguous or contradictory content remains representable rather than coerced into support.

Full-cycle tests exercise ResearchSeed → multi-source Curie → frozen EP:v1 → Einstein → EvidenceGapRequest → Curie retry → EP:v2 → Einstein rerun, together with tamper, identity-conflict, missing-source, provider-failure, PaperQA2-failure, and max-round failure injection.

## Native evidence binding

The native v2.1 binding is an immutable receipt linking:

`ResearchSeed hash → frozen EvidencePack manifest → acquisition run identity → pack version/lineage`.

It must not require a legacy Deep Research run file. Loading the binding revalidates the on-disk frozen pack at the actual L1 use boundary.

For native v2.1, L1 context assembly reads the exact active native evidence binding and injects the corresponding frozen pack. It must not infer the active pack from directory order, newest mtime, or legacy pre-research summary text.

## Gap-loop state machine

1. Curie freezes EP:v1 after coverage PASS.
2. Einstein consumes only EP:v1.
3. If Einstein identifies a concrete evidence deficiency, it emits one OPEN `EvidenceGapRequest` bound to EP:v1.
4. Curie validates the request and executes the next acquisition round.
5. If coverage passes, Curie freezes EP:v2 with `parent_pack_sha256 = EP:v1 artifact/content lineage` and `source_gap_request_id`.
6. The native binding advances append-only to EP:v2; EP:v1 remains immutable and addressable.
7. Einstein reruns against EP:v2.
8. The same process may produce EP:v3. No EP:v4 is authorized for the same ResearchSeed.

A request does not itself change candidate workflow status. Status authority remains with the existing designated DAG decision nodes.

## Testing strategy

Each PR follows RED → GREEN. Targeted contract/runtime tests run first, followed by existing L0.5/L1 isolation tests and the full Windows Python 3.13 regression suite. PR D adds real external smoke where deterministic public endpoints are available and bounded failure-injection tests for non-deterministic integrations.

Completion requires no regression in legacy v2.0 compatibility behavior, no direct search/retrieval authority in Einstein, exact frozen-pack revalidation at L1 use, and a successful native full-cycle evidence-gap rerun.