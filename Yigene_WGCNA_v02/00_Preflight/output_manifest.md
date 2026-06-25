# Output Manifest (Linnaeus L0)

Project: Yigene_WGCNA_v02
Date: 2026-06-24

## Expected Output Directory

D:/R-HK/yigene/results_wgcna_v02/

## Expected Outputs (by analysis step)

### Network Construction (per network: all-sample, atrium-only, ventricle-only)

| Output | Format | Description |
|--------|--------|-------------|
| {network}_network.RData | RData | Full network object: datExpr, net, moduleColors, MEs, gene_names, soft_power |
| {network}_module_assignment.csv | CSV | Gene-to-module mapping (5000+ genes) |
| {network}_module_eigengenes.csv | CSV | Sample-level eigengene values |
| {network}_sample_dendrogram.pdf | PDF | Sample clustering dendrogram |
| {network}_soft_threshold.pdf | PDF | Scale-free topology fit plot |

### Module-Trait Correlations

| Output | Format | Description |
|--------|--------|-------------|
| {network}_module_trait_correlation.csv | CSV | Module x trait correlation matrix |
| {network}_module_trait_heatmap.pdf | PDF | Heatmap of module-trait correlations |

### Hub Genes

| Output | Format | Description |
|--------|--------|-------------|
| {network}_hub_genes.csv | CSV | Per-module top genes by kME |

### Functional Enrichment

| Output | Format | Description |
|--------|--------|-------------|
| {network}_{module}_GO_enrichment.csv | CSV | GO enrichment per module |
| {network}_{module}_KEGG_enrichment.csv | CSV | KEGG enrichment per module |

### Module-DEG Overlap

| Output | Format | Description |
|--------|--------|-------------|
| module_deg_overlap.csv | CSV | Fisher exact test: module vs each DEG gene set |
| module_deg_overlap_heatmap.pdf | PDF | Heatmap of overlap significance |

### Convergent Module Analysis (CORE QUESTION)

| Output | Format | Description |
|--------|--------|-------------|
| convergent_modules_atrium.csv | CSV | Modules shared between Sk and Sm in atrium |
| convergent_modules_ventricle.csv | CSV | Modules shared between Sk and Sm in ventricle |
| convergent_module_summary.pdf | PDF | Summary figure of convergent modules |

### Execution Reports

| Output | Format | Description |
|--------|--------|-------------|
| execution_report.md | MD | Turing execution report |
| crash_log.md | MD | Any crashes encountered (update existing CRASH_LOG.md) |

## Trait Matrix Columns (for module-trait correlation)

- species (Rn=1, Sk=2, Sm=3)
- chamber (A=1, V=2)
- high_heart_rate (Rn=0, Sk=1, Sm=1)
- Sk_vs_Rn (binary, no NA - fixed from v0.1 bug)
- Sm_vs_Rn (binary, no NA - fixed from v0.1 bug)
- all4_pattern (Sk or Sm = 1, Rn = 0)
- atrium_shared (Sk/Sm and A = 1, else 0)
- ventricle_shared (Sk/Sm and V = 1, else 0)
