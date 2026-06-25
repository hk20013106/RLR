# Pre-Research (deep research) — before L1 (Round 4)

Focus: pathway identity of the tissue-controlled convergent modules and whether
the round-2 mitochondrial story survives a chamber-controlled framing.

## Key findings (background)
- High-heart-rate / high-metabolic-rate small mammals repeatedly up-regulate
  **mitochondrial oxidative phosphorylation (OXPHOS)** and contractile/energy
  programs in heart — the expected convergent signal.
- **Atrial vs ventricular metabolism differ**: ventricle is more oxidative
  (higher mito density / OXPHOS), atrium has distinct conduction/secretory
  programs. So a "mitochondrial convergence" could legitimately look different in
  atrium (MEblue, up) vs ventricle (MEbrown, down) — direction may flip by chamber.
- ORA (over-representation of a gene set) and **kME-ranked GSEA** are the standard
  pair to name a WGCNA module's biology; GSEA is more sensitive to coordinated
  shifts ORA misses (this is exactly what round-2 found for turquoise).

## Methods used in literature
- Characterize a module by ORA(GO BP) on members + GSEA on kME-ranked members.
- Test module specificity by **module preservation (Zsummary)** across conditions
  /tissues: low preservation => the module is context-specific (here: chamber-specific).

## Gaps our study addresses
- Whether atrium-MEblue / ventricle-MEbrown are mitochondrial/OXPHOS (i.e. the
  round-2 signal in a tissue-controlled form) or something else.
- Whether round-2 all_sample turquoise genes stay co-modular within one tissue
  (gene-level confound quantification) — the round-3 subtest that failed.
