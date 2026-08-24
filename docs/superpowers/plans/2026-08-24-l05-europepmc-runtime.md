# L0.5 Europe PMC Runtime — Implementation Plan

**Goal:** Replace the Phase-1 compatibility-only acquisition path with one real, auditable Europe PMC vertical slice that executes `QueryPlanner -> DiscoveryTransport -> Selector -> Retrieval -> Verification -> Coverage -> EvidencePack -> FREEZE`.

## Scope

- Europe PMC only.
- End at frozen `L05EvidencePack/v1`; do not change the native L1 binding in this PR.
- No PubMed/OpenAlex/Crossref/Semantic Scholar adapters.
- No PaperQA2.
- Unit tests must not depend on live network.
- A separate controlled live smoke may call Europe PMC with a known OA article.

## Architecture

1. `build_europepmc_query_plan()` derives an auditable `L05QueryPlan/v1` from the canonical `ResearchSeed`; an explicit operator query may be recorded for reproducible smoke/debug runs.
2. `EuropePmcTransport` calls `search?resultType=core&format=json`, persists the raw response, hashes request/response, and returns normalized `L05DiscoveryBatch/v1` records.
3. Canonical identity normalizes DOI/PMID/PMCID and deduplicates by identifier priority before title/year fingerprint fallback.
4. `select_europepmc_candidates()` preserves a complete INCLUDE/EXCLUDE/RESERVE decision ledger and only sends PMCID-backed full-text candidates to retrieval.
5. `EuropePmcEvidenceRetriever` downloads `{PMCID}/fullTextXML`, persists the exact XML source snapshot, and emits unverified candidate extracts with deterministic locators.
6. `EuropePmcEvidenceVerifier` independently reloads the source snapshot, rechecks SHA-256, resolves the locator, verifies exact normalized text, then emits `verification_status=LOCATED` extracts.
7. Coverage is a declared minimal acquisition gate, not a claim of literature completeness. It requires at least one verified full-text source and located Results/Discussion/Conclusion evidence.
8. `run_europepmc_acquisition()` assembles and freezes the EvidencePack and writes a final acquisition audit manifest containing query, discovery, selection, source snapshot, verification, coverage, and frozen-pack receipts.
9. Add `l05-acquire-europepmc` CLI as a thin extension.

## TDD sequence

- RED 1: planner, normalization/dedup, transport receipt tests.
- GREEN 1: implement planner + Europe PMC discovery transport.
- RED 2: selector, XML retrieval, independent verifier tests.
- GREEN 2: implement selector/retriever/verifier.
- RED 3: full runtime and CLI end-to-end tests.
- GREEN 3: implement runtime, audit manifest, CLI.
- Verify targeted CI, then repository full CI.
- Run controlled live Europe PMC smoke using PMID 22253597 / PMCID PMC3257301 with bounded retries.
