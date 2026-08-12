"""Reporting CLI command family (extracted from engine.py)."""

import json
import re
import sys
from pathlib import Path

from research_loop.common import _now
from research_loop.delta import _delta_for_candidate
from research_loop.delta_render import (
    SECTION_TITLES_CN,
    SECTION_TITLES_EN,
    _format_delta_body,
    _translate_delta_body_cn,
)
from research_loop.paths import _candidate_file
from research_loop.topology import DELTA_DAG_ORDER
from research_loop.delta import DELTA_PERSONA
from research_loop.compatibility import PROFILE_V20, get_profile
from research_loop.hypothesis_ledger import binding_path
from research_loop.delta import artifact_for_node
from research_loop.l0_state import L0StateError, write_round_manifest
from research_loop.yamlio import _load_yaml_front
from research_loop.version import VERSION

__version__ = VERSION


def _profile_for_project(project_dir: Path):
    """Read the immutable project binding without inventing a schema profile."""
    path = binding_path(project_dir)
    if not path.is_file():
        return get_profile(PROFILE_V20)
    try:
        return get_profile(str(json.loads(path.read_text(encoding="utf-8"))["profile_id"]))
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid project profile binding: {exc}") from exc


def cmd_list(args):
    project_dir = Path(args.project_dir)
    cdir = project_dir / "01_Candidates"
    adir = project_dir / "99_Archive"
    print(f"# Candidates in {project_dir}\n")
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            fm = _load_yaml_front(f)
            print(f"- [{fm.get('current_status','?')}] {fm.get('candidate_id','?')}"
                  f"  owner={fm.get('current_owner','?')}  | {fm.get('title','')}")
    print("\n# Archived\n")
    if adir.exists():
        for f in sorted(adir.glob("*.md")):
            fm = _load_yaml_front(f)
            print(f"- [{fm.get('current_status','?')}] {fm.get('candidate_id','?')}"
                  f"  | {fm.get('title','')}")
    return 0


def cmd_show(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        cf = Path(project_dir) / "99_Archive" / f"{args.cand_id}.md"
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    print(cf.read_text(encoding="utf-8"))
    return 0


def cmd_obsidian_sync(args):
    """Delegate to the single human-readable Obsidian sync implementation."""
    import sync_to_obsidian

    rc = sync_to_obsidian.sync_project(
        args.project_dir, vault_dir=getattr(args, "vault", None))
    return 0 if rc == 0 else 2


def _shared_report_owner(shared_path):
    if not shared_path.exists():
        return None
    head = shared_path.read_text(encoding="utf-8")[:200]
    m = re.search(r"candidate (C\w+)", head)
    return m.group(1) if m else None


def _update_reports_index(project_dir, cand_id, status):
    idx = Path(project_dir) / "00_Reports_Index.md"
    lines = idx.read_text(encoding="utf-8").splitlines() if idx.exists() else ["# Reports Index", ""]
    lines = [ln for ln in lines if f"FINAL_REPORT_{cand_id}.md" not in ln]
    lines.append(f"- [{cand_id}](FINAL_REPORT_{cand_id}.md) -- status: {status}")
    idx.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_aggregate_report(args):
    """L10c Linnaeus: read all delta JSON, generate FINAL_REPORT.md + _CN.md."""
    import json

    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    try:
        profile = _profile_for_project(project_dir)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Read all deltas in DAG order
    deltas = {}
    for delta_key in DELTA_DAG_ORDER:
        persona = DELTA_PERSONA[delta_key]
        storage_key = (artifact_for_node(profile, "L8").storage_key
                       if delta_key == "L8_curie" else delta_key)
        delta_path = _delta_for_candidate(project_dir, storage_key, args.cand_id)
        if delta_path and delta_path.exists():
            try:
                deltas[delta_key] = json.loads(delta_path.read_text(encoding="utf-8"))
            except Exception as e:
                deltas[delta_key] = {"_error": str(e)}
        else:
            deltas[delta_key] = None

    title = fm.get("title", args.cand_id)
    question = fm.get("question", "")
    claim = fm.get("claim", "")
    status = fm.get("current_status", "?")

    # --- English report ---
    en = []
    en.append(f"# Final Report: {title}\n")
    en.append(f"**Candidate:** {args.cand_id}")
    en.append(f"**Status:** {status}")
    en.append(f"**Generated:** {_now()}")
    en.append(f"**Framework:** RLR v{__version__}\n")
    en.append("![Continuous enhancer Signal per pathway](03_Figures/deltaSignal_pathway_comparison.png)\n")
    en.append(f"## Scientific Question\n\n{question}\n")
    en.append(f"## Claim\n\n{claim}\n")

    for delta_key in DELTA_DAG_ORDER:
        title_en = SECTION_TITLES_EN.get(delta_key, delta_key)
        if delta_key == "L8_curie":
            title_en = (
                f"L8 - Evidence Audit "
                f"({artifact_for_node(profile, 'L8').display_persona})"
            )
        en.append(f"## {title_en}\n")
        en.append(_format_delta_body(delta_key, deltas.get(delta_key)))
        en.append("")

    final = fm.get("final_decision", "")
    en.append("---\n")
    en.append(f"**Final decision:** {final}\n")
    en.append(f"_Report generated by RLR v{__version__} aggregate-report (L10c Linnaeus)_")

    en_report = "\n".join(en)
    # v0.6: candidate-scoped canonical report (never clobbered by another candidate)
    en_path = project_dir / f"FINAL_REPORT_{args.cand_id}.md"
    en_path.write_text(en_report, encoding="utf-8")

    # --- Chinese report ---
    cn = []
    cn.append(f"# 最终报告: {title}\n")
    cn.append(f"**候选编号:** {args.cand_id}")
    cn.append(f"**状态:** {status}")
    cn.append(f"**生成时间:** {_now()}")
    cn.append(f"**框架:** RLR v{__version__}\n")
    cn.append(f"## 科学问题\n\n{question}\n")
    cn.append(f"## 主张\n\n{claim}\n")
    cn.append("> 注：以下 delta 内容由各 persona 生成，如未包含 `cn` 字段则为英文原文。下一轮 v0.4 循环将要求 agent 同时输出中文版。\n")

    for delta_key in DELTA_DAG_ORDER:
        title_cn = SECTION_TITLES_CN.get(delta_key, delta_key)
        if delta_key == "L8_curie":
            title_cn = (
                f"L8 - 证据审查 "
                f"({artifact_for_node(profile, 'L8').display_persona})"
            )
        cn.append(f"## {title_cn}\n")
        cn.append(_translate_delta_body_cn(
            _format_delta_body(delta_key, deltas.get(delta_key), lang="cn")))
        cn.append("")

    cn.append("---\n")
    cn.append(f"**最终决策:** {final}\n")
    cn.append(f"_报告由 RLR v{__version__} aggregate-report (L10c Linnaeus) 生成_")

    cn_report = "\n".join(cn)
    cn_path = project_dir / f"FINAL_REPORT_CN_{args.cand_id}.md"
    cn_path.write_text(cn_report, encoding="utf-8")

    # v0.6: shared FINAL_REPORT.md is a pointer to the latest candidate. Candidate-
    # scoped copies above are never overwritten; the shared file advances with an
    # audit NOTE when it changes owner (silence with --force).
    shared = project_dir / "FINAL_REPORT.md"
    prev_owner = _shared_report_owner(shared)
    banner = f"<!-- shared FINAL_REPORT points to candidate {args.cand_id} -->\n"
    if prev_owner and prev_owner != args.cand_id and not getattr(args, "force", False):
        print(f"NOTE: repointing FINAL_REPORT.md from {prev_owner} to {args.cand_id} "
              f"(candidate-scoped copies preserved).", file=sys.stderr)
    shared.write_text(banner + en_report, encoding="utf-8")
    (project_dir / "FINAL_REPORT_CN.md").write_text(banner + cn_report, encoding="utf-8")
    _update_reports_index(project_dir, args.cand_id, status)

    # L10c freezes the physical evidence state after candidate-scoped reports
    # exist. Large files remain in place and are bound by exact path + SHA-256.
    try:
        manifest_path, manifest_hash = write_round_manifest(project_dir, args.cand_id)
    except L0StateError as exc:
        print(f"ERROR: {exc.code}: {exc.detail}", file=sys.stderr)
        return 2

    found = sum(1 for v in deltas.values() if v is not None)
    print(f"FINAL_REPORT generated:")
    print(f"  EN: {en_path}")
    print(f"  CN: {cn_path}")
    print(f"  shared: {shared}")
    print(f"  round manifest: {manifest_path} sha256={manifest_hash}")
    print(f"  deltas found: {found}/{len(DELTA_DAG_ORDER)}")
    return 0