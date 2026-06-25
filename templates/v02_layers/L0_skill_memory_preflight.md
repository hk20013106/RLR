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
python research_loop_v02.py preflight PROJECT_DIR
```
