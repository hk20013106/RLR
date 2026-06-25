# Pre-Research (code search) — before L7 (Round 4)

## Existing tools / code to reuse
- `scripts_wgcna_loop/09_kme_ranked_gsea.R` — the debugged kME-ranked GSEA pattern
  (clusterProfiler::gseGO, org.Mm.eg.db, rat->mouse entrez map). Reuse the mapping
  + gseGO call.
- `scripts_wgcna_loop/08_turquoise_core_ora.R` — ORA (enrichGO) pattern.
- Mapping: `gemini_out_chamber_species_deg_length_aware/results/gene_symbol_to_mouse_entrez_mapping_used.csv` (rat_symbol -> mouse_entrez).
- Module membership: `{atrium,ventricle,all_sample}_module_assignment.csv` (cols
  gene_symbol, module, module_color) — round-3 overlap fix: use module_color.
- Networks: `{atrium,ventricle}_network.RData` (datExpr, MEs) for kME; eigengene
  CSVs for MEs.
- `WGCNA::modulePreservation` for Zsummary.

## Reusable code
- gseGO/enrichGO + rat->mouse mapping from 09; phyper for overlap; kME = cor(gene, ME).

## Gap: what to write
- `14_round4_enrichment.R`: ORA + kME-GSEA for atrium-blue (1537g) and
  ventricle-brown (921g); all_sample turquoise -> tissue overlap (module_color,
  hypergeometric, shared universe). All fast.
- `15_preservation.R`: modulePreservation across atrium/ventricle (low nPerm,
  indicative) — slower; attempt with guard, defer if it does not finish.
