# L9 Feynman - Result Falsification

## What could kill these results?

### 1. Species vs heart-rate confound (HIGH risk)
Turquoise correlates with species (r=-0.962) and heart_rate (r=-0.955) nearly identically. In a 3-species design where Sk+Sm are high-rate and Rn is low-rate, these are perfectly confounded. The convergence claim rests on module preservation (Sk<->Sm Z=16.9), which shows shared co-expression structure between bat and shrew specifically. But without a 4th high-rate species or low-rate bat/shrew, heart-rate vs species is unresolvable with current data.

### 2. Batch effects in subset networks (MEDIUM risk)
All-sample network used batch as covariate. Atrium (n=23) and ventricle (n=48) subsets used ~0+group without batch (rank deficiency). Subset modules may retain batch signal. All-sample network is more trustworthy.

### 3. Green module unfairly excluded (MEDIUM)
Green (179 genes, Z=20.2, hhr r=-0.52) fails criterion (c) no DEG overlap. But its GO enrichment is the most specific: cardiac muscle development, striated muscle development. Module-level co-expression convergence does not require gene-level DEG convergence. Criterion (c) is too strict. Flag for Darwin.

### 4. Power sensitivity not run (LOW-MEDIUM)
Power=4 forced (auto=1). Module sizes reasonable, not fragmented. Sensitivity comparison listed as analysis_needed #6 but NOT run. Gap.

### 5. nPermutations=50 (LOW)
Strong modules (green Z=20, turquoise Z=17) unlikely to change. Moderate modules (brown Z=4.5, yellow Z=2.5) could shift. Recommend 200+ for publication.

## What survives falsification?
- Turquoise and brown as convergent candidates: SURVIVES with species-confound caveat
- Green as cardiac identity module: SURVIVES as biologically meaningful, criterion (c) too strict
- Atrium/ventricle subset networks: SURVIVES as exploratory only
- Core hypothesis (Sk and Sm share co-expression modules): SURVIVES, supported by preservation Z-scores