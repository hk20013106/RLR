# L1 Einstein — Idea Divergence

## Candidate hypotheses

### H1 (PRIMARY): Convergent atrial co-expression modules
Sk (bat) and Sm (shrew) share atrial co-expression modules that are absent or weak in Rn (rat). These modules represent convergent molecular signatures of high-rate atrial adaptation.

### H2: Convergent ventricular co-expression modules
Same logic but for ventricle. 48 ventricular samples (16 per species) provide better statistical power than atrium (23 samples, 7-8 per species).

### H3: Whole-heart convergent signature
Sk and Sm share modules in BOTH chambers. Less specific than H1/H2 but possible if the convergent pressure is systemic.

### H4: Shared modules enriched for energy metabolism
High heart rate demands high ATP. Convergent modules should be enriched for OXPHOS, fatty acid oxidation, and mitochondrial genes.

### H5: Shared modules enriched for calcium handling
Direct relevance to heart rate: CACNA1S, RyR2, ATP2A2, CASQ2. The bat-heart-target-screen skill context supports this.

### H6: Shared modules enriched for ECM/structural remodeling
Mechanical stress from high heart rate may drive convergent extracellular matrix remodeling.

### H7 (NULL): No convergent module
Sk and Sm each have species-specific modules with no overlap. Any apparent sharing is due to chance or batch artifact.

## Why each matters
- H1/H2: Chamber-specific convergence is more scientifically interesting than whole-heart. Implies chamber-specific selective pressure.
- H4: Energy metabolism is the most predicted convergent pathway from first principles.
- H5: Calcium handling is mechanistically linked to heart rate and connects to existing bat-heart-target-screen data.
- H7: Must be explicitly testable via module preservation statistics.

## What data could test each
- H1/H2/H3: WGCNA on chamber-specific subsets + module preservation (Sk vs Sm) + module-trait correlation with high_heart_rate_status
- H4/H5/H6: GO/KEGG enrichment per module
- H7: Module preservation Z-summary < 2 in Sk-vs-Sm comparison

## Key uncertainty
The first round (all-sample WGCNA) found turquoise (r=-0.96 species), yellow (Sm-specific r=+0.98), brown (Sk-specific r=+0.91), green (chamber r=-0.64). But all-sample network cannot distinguish chamber-specific convergence. Need chamber-specific networks.
