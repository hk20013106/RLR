---
kind: round_starting_point
round: 3
parent_candidate_id: C20260625155135814538
created_at: 2026-06-25
---

# Round 3 Starting Point

Combines the Round 2 L10 summary (the loop's own conclusion) with the user's new
methodological guidance. This is the input anchor for the Round 3 candidate.

## Part A — Round 2 L10 summary (the loop's own conclusion)

**L10b decision:** KEEP, evidence MODERATE-STRONG.
**Headline (L10a):** "High heart-rate bat and shrew converge on a mitochondrial
energy-metabolism co-expression module" — derived from an **all_sample** WGCNA
network (turquoise module; GSEA NES -2.80 mitochondrial respiratory chain,
-2.71 translation; ECM score correlates green r=+0.69, turquoise r=+0.41; signed
network confirms turquoise persists).
**Open next-steps carried in:** KEGG rerun, signed-vs-unsigned overlap,
permutation GSEA p-values, hub-gene STRING, final report.

## Part B — User guidance for Round 3 (methodological control)

The Round 1-2 conclusions rest on an **all_sample** network. Chamber identity
(atrium vs ventricle) is almost certainly the **dominant expression axis**, so a
module that "tracks high heart rate" in an all_sample network can be confounded
by tissue composition rather than reflecting a true cross-species convergence.
Round 3 controls for this:

1. **Build two tissue-context-controlled networks** (already built; see
   `D:/R-HK/yigene/results_wgcna_loop/{atrium,ventricle}/`):
   - **atrium-only WGCNA** — LA/RA (or merged atrial samples).
   - **ventricle-only WGCNA** — LV/RV/SP (or merged ventricular samples).

2. **Within each network, examine the species/heart-rate contrasts** so the
   interpretation is "species/heart-rate difference *within the same tissue
   context*":
   - `Sk_vs_Rn`, `Sm_vs_Rn`, `high_heart_rate`, `all_pattern`, `shared pattern`.

3. **The all_sample network is supplementary only.** It may show that
   atrium-vs-ventricle is the largest expression axis, or that some modules are
   conserved across chambers — but it must **not** be used to directly support
   "high-heart-rate animals co-upregulate module X". That claim must come from
   the within-tissue (atrium-only / ventricle-only) networks.

## Round 3 question

Within tissue-context-controlled networks (atrium-only and ventricle-only
WGCNA), does a co-expression module track the high-heart-rate species contrast
(Sk/Sm vs Rn) within each tissue context — and is the all_sample "convergence"
partly an artifact of the atrium-vs-ventricle axis?
