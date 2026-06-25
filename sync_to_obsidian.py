#!/usr/bin/env python3
"""Sync RLR v0.3 project to Obsidian vault - human-readable format.

Run after aggregate-report. Produces:
- 02_Agent_Notes/<persona>/L<n>_<persona>_NOTE.md  (human-readable delta summary)
- 05_Decision_Log/ROUND_SUMMARY_<cand>.md           (one-page round summary)
- 03_Figures/                                        (PDF/PNG copied from results)
- 01_Candidates/                                     (renamed with readable title)
- FINAL_REPORT.md / FINAL_REPORT_CN.md              (already generated)
"""

import json
import os
import shutil
import re
from pathlib import Path

# --- config ---
DEFAULT_VAULT = Path(os.environ.get("OBSIDIAN_VAULT", ""))
DEFAULT_RESULTS = Path("D:/R-HK/yigene/results_wgcna_loop")

PERSONAS = {
    "Linnaeus": ("L0", "Catalog Master"),
    "Einstein": ("L1", "Conceptual Explorer"),
    "Feynman": ("L2", "Idea Falsifier"),
    "Oppenheimer": ("L3", "Triage Judge"),
    "Fisher": ("L4", "Method Designer"),
    "Tukey": ("L5", "QC Critic"),
    "Turing": ("L7", "Code Executor"),
    "Curie": ("L8", "Evidence Auditor"),
    "Darwin": ("L9b", "Biology Interpreter"),
    "Jobs": ("L10a", "Value Assessor"),
}

DAG_ORDER = [
    "L0_linnaeus", "L1_einstein", "L2_feynman", "L3_oppenheimer",
    "L4_fisher", "L5_tukey", "L6_oppenheimer", "L7_turing",
    "L8_curie", "L9a_feynman", "L9b_darwin",
    "L10a_jobs", "L10b_oppenheimer",
]

DELTA_PERSONA = {
    "L0_linnaeus": "Linnaeus", "L1_einstein": "Einstein",
    "L2_feynman": "Feynman", "L3_oppenheimer": "Oppenheimer",
    "L4_fisher": "Fisher", "L5_tukey": "Tukey",
    "L6_oppenheimer": "Oppenheimer", "L7_turing": "Turing",
    "L8_curie": "Curie", "L9a_feynman": "Feynman",
    "L9b_darwin": "Darwin", "L10a_jobs": "Jobs",
    "L10b_oppenheimer": "Oppenheimer",
}

LAYER_TITLES_EN = {
    "L0_linnaeus": "L0 - Preflight (Linnaeus)",
    "L1_einstein": "L1 - Hypotheses (Einstein)",
    "L2_feynman": "L2 - Falsification (Feynman)",
    "L3_oppenheimer": "L3 - Triage (Oppenheimer)",
    "L4_fisher": "L4 - Method Design (Fisher)",
    "L5_tukey": "L5 - QC Checkpoints (Tukey)",
    "L6_oppenheimer": "L6 - Method Approval (Oppenheimer)",
    "L7_turing": "L7 - Execution (Turing)",
    "L8_curie": "L8 - Evidence Audit (Curie)",
    "L9a_feynman": "L9a - Result Falsification (Feynman)",
    "L9b_darwin": "L9b - Biology Interpretation (Darwin)",
    "L10a_jobs": "L10a - Value Assessment (Jobs)",
    "L10b_oppenheimer": "L10b - Final Decision (Oppenheimer)",
}


def load_delta(project_dir, delta_key):
    persona = DELTA_PERSONA[delta_key]
    p = Path(project_dir) / "02_Agent_Notes" / persona / f"{delta_key}_delta.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def fmt_list(lst):
    if not lst:
        return "_none_"
    if isinstance(lst, list):
        return ", ".join(str(x) for x in lst)
    return str(lst)


def fmt_delta_note(delta_key, delta):
    """Convert a delta JSON into a human-readable Markdown note."""
    if delta is None:
        return "_No delta found._"
    if isinstance(delta, dict) and "_error" in delta:
        return f"_Error: {delta['_error']}_"

    # Use CN field if available
    d = delta.get("cn", delta) if isinstance(delta, dict) else delta
    L = []

    if delta_key == "L0_linnaeus":
        L.append(f"**Skills:** {fmt_list(d.get('skills_found'))}")
        L.append(f"**Gaps:** {fmt_list(d.get('skills_gaps'))}")
        L.append(f"**Input verified:**")
        for k, v in (d.get('input_verified') or {}).items():
            L.append(f"  - {k}: {v}")
        L.append(f"**Environment:**")
        for k, v in (d.get('environment') or {}).items():
            L.append(f"  - {k}: {v}")

    elif delta_key == "L1_einstein":
        for h in d.get("hypotheses", []):
            L.append(f"- **{h.get('id','?')}:** {h.get('text','')} _(testable={h.get('testable','?')})_")
            L.append(f"  - {h.get('rationale','')}")
        L.append(f"\n**Primary:** {d.get('primary_hypothesis','')}")
        L.append(f"**Uncertainty:** {d.get('key_uncertainty','')}")

    elif delta_key == "L2_feynman":
        for a in d.get("attacks", []):
            L.append(f"- **[{a.get('severity','?')}]** {a.get('hypothesis_id','?')}: {a.get('text','')}")
        L.append(f"\n**Confounders:**")
        for c in d.get("confounders", []):
            L.append(f"- [{c.get('severity','?')}] {c.get('name','')}: {c.get('text','')}")
        L.append(f"\n**Verdict:** {d.get('verdict','')}")

    elif delta_key == "L3_oppenheimer":
        L.append(f"**Selected:** {fmt_list(d.get('selected'))}")
        L.append(f"**Rejected:** {fmt_list(d.get('rejected'))}")
        L.append(f"**Reason:** {d.get('reason','')}")

    elif delta_key == "L4_fisher":
        for s in d.get("strategies", []):
            L.append(f"- **{s.get('id','?')}: {s.get('name','')}** (n={s.get('samples','?')})")
            L.append(f"  - Steps: {fmt_list(s.get('steps'))}")
        L.append(f"\n**Recommended:** {d.get('recommended','')}")
        L.append(f"**Scripts needed:**")
        for s in d.get("scripts_needed", []):
            L.append(f"- {s.get('name','')}: {s.get('purpose','')}")

    elif delta_key == "L5_tukey":
        L.append(f"**QC checkpoints:**")
        for q in d.get("qc_checkpoints", []):
            L.append(f"- {q.get('name','')}: {q.get('text','')}")
        L.append(f"\n**Failure stop rules:**")
        for f in d.get("failure_stop_rules", []):
            L.append(f"- {f.get('name','')}: {f.get('text','')}")

    elif delta_key == "L6_oppenheimer":
        L.append(f"**Approved:** {d.get('approved_strategy','')}")
        ap = d.get("analysis_plan", {})
        L.append(f"**Scripts:** {fmt_list(ap.get('scripts'))}")
        L.append(f"**Parameters:** {ap.get('parameters',{})}")
        L.append(f"**Outputs:** {fmt_list(ap.get('outputs'))}")

    elif delta_key == "L7_turing":
        for s in d.get("scripts_run", []):
            L.append(f"- **{s.get('name','')}** exit={s.get('exit_code','?')}")
            L.append(f"  - Output: {fmt_list(s.get('output_files'))}")
        L.append(f"\n**Key results:**")
        for k, v in (d.get("key_results") or {}).items():
            L.append(f"  - **{k}:** {v}")
        if d.get("warnings"):
            L.append(f"\n**Warnings:** {fmt_list(d.get('warnings'))}")

    elif delta_key == "L8_curie":
        for e in d.get("evidence_verified", []):
            L.append(f"- {e.get('file','')}: {e.get('check','')} = {e.get('result','')}")
        L.append(f"\n**Evidence level:** {d.get('evidence_level','')}")
        if d.get("caveats"):
            L.append(f"**Caveats:** {fmt_list(d.get('caveats'))}")

    elif delta_key == "L9a_feynman":
        for r in d.get("falsification_risks", []):
            L.append(f"- **[{r.get('severity','?')}]** {r.get('name','')} _(resolvable={r.get('resolvable','?')})_: {r.get('text','')}")
        L.append(f"\n**Survives:** {fmt_list(d.get('survives'))}")
        L.append(f"**Falsified:** {fmt_list(d.get('falsified'))}")

    elif delta_key == "L9b_darwin":
        for m in d.get("module_interpretations", []):
            L.append(f"- **{m.get('module','')}:** {m.get('meaning','')}")
            L.append(f"  - Genes: {fmt_list(m.get('genes'))}")
            L.append(f"  - Evidence: {m.get('evidence','')}")
        L.append(f"\n**Convergent evolution:** {d.get('convergent_evolution','')}")
        L.append(f"**Limitations:** {fmt_list(d.get('limitations'))}")

    elif delta_key == "L10a_jobs":
        L.append(f"**Value:** {d.get('value_assessment','')}")
        L.append(f"**Headline:** {d.get('headline','')}")
        L.append(f"**Publishable now:** {fmt_list(d.get('publishable_now'))}")
        L.append(f"**Needs more work:** {fmt_list(d.get('needs_more_work'))}")
        L.append(f"**Framing:** {d.get('manuscript_framing','')}")

    elif delta_key == "L10b_oppenheimer":
        L.append(f"**Decision:** {d.get('decision','')}")
        L.append(f"**Evidence level:** {d.get('evidence_level','')}")
        L.append(f"**Reason:** {d.get('reason','')}")
        L.append(f"**Next steps:**")
        for s in d.get("next_steps", []):
            L.append(f"- {s}")

    return "\n".join(L)


def slugify(s):
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-\s]+", "_", s)[:60]


def sync_project(project_dir, vault_dir=None, results_dir=None, cand_id=None):
    project_dir = Path(project_dir)
    vault_dir = Path(vault_dir or DEFAULT_VAULT)
    results_dir = Path(results_dir or DEFAULT_RESULTS)
    project_name = project_dir.name
    vault_project = vault_dir / "ResearchLoop" / project_name

    # Find candidates
    cand_dir = project_dir / "01_Candidates"
    candidates = []
    for cf in sorted(cand_dir.glob("C*.md")):
        text = cf.read_text(encoding="utf-8")
        fm = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip().strip('"')
        cid = cf.stem
        title = fm.get("title", cid)
        round_id = fm.get("round_id", "1")
        parent = fm.get("parent_candidate_id", "")
        candidates.append({"id": cid, "title": title, "round": round_id,
                            "parent": parent, "fm": fm})

    if cand_id:
        candidates = [c for c in candidates if c["id"] == cand_id]

    if not candidates:
        print("No candidates found")
        return 1

    # --- 01_Candidates: rename with readable title ---
    new_cand_dir = vault_project / "01_Candidates"
    new_cand_dir.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        slug = slugify(c["title"])
        round_tag = f"R{c['round']}" if c["round"] != "1" else "R1"
        new_name = f"{round_tag}_{slug}.md"
        src = project_dir / "01_Candidates" / f"{c['id']}.md"
        dst = new_cand_dir / new_name
        shutil.copy2(src, dst)
        print(f"  candidate: {new_name}")

    # --- 02_Agent_Notes: human-readable NOTE.md per delta ---
    notes_dir = vault_project / "02_Agent_Notes"
    # Clean old empty dirs
    if notes_dir.exists():
        for old in notes_dir.glob("**/*.json"):
            old.unlink()
    for delta_key in DAG_ORDER:
        persona = DELTA_PERSONA[delta_key]
        delta = load_delta(project_dir, delta_key)
        if delta is None:
            continue
        pdir = notes_dir / persona
        pdir.mkdir(parents=True, exist_ok=True)
        note_name = f"{delta_key}_NOTE.md"
        note_path = pdir / note_name
        title = LAYER_TITLES_EN.get(delta_key, delta_key)
        body = f"# {title}\n\n"
        body += fmt_delta_note(delta_key, delta)
        body += f"\n\n---\n_Source: `{delta_key}.json` (machine-readable)_\n"
        note_path.write_text(body, encoding="utf-8")
        print(f"  note: {persona}/{note_name}")

    # --- 03_Figures: copy PDFs/PNGs from results ---
    fig_dir = vault_project / "03_Figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig_count = 0
    if results_dir.exists():
        for ext in ("*.pdf", "*.png", "*.jpg"):
            for f in results_dir.rglob(ext):
                rel = f.relative_to(results_dir)
                dst = fig_dir / rel.name
                shutil.copy2(f, dst)
                fig_count += 1
                print(f"  figure: {rel.name}")
    print(f"  figures copied: {fig_count}")

    # --- 05_Decision_Log: ROUND_SUMMARY (human) + final_decision only ---
    log_dir = vault_project / "05_Decision_Log"
    # Remove old D00xx files from vault (keep only in local project)
    if log_dir.exists():
        for old in log_dir.glob("D0*.md"):
            old.unlink()
        for old in log_dir.glob("analysis_plan_decision_*.md"):
            old.unlink()
        for old in log_dir.glob("candidate_triage_decision_*.md"):
            old.unlink()
    log_dir.mkdir(parents=True, exist_ok=True)

    for c in candidates:
        summary_path = log_dir / f"ROUND_SUMMARY_R{c['round']}.md"
        l10b = load_delta(project_dir, "L10b_oppenheimer")
        l8 = load_delta(project_dir, "L8_curie")
        l7 = load_delta(project_dir, "L7_turing")
        lines = [f"# Round {c['round']} Summary\n"]
        lines.append(f"**Candidate:** {c['id']}")
        lines.append(f"**Title:** {c['title']}")
        if c["parent"]:
            lines.append(f"**Parent (previous round):** {c['parent']}")
        lines.append(f"\n## Decision\n")
        if l10b:
            d = l10b.get("cn", l10b)
            lines.append(f"**Status:** {d.get('decision','')}")
            lines.append(f"**Evidence:** {d.get('evidence_level','')}")
            lines.append(f"**Reason:** {d.get('reason','')}")
            lines.append(f"\n**Next steps:**")
            for s in d.get("next_steps", []):
                lines.append(f"- {s}")
        lines.append(f"\n## Key Results\n")
        if l7:
            d = l7.get("cn", l7)
            for k, v in (d.get("key_results") or {}).items():
                lines.append(f"- **{k}:** {v}")
        lines.append(f"\n## Evidence Audit\n")
        if l8:
            d = l8.get("cn", l8)
            lines.append(f"**Level:** {d.get('evidence_level','')}")
            for e in d.get("evidence_verified", []):
                lines.append(f"- {e.get('file','')}: {e.get('check','')} = {e.get('result','')}")
            if d.get("caveats"):
                lines.append(f"\n**Caveats:** {fmt_list(d.get('caveats'))}")
        lines.append(f"\n## Figures\n")
        lines.append(f"See [[03_Figures/]] for all plots.")
        summary_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  summary: ROUND_SUMMARY_R{c['round']}.md")

    # --- FINAL_REPORT copy ---
    for fname in ("FINAL_REPORT.md", "FINAL_REPORT_CN.md"):
        src = project_dir / fname
        if src.exists():
            shutil.copy2(src, vault_project / fname)
            # Append figure embeds to FINAL_REPORT
            if fname in ("FINAL_REPORT.md", "FINAL_REPORT_CN.md"):
                fig_dir = vault_project / "03_Figures"
                if fig_dir.exists():
                    figs = sorted(fig_dir.glob("*"))
                    if figs:
                        lines = ["", "## Figures", ""]
                        for fig in figs:
                            lines.append(f"![{fig.stem}](03_Figures/{fig.name})")
                        lines.append("")
                        with open(vault_project / fname, "a", encoding="utf-8") as f:
                            f.write("\n".join(lines))

    # --- 08_Audit: remove from vault (machine-only) ---
    audit_dir = vault_project / "08_Audit"
    if audit_dir.exists():
        shutil.rmtree(audit_dir)

    # --- 00_Index: readable navigation ---
    index_path = vault_project / "00_Index.md"
    lines = [f"# {project_name}\n"]
    lines.append("## Candidates\n")
    for c in candidates:
        slug = slugify(c["title"])
        round_tag = f"R{c['round']}"
        lines.append(f"- [[01_Candidates/{round_tag}_{slug}|Round {c['round']}: {c['title']}]]")
    lines.append(f"\n## DAG Notes (L0-L10c)\n")
    for delta_key in DAG_ORDER:
        persona = DELTA_PERSONA[delta_key]
        title = LAYER_TITLES_EN.get(delta_key, delta_key)
        note_path = f"02_Agent_Notes/{persona}/{delta_key}_NOTE"
        lines.append(f"- [[{note_path}|{title}]]")
    lines.append(f"\n## Round Summaries\n")
    for c in candidates:
        lines.append(f"- [[05_Decision_Log/ROUND_SUMMARY_R{c['round']}|Round {c['round']} Summary]]")
    lines.append(f"\n## Reports\n")
    lines.append(f"- [[FINAL_REPORT|Final Report (EN)]]")
    lines.append(f"- [[FINAL_REPORT_CN|最终报告 (中文)]]")
    lines.append(f"\n## Figures\n")
    lines.append(f"- [[03_Figures/|All figures]]")
    index_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  index: 00_Index.md")

    print(f"\n=== SYNC COMPLETE: {vault_project} ===")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Sync RLR project to Obsidian (human-readable)")
    p.add_argument("project_dir", help="RLR project directory (e.g. Yigene_WGCNA_v03)")
    p.add_argument("--vault", default=str(DEFAULT_VAULT), help="Obsidian vault root")
    p.add_argument("--results", default=str(DEFAULT_RESULTS), help="WGCNA results root")
    p.add_argument("--cand", default=None, help="specific candidate ID")
    args = p.parse_args()
    sync_project(args.project_dir, args.vault, args.results, args.cand)




