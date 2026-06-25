# Forbidden Shortcuts (Linnaeus L0)

Project: Yigene_WGCNA_v02
Date: 2026-06-24

## Hard Forbidden Actions

1. **No skipping L0 preflight** - skill_use_plan and input_manifest must exist before any candidate work
2. **No jumping to Execution** - must pass through L1-L6 (idea triage + method triage) first
3. **No monolithic scripts** - WGCNA scripts must be split into modular steps (learned from v0.1 crash)
4. **No sink() in R scripts** - causes silent crashes on Windows (CRASH_LOG.md crash 6)
5. **No WGCNA multithreading** - disableWGCNAThreads() + nThreads=1 required (CRASH_LOG.md crash 5)
6. **No rownames(datExpr) for gene names** - use colnames(datExpr) (v0.1 crash 8 root cause)
7. **No NA in binary trait columns** - replace NA with 0 before cor() (v0.1 crash 8 secondary bug)
8. **No infinite retry loops** - max 2 retries on same file-write/debug method, then handoff to Claude Code
9. **No overwriting raw inputs** - length_scaled_counts.csv and sample_metadata_checked.csv are read-only
10. **No scientific conclusions from Turing** - Turing reports execution results only, no interpretation

## Conditional Forbidden (context-dependent)

- Do NOT use signed network type unless justified (v0.1 showed unsigned gives 5 modules, signed gives 0 at power=8)
- Do NOT use auto power=1 without checking module structure (power=4 gives 5 well-sized modules)
- Do NOT claim modules as ECM/OXPHOS/sarcomere/etc without enrichment analysis
- Do NOT claim convergent evolution without checking BOTH atrium and ventricle subnetworks

## Memory Rules

- EverOS memory: search before substantive work, add only durable cross-tool facts
- Obsidian: link to outputs, do not duplicate large files
- CRASH_LOG.md: update with any new crash points for future skill updates
