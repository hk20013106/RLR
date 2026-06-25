# Layer L10c - Aggregate Report (Linnaeus)

- **Phase:** 4 - Result Review Loop (terminal)
- **Owner:** Linnaeus | Catalog Master (separate subagent instance from L0)

## Purpose

Read ALL delta JSON files in DAG order and generate the final report
(FINAL_REPORT.md + FINAL_REPORT_CN.md). Replaces manual report writing.

## DAG dependencies (v0.3)

- ALL delta files: L0, L1, L2, L3, L4, L5, L6, L7, L8, L9a, L9b, L10a, L10b

**Isolated from:** none (aggregation node sees everything).

## Output

- `FINAL_REPORT.md` (English)
- `FINAL_REPORT_CN.md` (Chinese)
- If a report already exists, write a timestamped copy (no overwrite).

## Command

```
python research_loop_v03.py aggregate-report PROJECT_DIR CAND_ID
```

## Forbidden

No new analysis, no interpretation, no status change. Linnaeus only aggregates.
