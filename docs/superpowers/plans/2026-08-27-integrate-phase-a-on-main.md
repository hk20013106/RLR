# Phase A Integration on Current Main Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the already-validated Phase A canonical paper-identity work onto current `main` without regressing Phase C strict discovery/query-lineage behavior.

**Architecture:** Keep `multisource.py` as the single provider-neutral owner of DOI/PMID/PMCID normalization, canonical paper identity, metadata fallback, and deterministic identity-graph deduplication. Europe PMC remains a provider adapter that maps provider fields and provenance into that canonical owner. Preserve Phase C strict ResearchSeed binding and QueryPlan-owned `originating_query_ids`.

**Tech Stack:** Python 3, pytest, GitHub Actions.

**Spec:** `docs/superpowers/plans/2026-08-26-l05-canonical-paper-identity.md` on historical Phase A branch plus current Phase C contracts on `main`.

## Global Constraints

- Do not rewrite or force-push PR #54.
- Do not modify frozen EvidencePack byte/hash semantics.
- Preserve Phase C `run_multisource_discovery_strict()` and QueryPlan-owned lineage.
- Europe PMC `source` / `ext_id` remain provenance, not canonical identifiers.
- No Phase B, PR #38, P2, or unrelated cleanup in this branch.

---

### Task 1: Re-establish the Phase A identity authority on current main

**Files:**
- Modify: `src/research_loop/l05_curie/multisource.py`
- Modify: `src/research_loop/l05_curie/europepmc.py`
- Test: `tests/test_l05_curie_multisource_discovery.py`
- Test: `tests/test_l05_curie_europepmc_discovery.py`

**Interfaces:**
- Consumes: current Phase C strict discovery/query-lineage behavior.
- Produces: provider-neutral `normalize_doi`, `normalize_pmid`, `normalize_pmcid`, `canonicalize_provider_record`, deterministic canonical identity graph.

- [ ] Add/retain regressions proving DOI/PMID/PMCID identity equivalence, transitive cross-provider merge, provider-order invariance, deterministic metadata fallback, and Europe PMC source/ext IDs as provenance only.
- [ ] Restore Phase A identity ownership in `multisource.py` while preserving Phase C `originating_query_ids`, strict seed binding, and strict discovery entry point.
- [ ] Convert `europepmc.py` to consume the provider-neutral identity owner rather than defining a second identity system.
- [ ] Run focused L0.5 identity/discovery tests.
- [ ] Run the relevant L0.5 suite.
- [ ] Run full pytest.
- [ ] Commit only Phase A integration changes.

### Task 2: Independent verification and integration gate

**Files:**
- Review only all Phase A integration diff.

**Interfaces:**
- Consumes: Task 1 exact head.
- Produces: merge-ready Phase A integration branch.

- [ ] Verify no second canonical paper-identity authority remains.
- [ ] Verify Europe PMC provider IDs are provenance only.
- [ ] Verify Phase C strict discovery/query-lineage behavior remains intact.
- [ ] Verify no frozen artifact/hash rewrite.
- [ ] Push exact head and wait for GitHub Actions.
- [ ] Require all exact-head CI jobs to pass before integration.
