#!/usr/bin/env python3
"""L7 Turing script: validate_ortholog_inputs.py

Approved by candidate L6 analysis_plan (S1, mandatory first stage). Audits the
staged enhancer + DEG inputs in THIS Turing workspace: file/row counts, usable
gene-identifier columns, join coverage between enhancer evidence (per species)
and the DEG ortholog table, and the COL6A1-specific mapping status that gates
S2 (S3 is gated only on general join validity, not this gene-specific check).

Workspace-local only: all paths resolve relative to this script's own
location (scripts/../ == workspace root), never to the source project tree.
Fails closed (exit 1) on missing/unreadable files or required columns.
"""
import json
import sys
from pathlib import Path

import pandas as pd

WS = Path(__file__).resolve().parent.parent  # scripts/.. == workspace root
INPUTS = WS / "inputs"
RESULTS = WS / "results"
NODE = "L7"

ENH_SPECIES = ["Rn", "Sk", "Sm"]
CONTRASTS = {"Sk": "SkV_vs_RnV", "Sm": "SmV_vs_RnV"}
DEG_COLS_REQUIRED = ["gene_symbol", "logFC", "adj.P.Val", "qc_flag"]
TARGET_GENE = "COL6A1"


def clean_gene_name(s):
    if pd.isna(s):
        return ""
    s = str(s).strip()
    for prefix in ("rna-", "gene-", "LOC-"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    return s.upper().strip()


def load_manifest():
    mpath = WS / "WORKSPACE_MANIFEST.json"
    if not mpath.exists():
        fail(f"WORKSPACE_MANIFEST.json missing at workspace root ({mpath})")
    return json.loads(mpath.read_text(encoding="utf-8"))


def sha256_for(manifest, workspace_relpath):
    target = str((WS / workspace_relpath).resolve())
    for rec in manifest.get("staged_files", []):
        if rec.get("workspace_path") == target:
            return rec.get("sha256")
    return None


def fail(reason):
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = {"status": "FAIL", "node": NODE, "reason": reason}
    (RESULTS / "input_validation_report.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"FAIL: {reason}", file=sys.stderr)
    sys.exit(1)


def load_enhancer(sp):
    path = INPUTS / "enhancer_per_species" / sp / "enhancer_genes.xls"
    if not path.exists():
        fail(f"missing enhancer input: {path.relative_to(WS)}")
    df = pd.read_csv(path, sep="\t", encoding="gbk", encoding_errors="replace")
    for col in ("Closest", "Signal", "Rank"):
        if col not in df.columns:
            fail(f"enhancer file {sp} missing required column '{col}'")
    df["Closest_clean"] = df["Closest"].apply(clean_gene_name)
    return df, path


def load_deg(contrast):
    path = (INPUTS / "gemini_out_chamber_species_deg_length_aware" / "results"
            / f"DEG_{contrast}_all_genes.csv")
    if not path.exists():
        fail(f"missing DEG input: {path.relative_to(WS)}")
    df = pd.read_csv(path)
    for col in DEG_COLS_REQUIRED:
        if col not in df.columns:
            fail(f"DEG file {contrast} missing required column '{col}'")
    df["gene_upper"] = df["gene_symbol"].astype(str).str.upper().str.strip()
    return df, path


def main():
    manifest = load_manifest()
    candidate_id = manifest.get("candidate_id", "UNKNOWN")

    enhancer, enhancer_paths = {}, {}
    for sp in ENH_SPECIES:
        df, path = load_enhancer(sp)
        enhancer[sp] = df
        enhancer_paths[sp] = path

    deg, deg_paths = {}, {}
    for sp, contrast in CONTRASTS.items():
        df, path = load_deg(contrast)
        deg[sp] = df
        deg_paths[sp] = path

    species_report = {
        sp: {
            "row_count": int(len(enhancer[sp])),
            "unique_genes": int(
                enhancer[sp]["Closest_clean"].replace("", pd.NA).nunique(dropna=True)),
        }
        for sp in ENH_SPECIES
    }

    join_audit_rows = []
    join_report = {}
    for sp, contrast in CONTRASTS.items():
        enh_df, deg_df = enhancer[sp], deg[sp]
        enh_genes = set(enh_df.loc[enh_df["Closest_clean"] != "", "Closest_clean"])
        deg_genes = set(deg_df["gene_upper"])
        matched = enh_genes & deg_genes
        dup_deg = deg_df["gene_upper"].value_counts()
        dup_deg_genes = dup_deg[dup_deg > 1]
        join_report[contrast] = {
            "enhancer_species": sp,
            "enhancer_unique_genes": len(enh_genes),
            "deg_unique_genes": len(deg_genes),
            "deg_row_count": int(len(deg_df)),
            "matched_genes": len(matched),
            "unmatched_enhancer_genes": len(enh_genes - deg_genes),
            "deg_duplicate_gene_upper_count": int(len(dup_deg_genes)),
        }
        for g in sorted(matched | (enh_genes - deg_genes)):
            join_audit_rows.append({
                "gene": g, "contrast": contrast,
                "in_enhancer": g in enh_genes, "in_deg": g in deg_genes,
            })

    # --- COL6A1 mapping status: mandatory stop-gate for S2 only ------------
    col6a1 = {"gene": TARGET_GENE, "per_contrast": {}}
    ambiguous_or_missing = False
    for sp, contrast in CONTRASTS.items():
        deg_df = deg[sp]
        rows = deg_df[deg_df["gene_upper"] == TARGET_GENE]
        pass_rows = rows[rows["qc_flag"] == "pass"]
        enh_rows = enhancer[sp][enhancer[sp]["Closest_clean"] == TARGET_GENE]
        n_deg, n_pass = int(len(rows)), int(len(pass_rows))
        status = "missing" if n_deg == 0 else (
            "ambiguous" if n_pass != 1 else "comparable")
        if status != "comparable":
            ambiguous_or_missing = True
        col6a1["per_contrast"][contrast] = {
            "deg_row_count": n_deg, "deg_qc_pass_count": n_pass,
            "enhancer_region_count": int(len(enh_rows)), "status": status,
        }
    col6a1["overall_status"] = "ambiguous_or_missing" if ambiguous_or_missing else "comparable"
    col6a1["stop_gene_specific"] = ambiguous_or_missing

    decision = "STOP" if ambiguous_or_missing else "PROCEED"
    reason = (
        "COL6A1 mapping is not unambiguously comparable in one or both "
        "contrasts (L5 stop rule: ambiguous COL6A1 mapping)."
        if ambiguous_or_missing else
        "COL6A1 has exactly one QC-pass DEG record in both contrasts; "
        "gene-specific concordance (S2) may proceed.")

    provenance = {
        "candidate_id": candidate_id,
        "node": NODE,
        "inputs": [
            {"file": str(p.relative_to(WS)),
             "sha256": sha256_for(manifest, p.relative_to(WS))}
            for p in list(enhancer_paths.values()) + list(deg_paths.values())
        ],
        "columns_used": {"enhancer": ["Closest", "Signal", "Rank"],
                         "deg": DEG_COLS_REQUIRED},
        "filters_applied": [
            "gene symbol cleaned via rna-/gene-/LOC- prefix strip + uppercase"],
        "assumptions": [
            "Join key is the cleaned gene SYMBOL (Closest / gene_symbol), not "
            "the per-species accession columns -- see limitations.",
            "0 enhancer rows for a gene is reported as 'no enhancer entry "
            "found', NOT interpreted as enhancer loss (per L0 "
            "forbidden_shortcuts).",
        ],
        "limitations": [
            "The trailing per-species cross-reference ID columns in "
            "enhancer_genes.xls (after Closest_id) have mojibake headers that "
            "do not decode cleanly under gbk in this environment; they were "
            "NOT used for joining. Joining used the cleaned gene-symbol "
            "column only (Closest <-> gene_symbol), matching this project's "
            "existing convention in 04_Analysis_Outputs/multi_omic_concordance.py.",
            "S4 (mechanics/protein/compliance) is out of scope; not attempted.",
        ],
    }

    report = {
        "status": "OK", "node": NODE, "candidate_id": candidate_id,
        "decision": decision, "reason": reason,
        "species_report": species_report, "join_audit": join_report,
        "col6a1": col6a1, "provenance": provenance,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "input_validation_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(join_audit_rows).to_csv(
        RESULTS / "ortholog_join_audit.tsv", sep="\t", index=False)

    print(f"OK: decision={decision}; col6a1={col6a1['overall_status']}")
    sys.exit(0)


if __name__ == "__main__":
    main()
