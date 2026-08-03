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

- [x] Test that `l4a_discovery_schema()` is strict metadata-only.
- [x] Test ordered identities `L4A`, `L4B`, `L4C`, and `L4.5`.
- [x] Observe RED before implementation.

## Task 2: Implement and test L4A discovery

- [x] Strict provider schema.
- [x] Identifier-first deterministic deduplication.
- [x] Immutable hash-bound manifest persistence.
- [x] Tests for deduplication, persistence, and zero-selection failure.
- [ ] Reuse configured ARS execution helpers.
- [ ] Observe GREEN through CI.

## Task 3: Implement and test frozen-corpus L4B

- [ ] Install after existing method-evidence extensions.
- [ ] Capture and delegate to mature L4 implementation.
- [ ] Run L4A first and freeze selected asset catalog.
- [ ] Bind L4B artifact to L4A path/hash.
- [ ] Fail closed on missing or tampered L4A manifest.
- [ ] Add two-call, failure-retention, and non-L4 delegation tests.

## Task 4: Implement and test L4.5 deterministic commit

- [ ] Implement `commit_l45_method_projection(...)`.
- [ ] Validate L4A, L4B, and persisted L4C hashes.
- [ ] Persist immutable idempotent projection.
- [ ] Integrate with native L4 finalize transaction.
- [ ] Preserve legacy behavior.
- [ ] Add tamper and idempotency tests.

## Task 5: Documentation and verification

- [ ] Document L4A/L4B/L4C/L4.5 and reuse-first adapters.
- [ ] Run focused tests and full Windows Python 3.11/3.12 CI.
- [ ] Inspect logs and fix defects without weakening gates.
- [ ] Compare with `main` for unrelated/runtime artifacts.
- [ ] Keep draft PR open and never merge automatically.

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

Current checkpoint: L4A implementation committed; CI verification pending.
