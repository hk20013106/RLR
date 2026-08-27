# L0.5 Canonical Identity Integration Design

## Goal

Integrate the already-validated Phase A canonical-paper-identity work from PR #54 onto current `main` after Phase C, without rewriting old PR history and without regressing Phase C strict discovery/query-lineage behavior.

## Baseline

- Integration base: `main@25c6eb832a4fd6da3623521203563a046b4a2a00`
- Historical Phase A source: PR #54, head `68c3f465185f90daf5a79d391c0a380548b416a0`
- Historical PR #54 remains untouched as provenance.

## Required Architecture

`multisource.py` is the single provider-neutral owner of canonical paper identity. It owns DOI/PMID/PMCID normalization, canonical paper-id generation, metadata fallback identity, canonical provider-record construction, and deterministic identity-graph deduplication.

Provider modules only adapt provider fields and provenance. `europepmc.py` may retain Europe-PMC-specific source/ext-id provenance and retrieval behavior, but must not own a competing paper-identity algorithm.

Phase C behavior already on `main` must remain intact: externally bound ResearchSeed SHA validation, `run_multisource_discovery_strict`, QueryPlan-authoritative `originating_query_ids`, strict discovery-batch source identity checks, and deterministic lineage merging.

## Compatibility and Safety

- Do not modify frozen EvidencePack byte/hash contracts.
- Do not change selector or semantic-admission authority.
- Europe PMC `source`/`ext_id` remain provenance, not canonical identifiers.
- Preserve legacy callable entry points added by Phase C.
- Do not perform unrelated P2 cleanup.

## Acceptance Criteria

1. DOI/PMID/PMCID normalization has one production owner in `multisource.py`.
2. Europe PMC canonicalization delegates canonical identity construction to `multisource.py`.
3. Cross-provider transitive identity merging is deterministic and provider-order invariant.
4. Metadata fallback remains deterministic when no stable identifier exists.
5. Provider-specific provenance survives deduplication.
6. Phase C strict seed/query-lineage tests continue to pass.
7. Focused L0.5 tests, relevant L0.5 suite, full pytest, compile/import/CLI checks, and exact-head GitHub CI pass before merge.
