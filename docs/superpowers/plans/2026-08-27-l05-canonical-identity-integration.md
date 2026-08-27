# L0.5 Canonical Identity Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the validated Phase A canonical-paper-identity implementation onto current Phase-C `main` without regressing strict discovery/query-lineage behavior.

**Architecture:** Keep `multisource.py` as the sole provider-neutral identity owner. Semantic-replay only the effective PR #54 behavior onto the current file versions; do not merge/rebase the historical branch. Europe PMC delegates identity construction while retaining provider-specific provenance.

**Tech Stack:** Python 3, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-27-l05-canonical-identity-integration-design.md`

## Global Constraints

- Base exactly on `main@25c6eb832a4fd6da3623521203563a046b4a2a00`.
- Do not rewrite PR #54 history.
- Preserve Phase C strict ResearchSeed SHA binding, strict discovery entry point, QueryPlan-owned query lineage, and source-identity checks.
- Do not change frozen EvidencePack byte/hash semantics.
- Do not perform P2 cleanup.

---

### Task 1: Lock Phase A identity behavior with regression tests

**Files:**
- Modify: `tests/test_l05_curie_multisource_discovery.py`
- Modify: `tests/test_l05_curie_europepmc_discovery.py`

**Interfaces:**
- Consumes: current Phase C discovery and canonical-record APIs.
- Produces: regressions proving provider-neutral normalization/identity authority and deterministic transitive deduplication.

- [ ] **Step 1: Restore/adapt the Phase A regressions from PR #54**

Cover DOI, PMID and PMCID normalization; Europe PMC source/ext-id as provenance only; transitive stable-ID merge; metadata fallback; provider-order invariance; preservation of source provenance.

- [ ] **Step 2: Run focused tests and verify at least one Phase A authority regression fails on the pre-integration implementation**

Run: `python -m pytest tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py -q`

Expected before production replay: failure showing Europe-PMC-owned normalization/identity or non-transitive canonicalization behavior.

- [ ] **Step 3: Commit test-only RED evidence**

```bash
git add tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py
git commit -m "test: lock canonical paper identity ownership"
```

### Task 2: Make multisource the sole canonical identity owner

**Files:**
- Modify: `src/research_loop/l05_curie/multisource.py`
- Modify: `src/research_loop/l05_curie/europepmc.py`

**Interfaces:**
- Produces: `normalize_doi(value) -> str`, `normalize_pmid(value) -> str`, `normalize_pmcid(value) -> str`, `canonicalize_provider_record(...) -> dict` owned by `multisource.py`.
- Europe PMC consumes those functions and retains only provider-specific field/provenance mapping.

- [ ] **Step 1: Move canonical identifier normalization into `multisource.py`**

Implement the already-validated Phase A normalization semantics while preserving current Phase C code around them.

- [ ] **Step 2: Expose one canonical provider-record constructor in `multisource.py`**

The constructor computes canonical paper identity and accepts provider-specific metadata/provenance extensions; it must not overwrite Phase C query lineage.

- [ ] **Step 3: Convert Europe PMC canonicalization to delegate identity construction**

Remove its competing DOI/PMID/PMCID normalization and paper-id fallback logic. Keep `source` and `ext_id` only under provenance.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py -q`

Expected: PASS.

- [ ] **Step 5: Commit canonical ownership change**

```bash
git add src/research_loop/l05_curie/multisource.py src/research_loop/l05_curie/europepmc.py tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_europepmc_discovery.py
git commit -m "refactor: integrate canonical paper identity ownership"
```

### Task 3: Integrate deterministic identity-graph dedup with Phase C lineage

**Files:**
- Modify: `src/research_loop/l05_curie/multisource.py`
- Test: `tests/test_l05_curie_multisource_discovery.py`
- Test: `tests/test_l05_curie_explicit_composition.py`

**Interfaces:**
- Consumes: stable identifiers and metadata fallback identities.
- Produces: deterministic connected-component deduplication while merging `originating_query_ids` and provider provenance.

- [ ] **Step 1: Replay Phase A identity-graph union semantics onto current Phase C dedup code**

Records connected through DOI/PMID/PMCID edges must collapse into one component independent of input/provider ordering. Metadata fallback applies only when stable identifiers are absent.

- [ ] **Step 2: Preserve Phase C provenance merging**

Retain and union `originating_query_ids`; retain all provider `source_records`; deterministic-sort canonical output and duplicate IDs.

- [ ] **Step 3: Run focused + Phase C composition regressions**

Run: `python -m pytest tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_explicit_composition.py -q`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/research_loop/l05_curie/multisource.py tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_explicit_composition.py
git commit -m "fix: preserve lineage in identity graph dedup"
```

### Task 4: Verification gate

**Files:** no production changes unless a verified regression requires a scoped fix.

- [ ] **Step 1: Run relevant L0.5 suite**

Run: `python -m pytest tests/test_l05*.py -q`
Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Static/smoke verification**

Run: `python -m compileall -q src`
Run the repository CLI help smoke used by current CI.
Run: `git diff --check main...HEAD`
Expected: PASS.

- [ ] **Step 4: Independent scope review**

Verify the diff contains Phase A identity integration only, preserves Phase C strict discovery/query lineage, and contains no P2 cleanup.

- [ ] **Step 5: Push exact head and require exact-head GitHub Actions success**

Required checks: main CI/full suite, L0.5 Curie contracts, Europe PMC live smoke, and L4 evidence/runtime jobs that target the changed path.

- [ ] **Step 6: Open a new Draft PR against `main`**

The PR must state that it supersedes the integration role of historical PR #54 but leaves #54 untouched until the new PR merges.
