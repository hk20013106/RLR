# L4a Pre-Research Prompt — ARS Deep Research (method literature review)

> RLR v0.5b · node **L4a** (Curie) · literature engine: **academic-research-skills (ARS)**.
> Fill the `{{...}}` placeholders before running. This produces the artifact RLR
> v0.5b hard-gates; it does NOT prove the tool ran — RLR validates the file.

## How to invoke ARS

- **Claude Code:** with ARS installed
  (`/plugin marketplace add Imbad0202/academic-research-skills`,
  `/plugin install academic-research-skills`), run ARS **Deep Research in
  method-focused literature-review mode** (e.g. `/ars-lit-review` scoped to
  methodology) on the brief below.
- **Codex CLI:** use the sibling `academic-research-skills-codex` distribution,
  which exposes the same workflow content as `$academic-research-suite`.

## Brief

You are doing a **method literature review** for this candidate. **Do NOT design
the final analysis yet. Do NOT execute code.**

- Title: {{title}}
- Question: {{question}}
- Our actual data / input manifest (from L0): {{input_manifest}}
- Hypotheses to support (from L1): {{l1_hypotheses}}

Extract, from how others analyzed comparable data:
1. **Methods** used (statistics, models, pipelines) and their **assumptions**.
2. **Pitfalls** and how they failed / were mitigated.
3. **Null / background choices** (what universe others tested against).
4. **Statistical constraints** relevant to OUR data shape and sample sizes.

Register every cited paper so its citekey resolves:
`python manage_literature_db.py add {{project_dir}} --round {{round}} --json-data "<one-line JSON>"`
and cite via `[[09_Literature_Database/<citekey>|Title]]`.

Write the result to: `{{project_dir}}/02_Agent_Notes/_pre_research/L4a_research.md`
(note the `a` — RLR v0.5b reads `L4a_research.md`, not `L4_research.md`).

---

## Required RLR output contract (this file MUST end with the two sections below)

## Runtime digest

For each paper/source:

- citekey:
- DOI/PMID/URL:
- title:
- year:
- core finding:
- relevance to current candidate/data:
- downstream implication:
- caveat / limitation:

## RLR handoff summary

For L4a:
- method constraints:
- methods suitable for current data:
- methods to avoid:
- null/background recommendations:
- QC/failure rules implied by literature:

---

> RLR v0.5b will reject L4a unless this file exists, contains a non-empty
> `## Runtime digest` with at least one DOI/PMID/URL and resolving citekeys, and
> the L4a delta carries `method_literature_digest`.
