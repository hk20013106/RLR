# L1 Pre-Research Prompt — ARS Deep Research (literature-grounded hypotheses)

> RLR v0.5b · node **L1** (Einstein) · literature engine: **academic-research-skills (ARS)**.
> Fill the `{{...}}` placeholders from the candidate frontmatter + L0 input manifest
> before running. This prompt produces the artifact RLR v0.5b will hard-gate; it
> does NOT itself prove the tool ran — RLR validates the resulting file.

## How to invoke ARS

- **Claude Code:** ensure ARS is installed
  (`/plugin marketplace add Imbad0202/academic-research-skills` then
  `/plugin install academic-research-skills`), then run ARS **Deep Research in
  literature-review mode** (e.g. `/ars-lit-review`, or the deep-research harness)
  on the brief below.
- **Codex CLI:** the sibling distribution `academic-research-skills-codex`
  exposes the same workflow content as `$academic-research-suite`; invoke that.

## Brief

You are doing **literature-grounded hypothesis generation** for this candidate —
NOT a generic literature summary.

- Title: {{title}}
- Question: {{question}}
- Claim: {{claim}}
- Our actual data / input manifest (from L0): {{input_manifest}}

Requirements:
1. Use ARS Deep Research / lit-review mode to find and read the relevant primary
   literature (mechanisms, prior findings, comparable systems).
2. **Connect each literature finding to our actual data** — do not report
   findings that cannot touch our input manifest.
3. From that grounding, propose candidate **hypotheses**, each with an
   **expected signal** in our data and an explicit **falsification condition**.
4. Register every cited paper in the growable DB so its citekey resolves:
   `python manage_literature_db.py add {{project_dir}} --round {{round}} --json-data "<one-line JSON>"`
   and cite via `[[09_Literature_Database/<citekey>|Title]]`.

Write the result to: `{{project_dir}}/02_Agent_Notes/_pre_research/L1_research.md`

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

For L1:
- hypothesis implications:
- data-specific constraints:
- hypotheses not supported by literature:
- unresolved uncertainties:

## Query log

The ACTUAL search queries you issued (one bullet per query, verbatim). If a
query returned zero results, record it explicitly — do NOT omit it:

- <query string> (e.g. "0 results" when empty)

## Tool receipt

One bullet per tool invocation: tool name, timestamp, one-line return summary:

- tool: <name> | time: <ISO-8601> | summary: <what it returned>

## Source count

<integer> — number of distinct sources actually retrieved (0 is allowed and
must be stated, not hidden).

---

> RLR v0.5b will reject L1 unless this file exists, contains a non-empty
> `## Runtime digest` with at least one DOI/PMID/URL, references citekeys that
> resolve in `09_Literature_Database/` (or inline in the digest), and the L1
> delta carries `literature_used` with per-hypothesis `literature_basis`.
