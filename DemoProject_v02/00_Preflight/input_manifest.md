---
project_name: DemoProject_v02
preflight_file: input_manifest.md
owner: Linnaeus
created_at: "2026-06-24T00:56:27"
---

# Input Manifest — DemoProject_v02

> Maintained by **Linnaeus｜Catalog Master** (L0 boot gate). Linnaeus organizes
> and registers; he never interprets data or runs code.

## Input classification

Classify every input as: **primary**, **fallback**, **reference-only**, or
**forbidden**. Execution may only consume primary/fallback inputs.

| file / path | role | classification | notes |
|-------------|------|----------------|-------|
| _e.g. results/length_scaled_counts.csv_ | expression matrix | primary | length-scaled |
| _e.g. raw fastq_ | reads | forbidden | do not touch raw |

## Required inputs for execution

_List the inputs the approved plan must have before the Execution Gate opens._
