# L4 Methods Evidence and User PDF Workflow

L4 creates an evidence-backed catalog of method candidates. It does not make the final method decision.

```text
L4: method components + candidates + evidence anchors
→ L5: candidate-level EDA/QC critique
→ L6: selected methods and frozen execution plan
→ L7: execute only the approved plan
```

## Core objects

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

On the next L4 deep-research run, ARS receives the registered source ID, path, and SHA256. ARS must read the local PDF and return:

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

The generated L4 Markdown catalog is stored with the evidence run:

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

L5 critiques these candidates without deleting the comparison record. L6 records the final selection, rejected alternatives, parameters, software versions, scripts, required QC checks, and supporting anchor IDs. Raw source excerpts remain in the evidence store and are referenced by ID rather than copied wholesale into the execution plan.
