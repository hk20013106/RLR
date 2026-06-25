# L10 Linnaeus - Memory & Knowledge Registry

## Project: Yigene_WGCNA_v02 (Cross-species WGCNA convergent heart modules)

### Key parameters proven on Windows R 4.6.0
- R library: D:/R-HK/Seurat5_lib via .libPaths() before library()
- cor <- WGCNA::cor (namespace conflict fix)
- WGCNA::disableWGCNAThreads() + nThreads=1 (Windows crash fix)
- No sink() (causes silent crashes)
- colnames(datExpr) = gene names, rownames(datExpr) = sample names
- Unsigned network, power=4 (auto=1 gives poor modules)
- maxBlockSize=6000, minModuleSize=30, mergeCutHeight=0.25
- Split into stepA/B/C/D modular scripts (crash-safe)

### Data provenance
- Expression: gemini_out_chamber_species_deg_length_aware/results/length_scaled_counts.csv (11974 genes x 71 samples)
- Metadata: results_v2/qc/sample_metadata_checked.csv
- DEG sets: gene_sets/ (18 sets + Hallmark)
- Gene mapping: gene_symbol_to_mouse_entrez_mapping_used.csv (11648 rows)
- Species: Sk (bat, high HR), Sm (shrew, high HR), Rn (rat, low HR)
- Chambers: atrium (n=23), ventricle (n=48)

### Results registry
- All-sample: 5 modules + grey (5000 genes, power=4)
- Atrium: 4 modules + grey (exploratory, n=23)
- Ventricle: 5 modules + grey (n=48)
- Convergent modules: turquoise (heart-rate anti-correlated, ventricle-down DEG, Z=16.9) + brown (heart-rate correlated, atrium-up DEG, Z=4.5)
- Green module: cardiac identity (GO: muscle tissue development), Z=20.2 but no DEG overlap
- Preservation: nPermutations=50 (feasibility, raise to 200+ for publication)
- Enrichment: only green module had significant GO terms (universe-size effect on large modules)

### Skills/memory to update
1. WGCNA-on-Windows crash patterns are fully documented in CRASH_LOG.md
2. RLR v0.2 flow: L0->L10 walked successfully on real data
3. File-writing lesson: use Set-Content for Markdown, avoid apply_patch for >50 lines, avoid Python open().write() in PowerShell pipes
4. Species-heart-rate confound is inherent to 3-species design; needs 4th species to resolve
5. Module preservation is the key evidence for convergence (not trait correlation alone)
