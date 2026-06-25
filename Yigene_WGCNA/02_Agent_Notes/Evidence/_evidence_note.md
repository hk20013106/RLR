# Evidence Agent Note — Evaluate WGCNA results against original claim

## Original claim
WGCNA reveals conserved co-expression modules (ECM/collagen, OXPHOS, sarcomere, immune, fatty acid)
whose eigengenes correlate with species, chamber, AV_group, and shared DEG patterns.

## What the data shows

### Module-trait correlations (verified from CSV)

1. **Species separation is strong**: turquoise r=-0.96 (species), yellow r=+0.92 (species)
   - This confirms modules separate by species, but does NOT yet confirm the specific
     biological categories claimed (ECM, OXPHOS, sarcomere, immune, fatty acid).

2. **Chamber signal exists**: green module chamber r=-0.64, but this is moderate, not strong.
   - Atrium-only and ventricle-only networks are needed to test chamber-specific modules.

3. **High heart rate signal**: turquoise r=-0.95, brown r=+0.80
   - This is a proxy for species (Sk/Sm = high HR, Rn = low HR), so it may be confounded.

4. **Sk_vs_Rn and Sm_vs_Rn**: blue (Sk r=+0.87), yellow (Sm r=+0.98), brown (Sk r=+0.91)
   - These are species-contrast traits, so high correlation is expected, not surprising.

### What is NOT yet evidenced

- **No functional enrichment performed**: the claim mentions specific biological categories
  (ECM, OXPHOS, sarcomere, immune, fatty acid). Without GO/KEGG enrichment, we cannot
  confirm these categories map to the 5 modules.
- **No gene set overlap analysis**: the claim mentions "shared DEG patterns". The gene_sets/
  directory has all4_up, all4_down, atrium_shared, ventricle_shared, Sk_AV_shared, Sm_AV_shared.
  No overlap test has been run yet.
- **Only 1 of 3 networks built**: all_sample is done, but atrium-only and ventricle-only
  are missing. The claim about chamber-specific modules cannot be fully evaluated.

### Hub genes — preliminary signal

- blue top hub: Gapdhs (glycolysis), Chrnb1 (cholinergic receptor) — not clearly OXPHOS/sarcomere
- Full hub gene interpretation requires enrichment analysis

## Evidence verdict

**PARTIAL**: The network construction is valid and module-trait correlations are real.
However, the specific biological category claims (ECM, OXPHOS, sarcomere, immune, fatty acid)
are NOT yet supported by functional enrichment or gene set overlap.
The claim is plausible but unverified at the module-function level.

## Recommended next steps for Evidence

1. Run GO/KEGG enrichment on each of the 5 modules (clusterProfiler + org.Mm.eg.db)
2. Run Fisher exact test: module genes vs DEG gene sets (all4_up, all4_down, etc.)
3. Build atrium-only and ventricle-only networks
4. Compare module overlap across the 3 networks
