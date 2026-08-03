# L4 Provenance Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make staged L4 fail closed when L4A payloads are malformed, L4B introduces out-of-corpus literature, or L4A/L4B identities do not agree.

**Architecture:** Add a focused `research_loop.l4_provenance` extension installed after the staged L4 wrappers and before lineage/ledger consumers import their function references. It wraps the existing L4A persistence/validation and L4B linkage boundaries rather than duplicating retrieval or evidence validation. Existing evidence gates, the formal DAG, and legacy non-staged behavior remain unchanged.

**Tech Stack:** Python 3.11+, `jsonschema`, pytest, existing RLR extension-install pattern.

## Global Constraints

- Keep the public DAG unchanged.
- Do not weaken source-payload, verbatim, Methods-section, review-receipt, registered-source, or required-component gates.
- L4B may consume only L4A-selected assets plus candidate-owned verified user sources.
- New validation must fail before a staged L4B linkage is persisted.
- Legacy non-staged evidence packs remain readable.
- Use TDD: tests must fail before production implementation is added.

---

### Task 1: Add failing provenance regression tests

**Files:**
- Create: `tests/test_l4_provenance_hardening.py`

**Interfaces:**
- Consumes: `l4_pipeline.persist_l4a_discovery`, `l4_pipeline._persist_l4b_linkage`, `l4_pipeline.commit_l45_method_projection`.
- Produces: regression coverage for full L4A contract validation, frozen-corpus enforcement, registered-source allowance, and identity binding.

- [ ] Add tests rejecting malformed L4A queries, duplicate IDs, missing required asset fields, and inconsistent persisted selected IDs.
- [ ] Add tests accepting normalized DOI membership and a verified registered user source.
- [ ] Add a test rejecting an out-of-corpus L4B paper before staged linkage persistence.
- [ ] Add cross-candidate, cross-run, and project/round/profile mismatch tests.
- [ ] Push the tests-only commit and verify CI fails for the intended missing validation behavior.

### Task 2: Implement the focused provenance extension

**Files:**
- Create: `src/research_loop/l4_provenance.py`
- Modify: `src/research_loop/__init__.py`

**Interfaces:**
- Produces: `install(l4_pipeline_module, deep_research_module)`.
- Wraps: `persist_l4a_discovery`, `validate_l4a_manifest`, `_persist_l4b_linkage`, and `commit_l45_method_projection`.

- [ ] Validate provider payloads with the published L4A JSON schema before persistence.
- [ ] Enforce non-empty unique `query_id` and `asset_id` values.
- [ ] Revalidate persisted manifest selected IDs and identity fields.
- [ ] Match L4B papers to selected L4A assets by normalized DOI, PMID, stable URL, then title+year.
- [ ] Allow only candidate-owned verified registered sources outside the L4A external-identifier catalog.
- [ ] Enforce candidate, L4A run, and populated project/round/profile identity agreement.
- [ ] Install the extension before lineage and ledger consumers capture function references.

### Task 3: Verify and update PR #10

**Files:**
- Modify only if needed: PR description and the existing implementation plan checklist.

- [ ] Run focused tests through CI.
- [ ] Run the full Windows Python 3.11/3.12 matrix.
- [ ] Re-run the real Codex L4A strict-schema probe outside CI and record the exact exit status.
- [ ] Confirm no complete L4B/L4C/L4.5 pilot claim is made.
- [ ] Review the final diff for unrelated changes before merge.
