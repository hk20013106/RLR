# L4A method-support identity ownership and per-method adjudication TDD evidence

**Date:** 2026-09-03
**Branch:** `codex/l4a-specter2-method-support`
**Base/start SHA:** `4d9c00143b62834b40df8003010925ce43363a66`
**Scope:** L4A cognitive method-support adjudication only. SPECTER2 ranking,
Curie canonical discovery/provenance, L4 inventory projection, and L4B remain
unchanged.

## Architecture audit

- `l05_curie.multisource` remains the canonical paper identity and provenance
  owner.
- `_select_contextual_candidates` remains the pair-identity boundary and
  existing `l05_curie.selector.select_candidates_strict` remains the bounded
  Top-K selector.
- `deep_research.build_invocation`, `subprocess_invocation`,
  `execute_provider_invocation`, `skill_receipt`, and the existing provider
  observability layer are reused. No second provider or judge framework was
  added.
- The previous defect was the provider contract requiring `paper_id` and
  `method_id` in a monolithic all-pairs response. This made identity drift and
  cross-method adjudication possible.

## RED

Before the production contract change, the eight new identity/per-method tests
were run with:

```text
micromamba run -n rlr python -m pytest -q tests/test_l4a_method_support_identity.py --no-header -p no:cacheprovider
```

Result: **8 failed**. Failures exposed the old provider-owned identity fields
and pair-set validator rather than the required caller-owned ordered contract.

## GREEN and regression evidence

The new wire contract is `L4AMethodSupportAdjudication/v2`. Each provider call
receives one method and its ordered candidate metadata; each decision may only
contain `classification` and `rationale`. The caller validates exact decision
count, then restores `(paper_id, method_id)` by ordered position. Only
`DIRECT_METHOD_SUPPORT` is eligible for binding; zero DIRECT decisions remain
valid.

| Check | Command/result |
| --- | --- |
| Identity/per-method tests | `micromamba run -n rlr python -m pytest -q tests/test_l4a_method_support_identity.py --no-header -p no:cacheprovider` — **8 passed** |
| L4A/contextual targeted tests | `micromamba run -n rlr python -m pytest -q tests/test_l4a_specter2_method_support.py tests/test_l4a_method_support_identity.py tests/test_l4a_bounded_resolution.py tests/test_l4a_contextual_literature.py --no-header -p no:cacheprovider` — **66 passed** |
| Curie/inventory/L4B regression tests | `micromamba run -n rlr python -m pytest -q tests/test_l05_curie_multisource_discovery.py tests/test_l05_curie_selector.py tests/test_l4_inventory_schema.py tests/test_l4_inventory_projection.py tests/test_l4_pipeline.py tests/test_l4b_closed_corpus_fulltext.py tests/test_l4_evidence_bundle.py --no-header -p no:cacheprovider` — **97 passed** |
| Canonical repository suite | `micromamba run -n rlr python -m pytest -q --no-header -p no:cacheprovider` — **1202 passed** |
| Whitespace check | `git diff --check` — **passed** |

The full count is the 1194-test baseline plus the eight new regression tests.
An initial full-suite attempt reported 1201 passed and one failure in the
pre-existing `test_l4_persistence_uses_same_canonical_reference_structure`;
that fixture hashes a fresh receipt containing second-resolution
`executed_at`. The unchanged test passed in isolation and the deliberate
second full-suite run completed with the 1202-pass result recorded above.

## Real configured-provider cognitive smoke

One bounded smoke used the existing project configuration at
`D:\research_loop\RLR-final-clean-e2e-20260830-210959`, the real configured
Codex provider, candidate `C20260830211059947031`, method `M10`, and five
canonical-looking metadata candidates. It was executed through the existing
provider observation context, not through a new parser or fallback.

```text
status=PASS
method=M10
candidate_count=5
adjudication_call_count=1
wire_decision_count=5
wire_decision_keys=[classification,rationale] x5
caller_bound_identity_order_exact=true
provider_final_status=succeeded
observability_artifacts=events.jsonl,runtime_receipt.json,final_output.json
```

An initial direct helper probe outside the observation context received the
provider's JSONL stream and failed closed with `JSONDecodeError: Extra data`.
The probe was not treated as a production defect: the corrected smoke used the
existing observed final-output boundary, and no extraction, fence stripping,
repair, or second-LLM recovery was added.

## Source-type and duplicate audit

- Existing Curie records retain provider `publication_types` in canonical
  metadata; the L4 source registry retains its existing `source_kind` values.
- No new contextual `source_type` abstraction or Supplementary filter was
  added, because the current infrastructure does not provide a unified
  relation/parent-source contract.
- No changes were made to SPECTER2, Curie, L4B, Top-K, thresholds, or model
  pins. There is one method-support schema/validator and one caller-owned
  binding path.
