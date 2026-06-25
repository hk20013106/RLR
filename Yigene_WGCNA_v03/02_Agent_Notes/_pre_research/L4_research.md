# Pre-Research (method literature review) — before L4 (Round 4)

## Methods found
- **ORA (over-representation)**: `clusterProfiler::enrichGO(gene=module_genes,
  universe=mapped_background, OrgDb=org.Mm.eg.db, ont="BP")`. Fast, names a module
  but tends to generic terms for large modules.
- **kME-ranked GSEA**: rank a module's genes by kME (within-network connectivity),
  `gseGO(geneList=ranked, ont="BP"/"MF")`. More diagnostic of coordinated shift;
  this is what surfaced the round-2 mitochondrial signal that ORA missed.
- **Hypergeometric overlap**: all_sample turquoise genes -> atrium/ventricle
  modules using `module_color`; `phyper` on the shared-gene universe (genes in both
  networks), not all genes.
- **Module preservation**: `WGCNA::modulePreservation(multiData, multiColor)` -> 
  Zsummary; <2 not preserved (context/chamber-specific), 2-10 weak, >10 strong.

## Recommended approach
For atrium-blue and ventricle-brown: kME from network RData -> ORA + kME-GSEA;
report FDR + NES + top terms. Overlap turquoise->tissue via module_color +
hypergeometric. Preservation across the two tissue networks (low nPerm, honest).

## Pitfalls to avoid
- Use the rat->mouse mapped Entrez set as the GSEA/ORA background, not all 5000.
- Large module -> generic ORA terms; lead with GSEA NES.
- Low-nPerm modulePreservation Z is unstable -> report as indicative only.
- Compare modules by gene membership across networks, never by color name.

## Implementation
- kME = WGCNA::cor(datExpr[,mod_genes], ME_mod). gene = colnames(datExpr).
- map rat symbol -> mouse entrez via gene_symbol_to_mouse_entrez_mapping_used.csv.
