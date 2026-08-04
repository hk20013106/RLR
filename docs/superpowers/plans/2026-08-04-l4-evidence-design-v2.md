# L4 Evidence Architecture v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple L4 method inventory, deterministic evidence retrieval, Fisher method design, and required-path audit so L4B no longer creates its own blocking method obligations.

**Architecture:** Extend L4A with an identifier-bearing method inventory. Replace staged L4B's cognitive provider path with a deterministic evidence-bundle builder using the existing closed-corpus resolver. Keep method components/candidates in L4C, and make L4.5 validate only Fisher-declared required implementation paths against accepted evidence cards.

**Tech Stack:** Python 3.11+, stdlib, jsonschema, pytest, GitHub Actions.

## Global Constraints

- Preserve the formal DAG and all authority boundaries.
- Preserve exact-source identity, path safety, credential redaction, 500-byte substantive threshold, contiguous extract, locator, payload hash, and immutable lineage checks.
- Do not permit L4B online literature search or corpus expansion.
- Do not modify L0-L3, source projects, ledgers, real data, or execute L7.
- Historical v1 staged artifacts remain readable.
- New staged artifacts use explicit v2 schema markers.

---

### Task 1: Add L4A Method Inventory Contract

**Files:**
- Modify: `src/research_loop/l4_pipeline.py`
- Test: `tests/test_l4_pipeline.py`

**Interfaces:**
- Produces: `method_inventory` in `L4ADiscoveryManifest/v2`.
- Produces: `inventory_l4a_sources(manifest) -> list[dict]` for deterministic resolution.

- [ ] Add strict schemas for inventory items and exact source hints.
- [ ] Validate unique `method_id`, valid `source_asset_ids`, and at least one source reference per inventory method.
- [ ] Persist the normalized inventory and include it in manifest hashing.
- [ ] Update the L4A prompt so known identifiers are carried forward and method inventory is independent of asset selection.
- [ ] Add tests for an inventory source hint whose paper is not selected and for a reserve asset referenced by the inventory.

### Task 2: Build Deterministic L4B Evidence Bundles

**Files:**
- Create: `src/research_loop/l4_evidence_bundle.py`
- Modify: `src/research_loop/l4_closed_corpus.py`
- Modify: `src/research_loop/l4_pipeline.py`
- Modify: `src/research_loop/__init__.py`
- Test: `tests/test_l4_evidence_bundle.py`
- Modify: `tests/test_l4b_closed_corpus_fulltext.py`

**Interfaces:**
- Consumes: `inventory_l4a_sources(manifest)`.
- Produces: `run_l4b_evidence(project_dir, candidate_id, manifest, work_dir, ...) -> dict`.
- Produces: `L4BEvidenceBundle/v2` with `evidence_cards` and `evidence_gaps`.

- [ ] Refactor the resolver into callable service functions without provider-state monkey patching.
- [ ] Preserve exact-source allowlisting, deterministic aliases, redirect identity validation, redaction, payload retention, and Methods extraction.
- [ ] Persist paper records, source payloads, retrieval receipts, accepted evidence cards, and unresolved evidence gaps.
- [ ] Render an L4B summary that lists accepted cards and gaps without generating method candidates.
- [ ] Change staged `deep-research-run --node L4` to invoke deterministic L4B after L4A instead of the L4 cognitive provider.
- [ ] Keep the old installer as a compatibility no-op for historical imports.
- [ ] Add tests proving no `method_components`, `method_candidates`, or `required` obligations are emitted by L4B.

### Task 3: Split Evidence Integrity Audit from Method Coverage

**Files:**
- Modify: `src/research_loop/l4_evidence_bundle.py`
- Modify: `src/research_loop/__init__.py`
- Test: `tests/test_l4_evidence_bundle.py`

**Interfaces:**
- Produces: staged-v2 `audit_evidence_pack` behavior that validates bundle integrity only.

- [ ] Add an audit wrapper that recognizes `L4BEvidenceBundle/v2`.
- [ ] Verify every accepted card has a retained payload, matching content hash, contiguous extract, valid locator, exact source identity, and receipt.
- [ ] Verify every unresolved gap has attempted routes and a non-empty deterministic reason.
- [ ] Allow a mixed accepted/gap bundle to pass integrity audit.
- [ ] Preserve historical v1 and non-L4 audit behavior unchanged.

### Task 4: Move Method Obligations to Fisher/L4C

**Files:**
- Modify: `src/research_loop/method_contracts.py`
- Modify: `templates/layers/L4_method_brainstorm.md`
- Test: `tests/test_method_contracts.py`

**Interfaces:**
- Produces: L4C candidates with `execution_required`, `evidence_card_ids`, and `evidence_gap_ids`.

- [ ] Extend native v2.1 method-candidate schema additively.
- [ ] Require accepted evidence only when a candidate is both `eligible` and `execution_required: true`.
- [ ] Permit optional alternatives to remain eligible with visible evidence gaps and no blocking card.
- [ ] Update Fisher instructions to consume inventory/cards/gaps and never claim that an evidence gap is an accepted source.
- [ ] Preserve legacy `method_anchor_ids` for compatibility.

### Task 5: Add Required-Path L4.5 Audit

**Files:**
- Modify: `src/research_loop/l4_pipeline.py`
- Test: `tests/test_l4_pipeline.py`
- Test: `tests/test_l45_context_binding.py`
- Test: `tests/test_l45_ledger_integration.py`

**Interfaces:**
- Consumes: persisted L4C delta `method_components` and `method_candidates`.
- Consumes: L4B `evidence_cards`.
- Produces: L4.5 projection listing inventory, card, gap, component, and candidate IDs.

- [ ] Parse and validate the persisted L4C delta before commit.
- [ ] Require every required component to have at least one eligible `execution_required` candidate.
- [ ] Require those candidates' `evidence_card_ids` to resolve to accepted L4B cards.
- [ ] Reject references to unresolved gaps as accepted evidence.
- [ ] Do not require evidence cards for optional alternatives.
- [ ] Preserve immutable L4A/L4B/L4C hash and lineage checks.

### Task 6: Documentation and Compatibility

**Files:**
- Modify: `docs/L4_METHOD_EVIDENCE.md`
- Modify: `docs/AGENT_CONTEXT.md`
- Add or modify focused compatibility tests as required.

- [ ] Document the five-stage responsibility model.
- [ ] Mark PR #12's provider-enrichment architecture as superseded for staged v2 runs.
- [ ] Document evidence-gap semantics and the later local real-pilot requirement.

### Task 7: GitHub Actions CI

**Files:**
- Create: `.github/workflows/l4-evidence-ci.yml`

- [ ] Run on pull requests and manual dispatch.
- [ ] Use Python 3.11 and 3.13.
- [ ] Install the project test dependencies.
- [ ] Run targeted L4 pipeline, resolver, contracts, provenance, path-safety, and L4.5 tests.
- [ ] Run the full pytest suite on Python 3.13.
- [ ] Run `git diff --check` against the PR base.

### Task 8: Verification and Pull Request

- [ ] Run syntax/compile checks available in the editing environment.
- [ ] Open a pull request from `refactor/l4-evidence-design` to `codex/l4a-source-metadata-contract`.
- [ ] State that the PR supersedes PR #12 and includes its resolver and real-pilot evidence.
- [ ] Inspect GitHub Actions results and fix deterministic failures.
- [ ] Do not merge.
- [ ] After CI passes, provide a local synchronization and controlled real-pilot prompt for the user.