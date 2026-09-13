# English Literature Query Boundary Design

## Goal

Allow RLR scientific semantics (ResearchSeed, method descriptions, L7/L8 findings) to remain in any language while guaranteeing that every retrieval string sent to English literature systems is validated English scientific text.

## Confirmed native-v2.1 problem surface

1. L0.5 default scientific query planning is project-specific and can lose non-English semantics.
2. L0.5 Europe PMC candidate ranking reuses raw ResearchSeed text against English titles/abstracts.
3. L0.5 PaperQA2 retrieval re-injects raw ResearchSeed text after English discovery.
4. L4A SPECTER2 ranking re-injects method name/purpose/inventory text instead of reusing the validated contextual query.
5. L4B PaperQA2 retrieval can fall back to a non-English method purpose/name.
6. L8.5 derives queries with an ASCII-token regex, dropping non-English finding semantics.

No seventh native-v2.1 literature retrieval/ranking boundary was found in the final audit.

## Architecture

- Keep scientific semantic text in its original language.
- Add one shared English retrieval-query contract in Curie contracts. It validates language only; it does not own retrieval, identity, evidence, or model invocation.
- Keep stage-specific semantic planning:
  - L0.5 plans scientific-question queries.
  - L4A keeps its existing method-first contextual planner.
  - L8.5 plans result-verification queries.
- Once an English query exists, downstream ranking/retrieval reuses it instead of reconstructing a query from raw scientific text.
- Provider-aware model invocation remains outside deterministic Curie identity/retrieval code and reuses the existing structured model execution/runtime boundary.

## Hard invariants

- `ResearchSeed` schema is unchanged.
- SINGLE OWNER is preserved.
- HASH BYTES NOT MEANING is preserved.
- NO RE-HASHING DOWNSTREAM is preserved.
- No new paper/evidence identity owner.
- No new retriever or provider transport.
- No new retry owner.
- No EvidencePack/store redesign.
- No DAG restructure.
- No extra L4A model invocation.
- Existing explicit English queries remain valid and bypass automatic query generation.
- Any CJK-bearing retrieval query fails before an English literature transport, PaperQA2 retrieval, or SPECTER2 ranking call.
- Semantic verification may still compare English evidence to a non-English scientific question/claim; that is not retrieval.

## Stage behavior

### L0.5

For an English ResearchSeed, the existing bounded deterministic planner may remain available. For a non-English ResearchSeed in the formal runner, the existing configured structured-model runtime produces 3–6 concise English scientific queries. Curie validates them and receives them through the existing explicit-query path. Standalone Curie calls that lack a provider must fail closed rather than silently reduce non-English semantics to ASCII fragments.

Candidate ranking uses the canonical QueryPlan text associated with each record's originating query IDs. PaperQA2 retrieval uses the selected paper title plus validated QueryPlan text, never raw ResearchSeed retrieval text.

### L4A / L4B

The existing L4A contextual planner remains the method-query owner for unresolved methods. SPECTER2 consumes only its validated English query text.

The first existing L4A inventory call must emit a standard English canonical `method.name` even when the scientific question/claim is non-English; controller validation enforces that contract. L4B PaperQA2 uses the richer contextual English query when one exists; otherwise it uses the validated English canonical method name. It never falls back to non-English purpose/inventory text.

### L8.5

Remove ASCII-token extraction as a query planner. The caller uses the existing structured-model runtime to create a finding-ID-bound English verification query for every active finding, validates all queries, then passes them to the existing Curie multisource QueryPlan path. Discovery, identity, source retrieval, semantic adjudication, verdicts, and run manifests remain owned by the current L8.5 implementation.

## Failure semantics

Invalid planner JSON, missing queries, duplicate/mismatched finding IDs, CJK-bearing retrieval queries, or query-planner runtime failure are software/planning failures. They must fail closed before external literature retrieval and must not be reported as scientific insufficiency.

## Acceptance

- A Chinese ResearchSeed unrelated to the old heart/shrew lexicon yields only English outbound L0.5 queries in a formal provider-backed run.
- Explicit Chinese L0.5 queries are rejected before transport.
- L0.5 ranking and PaperQA2 use QueryPlan text, not raw Chinese ResearchSeed text.
- Chinese L4 scientific context produces an English canonical method name; SPECTER2 and L4B PaperQA2 receive only validated English query text.
- A pure-Chinese L8.5 finding receives a complete English verification query instead of being dropped to ASCII residues or rejected as having no terms.
- Existing English-path behavior, identity/provenance, frozen evidence, retry bounds, and historical compatibility remain green.
