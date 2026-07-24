"""Human-readable delta rendering extracted from the runtime engine."""

from research_loop.common import _fmt_dict, _fmt_list


SECTION_TITLES_EN = {
    "L0_linnaeus": "L0 - Preflight (Linnaeus)",
    "L1_einstein": "L1 - Hypotheses (Einstein)",
    "L2_feynman": "L2 - Idea Falsification (Feynman)",
    "L3_oppenheimer": "L3 - Candidate Triage (Oppenheimer)",
    "L4_fisher": "L4 - Method Design (Fisher)",
    "L5_tukey": "L5 - Method Falsification (Tukey)",
    "L6_oppenheimer": "L6 - Analysis Plan Approval (Oppenheimer)",
    "L7_turing": "L7 - Execution (Turing)",
    "L8_curie": "L8 - Evidence Audit (Curie)",
    "L8.5_curie": "L8.5 - Literature Verification (Curie)",
    "L9a_feynman": "L9a - Result Falsification (Feynman)",
    "L9b_darwin": "L9b - Biology Interpretation (Darwin)",
    "L10a_jobs": "L10a - Value Assessment (Jobs)",
    "L10b_oppenheimer": "L10b - Final Decision (Oppenheimer)",
}

SECTION_TITLES_CN = {
    "L0_linnaeus": "L0 - \u9884\u68c0 (Linnaeus)",
    "L1_einstein": "L1 - \u5047\u8bf4\u751f\u6210 (Einstein)",
    "L2_feynman": "L2 - \u5047\u8bf4\u8bc1\u4f2a (Feynman)",
    "L3_oppenheimer": "L3 - \u5019\u9009\u7b5b\u9009 (Oppenheimer)",
    "L4_fisher": "L4 - \u65b9\u6848\u8bbe\u8ba1 (Fisher)",
    "L5_tukey": "L5 - \u65b9\u6848\u8bc1\u4f2a (Tukey)",
    "L6_oppenheimer": "L6 - \u5206\u6790\u8ba1\u5212\u5ba1\u6279 (Oppenheimer)",
    "L7_turing": "L7 - \u6267\u884c (Turing)",
    "L8_curie": "L8 - \u8bc1\u636e\u5ba1\u67e5 (Curie)",
    "L8.5_curie": "L8.5 - \u6587\u732e\u9a8c\u8bc1 (Curie)",
    "L9a_feynman": "L9a - \u7ed3\u679c\u8bc1\u4f2a (Feynman)",
    "L9b_darwin": "L9b - \u751f\u7269\u5b66\u89e3\u8bfb (Darwin)",
    "L10a_jobs": "L10a - \u4ef7\u503c\u8bc4\u4f30 (Jobs)",
    "L10b_oppenheimer": "L10b - \u6700\u7ec8\u51b3\u7b56 (Oppenheimer)",
}

# EN -> CN translations for the field labels emitted by _format_delta_body.
# Applied to each delta body when building FINAL_REPORT_CN.md (Bug 3 fix:
# previously only section TITLES were translated, leaving the body labels in
# English). Ordered longest-first via the list so a short label (e.g.
# "**Reason:**") never partially clobbers a longer one.
DELTA_LABELS_CN = [
    ("**Skills found:**", "**\u53d1\u73b0\u7684\u6280\u80fd\uff1a**"),
    ("**Skills gaps:**", "**\u6280\u80fd\u7f3a\u53e3\uff1a**"),
    ("**Input verified:**", "**\u8f93\u5165\u6821\u9a8c\uff1a**"),
    ("**Environment:**", "**\u73af\u5883\uff1a**"),
    ("**Skill use plan:**", "**\u6280\u80fd\u4f7f\u7528\u8ba1\u5212\uff1a**"),
    ("**Forbidden shortcuts:**", "**\u7981\u6b62\u7684\u6377\u5f84\uff1a**"),
    ("**Primary hypothesis:**", "**\u4e3b\u5047\u8bf4\uff1a**"),
    ("**Key uncertainty:**", "**\u5173\u952e\u4e0d\u786e\u5b9a\u6027\uff1a**"),
    ("**Confounders:**", "**\u6df7\u6742\u56e0\u7d20\uff1a**"),
    ("**Diagnostic tests:**", "**\u8bca\u65ad\u6027\u68c0\u9a8c\uff1a**"),
    ("**Verdict:**", "**\u88c1\u51b3\uff1a**"),
    ("**Selected:**", "**\u5df2\u9009\u4e2d\uff1a**"),
    ("**Rejected:**", "**\u5df2\u5426\u51b3\uff1a**"),
    ("**Route to:**", "**\u8def\u7531\u81f3\uff1a**"),
    ("**Recommended:**", "**\u63a8\u8350\u65b9\u6848\uff1a**"),
    ("**Scripts needed:**", "**\u6240\u9700\u811a\u672c\uff1a**"),
    ("**Key decisions:**", "**\u5173\u952e\u51b3\u7b56\uff1a**"),
    ("**QC checkpoints:**", "**\u8d28\u63a7\u68c0\u67e5\u70b9\uff1a**"),
    ("**Failure stop rules:**", "**\u5931\u8d25\u505c\u6b62\u89c4\u5219\uff1a**"),
    ("**Approved strategy:**", "**\u6279\u51c6\u7684\u7b56\u7565\uff1a**"),
    ("**Modifications:**", "**\u4fee\u6539\u9879\uff1a**"),
    ("**Analysis plan:**", "**\u5206\u6790\u8ba1\u5212\uff1a**"),
    ("**Key results:**", "**\u5173\u952e\u7ed3\u679c\uff1a**"),
    ("**Warnings:**", "**\u8b66\u544a\uff1a**"),
    ("**Failures:**", "**\u5931\u8d25\uff1a**"),
    ("**Evidence level:**", "**\u8bc1\u636e\u7ea7\u522b\uff1a**"),
    ("**Caveats:**", "**\u6ce8\u610f\u4e8b\u9879\uff1a**"),
    ("**Survives:**", "**\u901a\u8fc7\u9879\uff1a**"),
    ("**Falsified:**", "**\u88ab\u8bc1\u4f2a\u9879\uff1a**"),
    ("**Convergent evolution:**", "**\u8d8b\u540c\u8fdb\u5316\uff1a**"),
    ("**Limitations:**", "**\u5c40\u9650\u6027\uff1a**"),
    ("**Value assessment:**", "**\u4ef7\u503c\u8bc4\u4f30\uff1a**"),
    ("**Headline:**", "**\u6838\u5fc3\u7ed3\u8bba\uff1a**"),
    ("**Publishable now:**", "**\u5f53\u524d\u53ef\u53d1\u8868\uff1a**"),
    ("**Needs more work:**", "**\u4ecd\u9700\u5de5\u4f5c\uff1a**"),
    ("**Manuscript framing:**", "**\u8bba\u6587\u6846\u67b6\uff1a**"),
    ("**Decision:**", "**\u51b3\u5b9a\uff1a**"),
    ("**Next steps:**", "**\u540e\u7eed\u6b65\u9aa4\uff1a**"),
    ("**Reason:**", "**\u7406\u7531\uff1a**"),
    # L8.5 Curie literature verification
    ("**Verification verdict:**", "**\u9a8c\u8bc1\u88c1\u51b3\uff1a**"),
    ("**Evidence alignment:**", "**\u8bc1\u636e\u4e00\u81f4\u6027\uff1a**"),
    ("**Literature gaps:**", "**\u6587\u732e\u7a7a\u767d\uff1a**"),
    # indented bullet sub-labels
    ("- Rationale:", "- \u63a8\u7406\uff1a"),
    ("- Output files:", "- \u8f93\u51fa\u6587\u4ef6\uff1a"),
    ("- Scripts:", "- \u811a\u672c\uff1a"),
    ("- Parameters:", "- \u53c2\u6570\uff1a"),
    ("- Outputs:", "- \u8f93\u51fa\uff1a"),
    ("- Steps:", "- \u6b65\u9aa4\uff1a"),
    ("- Genes:", "- \u57fa\u56e0\uff1a"),
    ("- Evidence:", "- \u8bc1\u636e\uff1a"),
    # inline key=value tokens
    ("testable=", "\u53ef\u68c0\u9a8c="),
    ("resolvable=", "\u53ef\u89e3\u51b3="),
    ("samples=", "\u6837\u672c\u6570="),
    ("status=", "\u72b6\u6001="),
    ("exit=", "\u9000\u51fa\u7801="),
    ("_none_", "_\u65e0_"),
]


def _translate_delta_body_cn(text):
    """Translate _format_delta_body output labels into Chinese (Bug 3 fix)."""
    for en, cn in DELTA_LABELS_CN:
        text = text.replace(en, cn)
    return text


def _format_delta_body(delta_key, delta, lang="en"):
    """Format a delta dict as markdown content (language-agnostic)."""
    if delta is None:
        return "_No delta found._\n"
    if not isinstance(delta, dict):
        return f"_Unexpected delta type: {type(delta).__name__}_\n"
    if "cn" in delta and lang == "cn":
        cn_delta = delta["cn"]
        # Only use cn sub-dict if it has the same structure as the English delta.
        # If cn fields have simplified types (e.g. attacks as string instead of list),
        # fall back to English content to avoid AttributeError in list traversal.
        _compatible = True
        for _k in ("attacks", "confounders", "diagnostic_tests",
                   "hypotheses", "strategies", "scripts_needed",
                   "qc_checkpoints", "failure_stop_rules",
                   "scripts_run", "evidence_verified",
                   "falsification_risks", "module_interpretations",
                   "publishable_now", "needs_more_work", "next_steps"):
            if _k in delta and _k in cn_delta:
                if type(delta[_k]) != type(cn_delta[_k]):
                    _compatible = False
                    break
        if _compatible:
            delta = cn_delta
    if isinstance(delta, dict) and "_error" in delta:
        return f"_Error reading delta: {delta['_error']}_\n"

    L = []
    if delta_key == "L0_linnaeus":
        L.append(f"**Skills found:** {_fmt_list(delta.get('skills_found'))}")
        L.append(f"**Skills gaps:** {_fmt_list(delta.get('skills_gaps'))}")
        L.append(f"**Input verified:** {_fmt_dict(delta.get('input_verified'))}")
        L.append(f"**Environment:** {_fmt_dict(delta.get('environment'))}")
        L.append(f"**Skill use plan:** {_fmt_list(delta.get('skill_use_plan'))}")
        L.append(f"**Forbidden shortcuts:** {_fmt_list(delta.get('forbidden_shortcuts'))}")
    elif delta_key == "L1_einstein":
        for h in delta.get("hypotheses", []):
            L.append(f"- **{h.get('id', '?')}:** {h.get('text', '')} (testable={h.get('testable', '?')})")
            L.append(f"  - Rationale: {h.get('rationale', '')}")
        L.append(f"\n**Primary hypothesis:** {delta.get('primary_hypothesis', '')}")
        L.append(f"**Key uncertainty:** {delta.get('key_uncertainty', '')}")
    elif delta_key == "L2_feynman":
        for a in delta.get("attacks", []):
            L.append(f"- **[{a.get('severity', '?')}]** {a.get('hypothesis_id', '?')}: {a.get('text', '')}")
        L.append("\n**Confounders:**")
        for c in delta.get("confounders", []):
            L.append(f"- [{c.get('severity', '?')}] {c.get('name', '')}: {c.get('text', '')}")
        L.append("\n**Diagnostic tests:**")
        for t in delta.get("diagnostic_tests", []):
            L.append(f"- {t.get('name', '')}: {t.get('text', '')}")
        L.append(f"\n**Verdict:** {delta.get('verdict', '')}")
    elif delta_key == "L3_oppenheimer":
        L.append(f"**Selected:** {_fmt_list(delta.get('selected'))}")
        L.append(f"**Rejected:** {_fmt_list(delta.get('rejected'))}")
        L.append(f"**Reason:** {delta.get('reason', '')}")
        L.append(f"**Route to:** {delta.get('route_to', '')}")
    elif delta_key == "L4_fisher":
        for s in delta.get("strategies", []):
            L.append(f"- **{s.get('id', '?')}: {s.get('name', '')}** (samples={s.get('samples', '?')}, status={s.get('status', '?')})")
            L.append(f"  - Steps: {_fmt_list(s.get('steps'))}")
        L.append(f"\n**Recommended:** {delta.get('recommended', '')}")
        L.append("\n**Scripts needed:**")
        for s in delta.get("scripts_needed", []):
            L.append(f"- {s.get('name', '')}: {s.get('purpose', '')} (status={s.get('status', '?')})")
        L.append(f"\n**Key decisions:** {_fmt_list(delta.get('key_decisions'))}")
    elif delta_key == "L5_tukey":
        for a in delta.get("attacks", []):
            L.append(f"- **[{a.get('severity', '?')}]** {a.get('target', '')}: {a.get('text', '')}")
        L.append("\n**QC checkpoints:**")
        for q in delta.get("qc_checkpoints", []):
            L.append(f"- {q.get('name', '')}: {q.get('text', '')}")
        L.append("\n**Failure stop rules:**")
        for fr in delta.get("failure_stop_rules", []):
            L.append(f"- {fr.get('name', '')}: {fr.get('text', '')}")
    elif delta_key == "L6_oppenheimer":
        L.append(f"**Approved strategy:** {delta.get('approved_strategy', '')}")
        L.append(f"**Modifications:** {_fmt_list(delta.get('modifications'))}")
        L.append(f"**Reason:** {delta.get('reason', '')}")
        ap = delta.get("analysis_plan", {})
        L.append("\n**Analysis plan:**")
        L.append(f"- Scripts: {_fmt_list(ap.get('scripts'))}")
        L.append(f"- Parameters: {_fmt_dict(ap.get('parameters'))}")
        L.append(f"- Outputs: {_fmt_list(ap.get('outputs'))}")
    elif delta_key == "L7_turing":
        for s in delta.get("scripts_run", []):
            L.append(f"- **{s.get('name', '')}** exit={s.get('exit_code', '?')}")
            L.append(f"  - Output files: {_fmt_list(s.get('output_files'))}")
        L.append(f"\n**Key results:** {_fmt_dict(delta.get('key_results'))}")
        if delta.get("warnings"):
            L.append(f"**Warnings:** {_fmt_list(delta.get('warnings'))}")
        if delta.get("failures"):
            L.append(f"**Failures:** {_fmt_list(delta.get('failures'))}")
    elif delta_key == "L8_curie":
        for e in delta.get("evidence_verified", []):
            L.append(f"- {e.get('file', '')}: {e.get('check', '')} = {e.get('result', '')}")
        L.append(f"\n**Evidence level:** {delta.get('evidence_level', '')}")
        if delta.get("caveats"):
            L.append(f"**Caveats:** {_fmt_list(delta.get('caveats'))}")
    elif delta_key == "L8.5_curie":
        for p in delta.get("papers_found", []):
            L.append(f"- **{p.get('title', '?')}** ({p.get('journal', '?')}, {p.get('year', '?')})")
            L.append(f"  - Relevance: {p.get('relevance', '')}")
            if p.get("supports"):
                L.append(f"  - Supports: {p.get('supports', '')}")
            if p.get("contradicts"):
                L.append(f"  - Contradicts: {p.get('contradicts', '')}")
        L.append(f"\n**Verification verdict:** {delta.get('verification_verdict', '')}")
        L.append(f"**Evidence alignment:** {delta.get('evidence_alignment', '')}")
        if delta.get("gaps"):
            L.append(f"**Literature gaps:** {_fmt_list(delta.get('gaps'))}")
    elif delta_key == "L9a_feynman":
        for r in delta.get("falsification_risks", []):
            L.append(f"- **[{r.get('severity', '?')}]** {r.get('name', '')} (resolvable={r.get('resolvable', '?')}): {r.get('text', '')}")
        L.append(f"\n**Survives:** {_fmt_list(delta.get('survives'))}")
        L.append(f"**Falsified:** {_fmt_list(delta.get('falsified'))}")
    elif delta_key == "L9b_darwin":
        for m in delta.get("module_interpretations", []):
            L.append(f"- **{m.get('module', '')}:** {m.get('meaning', '')}")
            L.append(f"  - Genes: {_fmt_list(m.get('genes'))}")
            L.append(f"  - Evidence: {m.get('evidence', '')}")
        L.append(f"\n**Convergent evolution:** {delta.get('convergent_evolution', '')}")
        L.append(f"**Limitations:** {_fmt_list(delta.get('limitations'))}")
    elif delta_key == "L10a_jobs":
        L.append(f"**Value assessment:** {delta.get('value_assessment', '')}")
        L.append(f"**Headline:** {delta.get('headline', '')}")
        L.append(f"\n**Publishable now:** {_fmt_list(delta.get('publishable_now'))}")
        L.append(f"**Needs more work:** {_fmt_list(delta.get('needs_more_work'))}")
        L.append(f"\n**Manuscript framing:** {delta.get('manuscript_framing', '')}")
    elif delta_key == "L10b_oppenheimer":
        L.append(f"**Decision:** {delta.get('decision', '')}")
        L.append(f"**Evidence level:** {delta.get('evidence_level', '')}")
        L.append(f"**Reason:** {delta.get('reason', '')}")
        L.append("\n**Next steps:**")
        for s in delta.get("next_steps", []):
            L.append(f"- {s}")
        nh = delta.get("next_round_hypothesis", "")
        if nh:
            L.append(f"\n**下一轮假说 (Next round hypothesis):** {nh}")
            L.append("\n> [硬约束 - HARD CONSTRAINT] L10b 必须基于本轮结果生成新假说，作为下一轮 RLR 循环的起点。")
    return "\n".join(L) + "\n" if L else "_Empty delta._\n"


SEED_SCHEMA_KEYS = [
    "source_candidate_id", "terminal_node", "terminal_decision", "original_question",
    "previous_hypothesis", "final_reason", "next_round_hypothesis",
    "previous_final_decision", "previous_conclusion", "new_hypothesis",
    "round_id", "parent_round_id",
    "required_new_search_directions", "evidence_kept", "evidence_dropped",
    "explored_branches", "unexplored_branches", "data_modalities_used",
    "data_modalities_available_unused", "paper_card_ids", "method_card_ids", "hashes",
]
