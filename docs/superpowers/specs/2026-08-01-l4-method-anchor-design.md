# L4 Method-Anchor Evidence Design

## Goal

Change L4 from a paper-level requirement ("some primary paper has a Methods heading") to a method-component requirement: every critical method proposed for the current study must have at least one reliable, located, reproducible evidence anchor.

The change must preserve fail-closed behavior. Abstract labels, tables that merely mention a method, review prose, placeholder source payloads, and unlocated summaries must not satisfy the gate.

L4 does not make the final method decision. It builds an evidence-backed method candidate catalog. L5 critiques that catalog from an EDA/QC perspective, and L6 selects or rejects the final executable methods.

## Scope

This change covers the L4 deep-research prompt, structured output schema, payload validation, evidence persistence, L4 audit logic, diagnostics, user-supplied PDF registration, tests, and concise documentation.

It does not add a new network downloader, an RLR-owned PDF parser, OCR, authentication flow, or MCP integration. ARS remains responsible for retrieval and text extraction. RLR remains responsible for registering sources, defining structured outputs, validating provenance, persisting evidence, and auditing method coverage.

## Method decision flow

The method flow is deliberately separated across the existing DAG:

1. **L4 Fisher — candidate construction**
   - identify required method components;
   - construct one or more method candidates for each component;
   - attach located evidence anchors;
   - mark clearly ineligible candidates with explicit reasons;
   - do not select the final method.
2. **L5 Tukey — QC and falsification**
   - critique every eligible L4 method candidate;
   - test assumptions against the actual input data and study design;
   - add failure modes, QC checkpoints, and stop rules;
   - recommend rejection or modification where warranted.
3. **L6 Oppenheimer — final triage**
   - select one approved candidate, or an explicit combined strategy, for each required component;
   - record rejected alternatives and reasons;
   - freeze parameters and scripts needed for L7 execution.

The resulting data flow is:

```text
L4 method components + method candidates + method anchors
→ L5 candidate-level QC and attacks
→ L6 selected_methods / approved_strategy
→ L7 executable plan
```

## Evidence model

### Method components

L4 output adds a top-level `method_components` list. Each item contains:

- `component_id`: stable slug within the run, such as `cross_species_orthology`;
- `name`: human-readable method name;
- `required`: boolean; only required components participate in the gate;
- `rationale`: why the component is necessary for the proposed analysis.

A valid L4 run must contain at least one required component. Component identifiers must be unique.

### Method candidates

L4 output adds a top-level `method_candidates` list. Each candidate contains:

- `method_id`: stable slug within the run, such as `limma_voom`;
- `component_id`: the method component it addresses;
- `name`: human-readable method name;
- `status`: one of `eligible`, `ineligible`, or `needs_user_source`;
- `applicable_to`: input types or data representations for which it is suitable;
- `assumptions`: explicit statistical or computational assumptions;
- `strengths`: reasons to consider the method;
- `limitations`: known limitations relevant to this project;
- `rejection_reasons`: required when status is `ineligible`;
- `method_anchor_ids`: evidence anchors supporting the candidate.

Method identifiers must be unique. Every required method component must have at least one `eligible` candidate with at least one accepted anchor. An `ineligible` candidate may remain in the catalog to document why it was considered and rejected, but it does not satisfy coverage.

`needs_user_source` means the method is potentially important but cannot yet be audited because a necessary paywalled or locally held source is missing. This status blocks the L4 gate when no other eligible, anchored candidate covers the same required component.

### Method anchors

Each located extract used as an L4 method anchor contains:

- `anchor_id`: stable identifier within the run;
- `method_component_ids`: one or more component IDs covered by the extract;
- `method_ids`: one or more method candidate IDs supported by the extract;
- `source_kind`: one of `primary_study`, `method_paper`, `protocol`, `supplementary_methods`, `official_documentation`, `versioned_code`, or `user_supplied_pdf`;
- the existing `section`, `text`, `locator`, `verification_status`, and source provenance fields.

Existing paper/source records remain the persistence unit to avoid a disruptive rename. Non-journal sources use a stable URL as their identifier and retain the existing title, source database, metadata response, locator, and source payload fields.

Reviews remain valid discovery records but are not accepted as method anchors. Their Results/Conclusion extracts and `review_search` receipt remain useful for method navigation and rationale.

## Final Methods presentation

Methods are presented at three levels rather than collapsed prematurely into one narrative:

### L4 method catalog

The L4 delta contains the complete candidate catalog:

- required components;
- eligible, ineligible, and source-blocked candidates;
- assumptions, strengths, limitations, and input compatibility;
- evidence anchor IDs.

This is the comparison pool consumed by L5 and L6.

### L5 method critique

The L5 delta is keyed by `method_id` and records:

- assumption violations;
- EDA/QC risks;
- required diagnostics;
- failure stop rules;
- recommended modifications or rejection.

L5 does not silently delete L4 candidates. It leaves an auditable critique for each candidate.

### L6 selected methods

The L6 delta contains `selected_methods`, keyed by component ID. Each selection records:

- `selected_method_id`, or an explicit ordered list for a combined strategy;
- the decision rationale;
- rejected alternatives and reasons;
- final parameters;
- software and version requirements;
- scripts needed by L7;
- the method anchor IDs supporting the final choice;
- the L5 QC requirements that L7 must implement.

Only the L6 `selected_methods`/`approved_strategy` becomes executable. The raw Methods excerpts remain in the literature evidence store and are referenced by ID rather than copied wholesale into the execution plan.

## Accepted anchors

An anchor satisfies a required method component only when all of the following hold:

1. The extract has `verification_status: located`, non-empty text, and a non-empty locator.
2. The extract names valid component IDs and method candidate IDs.
3. `source_kind` is in the accepted anchor set above and is not `review` or `abstract`.
4. The source has a DOI, PMID, stable URL, or a registered user-source ID.
5. A real source payload was retained for the retrieved or extracted source.
6. The payload passes authenticity checks and contains the normalized extract text.

For `primary_study`, `supplementary_methods`, and `user_supplied_pdf`, the section must be a recognized Methods heading or Methods subsection. Protocols, method papers, official documentation, and versioned code may use their native section labels because their whole purpose is methodological.

## Source-payload authenticity

RLR must reject obvious placeholder payloads before persistence and before gate evaluation.

Validation rules:

- payload must not be empty;
- UTF-8 payload length must be at least 500 bytes;
- payload must not match known placeholder patterns such as "full text was retrieved" without actual content;
- after whitespace, HTML-entity, Unicode-dash, and case normalization, every anchor extract must be found within the retained payload;
- payload remains capped at the existing 5 MiB limit.

These checks deliberately validate provenance consistency, not scientific correctness. They do not attempt to parse arbitrary PDFs or infer missing text.

## User-supplied PDF workflow

### Storage location

The user places or imports legally obtained PDFs under the project-controlled directory:

```text
09_Literature_Database/user_sources/
```

RLR stores each registered PDF in a candidate-scoped immutable path:

```text
09_Literature_Database/user_sources/<candidate_id>/<sha256-prefix>_<safe-filename>.pdf
```

The original external PDF is never modified.

### Registration command

A new logical CLI subcommand is registered in `research_loop.cli`:

```text
literature-import-pdf <project_dir> <candidate_id> --file <pdf> [--doi ... | --pmid ... | --url ...]
```

The command is independent of the legacy `research_loop_v04.py` filename. Existing users may invoke it through the compatibility shim until a versionless launcher is introduced, but the implementation and documentation refer to the `literature-import-pdf` subcommand itself.

Registration performs only deterministic file handling:

1. verify that the input is a readable PDF;
2. calculate byte size and SHA256;
3. copy it into the immutable candidate-scoped directory;
4. create a sidecar registration record;
5. record DOI, PMID, or stable URL when supplied;
6. mark the source as `registered`, not as accepted evidence.

The sidecar record contains:

- `user_source_id`;
- `candidate_id`;
- original filename;
- stored relative path;
- bytes and SHA256;
- DOI, PMID, or URL if supplied;
- registration timestamp;
- extraction status;
- IDs of later evidence runs that consume it.

A PDF registration never passes L4 by itself.

### Extraction by ARS

On an L4 retry, the prompt includes registered PDFs for that candidate. ARS is instructed to read the local PDF and return:

- `source_kind: user_supplied_pdf`;
- `user_source_id`;
- the registered PDF SHA256;
- extracted text as `source_payload`;
- a located Methods extract with page/section locator;
- covered component IDs and method IDs.

RLR verifies that the returned `user_source_id` and PDF SHA256 match the registration record. It then applies the same payload authenticity and extract-in-payload checks as for online sources.

RLR does not implement its own PDF parser in this change. If ARS cannot extract usable text, the source remains registered but does not satisfy the gate. Scanned PDFs that require OCR are reported explicitly and remain outside this scope.

## Retrieval priority communicated to ARS

The L4 prompt instructs ARS to retrieve sources in this order:

1. registered user-supplied PDFs relevant to currently uncovered components;
2. Europe PMC/PMC JATS XML;
3. publisher open-access HTML/XML;
4. open-access PDF text;
5. Supplementary Methods;
6. protocol or method paper;
7. official software documentation or versioned analysis workflow;
8. preprint full text.

For a paywalled study, ARS may record metadata and use it for navigation, but it must not fabricate a source payload or count abstract text as a method anchor. If a uniquely necessary method remains unsupported, the run records the affected candidate as `needs_user_source` and reports which paper or source is needed.

## L4 prompt behavior

The L4 request becomes a three-part task:

1. identify the critical method components implied by the current question and claim;
2. construct method candidates for every required component;
3. retrieve at least one accepted method anchor for every eligible candidate needed to cover those components.

The prompt explicitly separates biological relevance sources from implementation sources. A relevant primary paper may justify that an analysis is used in the field, while a method paper, protocol, official documentation, versioned code, or user-supplied PDF may provide the reproducible implementation anchor.

## Validation and persistence

`validate_payload` becomes node-aware so L4-specific requirements do not affect L1 or L8.5.

For L4 it validates:

- non-empty, unique method components;
- non-empty, unique method candidates;
- valid component references from candidates;
- valid component and candidate references from anchors;
- at least one eligible, accepted, anchored candidate for every required component;
- allowed source kinds;
- authentic payloads for proposed anchors;
- valid user-source ID and PDF hash for user-supplied anchors;
- no review extract counted as an anchor.

`persist_run` stores method components and method candidates in the run receipt and stores component IDs, candidate IDs, anchor ID, and source kind with each evidence extract. Existing L1/L8.5 records remain readable. Older L4 receipts remain readable for audit history but do not satisfy the new component-level gate unless they contain the new fields.

Registered user PDFs and their sidecar records are immutable. Evidence extraction produces new evidence records; it does not rewrite the source registration.

## Gate behavior

The L4 audit computes coverage by required component and eligible candidate.

It passes only when every required component has at least one eligible candidate with at least one accepted anchor. Failure messages enumerate uncovered components and distinguish:

- no method candidate proposed;
- candidate exists but is ineligible;
- candidate requires a user-provided source;
- no candidate source located;
- source found but no full payload retained;
- payload rejected as placeholder or too short;
- extract not present in source payload;
- only review/abstract/table evidence available;
- component or method reference missing or invalid;
- user-source ID or PDF hash does not match the registration record.

The existing review-search requirement remains. Review evidence supports navigation but never substitutes for candidate coverage.

## Compatibility

- L0 contract schema remains `1.0` and is untouched.
- Deep-research output remains schema `1.0`; the strict schema is extended with L4-only fields rather than globally renaming records.
- L1 and L8.5 behavior remains unchanged.
- Existing immutable evidence files are not rewritten.
- The legacy `research_loop_v04.py` files remain compatibility shims; no new business logic is added to them.
- The current halted real-data run must perform a new L4 retrieval after the change; L0-L3 must not be rerun.

## Files

Expected implementation surface:

- `src/research_loop/deep_research.py`: schema, prompt, validation, normalization, persistence, and L4 audit;
- `src/research_loop/commands/research.py`: PDF registration command handler and L4 source discovery wiring;
- `src/research_loop/cli.py`: register `literature-import-pdf`;
- a focused user-source module if PDF registration would otherwise make `deep_research.py` larger and less cohesive;
- `tests/test_deep_research.py`: RED/GREEN coverage for component coverage and source authenticity;
- focused CLI/user-source tests for registration, immutability, hash binding, and candidate isolation;
- one concise documentation file describing L4 evidence semantics and the PDF workflow, if no suitable existing document exists.

No unrelated refactoring is included.

## Test strategy

Targeted tests must cover:

- all required components covered by primary Methods plus official documentation;
- multiple candidates retained for one component and only later selected by L6;
- method paper, protocol, supplementary Methods, versioned code, and user-supplied PDF anchors;
- review evidence rejected as an anchor;
- abstract `Methods and results` rejected;
- table-only mention rejected;
- placeholder payload rejected;
- payload under 500 bytes rejected;
- extract absent from payload rejected;
- unknown component ID or method ID rejected;
- duplicate component IDs or method IDs rejected;
- one uncovered required component fails with a precise diagnostic;
- optional components do not block the gate;
- PDF registration copies bytes unchanged and records SHA256;
- PDF registration does not itself satisfy L4;
- user-supplied anchor with mismatched source ID or SHA256 is rejected;
- one candidate cannot consume another candidate's registered PDF accidentally;
- existing L1 and L8.5 tests remain green;
- full test suite and `git diff --check` pass.

## Delivery

Implementation will be developed on `feat/l4-method-anchors` using TDD and small commits. A pull request will target `main`. It will merge only after targeted tests, the full suite, and GitHub CI pass. After merge, the existing real-data project will resume at L4 with a new retrieval; earlier nodes and the real-data inputs will not be modified.