---
report_id: X-L7-yigene-wgcna-20260624
project: Yigene_WGCNA_v02
agent: Turing
layer: L7 Execution
created_at: 2026-06-24T01:54:00
---

# Execution Report — Yigene_WGCNA_v02 L7 (6 follow-up analyses)

> Written by **Turing｜Execution Engine**. Reports exactly what was run and
> produced; draws no scientific conclusion (that is Curie/Darwin/Jobs at L8–L10).

Source plan: `D:/R-HK/yigene/HANDOFF_L7_EXECUTION.md`. All 6 approved scripts
built and run in order; **all exited 0**. Parameters held constant with round 1
(unsigned, power=4 forced, maxBlockSize=6000, minModuleSize=30,
mergeCutHeight=0.25, nThreads=1, `cor <- WGCNA::cor`, no `sink()`).

## Input files (registered, primary)

- Expression: `gemini_out_chamber_species_deg_length_aware/results/length_scaled_counts.csv`
- Metadata: `results_v2/qc/sample_metadata_checked.csv`
- Round-1 network: `results_wgcna_loop/all_sample/all_sample_network.RData` (71×5000, 5 modules + grey)
- Round-1 stepB: `results_wgcna_loop/all_sample/all_sample_stepB.RData` (module-trait cor)
- DEG sets: `…/results/gene_sets/*_FDR05.csv` (18 sets)
- Gene map: `…/results/gene_symbol_to_mouse_entrez_mapping_used.csv` (rat_symbol → mouse_entrez)

## Scripts (in `scripts_wgcna_loop/`)

| # | Script | Purpose | Status |
|---|--------|---------|--------|
| 1 | `02_run_wgcna_atrium.R` | Atrium-only WGCNA (n=23) | ✅ 4 modules + grey |
| 2 | `03_run_wgcna_ventricle.R` | Ventricle-only WGCNA (n=48) | ✅ 5 modules + grey |
| 3 | `04_module_preservation.R` | Sk↔Sm preservation of all-sample modules | ✅ both directions |
| 4 | `05_gene_set_overlap.R` | Module × DEG-set Fisher exact | ✅ 108 tests |
| 5 | `06_go_kegg_enrichment.R` | GO (BP/MF/CC) + KEGG per module | ✅ KEGG online |
| 6 | `07_convergent_module_summary.R` | Combine (a)+(b)+(c) criteria | ✅ |

(`_wgcna_subset_common.R` is a sourced helper shared by scripts 1 & 2.)

## Actions & key results

### 1–2. Chamber-specific networks
- **Atrium** (Rn8/Sk7/Sm8 = 23): 10,150 genes pass filterByExpr → top-5000 MAD →
  **4 modules** (turquoise 1581, blue 1537, brown 1186, yellow 621; grey 75).
  *Feasibility flag: n=23 is small for WGCNA; treat atrium modules with caution.*
- **Ventricle** (16/16/16 = 48): 9,423 genes → top-5000 MAD → **5 modules**
  (turquoise 1533, blue 1232, yellow 872, brown 921, green 386; grey 56).
- Outputs: `results_wgcna_loop/{atrium,ventricle}/<label>_network.RData`,
  `_module_assignment.csv`, `_module_eigengenes.csv`, `_soft_threshold.pdf`.
- Note: auto soft-power estimate = 1 in both subsets (as in round 1); power forced
  to 4 for cross-network comparability. Subset voom design simplified to `~0+group`
  (single chamber; avoids rank deficiency from sex/batch on small n) — a documented
  deviation from the all-sample design.

### 3. Module preservation (Sk ↔ Sm), nPermutations = 50
`results_wgcna_loop/preservation/preservation_summary.csv` (Zsummary: ≥10 strong, ≥2 moderate)

| module | size | Z(Sk→Sm) | Z(Sm→Sk) | Z_min | preservation |
|--------|-----:|---------:|---------:|------:|--------------|
| green | 179 | 20.23 | 21.55 | 20.23 | **strong** |
| turquoise | 1720 | 20.40 | 16.90 | 16.90 | **strong** |
| blue | 1440 | 12.28 | 9.57 | 9.57 | moderate→strong |
| brown | 1257 | 7.11 | 4.51 | 4.51 | moderate |
| yellow | 291 | 2.52 | 3.16 | 2.52 | moderate |

(`gold` = WGCNA random-gene benchmark, `grey` = unassigned; both reported by the
tool but excluded from interpretation. nPermutations=50 is a feasibility setting —
raise to ≥100 for publication.)

### 4. Gene-set overlap (Fisher exact, universe = 5000 WGCNA genes, BH-adjusted)
`results_wgcna_loop/overlap/overlap_matrix.csv` (108 tests = 6 modules × 18 sets).
Strongest enrichments: **turquoise** with `ventricle_shared_down` (OR 5.9, p_adj 1e-146),
`all4_down`, `atrium_shared_down`; **brown** with `Sk_AV_shared_up`, `atrium_shared_up`.

### 5. GO + KEGG over-representation (clusterProfiler, org.Mm.eg.db, mmu)
`results_wgcna_loop/enrichment/` — 4831/5000 genes (96.6%) mapped to mouse Entrez.
- **green**: 49 GO-BP, 15 GO-MF, 1 KEGG significant term(s) → `green_GO_BP.csv`, `green_GO_MF.csv`, `green_KEGG.csv`.
- blue/brown/turquoise/yellow: 0 significant terms.
- **Caveat (statistical, not biological):** the large modules each span ~¼–⅓ of the
  4831-gene universe, so over-representation against that universe is underpowered;
  the absence of enriched terms there is expected, not evidence of "no function."
  Only the compact green module gives clean enrichment.

### 6. Convergent modules
`results_wgcna_loop/reports/convergent_module_summary.csv`. Criteria: (a) module-trait
corr with `high_heart_rate` p<0.05; (b) Sk↔Sm Z_min≥2; (c) BH<0.05 overlap with an
atrium_shared/ventricle_shared DEG set.

| module | hhr_cor | hhr_p | (a) | Z_min | (b) | best shared set | (c) | **convergent** |
|--------|--------:|------:|:---:|------:|:---:|-----------------|:---:|:--------------:|
| turquoise | −0.955 | 5e-38 | ✓ | 16.90 | ✓ | ventricle_shared_down | ✓ | **YES** |
| brown | +0.799 | 7e-17 | ✓ | 4.51 | ✓ | atrium_shared_up | ✓ | **YES** |
| yellow | +0.611 | 2e-08 | ✓ | 2.52 | ✓ | — | ✗ | no |
| green | −0.524 | 3e-06 | ✓ | 20.23 | ✓ | — | ✗ | no |
| blue | +0.008 | 0.95 | ✗ | 9.57 | ✓ | — | ✗ | no |

→ **Convergent modules: turquoise, brown.**

## Output files

```
results_wgcna_loop/
├─ atrium/      atrium_{network.RData, module_assignment.csv, module_eigengenes.csv, soft_threshold.pdf}
├─ ventricle/   ventricle_{network.RData, module_assignment.csv, module_eigengenes.csv, soft_threshold.pdf}
├─ preservation/ Sk_ref_Sm_test_preservation.csv, Sm_ref_Sk_test_preservation.csv,
│                preservation_summary.csv, module_preservation.RData
├─ overlap/     overlap_matrix.csv
├─ enrichment/  enrichment_summary.csv, green_GO_BP.csv, green_GO_MF.csv, green_KEGG.csv
└─ reports/     convergent_module_summary.csv
```

## Warnings

- Atrium WGCNA n=23 is small; modules are exploratory.
- Preservation used nPermutations=50 (feasibility).
- GO/KEGG under-powered for the large modules (universe-size effect).
- Subset networks used a simplified `~0+group` voom design (documented).

## Failures

None. All 6 scripts exited 0. KEGG REST was reachable (online).

## Recommended next route (for Oppenheimer)

→ **L8 Curie (Evidence Audit):** verify preservation thresholds, the overlap
universe choice, and the GO universe-size caveat; assign evidence level.
→ **L9 Feynman/Darwin:** turquoise (high-rate-correlated, ventricle-down DEG,
strongly preserved) and brown (atrium-up DEG) are the convergent candidates;
request partial-correlation vs chamber and biological interpretation of the
green module's enriched GO terms.
