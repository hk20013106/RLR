# L4A/L4B/L4C and L4.5 Implementation Plan

> Execute with test-driven development. Do not write production behavior before
> observing the corresponding test fail.

**Goal:** Implement the approved global L4 pipeline as L4A discovery, L4B
strict evidence construction, existing L4C Fisher method design, and a
non-LLM L4.5 commit gate, while preserving the public DAG and all downstream
contracts.

**Architecture:** Add one focused `research_loop.l4_pipeline` extension. It
wraps the fully installed Deep Research runtime only for node L4. L4A produces
an immutable metadata manifest; L4B delegates to the existing mature L4 method
evidence stack with a frozen corpus; L4C remains `L4_fisher`; L4.5 commits a
hash-bound audit projection in the native L4 delta transaction.

**Reuse:** Academic Research Skills, `deep_research.py`, `method_evidence.py`,
`method_review_navigation.py`, registered user sources, existing evidence
audits, context manifests, and the hypothesis ledger are reused directly.
Optional external retrieval/parsing tools remain adapters and are not added as
hard dependencies.

## Global constraints

- No L3.5 node.
- Do not renumber L5-L10 or change their personas.
- Do not change the `L4_fisher` storage key or delta schema.
- Do not weaken source-payload, verbatim, Methods-section, review-receipt,
  registered-source, or required-component gates.
- Non-L4 runtime behavior must delegate byte-for-byte through the captured
  implementation path.
- Legacy evidence packs remain readable.
- New artifacts must use project-relative paths and hash-bound lineage.
- No real-data success claim without a real-data run.

---

## Task 1: Specify L4A and stage identities with failing tests

**Create:** `tests/test_l4_pipeline.py`

- [x] Test that `l4a_discovery_schema()` is strict metadata-only: it contains
  identifiers, metadata, availability, relevance, selection, and receipts, but
  no `source_payload`, `extracts`, `method_components`, or
  `method_candidates` anywhere in the schema.
- [x] Test that `L4_PIPELINE_STAGES` declares ordered identities `L4A`, `L4B`,
  `L4C`, and `L4.5`, with L4C mapped to existing `L4_fisher` and L4.5 marked
  deterministic/non-cognitive.
- [ ] Commit the tests and observe CI fail because `research_loop.l4_pipeline`
  does not exist.

## Task 2: Implement and test L4A discovery

**Create:** `src/research_loop/l4_pipeline.py`

- [ ] Implement the strict provider schema.
- [ ] Reuse the configured ARS backend and existing command/receipt/subprocess
  helpers; add only the metadata-discovery prompt and schema boundary.
- [ ] Implement identifier-first deterministic deduplication: DOI, PMID, stable
  URL, normalized title plus year. Keep the higher relevance score and retain
  duplicate audit records.
- [ ] Persist `L4ADiscoveryManifest/v1` under
  `09_Literature_Database/l4/discovery/manifests/` with immutable run ID,
  runtime receipt, selected IDs, and manifest SHA256.
- [ ] Add tests for deduplication, manifest persistence, and zero-selected
  failure after persistence.
- [ ] Observe RED, implement minimally, then observe GREEN through CI.

## Task 3: Implement and test frozen-corpus L4B

**Modify:** `src/research_loop/l4_pipeline.py`, `src/research_loop/__init__.py`

- [ ] Install the extension after all existing method-evidence/navigation/status
  extensions.
- [ ] Capture the mature final `deep_research.run_and_persist` implementation.
- [ ] For node L4, run L4A first and inject a canonical frozen selected-asset
  catalog into the L4B request.
- [ ] Delegate L4B execution and validation to the captured existing L4
  implementation; do not duplicate its method evidence logic.
- [ ] Add the versioned L4A linkage fields to the completed L4B artifact and
  rewrite its existing artifact atomically before returning success.
- [ ] Extend `audit_evidence_pack` and `evidence_artifact_manifest` only for new
  linked artifacts so a missing/tampered L4A manifest fails closed and is
  included in context hashing.
- [ ] Add sequential fake-subprocess tests proving two calls, a frozen catalog
  in the second prompt, retained discovery after L4B failure, and unchanged
  non-L4 delegation.

## Task 4: Implement and test L4.5 deterministic commit

**Modify:** `src/research_loop/l4_pipeline.py`,
`src/research_loop/commands/ledger.py`

- [ ] Implement `commit_l45_method_projection(...)`.
- [ ] Validate the exact L4A manifest hash, exact L4B evidence audit and
  context-bound evidence manifest, and the persisted L4C delta hash.
- [ ] Project component, method, and anchor IDs from L4B without inventing
  values.
- [ ] Persist immutable `L45MethodCommit/v1` under
  `08_Audit/l4_method_commits/`; identical retries are idempotent and different
  content at the same path fails.
- [ ] Call it from the native L4 persistence finalize callback so a failure
  aborts the transaction and cleanup removes newly created artifacts.
- [ ] Preserve legacy behavior for evidence packs without
  `L4MethodPlanningPipeline/v1`.
- [ ] Add tests for successful commit, tampered discovery rejection, tampered
  L4C delta rejection, and idempotent retry.

## Task 5: Documentation and verification

**Modify:** `README.md`, `docs/README_CN.md`, `docs/DAG_TOPOLOGY.md`, and focused
L4 documentation only where necessary.

- [ ] Document L4A/L4B/L4C/L4.5 and the reuse-first adapter boundary.
- [ ] Run focused CI for the new tests and existing L4/deep-research tests.
- [ ] Run the complete Windows Python 3.11/3.12 CI matrix.
- [ ] Inspect CI job logs for failures; fix production defects rather than
  weakening tests or validators.
- [ ] Compare the branch with `main`; verify no runtime outputs, databases,
  PDFs, source payloads, or unrelated files were committed.
- [ ] Reopen the existing draft PR without merging. State that synthetic tests
  validate software behavior only and that no real-data full-loop success is
  claimed.

## Required verification

```text
python -m pytest tests/test_l4_pipeline.py -q
python -m pytest tests/test_l4_pipeline.py tests/test_l4_method_anchors.py tests/test_l4_review_navigation.py tests/test_deep_research.py -q
python -m compileall -q src tests/test_l4_pipeline.py
python -c "import research_loop"
python -m pytest -q
git diff --check
python run_loop.py --help
```

Because the active execution environment cannot clone GitHub directly, RED and
GREEN verification is performed by commits on the isolated feature branch and
observed GitHub Actions runs. The branch must never be merged automatically.
