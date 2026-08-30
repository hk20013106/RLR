# L4A Bounded Metadata Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make L4A inventory cognition offline and bounded, reuse frozen L0.5 metadata and the existing method registry deterministically, and allow external metadata lookup only for a fixed unresolved-method list.

**Architecture:** L4A remains one internal stage. The provider receives the scientific question/claim plus a compact frozen L0.5 metadata catalog, but no method registry, full text, extracts, source payloads, filesystem-reading instructions, or authorization to search. After the provider returns only a method inventory, deterministic code validates local asset references, applies the already-loaded registry, then performs at most one fixed Europe PMC metadata query per unique unresolved method name; no query rewriting or expansion is permitted. Existing L0.5 identifier normalization/canonicalization and transport code remain authoritative.

**Tech Stack:** Python 3.13, jsonschema, existing `research_loop.l05_curie` Europe PMC/multisource adapters, pytest.

**Spec:** User-approved L4A local-first optimization in the 2026-08-31 RLR conversation.

## Global Constraints

- Understand first; search before coding.
- Reuse > Extend > Refactor > Create.
- Do not create duplicate identifier normalization, metadata transport, schema, registry, or execution paths.
- Preserve L4A metadata-only / L4B full-text boundary.
- Registry is source-mapping authority only; it must not influence cognitive method selection.
- Missing metadata produces an explicit gap; no model-driven query expansion.
- L4A provider input must not contain full text, extracts, or source payloads.

---

### Task 1: Lock behavioral regressions

**Files:**
- Create: `tests/test_l4a_bounded_resolution.py`

**Interfaces:**
- Consumes: `l4_inventory.build_prompt`, `l4_inventory.run_discovery`, existing L0.5 EvidencePack and method registry interfaces.
- Produces: regression coverage proving offline cognition, registry isolation, local-source reuse, single bounded resolution, and explicit unresolved gaps.

- [ ] Add a test proving the cognitive prompt contains frozen local metadata but no registry entries, no full-text/extract payload, and explicitly forbids network/tool/filesystem lookup.
- [ ] Add a test proving a provider-returned local asset ID is resolved from the controller-built local catalog without a metadata network call.
- [ ] Add a test proving a registry-resolved method causes zero metadata network calls.
- [ ] Add a test proving duplicate unresolved method names cause one metadata resolution attempt.
- [ ] Add a test proving a metadata miss remains an explicit no-source method and does not trigger a second/expanded query.
- [ ] Run targeted tests and confirm the new tests fail for the current implementation before production changes.

### Task 2: Make L4A cognition offline and compact

**Files:**
- Modify: `src/research_loop/l4_inventory.py`

**Interfaces:**
- Consumes: active frozen L0.5 EvidencePack, existing `l4_method_registry.load_registry`.
- Produces: compact local metadata catalog plus loaded registry snapshot; provider sees only the compact local catalog.

- [ ] Refactor `_native_known_source_catalog` so the provider-facing catalog excludes registry contents, full-text/extract material, and filesystem-reading instructions while retaining exact IDs, title/year, source path/hash/status, and EvidencePack identity.
- [ ] Update `build_prompt` so the provider performs method inventory only, does not use Academic Research search, does not access network/filesystem/tools, returns no new literature assets/source hints, and may only reference controller-supplied local asset IDs.
- [ ] Validate provider output against the frozen local asset ID set before any source mapping.

### Task 3: Deterministic source mapping and bounded resolver

**Files:**
- Modify: `src/research_loop/l4_inventory.py`
- Reuse unchanged where possible: `src/research_loop/l05_curie/europepmc.py`, `src/research_loop/l05_curie/multisource.py`

**Interfaces:**
- Consumes: cognitive method inventory, controller-built local assets, loaded registry snapshot.
- Produces: final L4A assets/method inventory plus resolver receipt and unresolved methods.

- [ ] Materialize only authorized local L0.5 assets referenced by the cognitive inventory.
- [ ] Apply the already-loaded method registry after cognition; do not expose it to the provider.
- [ ] Build the unresolved-method list after local and registry mapping.
- [ ] Deduplicate unresolved methods by normalized method name using existing normalization primitives where available.
- [ ] Query existing Europe PMC metadata transport once per unique fixed method name; do not rewrite or expand queries.
- [ ] Accept a result only under conservative deterministic title/name matching; otherwise leave the method source arrays empty.
- [ ] Record resolver queries/status/receipts and explicit gaps in the L4A runtime receipt without inventing identifiers.

### Task 4: Verify integration and duplication constraints

**Files:**
- Test: `tests/test_l4a_bounded_resolution.py`
- Test: `tests/test_l4a_local_literature_first.py`
- Test: `tests/test_l4_inventory_schema.py`
- Test: `tests/test_l4_method_registry.py`
- Test: full suite

**Interfaces:**
- Consumes: final implementation.
- Produces: regression evidence.

- [ ] Run targeted L4A tests.
- [ ] Search for newly duplicated DOI/PMID/PMCID normalization or metadata transport logic; remove any duplicate implementation.
- [ ] Run the full Windows/Python 3.13 CI suite.
- [ ] Run `git diff --check` equivalent through CI and inspect failures before claiming completion.
