# Codex Desktop Recurring Failures — Lessons Log

Date: 2026-06-24
Project: D:\research_loop (RLR v0.2 + WGCNA)
Purpose: Record recurring error patterns so they stop repeating, and feed future skill updates.

---

## Pattern 1: apply_patch fails on large/complex files

**Symptoms:**

- "The first line of the patch must be *** Begin Patch"
- "invalid hunk header"
- Reports success but writes empty file (worst case)

**Root cause:** apply_patch cannot reliably handle files > ~50 lines, or content containing lines that look like patch syntax (===, @@, ***).

**Fix (proven):**

- Do NOT use apply_patch for files > 50 lines or with markdown headers containing ===
- Use Python script file: write a .py that does open(path,'w').write(content), then run it
- Or use python -c with base64 encoding for binary-safe content

**Status:** This is the MOST RECURRING error. It happened again while writing THIS file. Must stop using apply_patch for large files.

---

## Pattern 2: Codex Desktop enters dead loops / silent stops

**Symptoms:**

- Repeats the same failed command 3+ times without changing approach
- Silently stops mid-task (context exhaustion or crash)
- User has to say "you stopped again" multiple times

**Root cause:**

- No state checkpointing: when context compacts, lost track of what was done
- Retry without diagnosis: same command, same error, no variable changed
- Large file creation attempts eat context budget, causing premature stop

**Fix:**

- After 2 failures on the same command, STOP and switch method
- Write progress to a state file before each major step
- If file creation is the bottleneck, hand off to Claude Code immediately
- Never retry the exact same command more than twice

---

## Pattern 3: WGCNA on Windows R 4.6.0 silent crashes

**9 crash points documented in CRASH_LOG.md. Key ones:**

1. cor namespace conflict: edgeR/limma mask WGCNA::cor -> Fix: cor <- WGCNA::cor
2. Multithreading crash: enableWGCNAThreads() kills R on Windows -> Fix: disableWGCNAThreads() + nThreads=1
3. sink() causes deadlock -> Fix: no sink(), use cat() + flush.console()
4. rownames vs colnames: datExpr is samples x genes, so colnames = gene names -> Fix: use colnames(datExpr) for genes
5. NA in traits: 3-species binary traits have NA for other species -> Fix: replace NA with 0 before cor()
6. include_evolution_main: CSV stores "True"/"False" as string, not logical -> Fix: as.logical() before filtering

**Lesson:** WGCNA "silent crashes" were never silent — they were standard R errors masked by monolithic scripts. Splitting into stepA/B/C/D made every error visible and recoverable.

---

## Pattern 4: Phase discipline violations

**Symptom:** Jumping to execution (L7 Turing) without completing preflight (L0 Linnaeus), or skipping method approval (L6 Oppenheimer).

**Fix:** RLR v0.2 enforces this structurally now (execution-gate exits 1 unless METHOD_APPROVED + skill_use_plan + input_manifest exist). But the agent must still not try to bypass gates.

---

## Action Items for Skill Update

1. Create a "wgcna-windows" skill from CRASH_LOG.md patterns
2. Create a "codex-file-write-fallbacks" skill from Pattern 1+2
3. Add "max 2 retries then switch method" as a hard rule in AGENTS.md
4. The _next_seq bug (D0001 overwriting) was fixed in v0.2 but exists in v0.1 — v0.1 now deleted, so resolved

---

## Verified Working Configurations

### WGCNA on Windows

- .libPaths(c("D:/R-HK/Seurat5_lib", .libPaths())) FIRST
- cor <- WGCNA::cor after loading packages
- WGCNA::disableWGCNAThreads() + nThreads=1
- No sink()
- colnames(datExpr) = gene names
- power=4 (auto picks 1, but 4 gives 5 good modules)
- unsigned network, maxBlockSize=6000, minModuleSize=30, mergeCutHeight=0.25
- Split into stepA/B/C/D, each saves own RData
- Output dirs pre-created

### File creation in Codex Desktop

- < 50 lines: apply_patch OK
- > 50 lines: Python script file method (write .py, run it)
- > 200 lines: hand off to Claude Code
- Never use PowerShell here-string for R/Python code with $, -, @, or triple quotes
