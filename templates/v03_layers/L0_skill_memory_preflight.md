# Layer 0 — Skill & Memory Preflight (Boot Gate)

- **Phase:** 0 — Boot Gate
- **Owner:** Linnaeus｜Catalog Master
- **Gate:** No candidate may route to Execution until L0 outputs exist.

## Purpose

Make the project legible and safe before any idea or code. Discover skills,
register inputs/outputs, initialize project memory, and forbid the shortcuts
that broke the first WGCNA loop.

## Entry condition

A v0.4 project exists (`00_Project_Index.md` present).

## Activities

1. Read `AGENTS.md` and skills inventory / plugin lists if present.
2. Find project-specific and task-relevant local skills.
3. Build the skill-use plan (which skill/code pattern serves each later layer).
4. Confirm the Obsidian vault / project folder; create/update memory index.
5. **Verify and register every input from `source_input` in the candidate frontmatter.**
   For EACH input alias, you MUST record in the delta JSON:
   - `path`: the full directory or file path
   - `files`: list of key filenames found at that path (list at least the top 5)
   - `format`: file format (CSV, TSV, RData, XLSX, etc.)
   - `classification`: primary | fallback | reference-only | forbidden
   - `verified`: true/false (did you confirm the files exist?)
   - `notes`: any relevant note (column names, row counts, species mapping)
   If you cannot find a file, set `verified: false` and explain in `notes`.
6. Classify every input: primary / fallback / reference-only / forbidden.

## Required outputs

- `00_Preflight/skill_use_plan.md` (filled with real skills, not placeholders)
- `00_Preflight/input_manifest.md` (every input registered, not placeholders)
- `00_Preflight/output_manifest.md`
- `00_Preflight/forbidden_shortcuts.md`
- Obsidian `07_Obsidian_Sync/00_Obsidian_Index.md`

## Exit condition

All four preflight files exist AND are filled with real project data (not
template placeholders). Route to **L1 (Einstein)**.

## v0.4 Delta Output

`02_Agent_Notes/Linnaeus/L0_linnaeus_delta.json`:

```json
{
  "skills_found": ["academic-research-suite", "bulk-rnaseq"],
  "skills_gaps": [],
  "input_verified": {
    "enhancer_per_species": {
      "path": "D:/R-HK/yigene/chipseq_atac_enhancer/enhancer_per_species/",
      "files": ["Sk_enhancers.csv", "Sm_enhancers.csv", "Rn_enhancers.csv"],
      "format": "CSV",
      "classification": "primary",
      "verified": true,
      "notes": "3 species: Sk, Sm, Rn"
    }
  },
  "environment": {"python": "3.12", "R": "4.x"},
  "skill_use_plan": ["academic-research-suite for L1/L4/L8.5"],
  "forbidden_shortcuts": ["skip L0 preflight", "use unverified inputs"]
}
```

**CRITICAL:** `input_verified` must contain ONE entry per input alias in the
candidate's `source_input`. Each value must be a dict (not a bare string like
"valid"). Missing inputs = incomplete L0 = the loop must not proceed.

## Dependency gate (hard stop)

L0 also runs a **dependency gate**. `preflight` writes `00_Preflight/dependencies.md`
and verifies each required dependency. If any is missing, preflight exits
non-zero and the loop MUST halt at L0 — never skip.

## v0.4 DAG Dependencies

- **Node:** L0_linnaeus (L0)
- **Persona:** Linnaeus (isolated subagent, Path B)
- **Input deltas:** AGENTS.md, skills_inventory, candidate frontmatter (source_input)
- **Isolated from:** all execution notes, all downstream deltas
- **Knowledge base:** read-only (catalogs existing literature)
