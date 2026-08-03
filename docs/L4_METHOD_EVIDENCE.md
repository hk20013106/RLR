# L4 Methods Evidence and User PDF Workflow

The formal DAG still contains one L4 node and retains the `L4_fisher` storage
key. Internally, the method-planning pipeline is staged:

```text
L4A: metadata discovery and frozen asset selection
→ L4B: strict evidence construction and method candidate catalog
→ L4C: Fisher method design (`L4_fisher` delta)
→ L4.5: deterministic lineage validation and commit
→ L5: candidate-level EDA/QC critique
→ L6: selected methods and frozen execution plan
→ L7: execute only the approved plan
```

L4A/L4B/L4C/L4.5 are auditable internal stages, not additional formal DAG
nodes. There is no L3.5 and L5-L10 are not renumbered.

## Reuse-first implementation

RLR does not duplicate mature literature and parsing systems.

- L4A uses the configured Academic Research Skills runtime for metadata-only
  discovery and persists `L4ADiscoveryManifest/v1`.
- L4B delegates source retrieval, Methods extraction, source-payload retention,
  method-candidate construction, and anchor verification to the existing
  `deep_research.py`, `method_evidence.py`, review-navigation, and registered
  user-source implementations.
- L4C remains the existing Fisher cognitive node and existing delta contract.
- L4.5 calls no model. It revalidates the exact L4A manifest, L4B evidence
  artifact manifest, and persisted L4C delta hash before the native L4
  transaction finalizes.

Literature-search MCP, Zotero, GROBID, Docling, PaperQA2, and similar projects
may be attached through replaceable adapters. They are not vendored or added as
heavy base dependencies.

## L4A discovery manifest

L4A stores metadata and selection receipts only. Its schema includes paper
identifiers, source database responses, abstract when available, open-access
and full-text status, relevance score, selection status, and rationale.

L4A cannot emit:

- source payloads;
- verbatim evidence extracts;
- method components or candidates;
- method anchors;
- a final analysis plan.

The immutable manifest is written under:

```text
09_Literature_Database/l4/discovery/manifests/
```

Deduplication uses DOI, then PMID, then stable URL, then normalized title and
year. Duplicate records remain recorded in the manifest. L4B receives a
canonical frozen catalog containing only L4A-selected assets and may resolve
those assets or registered local sources; it may not silently broaden the
corpus.

## Core L4B objects

A **method component** is a necessary part of the analysis, such as cross-species orthology mapping, differential-expression modelling, co-expression analysis, or enrichment testing.

A **method candidate** is one possible implementation of a component. Each candidate records its purpose, compatible inputs, steps, assumptions, outputs, strengths, limitations, alternatives, and evidence anchors.

A **method anchor** is a located, verifiable source excerpt that supports how a candidate is implemented. Accepted source kinds are:

- primary-study Methods;
- method paper;
- protocol;
- Supplementary Methods;
- official software documentation;
- versioned code or workflow;
- verified user-supplied PDF.

A review may identify or compare methods, but it does not independently satisfy the reproducible-method requirement. Abstract labels such as `Methods and results`, table-only mentions, retrieval placeholders, and unlocated summaries are not accepted anchors.

For staged evidence packs, every audit and context manifest also revalidates
the linked L4A file and includes its exact file SHA256. Deleting or altering the
discovery manifest invalidates the L4B evidence pack.

## L4.5 deterministic commit

L4.5 runs inside the existing native L4 finalize boundary. It projects only
component, method, and anchor IDs already present in L4B and writes an immutable
`L45MethodCommit/v1` artifact under:

```text
08_Audit/l4_method_commits/
```

It verifies:

1. the staged L4B artifact points to an existing L4A manifest;
2. the persisted L4A contents and manifest hash match the L4B linkage;
3. the existing strict L4B evidence audit passes;
4. the exact L4B evidence artifact manifest is available;
5. the persisted `L4_fisher` delta still has the recorded SHA256.

Identical retries are idempotent. A collision or lineage mismatch fails closed.
Because L4.5 executes before the hypothesis commit receipt is written, failure
aborts the native L4 persistence transaction. Legacy evidence packs without the
staged pipeline marker retain their previous behavior.

## Registering a user-supplied PDF

Use this when a necessary paper is paywalled or otherwise unavailable to ARS, but you have legally obtained the PDF.

```powershell
python scripts/import_literature_pdf.py <project_dir> <candidate_id> `
  --file "D:\papers\paper.pdf" `
  [--doi "10.xxxx/xxxx" | --pmid "12345678" | --url "https://..."]
```

Example:

```powershell
python scripts/import_literature_pdf.py `
  "D:\research_loop\runs\four_species_hhr_v09_round1_20260801_212158" `
  C20260801212333507290 `
  --file "D:\papers\method-paper.pdf" `
  --doi "10.xxxx/example"
```

The script verifies that the candidate exists and that the file has PDF magic bytes, then calculates its byte size and SHA256. It copies the bytes unchanged to:

```text
09_Literature_Database/user_sources/<candidate_id>/<sha256-prefix>_<filename>.pdf
```

A JSON sidecar beside the PDF records:

- `user_source_id`;
- candidate ownership;
- original and stored filenames;
- byte size and SHA256;
- DOI, PMID, or stable URL when supplied;
- registration time;
- extraction status;
- consuming evidence-run IDs.

Re-registering the same bytes for the same candidate is idempotent. A source registered for one candidate cannot be consumed by another candidate without a separate registration.

## What registration does not do

Registration alone does **not** satisfy the L4 gate. It proves only file identity, integrity, and candidate ownership.

On the next L4B evidence-construction run, ARS receives the registered source ID, path, and SHA256. ARS must read the local PDF and return:

- `source_kind: user_supplied_pdf`;
- the exact `user_source_id` and PDF SHA256;
- extracted source text;
- a located Methods excerpt with section and page/paragraph locator;
- the method component IDs and candidate method IDs supported by the excerpt.

RLR then verifies:

1. the source belongs to the current candidate;
2. the returned SHA256 matches the registered PDF;
3. the retained source text is substantive rather than a placeholder;
4. the located excerpt occurs in that retained source text;
5. the section is Methods or a Methods subsection;
6. the anchor references valid method components and candidates.

Only after these checks can the excerpt become a `user_supplied_pdf` method anchor.

## Extraction failures

If ARS cannot extract usable text, the source remains registered but does not satisfy L4. Common causes include:

- scanned image-only PDF;
- encrypted or damaged PDF;
- missing Methods pages;
- text extraction that destroys the excerpt/locator relationship.

OCR is outside the current RLR scope. The failure report must identify the affected method component and candidate rather than silently accepting weak evidence.

## How Methods are presented

The generated L4B Markdown catalog is stored with the evidence run:

```text
09_Literature_Database/evidence_packs/runs/<run_id>.md
```

For every method candidate it presents:

- stable method ID and status;
- purpose and addressed component;
- applicable input and prerequisites;
- implementation steps;
- assumptions;
- expected outputs;
- strengths;
- limitations and failure conditions;
- alternatives;
- evidence anchors, source kinds, and locators;
- missing-source status and the exact PDF registration command when needed.

L4C Fisher uses this validated catalog to design the project-specific method
plan. L5 critiques the plan and candidates without deleting the comparison
record. L6 records the final selection, rejected alternatives, parameters,
software versions, scripts, required QC checks, and supporting anchor IDs. Raw
source excerpts remain in the evidence store and are referenced by ID rather
than copied wholesale into the execution plan.
