---
project_name: Yigene_WGCNA_v02
topic: "Cross-species WGCNA: convergent co-expression modules in high heart-rate species (bat Sk + shrew Sm)"
version: 0.2.0
framework: gated-multi-loop-council
created_at: "2026-06-24T01:12:49"
---

# Yigene_WGCNA_v02 — Research Loop Room v0.2 Index

Topic: Cross-species WGCNA: convergent co-expression modules in high heart-rate species (bat Sk + shrew Sm)

## Council (10 personas)

Linnaeus｜Catalog Master, Einstein｜Conceptual Explorer, Feynman｜Reality Checker, Oppenheimer｜Cold Director, Fisher｜Design Architect, Tukey｜EDA Scout, Turing｜Execution Engine, Curie｜Evidence Auditor, Darwin｜Evolutionary Biologist, Jobs｜Story Strategist

## Gated Loop (Layers 0–10)

- **L0 Skill & Memory Preflight** — Linnaeus
- **L1 Idea Divergence** — Einstein
- **L2 Idea Falsification** — Feynman
- **L3 Candidate Triage Decision** — Oppenheimer
- **L4 Method Brainstorm** — Fisher
- **L5 Method Falsification / Skill Match** — Tukey
- **L6 Analysis Plan Decision** — Oppenheimer
- **L7 Execution** — Turing
- **L8 Evidence Audit** — Curie
- **L9 Result Falsification + Biology** — Feynman/Darwin
- **L10 Value + Final Decision + Memory** — Jobs/Oppenheimer/Linnaeus

## Statuses

NEW, IDEA_PROPOSED, IDEA_REJECTED, IDEA_SELECTED, METHOD_PROPOSED, METHOD_REJECTED, METHOD_APPROVED, NEEDS_EXECUTION, EXECUTED, UNDER_REVIEW, KEEP, REVISE, DOWNGRADE, DROP, ARCHIVED

## Hard Invariants

- Only **Oppenheimer** changes candidate status.
- Only **Turing** executes code, and only after the Execution Gate passes.
- Execution Gate requires: `00_Preflight/skill_use_plan.md`,
  `00_Preflight/input_manifest.md`, and an approved plan (status METHOD_APPROVED).
- **Linnaeus** runs first (L0 boot gate); no route to Execution before L0 + L6.
- Agent notes are append-only and auditable; no hidden chain-of-thought.

## Boot Gate (00_Preflight/)

Run `preflight` before any candidate work: creates skill_use_plan.md,
input_manifest.md, output_manifest.md, forbidden_shortcuts.md.

## Obsidian

Run `obsidian-sync` to (re)build `07_Obsidian_Sync/00_Obsidian_Index.md`,
which links to outputs rather than duplicating them.
