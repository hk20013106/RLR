# User PDF Script and Methods Documentation Design

## Goal

Make user-supplied PDF handling operational and visible. The repository must provide a simple registration script, and every human-readable Methods artifact must explain each method and its evidence clearly enough for later L5/L6 comparison.

## Registration script

Create a thin user-facing script:

```text
scripts/import_literature_pdf.py
```

Usage:

```powershell
python scripts/import_literature_pdf.py <project_dir> <candidate_id> `
  --file "D:\papers\paper.pdf" `
  [--doi "10.xxxx/xxxx" | --pmid "12345678" | --url "https://..."]
```

The script must contain no duplicated registration logic. It imports a package function from a focused module such as `research_loop.user_sources` and returns machine-readable JSON.

Successful output must include:

- `user_source_id`;
- `candidate_id`;
- stored relative path;
- original filename;
- byte size;
- SHA256;
- supplied DOI/PMID/URL;
- `status: registered`;
- a statement that registration alone does not satisfy L4.

Registration is idempotent for the same candidate and identical PDF hash. It must not overwrite a different file, mutate the source PDF, or allow one candidate to consume another candidate's registered file without an explicit new registration.

The package CLI also exposes the same operation as `literature-import-pdf`, but the standalone script is the documented convenience entry point and does not use the versioned `research_loop_v04.py` name.

## Storage and sidecar

Registered PDFs are copied byte-for-byte to:

```text
09_Literature_Database/user_sources/<candidate_id>/<sha256-prefix>_<safe-filename>.pdf
```

A JSON sidecar beside the PDF records provenance, identifiers, registration timestamp, extraction status, and consuming evidence-run IDs. The PDF and initial registration record are immutable.

## Human-readable Methods artifacts

The implementation must not leave method information only in JSON receipts. It must generate or update these Markdown surfaces:

### 1. Static user guide

Create:

```text
docs/L4_METHOD_EVIDENCE.md
```

It must explain:

- what a method component, method candidate, and method anchor are;
- which evidence source kinds are accepted;
- how to run `scripts/import_literature_pdf.py`;
- where the PDF and sidecar are stored;
- why registration alone does not pass L4;
- how ARS extracts Methods from a registered PDF;
- how hash and extract consistency are verified;
- what to do when a PDF is scanned or extraction fails;
- how L4, L5, and L6 use the resulting evidence.

### 2. L4 layer instructions

Update:

```text
templates/layers/L4_method_brainstorm.md
```

The template must require every proposed method candidate to explain:

- purpose and the hypothesis/component addressed;
- required input type and data representation;
- main analytical steps;
- assumptions;
- expected outputs;
- strengths for this project;
- limitations and failure modes;
- feasible alternatives;
- evidence-anchor IDs and source kinds;
- whether a user PDF is required;
- the exact registration command when a source is missing.

A method name plus citation is not sufficient.

### 3. Generated L4 Markdown catalog

The existing human-readable L4 evidence-run summary under:

```text
09_Literature_Database/evidence_packs/runs/<run_id>.md
```

becomes the canonical L4 method catalog. For every component it presents all candidates in comparable sections, not only the recommended candidate.

Each candidate section must include:

1. method name and stable `method_id`;
2. status: `eligible`, `ineligible`, or `needs_user_source`;
3. scientific/analytical purpose;
4. applicable input and prerequisites;
5. implementation outline;
6. assumptions;
7. expected outputs;
8. strengths;
9. limitations and failure conditions;
10. alternatives;
11. evidence anchors with source title, source kind, locator, and verification status;
12. user-source status and exact import command when applicable.

The Markdown must state explicitly that L4 builds a candidate pool, L5 critiques it, and L6 selects the executable method.

### 4. L6 selected-method presentation

The final selected Methods representation must remain distinct from the L4 catalog. L6 records the selected method or combined strategy, parameters, software/version requirements, scripts, rejected alternatives, L5 QC obligations, and supporting anchor IDs. It references raw excerpts by ID rather than copying large copyrighted passages.

## Tests

Add tests that verify:

- the standalone script and package CLI return the same registration data;
- script output contains hash, stored path, status, and the non-passing warning;
- duplicate registration is idempotent;
- candidate isolation is enforced;
- static documentation contains a working command example and registration caveat;
- the L4 template requires all method-description fields listed above;
- generated L4 Markdown contains all candidates, evidence provenance, missing-source instructions, and the exact PDF import command;
- L6 output identifies the final selection without deleting the L4 comparison record.

## Scope boundary

This addition does not implement PDF text extraction, OCR, or network retrieval inside RLR. ARS performs extraction; RLR registers the source and validates provenance and returned text.