# L4A SPECTER2 method-support integration TDD evidence

> Historical implementation receipt only. The `poc_envs\specter2` runtime
> mentioned below is not a production environment and is superseded by
> [`2026-09-03-authoritative-rlr-specter2-runtime.md`](2026-09-03-authoritative-rlr-specter2-runtime.md).

**Date:** 2026-09-02
**Branch:** `codex/l4a-specter2-method-support`
**Base/start SHA:** `e68a0ca77f65eb2e6dacdc86cb2c264211021a8b`
**Scope:** native L4A contextual literature only; no Curie identity/discovery,
frozen L0.5 evidence, selector ownership, L4B resolver, benchmark directory,
or main-branch integration was changed.

## RED

Before adding `research_loop.l4a_specter2`, the new test file was collected
with:

```text
python -m pytest -q tests/test_l4a_specter2_method_support.py --no-header -p no:cacheprovider
```

Result: collection failed as intended with
`ModuleNotFoundError: No module named 'research_loop.l4a_specter2'`.

## GREEN and regression evidence

| Check | Command/result |
| --- | --- |
| L4A/contextual targeted tests | `python -m pytest -q tests/test_l4a_contextual_literature.py tests/test_l4a_bounded_resolution.py tests/test_l4a_specter2_method_support.py --no-header -p no:cacheprovider` — **52 passed** |
| SPECTER2 adapter coverage | `python -m pytest -q tests/test_l4a_specter2_method_support.py --no-header -p no:cacheprovider --cov=research_loop.l4a_specter2 --cov-report=term-missing` — **32 passed, 100%** for `src/research_loop/l4a_specter2.py` |
| Repository-wide tests | `python -m pytest -q --no-header -p no:cacheprovider` — **1188 passed in 667.54s (0:11:07)** |
| Python compilation | `python -m compileall -q src` — **passed** |
| Whitespace/error check | `git diff --check` — **passed** |

The tests cover English-only contextual eligibility without Curie-record
mutation, removal of the contextual token-overlap scorer, official title/SEP/
abstract and title-only input construction, lazy pinned-adapter loading, CPU
fallback, batching, CLS embeddings, finite cosine scores, per-method ranking
and Top-K, existing selector reuse, strict four-state metadata-only
adjudication, exact pair binding, zero-DIRECT behavior, unchanged Curie
identifiers/provenance, configured provider/model routing, malformed provider
output, and native manifest validation.

## Bounded runtime smokes

### SPECTER2

One bounded real local model smoke used the approved environment
`D:\research_loop\poc_envs\specter2` and cache
`D:\research_loop\model_cache\huggingface`, with offline Hugging Face flags.
The package-level import first exposed an environment-only missing `psutil`
dependency before model loading; the smoke then loaded the adapter module
directly without changing the environment. The real model run passed on CPU.

Receipt essentials:

```text
base: allenai/specter2_base @ 3447645e1def9117997203454fa4495937bfbd83
paper/proximity: allenai/specter2 @ 2081559630a80fc5851d8f798a05ba81e9468089
query: allenai/specter2_adhoc_query @ 3f4448817028388648a74349ece07af4518ec5bd
device=cpu, batch_size=8, max_length=512, deterministic_inference=true, no_grad=true
P_COEX=0.878789, P_TITLE_ONLY=0.815228, P_HAKKA=0.708334
```

The relevant co-expression candidate ranked first, and the title-only record
was encoded and returned. No token-overlap fallback or threshold-to-DIRECT
conversion was used.

### Configured cognitive provider

One bounded four-pair smoke used the existing runtime configuration from
`D:\research_loop\RLR-final-clean-e2e-20260830-210959` and the existing
provider observation layer. The direct helper invocation initially bypassed
that observation layer and received JSONL (`JSONDecodeError: Extra data`), so
it failed closed; no parser repair or fallback was added. The corrected smoke
used the already existing observer's final structured output and passed:

```text
backend/provider=codex, executable=codex, model receipt=default
skill=academic-research-suite, exit_code=0
classifications=DIRECT_METHOD_SUPPORT,
RELATED_BUT_NOT_METHOD_SUPPORT, IRRELEVANT, INSUFFICIENT_METADATA
direct_count=1
```

The live runtime JSON did not contain a model name, therefore the receipt is
reported as provider-configured `default`; no Luna model name is hard-coded in
the implementation.

## Boundary and duplicate-logic audit

- `l05_curie.multisource` remains the owner of canonical identity, discovery
  provenance, provider deduplication, and source records.
- `l05_curie.selector.select_candidates_strict` remains the only bounded
  selector; it is invoked once per method.
- `deep_research.RuntimeSpec` and its existing invocation/receipt helpers are
  reused for the cognitive adjudication call.
- Only `DIRECT_METHOD_SUPPORT` pairs populate method `source_asset_ids` and
  `method_component_hints`; all other classifications remain auditable.
- The old contextual `_tokens`/`_build_selector_scorer` path is absent. There
  is one SPECTER2 adapter module and no second judge framework.
- The native zero-DIRECT fixture returned
  `validate_native_l4a_manifest(...) == (True, "")`; a full real-project
  L4A→L4B E2E was intentionally not run in this change.
- The benchmark directories `D:\research_loop\specter2-poc-20260901` and
  `D:\research_loop\specter2-english-benchmark-20260902` were not modified.

## Changed files

- `src/research_loop/l4a_specter2.py`
- `src/research_loop/l4_contextual_literature.py`
- `src/research_loop/deep_research.py`
- `requirements-specter2.txt`
- `tests/test_l4a_specter2_method_support.py`
- `tests/test_l4a_bounded_resolution.py`
- `docs/specter2-official-sources.md`
- `docs/superpowers/plans/2026-09-02-l4a-specter2-method-support.md`
- `docs/testing/2026-09-02-l4a-specter2-method-support.tdd.md`
