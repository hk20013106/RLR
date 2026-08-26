# Explicit Installer Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove hidden import-time mutation from the high-confidence L0.5 semantic-pack and discovery-provenance paths while preserving an explicit compatibility surface for installer families whose migration is not yet proven safe.

**Architecture:** Canonical L0.5 modules will own their complete behavior directly: `store.py` validates semantic admission at its build/freeze/load boundaries, `multisource.py` attaches authoritative query lineage before returning discovery results, and `selector.py` requires that lineage directly. The historical `install()` entry points remain thin, documented compatibility facades with no mutation. Other installer families remain unchanged and are classified explicitly until a separate evidence-backed migration is justified.

**Tech Stack:** Python 3.11+, stdlib, jsonschema, pytest, GitHub Actions.

---

## Phase C inventory and evidence

Inventory source: AST scan of every `src/**/*.py` `def install`, package-level call scan, direct assignment scan, and `rg` call-site/test/doc scan on the clean `origin/main` baseline `876140228b1a80dbb37979ea8b608d131a72d59a0`.

Classification meanings:

- `CAN_BE_STATICIZED`: high-confidence direct ownership migration selected for this phase.
- `REQUIRED_COMPATIBILITY`: behavior is still used by legacy or cross-layer callers; leave unchanged in this phase.
- `UNCERTAIN`: import-order, closure, persistence, or migration evidence is insufficient for safe change.
- `CAN_BE_DELETED`: no production caller; only test support or an obsolete compatibility hook. No production deletion is included unless the selected migration proves it is unused.

### C1 — installer → target → original → replacement

| Installer | Target symbol(s) | Original implementation | Replacement / classification |
|---|---|---|---|
| `source_payload_integrity.install` | `deep_research.persist_run` | original `persist_run` | payload-integrity wrapper; `REQUIRED_COMPATIBILITY` |
| `method_evidence.install` | `deep_research` runtime/audit/persist symbols | original runtime functions | method-evidence wrapper family; `REQUIRED_COMPATIBILITY` |
| `method_evidence_compat.install` | `deep_research._parse_cli_output`, `persist_run`, `run_and_persist`, `validate_payload` | captured method-evidence functions | legacy payload facade; `REQUIRED_COMPATIBILITY` |
| `method_navigation_compat.install` | navigation `_split`, `_persist_navigation` | original navigation helpers | navigation-carrier compatibility; `REQUIRED_COMPATIBILITY` |
| `method_review_navigation.install` | `deep_research` schema/validate/persist/render/run | captured method runtime | navigation-only L4 extension; `REQUIRED_COMPATIBILITY` |
| `review_status_compat.install` | `deep_research.persist_run`, `run_and_persist` | original persistence/run | review-status normalization; `REQUIRED_COMPATIBILITY` |
| `l4_pipeline.install` | `deep_research.run_and_persist` | original run | staged L4 bridge; `REQUIRED_COMPATIBILITY` |
| `l4_pipeline_compat.install` | `l4_pipeline.run_l4a_discovery`, `deep_research._parse_cli_output` | original discovery/parser | historical L4 compatibility; `REQUIRED_COMPATIBILITY` |
| `l4_provenance.install` | L4 persistence/validation/commit symbols | original L4 functions | provenance enforcement wrapper; `REQUIRED_COMPATIBILITY` |
| `l4_provenance_compat.install` | L4 linkage and identity helpers | legacy helpers | historical L4 facade; `REQUIRED_COMPATIBILITY` |
| `l4_path_safety.install` | L4 persist/commit | original L4 functions | path-safety wrapper; `REQUIRED_COMPATIBILITY` |
| `l4_lineage.install` | `deep_research.audit_evidence_pack`, `evidence_artifact_manifest` | original audit/manifest | lineage wrapper; `REQUIRED_COMPATIBILITY` |
| `l45_context_binding.install` | L4.5 projection commit | original commit | context-binding wrapper; `REQUIRED_COMPATIBILITY` |
| `l4_registry_projection_integrity.install` | registry apply/inventory augment/validate | original registry functions | projection-integrity wrapper; `REQUIRED_COMPATIBILITY` |
| `l4_inventory_projection.install` | inventory source projection | original inventory function | source projection wrapper; `REQUIRED_COMPATIBILITY` |
| `l4_evidence_bundle.install` | L4 run/audit and L4.5 commit | original run/audit/commit | deterministic bundle boundary; `REQUIRED_COMPATIBILITY` |
| `l4_runtime_compat.install` | staged/legacy run dispatch | prior run functions | runtime compatibility selector; `REQUIRED_COMPATIBILITY` |
| `l4_closed_corpus.install` | closed-corpus discovery and deep-research run/validate/build | original functions | closed-corpus wrapper; `REQUIRED_COMPATIBILITY` |
| `provider_runtime_observability.install` | provider run/receipt/status symbols | original provider functions | runtime observability wrapper; `REQUIRED_COMPATIBILITY` |
| `provider_runtime_compat.install` | provider subprocess/status boundaries | existing provider functions | provider compatibility boundary; `REQUIRED_COMPATIBILITY` |
| `method_contracts.install` | `hypothesis_contracts.SCHEMA_REGISTRY` | base schemas | additive schema extension; `REQUIRED_COMPATIBILITY` until independently migrated |
| `hypothesis_reactivation_contracts.install` | L1/L3 schema objects | base schemas | additive reactivation schema extension; `REQUIRED_COMPATIBILITY` |
| `ledger_receipt_idempotency.install` | ledger clock/receipt/commit | original ledger methods | timestamp/idempotency wrapper; `REQUIRED_COMPATIBILITY` |
| `hypothesis_reactivation.install` | `HypothesisLedger.commit_delta`, `_event` | original ledger methods | lifecycle wrapper; `REQUIRED_COMPATIBILITY` |
| `hypothesis_reactivation_constraints.install` | `HypothesisLedger.commit_delta` | original commit | constraint wrapper; `REQUIRED_COMPATIBILITY` |
| `conditional_skip_constraints.install` | ledger validation/commit | original validation/commit | conditional-skip wrapper; `REQUIRED_COMPATIBILITY` |
| `hypothesis_reactivation_compat.install` | ledger ranking/verify and constraint selection | original methods | legacy reactivation facade; `REQUIRED_COMPATIBILITY` |
| `topology_extensions.install` | mutable `DAG_NODES` entries | base topology entries | runtime annotation extension; `REQUIRED_COMPATIBILITY` until topology ownership is migrated |
| `l05_native_binding.install` | `research_seed` binding/activation APIs | existing legacy binding entry helper | nested native binding API injection; `UNCERTAIN` |
| `conditional_routing.install` | lifecycle/context routing functions | original lifecycle/context functions | conditional DAG routing wrapper; `REQUIRED_COMPATIBILITY` |
| `l05_native_context_gate.install` | `context.cmd_assemble_context` | historical context assembler | native v2.1 gate wrapper; `UNCERTAIN` |
| `l05_context.install` | `context.cmd_assemble_context` | prior context gate/assembler | frozen-pack injection wrapper; `UNCERTAIN` |
| `hypothesis_recall_context.install` | context/ledger command boundaries | existing context/receipt functions | recall compatibility wrapper; `REQUIRED_COMPATIBILITY` |
| `l45_ledger.install` | ledger receipt/commit | original ledger methods | L4.5 receipt wrapper; `REQUIRED_COMPATIBILITY` |
| `hypothesis_pool_cli.install` | `cli.build_parser` | canonical parser | additive hypothesis-pool CLI; `REQUIRED_COMPATIBILITY` |
| `l05_curie_cli.install` | `cli.build_parser` | canonical parser | additive Europe PMC CLI; `REQUIRED_COMPATIBILITY` |
| `l05_curie.semantic_pack.install` | `store.build_evidence_pack`, `freeze_evidence_pack`, `load_frozen_evidence_pack` | canonical store functions | move validation into `store.py`; `CAN_BE_STATICIZED` |
| `l05_curie.provenance_hardening.install` | `multisource.run_multisource_discovery`, `selector._query_ids` | canonical discovery/selector functions | move lineage attachment/strict query IDs into owning modules; `CAN_BE_STATICIZED` |
| `rlr_maintenance.autowake_adapter.install` | `detached_task.run_worker` | maintenance worker | optional maintenance recovery adapter; `REQUIRED_COMPATIBILITY` |
| `tests.hypothesis_recall_test_support.install` | test helper module | test helper functions | test-only support; `CAN_BE_DELETED` from production scope |
| `tests.native_curie_test_support.install` | test helper module | test helper functions | test-only support; `CAN_BE_DELETED` from production scope |

The inventory has 41 definitions: 39 production/maintenance definitions and 2 test-only support installers. The two test-only helpers are not part of the production migration.

### C2 — import-order dependencies

`src/research_loop/__init__.py` currently performs the package-wide mutation chain in this order: Deep Research wrappers; staged L4 wrappers; provider wrappers; contract extensions; ledger/reactivation wrappers; topology extension; native binding; lifecycle/context wrappers; CLI wrappers. `src/research_loop/l05_curie/__init__.py` separately patches `store` before exporting store functions and patches `multisource`/`selector` before downstream runtime imports.

The selected L0.5 migration removes the only import-order dependency in those two Curie paths: `store` functions will own semantic validation at definition time, and `run_multisource_discovery`/`select_candidates` will own query-lineage behavior at definition time. The remaining package-level order is intentionally unchanged and documented as compatibility behavior.

### C3 — production callers

- `europepmc_runtime.py` imports `run_multisource_discovery`, `select_candidates`, and store functions directly; this is the primary L0.5 production path.
- `native_runtime.py`, `research_seed.py`, and native context code consume the exported store/binding contracts; no selected change rewrites frozen artifacts or native activation semantics.
- `research_loop/__init__.py` is the package composition boundary for legacy L4, provider, ledger, context, topology, and CLI extensions; those callers remain on their existing compatibility path.

### C4 — isolated tests and bypass risks

The Curie tests import `research_loop.l05_curie` plus direct submodules (`store`, `multisource`, `selector`, `europepmc_runtime`). Existing tests therefore exercise both package import and direct symbol capture. `tests/test_cli_standalone_imports.py` proves that modules may be imported without `engine.py`; this is evidence against adding another hidden dependency. Fresh-interpreter and direct-import characterization tests will be added before removing the two selected installers.

### C5 — compatibility facades and migration constraints

The `install()` names are not package `__all__` exports, but external code may import them by module path. Therefore `semantic_pack.install()` and `provenance_hardening.install()` remain callable no-op facades with explicit documentation after staticization. Existing frozen EvidencePacks, schema versions, legacy public function signatures, and error classes remain unchanged. Canonical Europe PMC acquisition uses separate strict discovery and selector entry points that require the externally derived seed digest and authorized QueryPlan IDs; the legacy entry points remain available only for historical self-consistent callers. Legacy source identity is admitted only through the explicit non-native context compatibility route; native binding, retry, and research-seed validation remain strict. No legacy installer outside the two selected families is deleted in this phase.

## Implementation tasks

### Task 1: Characterize direct Curie ownership

**Files:**
- Create: `tests/test_l05_curie_explicit_composition.py`
- Test existing: `tests/test_l05_curie_store.py`
- Test existing: `tests/test_l05_curie_multisource_discovery.py`
- Test existing: `tests/test_l05_curie_provenance_hardening.py`

- [x] Add a fresh-interpreter test proving `store.build_evidence_pack` enforces semantic admission without calling `semantic_pack.install`.
- [x] Add a fresh-interpreter test proving `multisource.run_multisource_discovery` returns authoritative `originating_query_ids` without calling `provenance_hardening.install`.
- [x] Add a direct-selector test proving missing provenance fails closed without a patched `_query_ids`.
- [x] Run only the new tests and confirm RED for the expected missing direct ownership.

### Task 2: Staticize semantic admission

**Files:**
- Modify: `src/research_loop/l05_curie/store.py`
- Modify: `src/research_loop/l05_curie/semantic_pack.py`
- Modify: `src/research_loop/l05_curie/__init__.py`
- Test: `tests/test_l05_curie_explicit_composition.py`

- [x] Move semantic-pack validation into store-owned helpers and add the optional `semantic_verifications` keyword to `build_evidence_pack`.
- [x] Validate semantic records at build, freeze, and load boundaries before content/hash validation completes.
- [x] Remove the package initializer call to `semantic_pack.install` while preserving the module-level compatibility facade.
- [x] Run the new tests, all Curie store/semantic tests, then the relevant L0.5 suite.
- [x] Commit only this family.

### Task 3: Staticize discovery provenance

**Files:**
- Modify: `src/research_loop/l05_curie/multisource.py`
- Modify: `src/research_loop/l05_curie/selector.py`
- Modify: `src/research_loop/l05_curie/provenance_hardening.py`
- Modify: `src/research_loop/l05_curie/__init__.py`
- Test: `tests/test_l05_curie_explicit_composition.py`
- Test: `tests/test_l05_curie_provenance_hardening.py`

- [x] Move canonical-record matching and query-lineage attachment into `multisource.py` and apply it before `run_multisource_discovery` returns.
- [x] Make selector provenance validation a native selector helper; remove the `UNKNOWN_QUERY` fallback for production selection.
- [x] Remove the package initializer call to `provenance_hardening.install` while preserving its callable no-op compatibility facade.
- [x] Run the new tests, all Curie discovery/selector/provenance tests, then the relevant L0.5 suite.
- [x] Commit only this family.

### Task 4: Review, full verification, and delivery gate

**Files:**
- Modify: `docs/superpowers/plans/2026-08-26-explicit-installer-composition.md` as checklist evidence only.

- [x] Run focused, relevant, and full `pytest` with fresh output and record exact counts.
- [x] Run compileall, `git diff --check`, and the CLI help smoke checks.
- [x] Perform a correctness review and a fresh thermo-nuclear review against the Phase C diff.
- [x] Fix all Critical/Important findings and rerun affected verification.
- [ ] Commit, push `codex/explicit-installer-composition`, create or update a Draft PR, and wait for exact-head CI.
- [ ] Stop at the Phase C gate; do not merge and do not automatically refactor the remaining P2 or `UNCERTAIN` installers.

## Verification evidence

- Final implementation HEAD before this evidence update: `019f0d3`.
- Focused Curie composition/provenance/runtime tests: `30 passed in 10.00s`.
- Relevant L0.5 suite (`l05|research_seed` test files): `140 passed in 10.77s`.
- Full canonical-source pytest run at `019f0d3`: `1040 passed in 570.92s (0:09:30)`.
- Static checks: `compileall`, both CLI `--help` smoke checks, and `git diff --check` passed.
- Fresh correctness review: no Critical/Important/Minor findings.
- Fresh thermo-nuclear review: no Critical/Important findings; one Minor compatibility re-export note was documented and retained intentionally.

## Self-review against the specification

- A/B ordering is satisfied: Phase B exact-head CI is green before this worktree was created.
- C1–C5 are recorded above; every discovered installer is classified.
- High-confidence direct ownership is limited to the two L0.5 Curie families; no speculative L4/context/ledger migration is mixed in.
- Frozen scientific artifacts are not rewritten by the selected changes.
- Compatibility facades remain callable, while production behavior no longer requires their import-time mutation.
- Remaining installer families are explicitly deferred as compatibility or uncertainty, not silently ignored.
