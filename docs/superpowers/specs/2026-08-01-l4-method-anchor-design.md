# L4 Method-Anchor Evidence Design

## Goal

Change L4 from a paper-level requirement ("some primary paper has a Methods heading") to a method-component requirement: every critical method proposed for the current study must have at least one reliable, located, reproducible evidence anchor.

The change must preserve fail-closed behavior. Abstract labels, tables that merely mention a method, review prose, placeholder source payloads, and unlocated summaries must not satisfy the gate.

## Scope

This change covers the L4 deep-research prompt, structured output schema, payload validation, evidence persistence, L4 audit logic, diagnostics, tests, and concise documentation.

It does not add a new network downloader, PDF parser, OCR pipeline, authentication flow, or MCP integration. ARS remains responsible for retrieval. RLR remains responsible for defining, persisting, and auditing evidence.

## Evidence model

### Method components

L4 output adds a top-level `method_components` list. Each item contains:

- `component_id`: stable slug within the run, such as `cross_species_orthology`;
- `name`: human-readable method name;
- `required`: boolean; only required components participate in the gate;
- `rationale`: why the component is necessary for the proposed analysis.

A valid L4 run must contain at least one required component. Component identifiers must be unique.

### Method anchors

Each located extract used as an L4 method anchor adds:

- `method_component_ids`: one or more component IDs covered by the extract;
- `source_kind`: one of `primary_study`, `method_paper`, `protocol`, `supplementary_methods`, `official_documentation`, or `versioned_code`.

Existing paper/source records remain the persistence unit to avoid a disruptive rename. Non-journal sources use a stable URL as their identifier and retain the existing title, source database, metadata response, locator, and source payload fields.

Reviews remain valid discovery records but are not accepted as method anchors. Their Results/Conclusion extracts and `review_search` receipt remain useful for method navigation and rationale.

## Accepted anchors

An anchor satisfies a required method component only when all of the following hold:

1. The extract has `verification_status: located`, non-empty text, and a non-empty locator.
2. The extract names the required component in `method_component_ids`.
3. `source_kind` is in the accepted anchor set above and is not `review` or `abstract`.
4. The source has a DOI, PMID, or stable URL.
5. A real source payload was retained for the retrieved source.
6. The payload passes authenticity checks and contains the normalized extract text.

For `primary_study` and `supplementary_methods`, the section must be a recognized Methods heading or Methods subsection. Protocols, method papers, official documentation, and versioned code may use their native section labels because their whole purpose is methodological.

## Source-payload authenticity

RLR must reject obvious placeholder payloads before persistence and before gate evaluation.

Validation rules:

- payload must not be empty;
- UTF-8 payload length must be at least 500 bytes;
- payload must not match known placeholder patterns such as "full text was retrieved" without actual content;
- after whitespace, HTML-entity, Unicode-dash, and case normalization, every anchor extract must be found within the retained payload;
- payload remains capped at the existing 5 MiB limit.

These checks deliberately validate provenance consistency, not scientific correctness. They do not attempt to parse arbitrary PDFs or infer missing text.

## Retrieval priority communicated to ARS

The L4 prompt instructs ARS to retrieve sources in this order:

1. Europe PMC/PMC JATS XML;
2. publisher open-access HTML/XML;
3. open-access PDF text;
4. Supplementary Methods;
5. protocol or method paper;
6. official software documentation or versioned analysis workflow;
7. preprint full text.

For a paywalled study, ARS may record metadata and use it for navigation, but it must not fabricate a source payload or count abstract text as a method anchor. If a uniquely necessary method remains unsupported, the run must report the missing component so the operator can provide a legally obtained full text later.

## L4 prompt behavior

The L4 request becomes a two-part task:

1. identify the critical method components implied by the current question and claim;
2. retrieve at least one accepted method anchor for every required component.

The prompt explicitly separates biological relevance sources from implementation sources. A relevant primary paper may justify that an analysis is used in the field, while a method paper, protocol, official documentation, or versioned code may provide the reproducible implementation anchor.

## Validation and persistence

`validate_payload` becomes node-aware so L4-specific requirements do not affect L1 or L8.5.

For L4 it validates:

- non-empty, unique method components;
- valid component references from extracts;
- allowed source kinds;
- authentic payloads for proposed anchors;
- no review extract counted as an anchor.

`persist_run` stores method components in the run receipt and stores method-component IDs and source kind with each evidence extract. Existing L1/L8.5 records remain readable. Older L4 receipts remain readable for audit history but do not satisfy the new component-level gate unless they contain the new fields.

## Gate behavior

The L4 audit computes coverage by required component.

It passes only when every required component has at least one accepted anchor. Failure messages enumerate uncovered components and distinguish:

- no candidate source located;
- source found but no full payload retained;
- payload rejected as placeholder or too short;
- extract not present in source payload;
- only review/abstract/table evidence available;
- component reference missing or invalid.

The existing review-search requirement remains. Review evidence supports navigation but never substitutes for component coverage.

## Compatibility

- L0 contract schema remains `1.0` and is untouched.
- Deep-research output remains schema `1.0`; the strict schema is extended with L4-only fields rather than globally renaming records.
- L1 and L8.5 behavior remains unchanged.
- Existing immutable evidence files are not rewritten.
- The current halted real-data run must perform a new L4 retrieval after the change; L0-L3 must not be rerun.

## Files

Expected implementation surface:

- `src/research_loop/deep_research.py`: schema, prompt, validation, normalization, persistence, and L4 audit;
- `tests/test_deep_research.py`: RED/GREEN coverage for component coverage and source authenticity;
- one concise documentation file describing L4 evidence semantics, if no suitable existing document exists.

No unrelated refactoring is included.

## Test strategy

Targeted tests must cover:

- all required components covered by primary Methods plus official documentation;
- method paper, protocol, supplementary Methods, and versioned code anchors;
- review evidence rejected as an anchor;
- abstract `Methods and results` rejected;
- table-only mention rejected;
- placeholder payload rejected;
- payload under 500 bytes rejected;
- extract absent from payload rejected;
- unknown component ID rejected;
- duplicate component IDs rejected;
- one uncovered required component fails with a precise diagnostic;
- optional components do not block the gate;
- existing L1 and L8.5 tests remain green;
- full test suite and `git diff --check` pass.

## Delivery

Implementation will be developed on `feat/l4-method-anchors` using TDD and small commits. A pull request will target `main`. It will merge only after targeted tests, the full suite, and GitHub CI pass. After merge, the existing real-data project will resume at L4 with a new retrieval; earlier nodes and the real-data inputs will not be modified.