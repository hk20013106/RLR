# L4 Evidence Architecture v2

## Problem

The controlled real-data pilot at commit `84d89324d04411453bd65229165062b8a150de9d` showed that the current staged L4 design couples three different responsibilities:

1. literature discovery and asset selection;
2. exact-source retrieval and Methods extraction;
3. method-component and candidate design.

This coupling creates two structural failures.

First, a known method source can disappear before retrieval because L4B is closed over only the assets selected by a stochastic L4A run. In the pilot, the known DESeq2 source A1 was absent from the new L4A manifest, so no resolver contract could be constructed for it.

Second, L4B itself invents method components and marks them `required`. It can therefore create new hard evidence obligations during the same model response that is supposed to satisfy them. In the pilot, `MC_IDENTIFIABILITY` and its ComBat/SVA candidates became the first fail-closed boundary even though the immediate technical task was exact-source retrieval and Methods extraction.

## Goal

Make the internal L4 pipeline follow five explicit responsibilities:

```text
method inventory
→ deterministic exact-source resolution
→ deterministic evidence extraction
→ Fisher method design
→ evidence-aware audit
```

The formal DAG remains unchanged. L4A, L4B, L4C, and L4.5 remain internal stages of formal node L4.

## Non-goals

- Do not weaken payload authenticity, provenance, source identity, contiguous-extract, or path-safety checks.
- Do not permit L4B to search for unrelated literature or expand the frozen source set.
- Do not move final method selection out of L6.
- Do not change L0-L3 or execute L7 code.
- Do not introduce OCR or authenticated publisher access.

## New responsibility boundaries

### L4A — method inventory and source metadata

L4A remains cognitive and metadata-only, but its primary product becomes a method inventory independent of asset selection.

Each inventory item contains:

- `method_id`: stable run-local slug;
- `name`;
- `purpose`;
- `source_asset_ids`: matching records in the L4A asset catalog, regardless of their selected/reserve status;
- `source_hints`: exact known DOI, PMID, PMCID, or stable URL identifiers;
- `inventory_reason`: why the method is relevant to the current question and claim.

L4A must carry forward exact identifiers already present in authorized context. It may perform metadata search only to fill missing identifiers. A known DOI/PMID/PMCID is not rediscovered merely because the corresponding paper was not selected as a general literature asset.

L4A does not define method components, candidate eligibility, execution requirements, or the final analysis plan.

### L4B — deterministic evidence service

L4B becomes non-cognitive. It receives the persisted L4A method inventory and constructs exact-source contracts from:

1. inventory source hints;
2. inventory-referenced L4A assets, whether selected or reserve;
3. selected L4A assets retained for navigation;
4. candidate-scoped registered local sources.

For each exact source it:

- resolves only registered identifiers and deterministic aliases;
- retains the source payload;
- computes content SHA-256;
- extracts a contiguous Methods section when present;
- stores a locator and retrieval receipt;
- emits an accepted evidence card or a truthful evidence gap.

L4B does not create method components, method candidates, eligibility statuses, `required` flags, alternatives, or an analysis plan.

An inaccessible or unsuitable source is an evidence gap, not automatically a failure of the whole L4 stage. L4B fails closed only for integrity violations such as identifier substitution, unregistered search, unsafe paths, invalid receipts, malformed payloads, or false anchor claims.

### L4C — Fisher method design

L4C remains the formal `L4_fisher` cognitive delta. Fisher receives:

- the method inventory;
- accepted evidence cards;
- explicit evidence gaps;
- the selected hypothesis and authorized context.

Fisher defines method components and candidates and records whether a candidate is an implementation path or an alternative.

Native v2.1 L4 method candidates gain:

- `execution_required`: boolean;
- `evidence_card_ids`: accepted L4B evidence cards supporting the candidate;
- `evidence_gap_ids`: unresolved source gaps relevant to the candidate.

Only an `eligible` candidate with `execution_required: true` must contain at least one accepted evidence card. Optional alternatives may remain in the comparison catalog without blocking L4.5, but their evidence limitations must remain visible.

The legacy `method_anchor_ids` field remains readable during compatibility cutover and aliases accepted evidence-card anchors.

### L4.5 — deterministic lineage and required-path audit

L4.5 validates:

- the immutable L4A manifest and hash;
- the immutable L4B evidence bundle and file manifest;
- the persisted L4C delta and hash;
- every `execution_required: true` eligible L4C candidate references an accepted L4B evidence card;
- every required component has at least one such candidate;
- evidence gaps are not passed off as accepted evidence.

L4.5 does not require every optional alternative to have a strong anchor.

### L6/L7 — final selection and execution

L6 remains the final method-selection authority. Its `selected_methods` must reference accepted evidence cards or their compatible anchor IDs. L7 may execute only the L6-approved plan.

## Artifact contracts

### L4A manifest

The existing immutable discovery manifest is extended additively with `method_inventory`. Existing asset records and hashes remain intact. The schema version is advanced to `L4ADiscoveryManifest/v2` for new staged runs; v1 remains readable for historical verification.

### L4B evidence bundle

A new staged artifact marker is used:

```text
pipeline_schema: L4MethodPlanningPipeline/v2
evidence_bundle_schema: L4BEvidenceBundle/v2
pipeline_stage: L4B
```

Top-level fields include:

- `method_inventory`;
- `evidence_cards`;
- `evidence_gaps`;
- `full_text_retrieval`;
- ordinary paper/source records required by the existing evidence-manifest machinery.

An evidence card contains:

- `evidence_card_id`;
- `method_id`;
- `source_ref_id`;
- `paper_id`;
- `evidence_id` and `anchor_id`;
- source kind;
- section and locator;
- content hash;
- status `accepted`.

An evidence gap contains:

- `evidence_gap_id`;
- `method_id`;
- `source_ref_id`;
- exact identifiers;
- attempted routes;
- deterministic failure reason;
- status `unresolved`.

## Compatibility

- Historical v1 L4A/L4B artifacts remain readable and auditable under their original semantics.
- New staged runs use v2 artifacts and the new responsibility boundaries.
- `method_evidence.py` remains available for historical/legacy evidence readers but is not the producer for staged v2 L4B.
- The public `deep-research-run --node L4` command still performs L4A followed by L4B; its L4B portion is now deterministic.
- Existing public CLI spellings, L0 contract, candidate identity, ledger rules, and artifact roots remain unchanged.

## Error semantics

L4B hard failures:

- unsafe or unregistered URL/path;
- exact-source identity mismatch;
- credential-bearing or private-network URL;
- source payload exceeds limit;
- claimed accepted extract is absent from retained payload;
- malformed or non-immutable artifact linkage.

L4B non-blocking evidence gaps:

- HTTP 403/404;
- paywall without registered local source;
- no explicit Methods section;
- Methods section below the accepted substantive threshold;
- metadata/abstract-only response.

L4.5 hard failures:

- required L4C implementation path lacks an accepted evidence card;
- component/candidate/evidence references are inconsistent;
- L4A/L4B/L4C lineage or hashes do not match.

## Test strategy

Targeted tests must prove:

1. inventory source hints create resolver contracts even when no corresponding asset is selected;
2. inventory-referenced reserve assets are resolved;
3. L4B emits evidence gaps without inventing method components/candidates;
4. L4B audit passes a truthful mixed bundle containing accepted cards and unresolved gaps;
5. L4B still rejects source substitution, unsafe URLs, malformed receipts, and false extracts;
6. L4C schema allows optional alternatives without evidence cards;
7. L4C schema requires an evidence card for `execution_required: true` eligible candidates;
8. L4.5 blocks a required implementation path without accepted evidence;
9. L4.5 accepts a required path backed by an accepted evidence card;
10. historical staged v1 artifacts remain readable;
11. L1, L8.5, ledger, provenance, path-safety, and full regression tests remain green.

## Delivery

Development occurs on `refactor/l4-evidence-design`, based on the PR #12 head containing the resolver implementation and real-pilot report. A new pull request supersedes PR #12. GitHub Actions must run targeted L4 tests and the full suite. A real-data pilot remains a separate local validation after CI.