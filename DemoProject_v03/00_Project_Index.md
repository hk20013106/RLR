---
project_name: DemoProject_v03
topic: RLR v0.3 DAG demo
version: 0.3.0
framework: gated-multi-loop-council-v03
created_at: "2026-06-25T11:27:55"
---

# DemoProject_v03 - Research Loop Room v0.3 Index

Topic: RLR v0.3 DAG demo

## Council (10 personas)

Linnaeus | Catalog Master, Einstein | Conceptual Explorer, Feynman | Reality Checker, Oppenheimer | Cold Director, Fisher | Design Architect, Tukey | EDA Scout, Turing | Execution Engine, Curie | Evidence Auditor, Darwin | Evolutionary Biologist, Jobs | Story Strategist

## DAG Topology (14 nodes L0-L10c)

- **L0 Skill & Memory Preflight** - Linnaeus
- **L1 Idea Divergence** - Einstein
- **L2 Idea Falsification** - Feynman
- **L3 Candidate Triage Decision** - Oppenheimer
- **L4 Method Brainstorm** - Fisher
- **L5 Method Falsification / Skill Match** - Tukey
- **L6 Analysis Plan Decision** - Oppenheimer
- **L7 Execution** - Turing
- **L8 Evidence Audit** - Curie
- **L9a Result Falsification** - Feynman
- **L9b Biology Interpretation** - Darwin
- **L10a Value Assessment** - Jobs
- **L10b Final Decision** - Oppenheimer
- **L10c Aggregation & Report** - Linnaeus

## Statuses

NEW, IDEA_PROPOSED, IDEA_REJECTED, IDEA_SELECTED, METHOD_PROPOSED, METHOD_REJECTED, METHOD_APPROVED, NEEDS_EXECUTION, EXECUTED, UNDER_REVIEW, KEEP, REVISE, DOWNGRADE, DROP, ARCHIVED

## Hard Invariants

- Only **Oppenheimer** changes candidate status.
- Only **Turing** executes code, and only after the Execution Gate passes.
- Execution Gate requires: `00_Preflight/skill_use_plan.md`,
  `00_Preflight/input_manifest.md`, and an approved plan (status METHOD_APPROVED).
- Each persona runs as an isolated subagent (v0.3).
- State flows between subagents via delta JSON files only.

## DAG Node Flow

L0 Linnaeus -> L1 Einstein -> L2 Feynman -> L3 Oppenheimer
-> L4 Fisher -> L5 Tukey -> L6 Oppenheimer -> L7 Turing
-> L8 Curie -> L9a Feynman || L9b Darwin -> L10a Jobs
-> L10b Oppenheimer -> L10c Linnaeus (FINAL_REPORT)

## Boot Gate (00_Preflight/)

Run `preflight` before any candidate work.

## Obsidian

Run `obsidian-sync` to copy delta JSON + FINAL_REPORT to vault.
