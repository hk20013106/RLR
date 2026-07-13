#!/usr/bin/env python3
"""L7 Turing script: analyze_ecm_ranked_program.py

Approved by candidate L6 analysis_plan (S3, gated on S1's GENERAL join
validity only -- NOT on the COL6A1-specific gate, which blocks S2 only).
Tests whether predefined, locked ECM/collagen gene programs show differential-
expression enrichment relative to each contrast's own tested universe.

Gene sets are locked BEFORE any comparison (L5 "Gene-set lock"). Any tier with
fewer than MIN_TIER_N genes in that contrast's universe is reported as
insufficient_coverage, not tested -- no fabricated statistic. Association-only
language; no causal/compliance claims.
"""
import json
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import mannwhitneyu

WS = Path(__file__).resolve().parent.parent
INPUTS = WS / "inputs"
RESULTS = WS / "results"
NODE = "L7"
CONTRASTS = {"Sk": "SkV_vs_RnV", "Sm": "SmV_vs_RnV"}
MIN_TIER_N = 3

# Locked gene sets (standard mammalian nomenclature; predefined BEFORE testing
# per L5 "Gene-set lock"). broad_ECM reuses this project's existing marker set
# from 04_Analysis_Outputs/multi_omic_concordance.py (project-local precedent).
GENE_SETS = {
    "collagen_VI": {"COL6A1", "COL6A2", "COL6A3", "COL6A4", "COL6A5", "COL6A6"},
    "fibrillar_collagen": {"COL1A1", "COL1A2", "COL2A1", "COL3A1", "COL5A1",
                          "COL5A2", "COL5A3", "COL11A1", "COL11A2"},
    "crosslinking": {"LOX", "LOXL1", "LOXL2", "LOXL3", "LOXL4",
                     "PLOD1", "PLOD2", "PLOD3"},
}
BROAD_ECM_MARKERS = ["COL1", "COL3", "COL4", "COL5", "COL6", "COL11", "COL15",
                     "COL18", "LOXL", "SERPINH", "MMP2", "POSTN", "FBN1",
                     "DCN", "OGN", "NID1", "ELN", "FBN2", "LTBP"]


def load_validation_report():
    path = RESULTS / "input_validation_report.json"
    if not path.exists():
        print("ERROR: input_validation_report.json missing -- run "
              "validate_ortholog_inputs.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8")), path


def sha256_for(manifest, workspace_relpath):
    target = str((WS / workspace_relpath).resolve())
    for rec in manifest.get("staged_files", []):
        if rec.get("workspace_path") == target:
            return rec.get("sha256")
    return None


def main():
    report, report_path = load_validation_report()
    candidate_id = report.get("candidate_id", "UNKNOWN")

    # S3 is gated on GENERAL join validity, not the COL6A1-specific gate
    # (that gate only blocks S2 per the L6 analysis_plan).
    if report.get("status") != "OK":
        print("ERROR: S1 validation did not complete structurally; refusing "
              "to run S3.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads((WS / "WORKSPACE_MANIFEST.json").read_text(encoding="utf-8"))
    RESULTS.mkdir(parents=True, exist_ok=True)

    tier_results, inputs_used, row_rows = {}, [], []

    for sp, contrast in CONTRASTS.items():
        deg_path = (INPUTS / "gemini_out_chamber_species_deg_length_aware" / "results"
                    / f"DEG_{contrast}_all_genes.csv")
        inputs_used.append(deg_path)
        deg_df = pd.read_csv(deg_path)
        for col in ("gene_symbol", "t", "logFC", "adj.P.Val"):
            if col not in deg_df.columns:
                print(f"ERROR: {contrast} DEG file missing required column "
                      f"'{col}'.", file=sys.stderr)
                sys.exit(1)
        deg_df["gene_upper"] = deg_df["gene_symbol"].astype(str).str.upper().str.strip()
        deg_df["abs_t"] = deg_df["t"].abs()

        universe = set(deg_df["gene_upper"])  # locked BEFORE any set comparison
        broad_tier = {g for g in universe if any(m in g for m in BROAD_ECM_MARKERS)}
        tiers = dict(GENE_SETS)
        tiers["broad_ECM"] = broad_tier

        contrast_tiers = {}
        for tier_name, tier_genes in tiers.items():
            in_universe = tier_genes & universe
            n = len(in_universe)
            if n < MIN_TIER_N:
                contrast_tiers[tier_name] = {
                    "n_in_universe": n, "n_defined": len(tier_genes),
                    "status": "insufficient_coverage",
                }
                continue
            in_mask = deg_df["gene_upper"].isin(in_universe)
            stat, p = mannwhitneyu(deg_df.loc[in_mask, "abs_t"],
                                   deg_df.loc[~in_mask, "abs_t"],
                                   alternative="two-sided")
            contrast_tiers[tier_name] = {
                "n_in_universe": n, "n_defined": len(tier_genes),
                "status": "tested",
                "test": "mannwhitneyu(|t|, tier vs rest of universe)",
                "statistic": float(stat), "p_value": float(p),
                "median_abs_t_tier": float(deg_df.loc[in_mask, "abs_t"].median()),
                "median_abs_t_rest": float(deg_df.loc[~in_mask, "abs_t"].median()),
            }
            for g in sorted(in_universe):
                row_rows.append({"contrast": contrast, "tier": tier_name, "gene": g})
        tier_results[contrast] = {"universe_size": len(universe),
                                  "tiers": contrast_tiers}

    out = {
        "status": "OK", "node": NODE, "candidate_id": candidate_id,
        "claim_scope": "regulatory association only",
        "gene_set_definitions": {k: sorted(v) for k, v in GENE_SETS.items()},
        "broad_ecm_marker_substrings": BROAD_ECM_MARKERS,
        "results_by_contrast": tier_results,
        "limitations": [
            "Universe is the set of genes tested for differential expression "
            "in that contrast's DEG table (locked before any gene-set "
            "comparison), not an independently curated background.",
            f"Tiers with fewer than {MIN_TIER_N} genes in the universe are "
            "reported as insufficient_coverage, not tested (no fabricated "
            "statistic).",
            "broad_ECM is a documented substring marker set reused from this "
            "project's prior analysis "
            "(04_Analysis_Outputs/multi_omic_concordance.py), not a curated "
            "ontology; it may include false positives.",
            "Association only; no causal, compliance, or mechanical claim.",
        ],
        "provenance": {
            "candidate_id": candidate_id, "node": NODE,
            "inputs": [{"file": str(p.relative_to(WS)),
                       "sha256": sha256_for(manifest, p.relative_to(WS))}
                      for p in inputs_used],
            "columns_used": ["gene_symbol", "t", "logFC", "adj.P.Val"],
            "upstream_validation_report": str(report_path.relative_to(WS)),
        },
    }

    (RESULTS / "analysis_summary.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(row_rows).to_csv(RESULTS / "ecm_ranked_program_results.tsv",
                                  sep="\t", index=False)
    print("OK: ECM ranked program analysis complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
