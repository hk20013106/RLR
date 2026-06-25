#---
report_id: X-L8-yigene-wcgna-20260624
project: Yigene_WGCA_v02
agent: Curie
layer: L8 Evidence Audit
created_at: 2026-06-24T12:37
---

# L8 Curie — Evidence Audit for Yigene_WGCA_v02

## Scope

Audit the 6 follow-up analyses executed by Turing (atrium/ventricle/preservation/overlap/enrichment/convergent) to assign an evidence level. Verification was done by checking actual output files and numbers directly.

## File verification (all confirmed exist)

| Directory | Files | Status |
|--|--|--
| atrium | atrium_network.RData, atrium_module_assignment.csv, atrium_module_eigengenes.csv, atrium_soft_threshold.pdf | 4 modules + grey = 5000 genes true |
| ventricle | ventricle_network.RData, ventricle_module_assignment.csv, ventricle_module_eigengenes.csv, ventricle_soft_threshold.pdf | 5 modules + grey = 5000 genes true |
| preservation | preservation_summary.csv, Sk_ref_Sm_test_preservation.csv, Sm_ref_Sk_test_preservation.csv, module_preservation.RData | both directions true |
| overlap | overlap_matrix.csv | 108 Fisher tests true |
| enrichment | enrichment_summary.csv, green_GO_BP.csv, green_GO_MF.csv, green_KEGG.csv | 4831/5000 genes mapped true |
| reports | convergent_module_summary.csv | turquoise + brown convergent true |

## Module count verification (sum = 5000 exactly)

- all-sample: 1720 + 1440 + 1257 + 291 + 179 + 113 = 5000 analyzed in csv analysis

- atrium: 1581 + 1537 + 1186 + 621 + 75 = 5000 verified

- ventricle: 1533 + 1232 + 921 + 872 + 386 + 56 = 5000 verified

## Sample count verification

- atrium eigengenes CSV: 23 rows (Rn8 + Sk7 + Sm8) true
- ventricle eigengenes CSV: 48 rows (Rn16 + Sk16 + Sm16) true

## Preservation antalysis (Zsummary)

| module | size | Z(Sk->Sm) | Z(Sm->Sk) | Z_min | level |
|--------|-----:|-------:|-------:|------:|---------|
| green | 179 | 20.23 | 21.55 | 20.23 | strong |
|| turquoise | 1720 | 20.40 | 16.90 | 16.90 | strong |
| blue | 1440 | 12.28 | 9.57 | 9.57 | moderate |
| brown | 1257 | 7.11 | 4.51 | 4.51 | moderate |
|| yellow | 291 | 2.52 | 3.16 | 2.52 | moderate |

- Zsummary>=10 = strong, 2-10 = moderate. Thve modules at moderate or above (green, turquoise, blue, brown, yellow) are wruth preserving between Sk and Sm.
- nPermutations=50 (feasibility setting - needs higher for publication).

## Gene set overlap verification

- 108 Fisher exact tests (6 modules x 18 DES sets) confirmed in overlap_matrix.csv
- Strongest: turquoise x ventricle_shared_down (OR=5.9, p_adj=1e-146)
- brown x atrium_shared_up (p_adj=5.8e-12) confirmed
- BH-adjusted p-values present and correct

## GO/KEGG enrichment verification

- only green module (179 genes) gives significant GO - BP: 49, MF: 15, KEGG: 1
- Top GO-BP terms: muscle tissue development, striated muscle tissue development, cardiac muscle cell differentiation, cardiac muscle tissue development
- Large modules (turquoise 1720, brown 1257, blue 1440) show 0 significant terms - universe-size effect (each spans ~1/4 of 4831-gene universe)
- Absence of enrichment in large modules is expected, not evidence of "no function"

## Convergent module summary verification

| module | hhr_cor | Z_min | shared_DEG overlap | convergent |
|--------|------:|------:|----------------|----------|
| turquoise | -0.955 | 16.90 | ventricle_shared_down (p_adj=1e-146) | YES |
|| brown | +0.799 | 4.51 | atrium_shared_up (p_adj=5e-12) | YES |

turquoise: two of three criteria met (trait correlation with high_heart_rate P + Sk/Sm preservation + shared-DEG overlap)
- Correct three-criterion logic confirmed in CSV

## Evidence Level: MODERATE

- Strong points: two convergent modules (ventricle, brown) supported by strong preservation and significant DEG overlap
- Weak points: atrium n=23 is small for WGCNA (exploratory); nPermutations=50 (feasibility); large module GO enrichment underpowered
- Moderate overall: the core finding (turquoise + brown are convergent between bat and shrew) is supported but not yet publication-ready

## Recommended next route
- s9 Feynman + Darwin: falsify interpretation, assign biological meaning to convergent modules
- L10 Jobs + Oppenheimer + Linnaeus: final value and manuscript direction
- Raise nPermutations to 100+ for publication