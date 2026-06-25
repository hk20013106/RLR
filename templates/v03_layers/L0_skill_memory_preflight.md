# Layer 0 — Skill & Memory Preflight (Boot Gate)

- **Phase:** 0 — Boot Gate
- **Owner:** Linnaeus｜Catalog Master
- **Gate:** No candidate may route to Execution until L0 outputs exist.

## Purpose

Make the project legible and safe before any idea or code. Discover skills,
register inputs/outputs, initialize project memory, and forbid the shortcuts
that broke the first WGCNA loop.

## Entry condition

A v0.2 project exists (`00_Project_Index.md` present).

## Activities

1. Read `AGENTS.md` and skills inventory / plugin lists if present.
2. Find project-specific and task-relevant local skills.
3. Build the skill-use plan (which skill/code pattern serves each later layer).
4. Confirm the Obsidian vault / project folder; create/update memory index.
5. Classify every input: primary / fallback / reference-only / forbidden.

## Required outputs

- `00_Preflight/skill_use_plan.md`
- `00_Preflight/input_manifest.md`
- `00_Preflight/output_manifest.md`
- `00_Preflight/forbidden_shortcuts.md`
- Obsidian `07_Obsidian_Sync/00_Obsidian_Index.md`

## Exit condition

All four preflight files exist. Route to **L1 (Einstein)**.

## Command

```
python research_loop_v03.py preflight PROJECT_DIR
```


---

## v0.3 DAG Dependencies

- **Node:** L0_linnaeus (L0)
- **Persona:** Linnaeus (isolated subagent)
- **Input deltas:** AGENTS.md, skills_inventory, data paths
- **Isolated from:** all execution notes

In v0.3 this layer runs as a subagent that receives only the deltas above
as embedded context (Path B). It does not access the filesystem. It emits a
single delta JSON instead of Markdown notes.

## v0.3 Delta Output

`02_Agent_Notes/Linnaeus/L0_linnaeus_delta.json`:

```json
{
  "skills_found": list,
  "skills_gaps": list,
  "input_verified": dict,
  "environment": dict,
  "skill_use_plan": list,
  "forbidden_shortcuts": list
}
```
## Dependency gate (hard stop)

L0 also runs a **dependency gate**. `preflight` writes `00_Preflight/dependencies.md`
(framework deps: PyYAML; declare project deps as `- python: X` / `- command: X`
under "## Required") and verifies each. If any **required dependency is missing,
preflight exits non-zero and the loop MUST halt at L0** — never skip. Re-run
`preflight` (or `check-deps PROJECT`) after installing it.
