# Plan: Integrate SPECTER2 and method-support adjudication into L4A

**Date:** 2026-09-02
**Base branch:** `codex/l4a-contextual-method-literature`
**Start SHA:** `e68a0ca77f65eb2e6dacdc86cb2c264211021a8b`
**Implementation branch:** `codex/l4a-specter2-method-support`

## Scope and ownership decisions

The change is limited to unresolved contextual-literature support in native L4A.
It does not change Curie discovery, canonical identity, cross-provider
deduplication, frozen L0.5 sources, the L4B closed-corpus resolver, or L4C method
design. The existing L4A contextual module remains the single owner of query
planning, contextual selection orchestration, and paper-to-method binding.

The audited reusable boundaries are:

- `l05_curie.multisource`: provider transports, canonical paper IDs,
  cross-provider identity/deduplication, and query provenance.
- `l05_curie.selector.select_candidates_strict`: deterministic eligibility,
  ordering, bounded selection, query-lineage checks, and selector receipts.
- `deep_research.RuntimeSpec`, `build_invocation`,
  `subprocess_invocation`, `execute_provider_invocation`, and `skill_receipt`:
  the configured cognitive/provider command boundary and model receipt.
- `l4_inventory` and `l4_pipeline`: native L4A inventory/assets and the
  existing L4A-to-L4B manifest contract.
- `l4_evidence_bundle`/`l4_closed_corpus`: exact registered-source retrieval
  and deterministic Methods extraction; these remain unchanged.

The old `_tokens`/`_build_selector_scorer` path is contextual-L4A-only after
caller tracing. It will be removed from the contextual flow; the selector will
receive SPECTER2 relevance values instead. Unrelated token helpers in Curie
source-matching code are out of scope.

## Design

### 1. English contextual eligibility

Add a deterministic L4A-only eligibility function in
`l4_contextual_literature.py`:

1. Use recursively available `language` metadata when present; known English
   values are admitted and an explicit non-English value is excluded.
2. If no language metadata is present, screen the candidate title and abstract
   for CJK characters; CJK candidates are excluded with
   `NON_ENGLISH_CONTEXTUAL_SOURCE`.
3. Otherwise retain the canonical record for the existing deterministic
   L4B-retrievability gate.

This function only returns an eligibility result. It never deletes or mutates
the canonical Curie record or its provenance. The contextual query-plan prompt
and validator will require English scientific query text and reject CJK/non-
letter query text without adding a translation layer.

### 2. Minimal SPECTER2 adapter

Add a lazy, dependency-injected adapter module (no import-time model loading),
with the conceptual interface `rank_method_papers(method_query, records)`.
The real implementation will:

- load `allenai/specter2_base` once per process with the pinned revision;
- load the official `allenai/specter2` proximity/paper adapter and
  `allenai/specter2_adhoc_query` adapter with their pinned revisions;
- encode papers as `title + tokenizer.sep_token + abstract`, or title-only
  when the abstract is absent;
- encode the raw English method query with the adhoc-query adapter;
- use `last_hidden_state[:, 0, :]`, cosine similarity, resource-sized batches,
  `model.eval()`, `torch.no_grad()`, and CPU fallback;
- fail closed when the runtime, cache, checkpoint, adapter, or output shape is
  unavailable. There is no token-overlap fallback, threshold-to-DIRECT rule,
  fine-tuning, or new neural scoring layer.

The approved existing environment/cache is used only by verification and local
runtime configuration; machine-specific paths will not be embedded in source.
The project will receive only the minimum explicit opt-in dependency manifest
needed for this runtime if verification confirms that the base requirements do
not already provide it; benchmark/scientific-evaluation dependencies are not
added.

### 3. Per-method selection and cognitive adjudication

For each unresolved method, collect only canonical records whose canonical
`originating_query_ids` map to that method. Apply English eligibility and the
existing `_l4b_retrievable` gate before invoking SPECTER2. Pass the resulting
scores to `select_candidates_strict` once per method with an explicit
configurable `top_k_per_method` value. This keeps the existing selector as the
only bounded-selection owner while avoiding a global cross-method ranking.

Add a strict L4A method-support response schema owned by the contextual flow.
The provider response contains only `paper_id`, `method_id`,
`classification`, and a short `rationale` per pair, plus the normal schema
envelope. The only classifications are:

- `DIRECT_METHOD_SUPPORT`
- `RELATED_BUT_NOT_METHOD_SUPPORT`
- `IRRELEVANT`
- `INSUFFICIENT_METADATA`

The prompt will explicitly distinguish topic relevance from method support,
require title/abstract evidence that the exact method is used/developed/
evaluated/benchmarked/explained, forbid inferred unavailable Methods content,
and make insufficient metadata map to `INSUFFICIENT_METADATA`. The prompt
payload will contain only the specified L4A method metadata, paper metadata,
and shortlisted pair IDs; it will contain no DOI/PMID/URL, provenance, full
text, Methods, semantic score, or web-search authority.

The call will use the existing `RuntimeSpec` model/provider command and receipt
helpers. Returned pairs must exactly match the shortlisted paper×method set:
unknown IDs, duplicates, missing pairs, extra fields, malformed JSON, and
unsupported classifications fail closed. No new provider client or judge
framework is introduced.

### 4. Binding and zero-DIRECT semantics

`originating_query_ids` remains discovery provenance only. The existing
`_bind_selected_records` owner will bind a paper to a method only when the
exact paper×method adjudication is `DIRECT_METHOD_SUPPORT`. It will populate
`source_asset_ids` and `method_component_hints` only for those pairs. Related,
irrelevant, and insufficient rows stay in contextual selection/adjudication
receipts and never become method source IDs. Canonical records remain present
in the discovery receipt.

The contextual receipt will include model/revision, per-method semantic score
and rank, selector inclusion, adjudication classification/rationale, and final
selected/bound state. Zero DIRECT classifications remain legal: no paper is
forced into a method binding. If a valid Top-K candidate exists it remains a
selected but unbound audit candidate, allowing the existing native L4B
validator/resolver to emit the normal no-source gap. The existing empty-corpus
fail-closed boundary is not broadened.

### 5. Configuration

Extend the existing runtime-spec configuration with one explicit
`top_k_per_method` field (defaulted in the existing config loader and
overrideable in project runtime JSON). Preserve all existing positional
`RuntimeSpec` call sites. Model selection continues to come only from the
runtime spec; Luna is not hard-coded.

## Test-first implementation sequence

1. Add RED tests before production code. Use fake semantic rankers and fake
   cognitive results; no test loads SPECTER2 weights.
2. Cover at minimum: CJK exclusion without Curie mutation; absence of the old
   token scorer from the contextual path; fake-ranker injection; distinct
   per-method ranks and per-method Top-K; query provenance not implying
   support; topic-related/non-method support; insufficient metadata; zero
   DIRECT; unchanged Curie IDs/DOI/PMID/PMCID; strict four-state validation;
   malformed/unknown/duplicate judge output; and native L4A manifest
   validation.
3. Implement the lazy SPECTER2 adapter and run the RED tests to GREEN.
4. Add the provider-backed adjudication using the existing runtime boundary,
   then replace query-level binding with exact DIRECT pair binding.
5. Update existing contextual fixtures to inject deterministic fakes and retain
   their prior coverage of query planning, multisource provenance, and L4B
   retrieval eligibility.
6. Run targeted L4A/contextual/selector/manifest/L4B/provider tests, then the
   full pytest suite and `python -m compileall src`.
7. Run exactly one bounded real local SPECTER2 smoke using the approved existing
   environment/cache and one bounded configured-provider structured-output
   smoke. Do not run full real-project E2E in this change.
8. Audit duplicate implementations, review the complete diff and worktree,
   then create one coherent commit only if every required check passes.

## Verification evidence to report

Report the exact branch, start SHA, final SHA, changed files, RED command/result,
targeted and full test commands/results, compile result, SPECTER2 environment
and model/revision receipt, cognitive-provider smoke receipt, native L4A/L4B
manifest result, duplicate-logic audit, and any skipped E2E status. If the
ownership boundaries cannot be preserved, stop with `BLOCKED_ARCHITECTURE`.
