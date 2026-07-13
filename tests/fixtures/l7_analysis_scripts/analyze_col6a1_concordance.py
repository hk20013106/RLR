#!/usr/bin/env python3
"""L7 Turing script: analyze_col6a1_concordance.py

Approved by candidate L6 analysis_plan (S2, gated on S1). Tests whether COL6A1
DEG evidence is directionally concordant across the two independent ventricular
contrasts (SkV_vs_RnV, SmV_vs_RnV), per L6 parameters: concordance = same
direction in both contrasts. Enhancer evidence is reported as association
context only (Signal/Rank are within-species ROSE metrics, not cross-species
normalized -- they are NOT used to compute concordance).

Refuses to run (writes a STOPPED result, computes no statistics) if S1's
validation report says COL6A1 mapping is ambiguous or missing. Association-only
language throughout; no causal or compliance claims.
"""
import json
import sys
from pathlib import Path

import pandas as pd

WS = Path(__file__).resolve().parent.parent
INPUTS = WS / "inputs"
RESULTS = WS / "results"
NODE = "L7"
TARGET_GENE = "COL6A1"
CONTRASTS = {"Sk": "SkV_vs_RnV", "Sm": "SmV_vs_RnV"}
SIG_ALPHA = 0.05


def clean_gene_name(s):
    if pd.isna(s):
        return ""
    s = str(s).strip()
    for prefix in ("rna-", "gene-", "LOC-"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    return s.upper().strip()


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


def direction_of(row):
    if row["adj.P.Val"] >= SIG_ALPHA:
        return "NS"
    return "DOWN" if row["logFC"] < 0 else "UP"


def write_stopped(out_base, reason):
    out = dict(out_base, status="STOPPED", reason=reason)
    (RESULTS / "col6a1_concordance.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame([out]).to_csv(RESULTS / "col6a1_concordance.tsv",
                               sep="\t", index=False)
    print(f"STOPPED: {reason}")
    sys.exit(0)


def main():
    report, report_path = load_validation_report()
    candidate_id = report.get("candidate_id", "UNKNOWN")
    col6a1 = report.get("col6a1", {})

    RESULTS.mkdir(parents=True, exist_ok=True)
    out_base = {"status": None, "node": NODE, "candidate_id": candidate_id,
               "gene": TARGET_GENE, "claim_scope": "regulatory association only"}

    if report.get("status") != "OK":
        write_stopped(out_base, "S1 validation did not complete structurally "
                                "(see input_validation_report.json).")
    if report.get("decision") != "PROCEED" or col6a1.get("stop_gene_specific", True):
        write_stopped(
            out_base,
            f"{col6a1.get('overall_status', 'unknown')} (see "
            "input_validation_report.json col6a1 block); S1 requires "
            "unambiguous COL6A1 mapping before S2 runs.")

    manifest = json.loads((WS / "WORKSPACE_MANIFEST.json").read_text(encoding="utf-8"))

    contrast_results, inputs_used = {}, []
    for sp, contrast in CONTRASTS.items():
        deg_path = (INPUTS / "gemini_out_chamber_species_deg_length_aware" / "results"
                    / f"DEG_{contrast}_all_genes.csv")
        enh_path = INPUTS / "enhancer_per_species" / sp / "enhancer_genes.xls"
        inputs_used += [deg_path, enh_path]
        deg_df = pd.read_csv(deg_path)
        deg_df["gene_upper"] = deg_df["gene_symbol"].astype(str).str.upper().str.strip()
        rows = deg_df[(deg_df["gene_upper"] == TARGET_GENE)
                      & (deg_df["qc_flag"] == "pass")]
        if len(rows) != 1:
            print(f"ERROR: expected exactly 1 QC-pass DEG row for {TARGET_GENE} "
                  f"in {contrast}, found {len(rows)}. Refusing to fabricate a "
                  f"result (S1 said comparable but re-check disagrees).",
                  file=sys.stderr)
            sys.exit(1)
        row = rows.iloc[0]

        enh_df = pd.read_csv(enh_path, sep="\t", encoding="gbk",
                             encoding_errors="replace")
        enh_df["Closest_clean"] = enh_df["Closest"].apply(clean_gene_name)
        enh_rows = enh_df[enh_df["Closest_clean"] == TARGET_GENE]

        contrast_results[contrast] = {
            "enhancer_species": sp,
            "logFC": float(row["logFC"]),
            "adj_p_val": float(row["adj.P.Val"]),
            "direction": direction_of(row),
            "significant": bool(row["adj.P.Val"] < SIG_ALPHA),
            "enhancer_region_count": int(len(enh_rows)),
            "enhancer_max_signal": (float(enh_rows["Signal"].max())
                                    if len(enh_rows) else None),
            "enhancer_best_rank": (int(enh_rows["Rank"].min())
                                   if len(enh_rows) else None),
        }

    directions = {c["direction"] for c in contrast_results.values()}
    both_significant = all(c["significant"] for c in contrast_results.values())
    concordant_direction = len(directions) == 1 and "NS" not in directions and both_significant

    out = dict(
        out_base, status="PROCEED",
        reason="COL6A1 mapping was unambiguous in both contrasts (S1 PASS).",
        contrasts=contrast_results,
        concordant_direction=bool(concordant_direction),
        concordance_definition=("same significant DEG direction "
                                f"(adj.P.Val<{SIG_ALPHA}) in both contrasts"),
        limitations=[
            "Enhancer Signal/Rank are within-species ROSE metrics, not "
            "cross-species normalized; reported as context only, not used to "
            "compute concordance.",
            "Association only; no causal, compliance, or mechanical claim is "
            "made or implied.",
        ],
        provenance={
            "candidate_id": candidate_id, "node": NODE,
            "inputs": [{"file": str(p.relative_to(WS)),
                       "sha256": sha256_for(manifest, p.relative_to(WS))}
                      for p in inputs_used],
            "columns_used": ["gene_symbol", "logFC", "adj.P.Val", "qc_flag",
                             "Closest", "Signal", "Rank"],
            "upstream_validation_report": str(report_path.relative_to(WS)),
        })

    (RESULTS / "col6a1_concordance.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    flat_rows = [dict(contrast=c, **v) for c, v in contrast_results.items()]
    pd.DataFrame(flat_rows).to_csv(RESULTS / "col6a1_concordance.tsv",
                                   sep="\t", index=False)
    print(f"PROCEED: concordant_direction={concordant_direction}")
    sys.exit(0)


if __name__ == "__main__":
    main()
