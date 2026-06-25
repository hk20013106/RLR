# Codex Desktop File-Writing: Failure Modes, Root Causes, and Reliable Methods

Date: 2026-06-24
Context: Codex Desktop on Windows/PowerShell, creating R scripts, Python scripts, and Markdown docs

## Failure Modes Observed

### 1. apply_patch Add File / Update File failures
- Symptom: 'The first line of the patch must be *** Begin Patch' or 'invalid hunk header'
- Root cause: Long content, or content containing lines like '===' or '@@', confuses the patch parser
- Fix: Do not use apply_patch for files longer than ~50 lines or containing markdown headers with ===
- Status: unreliable for large files

### 2. PowerShell here-string with Set-Content / pipe failures
- Symptom: 'ParserError: Unexpected token' or 'Missing expression after unary operator'
- Root cause: PowerShell parses the ENTIRE command line before executing. Content lines starting with - or containing / or special chars get misinterpreted as PowerShell operators, even inside here-strings in some contexts
- Fix: Never pipe here-string content directly to Set-Content or python -c for complex content
- Status: unreliable for content with special characters

### 3. Python triple-quote inside PowerShell here-string
- Symptom: 'SyntaxError: unterminated triple-quoted string'
- Root cause: Python triple-quotes inside a PowerShell @'...'@ here-string can confuse the boundary detection
- Fix: Avoid mixing Python triple-quotes with PowerShell here-strings
- Status: unreliable

## What Actually Works (verified multiple times)

### Method: Python script file with string list + join

Step 1: Create a .py file using Set-Content with a SINGLE line of Python code
Step 2: The .py file uses a list of strings and .join() to build content, then open().write()
Step 3: Execute the .py file with python

Example pattern:
  Set-Content -Path _writer.py -Value 'lines=[]; lines.append("line1"); ...; open("output.md","w").write("\n".join(lines))'
  python _writer.py

Why it works:
- Set-Content with a single-line Python expression avoids multiline parsing issues
- Python string list avoids triple-quote problems
- The .py file is executed by python, not by PowerShell

### Alternative: Python -c with open().write() for short content
  python -c "open('file.md','w').write('content here')"
  Works for content under ~200 chars with no quotes/newlines

## Next Execution Steps (L7 Turing handoff to Claude Code)

The RLR v0.2 first cycle ended at REVISE. The analysis_needed field lists 6 items:

1. Atrium-only WGCNA (23 samples: 8 Rn + 7 Sk + 8 Sm)
   - Reuse stepA-D pattern from all-sample network
   - Check if 23 samples is sufficient for WGCNA (min 15 recommended)
   - Soft power may differ from all-sample (test 1-20)

2. Ventricle-only WGCNA (48 samples: 16 Rn + 16 Sk + 16 Sm)
   - Same pattern, larger sample size = more reliable

3. Module preservation: Sk modules vs Sm modules
   - Use WGCNA::modulePreservation()
   - Run on all-sample network first (Sk as reference, Sm as test)
   - Key metric: Zsummary > 10 = strong preservation, 2-10 = moderate
   - This directly answers: do bat and shrew share co-expression modules?

4. Gene set overlap (Fisher exact test)
   - WGCNA modules vs DEG gene sets in gene_sets/
   - Key sets: atrium_shared_up/down, ventricle_shared_up/down
   - A module overlapping atrium_shared = convergent atrial module candidate

5. GO/KEGG enrichment per module
   - clusterProfiler::enrichGO and enrichKEGG
   - Gene mapping: gene_symbol_to_mouse_entrez_mapping_used.csv
   - Universe: all genes in the WGCNA network
   - Verify if turquoise = metabolic/OXPHOS, yellow/brown = species-specific

6. Power sensitivity analysis
   - Compare module structure at power=1 (auto) vs power=4 (forced)
   - Report module count, size distribution, trait correlations for both
   - Justify power=4 choice or switch to power=1 if artifacts found

## Environment (unchanged from round 1)
- R 4.6.0 at D:/Programs/R/R-4.6.0/bin/Rscript.exe
- R library: D:/R-HK/Seurat5_lib (must add via .libPaths BEFORE library())
- cor = WGCNA::cor (namespace conflict fix)
- WGCNA::disableWGCNAThreads() + nThreads=1 (Windows crash fix)
- No sink() (causes silent crashes)
- colnames(datExpr) = gene names, rownames(datExpr) = sample names
- Output dirs must be pre-created
- Scripts must be split into modular steps (stepA/B/C/D pattern)

## Key Data Paths
- Expression: D:/R-HK/yigene/gemini_out_chamber_species_deg_length_aware/results/length_scaled_counts.csv
- Metadata: D:/R-HK/yigene/results_v2/qc/sample_metadata_checked.csv
- DEG gene sets: D:/R-HK/yigene/gemini_out_chamber_species_deg_length_aware/results/gene_sets/
- Gene mapping: D:/R-HK/yigene/gemini_out_chamber_species_deg_length_aware/results/gene_symbol_to_mouse_entrez_mapping_used.csv
- Existing all-sample results: D:/R-HK/yigene/results_wgcna_loop/all_sample/
- Scripts dir: D:/R-HK/yigene/scripts_wgcna_loop/
- RLR project: D:/research_loop/Yigene_WGCNA_v02/

## Claude Code Prompt for Next Execution

You are working in D:/R-HK/yigene. The RLR v0.2 project is at D:/research_loop/Yigene_WGCNA_v02/.
Read D:/R-HK/yigene/HANDOFF_WGCNA_RLR_V02_EXECUTION.md for the full execution plan.
Existing all-sample WGCNA results are in results_wgcna_loop/all_sample/ (stepA-D pattern).
Create new scripts in scripts_wgcna_loop/ for: atrium WGCNA, ventricle WGCNA, module preservation, gene set overlap, GO/KEGG enrichment, power sensitivity.
Run each script and report results. Write outputs to results_wgcna_loop/atrium/ and results_wgcna_loop/ventricle/.
After completion, update the RLR project with execution notes.
