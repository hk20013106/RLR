## File-Write Failure Patterns and Execution Plan

Date: 2026-06-24
Project: D:\research_loop

---

## 1. Recurring File-Write Failures and Root Causes

### 1.a apply_patch failures

- `*** Begin Patch` / `*** End Patch` format errors
- Lines starting with `===` in content misinterpreted as hunk headers
- `@`` context marker expectations for Update File
- apply_patch reports `Success` but writes empty file (the worst case)
- Root cause: apply_patch cannot handle large file content reliably in this environment

### 1.b PowerShell here-string failures

- lines starting with `-` cause `ParserError: Missing expression after unary operator`
- content with `$` gets interpolated even in `@\'...''`
- Python triple-quote inside here-string causes `SintaxError: unterminated triple-quoted string`
- Root cause: PowerShell and Python/R have overlapping syntax (`$`, `()`, `-`, `@**`)

---

## 2. Reliable Method (proven)

### Method A: python -c with base64 (TESTED + RELIABLE)

```powershell
python -c "import base64; open('path', 'wb').write(base64.b64decode('b64 string'))"
```

- No quote conflicts, no here-string needed
- Works for any content type (R, Markdown, Python)
- Limit: command-line length (generate b64 outside this tool)

### Method B: Python script file via Set-Content ++ execute

1. Write the .py script using `set-variable -name file -value `ScriptBlob`
2. Execute: `python file.py`
3. The .py script uses `open().write()` to create target files

- Reliable for multiple files
- Avoid here-string for the .py script itself (use script file)

### Method C: EveroS memory store (for durable facts)

- Store the fix pattern as a durable fact in EverOS
- `$env:EVEROS_AGENT_ID='codex'; C\Users\hk200\everos-mem.bat add "fact"`

---

## 3. Execution Steps for WGCNA Second Round

The RLR v0.2 first cycle resulted in REVISE for the following gaps:

1. Atrium-only WGCNA (23 samples)
2. Ventricle-only WGCNA (48 samples)
3. Module preservation Sk vs Sm
4. Gene set overlap (Fisher exact)
5. GO/KEGG enrichment per module
6. Power sensitivity check

### Scripts needed (in D:\RHK\yigene\scripts_wgcna_loop\)

- `stepA_build_network.R` - EXISTS (all-sample)
- `stepB_trait_correlation.R`  - EXISTS (all-sample)
- `stepC_hub_genes.R`         - EXISTS (all-sample)
- `stepD_heatmaps.R`          - EXISTS (all-sample)
- `atrium_wgcna.R`       - NEW
- `ventricle_wgcna.R`      - NEW
- `step_atrium_hub.R`     - NEW
- `step_ventricle_hub.R`    - NEW
- `p_atrium.R`              - NEW (routine stepA to stepD)
- `p_ventricle.R`           - NEW
- `overlap_genesets.R`   - NEW
- `enrichment_go_kegg.R`  - NEW
- `sensitivity_power.R`  - NEW

### Key parameters (proven from round 1)

- `.libPaths(c("D/R-HK/Seurat5_lib", .libPaths()))` first
- `cor <- WGCNA::cor` (edgR/limma namespace conflict)
- `WGCNA::disableWGCNAThreads()` + `nThreads=1`
- `rownames(datExpr)` = sample names, `colnames(datExpr`` = gene names
- `networkType="unsigned"`, `TOTType="unsigned"`
- `power=4` (auto picks 1, but 4 gives 5 good modules)
- `maxBlockSize=6000`, `minModuleSize=30`, `mergeCutHeight=0.25`
- `saveTOMs=FALSE`
- No `sink()` (causes silent crashes)
- Output dirs PRE-created before running

### Execution routine

There are 3 ways to run the analyses:

#### Option A: Claude Code (for R script creation + execution)

Provided the following prompt:

```
You are working in D:\r\HK\yigene. Read HANDOFF_WGCNA_RLR_V02_EXECUTION.md for full spec.
Reads current WGCNA outputs in results_wgcna_loop\all_sample\.
Create atrium and ventricle WGCNA scripts, module preservation, gene set overlap, and GO/KEGG enrichment.
Rgene names are in colnames(datExpr) not rownames.
Run all scripts, save outputs to results_wgcna_loop\atrium\ and \ventricle\.
```

#### Option B: Server (ssh myserver)

- Upload scripts to /hpcfile/home/hk/bat_heart_rnseq
- Run on HPC (multiple cores)
- Retrieve results
- Prefer'd for heavy WGCNA (blockwiseModules is CPU-intensive)

#### Option C: Direct execution in codex
- Use exec_command with Rscript
- Works for short scripts
- LHd with debugging loops as seen in round 1

---

## 4. Lessons Learned (for future RLR cycles)

1. Route through Linneus (L)0° not skip to C or fore-through to Linnaeus again
-  Linnaeus finds skills and inputs - not doing this repeats the v0.1 mistake
2. Split complex scripts into modular steps (see round 1 crash log)
3. Use power=4 for unsigned network (autopick 1 gives poor modules)
4. `colnames(datExpr)` = gene names, not `rownames`
5. Replace NA with 0 in binary trait columns before cor()
6. `WGCNA::disableWGCNAThreads()` + `nThreads=1` on Windows
7. No `sink()` on Windows R
8. For atrium (n=23) and ventricle (n=48), check if WGCNA is feasible (min samples ~15)
9. Gene set overlap uses Fisher exact test not just counts
0. Go/KEGG enrichment needs orth.Me.eg.db + clusterProfiler
