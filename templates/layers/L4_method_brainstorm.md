# L4 — Method Candidate Catalog

## Purpose

Build a comparison pool of feasible analysis or experimental methods for the selected hypotheses. L4 does not approve the final method: L5 critiques every eligible candidate, and L6 selects the executable strategy.

## Required structure

For every required method component, retain all serious alternatives. Each method candidate must state:

1. stable `method_id` and the component/hypotheses addressed;
2. analytical purpose;
3. required input type and data representation;
4. prerequisites and main implementation steps;
5. statistical, biological, and computational assumptions;
6. expected outputs;
7. strengths for this project;
8. limitations and failure modes;
9. feasible alternatives;
10. status: `eligible`, `ineligible`, or `needs_user_source`;
11. evidence-anchor IDs, source kinds, and located source references;
12. whether a user-supplied PDF is required.

A method name plus a citation is not a sufficient method description.

## Evidence boundary

- Accept located anchors from primary Methods, method papers, protocols, Supplementary Methods, official documentation, versioned code, or a verified user-supplied PDF.
- Reviews may guide method discovery and comparison, but do not independently satisfy a method anchor.
- Abstract headings, table mentions, placeholder full-text payloads, and unlocated summaries do not count.
- Keep raw excerpts in the evidence store and reference them by anchor/evidence ID rather than copying large passages into the method plan.

## User-supplied PDF

When a necessary source is not openly available, state exactly which candidate/component is blocked and give the registration command:

```powershell
python scripts/import_literature_pdf.py <project_dir> <candidate_id> `
  --file "D:\papers\paper.pdf" `
  [--doi "10.xxxx/xxxx" | --pmid "12345678" | --url "https://..."]
```

Registration stores the PDF under:

```text
09_Literature_Database/user_sources/<candidate_id>/
```

Registration alone never satisfies L4. ARS must extract located Methods text, and RLR must verify the candidate binding, PDF SHA256, locator, and extract-to-source consistency.

## Handoff

Provide the complete candidate catalog and evidence references for L5. Do not silently delete ineligible alternatives, approve a final plan, run code, or imply that a proposed method has succeeded.

## Full-mode role

The current dynamic contract is authoritative for inputs, output schema, state changes, and runtime commands.
