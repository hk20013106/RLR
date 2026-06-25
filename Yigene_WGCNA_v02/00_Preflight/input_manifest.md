# Input Manifest (Linnaeus L0)

Project: Yigene_WGCNA_v02
Date: 2026-06-24

## Primary Inputs (verified)

| File | Path | Dimensions | Status |
|------|------|-----------|--------|
| Expression matrix | D:/R-HK/yigene/gemini_out_chamber_species_deg_length_aware/results/length_scaled_counts.csv | 11974 genes x 71 samples | VERIFIED |
| Sample metadata | D:/R-HK/yigene/results_v2/qc/sample_metadata_checked.csv | 95 rows, 71 after filtering | VERIFIED |
| Gene mapping | D:/R-HK/yigene/gemini_out_chamber_species_deg_length_aware/results/gene_symbol_to_mouse_entrez_mapping_used.csv | 11648 rows (rat_symbol, mouse_symbol, mouse_entrez) | VERIFIED |
| DEG results (full) | D:/R-HK/yigene/gemini_out_chamber_species_deg_length_aware/results/DEG_table_length_aware.csv | ~838KB, SmA/SkA/SmV/SkV vs RnA/RnV contrasts | VERIFIED |

## Gene Set Inputs (verified)

Directory: D:/R-HK/yigene/gemini_out_chamber_species_deg_length_aware/results/gene_sets/

| File | Type |
|------|------|
| all4_up_FDR05.csv | All 4 contrasts, upregulated, FDR<0.05 |
| all4_down_FDR05.csv | All 4 contrasts, downregulated, FDR<0.05 |
| atrium_shared_down_FDR05.csv | Atrium shared DEGs (SkA+SmA vs RnA) |
| atrium_shared_up_FDR05.csv | Atrium shared DEGs (SkA+SmA vs RnA) |
| ventricle_shared_down_FDR05.csv | Ventricle shared DEGs (SkV+SmV vs RnV) |
| ventricle_shared_up_FDR05.csv | Ventricle shared DEGs (SkV+SmV vs RnV) |
| Sk_AV_shared_down_FDR05.csv | Sk AV shared (both chambers) |
| Sk_AV_shared_up_FDR05.csv | Sk AV shared (both chambers) |
| Sm_AV_shared_down_FDR05.csv | Sm AV shared (both chambers) |
| Sm_AV_shared_up_FDR05.csv | Sm AV shared (both chambers) |
| SmA_vs_RnA_down_FDR05.csv | Sm atrium vs Rn atrium |
| SmA_vs_RnA_up_FDR05.csv | Sm atrium vs Rn atrium |
| SmV_vs_RnV_down_FDR05.csv | Sm ventricle vs Rn ventricle |
| SmV_vs_RnV_up_FDR05.csv | Sm ventricle vs Rn ventricle |
| SkA_vs_RnA_down_FDR05.csv | Sk atrium vs Rn atrium |
| SkA_vs_RnA_up_FDR05.csv | Sk atrium vs Rn atrium |
| SkV_vs_RnV_down_FDR05.csv | Sk ventricle vs Rn ventricle |
| SkV_vs_RnV_up_FDR05.csv | Sk ventricle vs Rn ventricle |
| MSBio_Hallmark_TERM2GENE_current_universe.csv | Hallmark gene sets for enrichment |
| MSBio_Hallmark_TERM2NAME.csv | Hallmark term names |

## Reference Inputs

| File | Path | Purpose |
|------|------|---------|
| CRASH_LOG.md | D:/R-HK/yigene/scripts_wgcna_loop/CRASH_LOG.md | 8 documented WGCNA-on-Windows crash points and fixes |
| Existing WGCNA scripts | D:/R-HK/yigene/scripts_wgcna_loop/stepA-D | v0.1 scripts that ran successfully (all-sample network) |
| Existing WGCNA outputs | D:/R-HK/yigene/results_wgcna_loop/all_sample/ | all-sample network results from v0.1 first cycle |

## Sample Summary (verified from metadata)

- Total samples after filtering: 71
- Species: Rn (Rattus norvegicus, rat, low heart rate) = 24 (8A + 16V)
- Species: Sk (Scotophilus kuhlii, lesser yellow bat, high heart rate) = 23 (7A + 16V)
- Species: Sm (Suncus murinus, house shrew, high heart rate) = 24 (8A + 16V)
- Sex: F=36, M=35
- Batch: batch1=59, batch2=12
- Unique animal_id: 12
- Chambers: Atrium (A) = 23, Ventricle (V) = 48 (Apex included in V)

## Forbidden Inputs

- HF (heart failure) samples: excluded by include_evolution_main filter
- ADM samples: heart failure model, not normal evolution
- Mixed-tissue or non-heart samples (per bat-heart-target-screen skill rules)
