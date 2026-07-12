"""ContextAssembler: assemble isolated per-node context (Phase 2b-2).

Path B core. Imports only leaf modules + pitfall_ledger -> no engine cycle.
Preserves the DAG visibility rules (NODE_MAP context_inputs) and the
context_manifest.allowed_inputs / injected_deltas audit contract byte-for-byte.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pitfall_ledger as pl

from research_loop.paths import (
    _candidate_file, _pre_research_file, _sha256,
    _persona_template_path, _layer_template_path, _audit_dir,
)
from research_loop.topology import NODE_MAP, DELTA_DAG_ORDER
from research_loop.common import (
    PERSONA_TITLE, _now, _stamp, _input_alias, _everos_scopes_for,
)
from research_loop.delta import DELTA_SCHEMAS, _delta_for_candidate
from research_loop.yamlio import _load_yaml_front
from research_loop.preresearch import (
    PRE_RESEARCH_MAP, _LIT_PRE_RESEARCH_TYPES, _estimate_tokens,
    _extract_section, _runtime_digest_budget_error,
    _parse_pre_research_provenance,
)
from research_loop.gates import (
    _audit_pre_research, _audit_divergence, _audit_branch_coverage,
    _audit_l0_contract,
)
from research_loop import l0_contract


def strip_candidate_to_frontmatter(candidate_path, include_source_path=False):
    """Read a candidate .md, return only frontmatter dict (not body).

    Returns dict with: candidate_id, title, question, claim, current_status.
    The body is never returned -- it may contain downstream info that must
    stay invisible to subagents (Path B isolation).
    """
    fm = _load_yaml_front(Path(candidate_path))
    keep = {}
    for k in ("candidate_id", "title", "question", "claim",
              "current_status", "current_owner"):
        if k in fm:
            keep[k] = fm[k]
    # Input visibility (problem 3): cognitive nodes see only the path-free
    # alias; the input-verification node (L0) sees the real source_input path.
    if include_source_path and "source_input" in fm:
        keep["source_input"] = fm["source_input"]
    if fm.get("input_alias"):
        keep["input_alias"] = fm["input_alias"]
    elif not include_source_path and "source_input" in fm:
        keep["input_alias"] = _input_alias(fm["source_input"])  # back-compat
    return keep

def _condense_delta(delta_key, data):
    """Return a token-efficient, condensed copy of the delta data for aggregation."""
    if not isinstance(data, dict):
        return data
    import copy
    d = copy.deepcopy(data)
    
    # 1. Truncate large lists in L0 Linnaeus skills found
    if delta_key == "L0_linnaeus":
        if "skills_found" in d and isinstance(d["skills_found"], list) and len(d["skills_found"]) > 10:
            d["skills_found"] = d["skills_found"][:5] + [f"... ({len(d['skills_found'])} skills found in total)"]
            
    # 2. Truncate large lists of steps in L4 Fisher
    elif delta_key == "L4_fisher":
        if "strategies" in d and isinstance(d["strategies"], list):
            for s in d["strategies"]:
                if isinstance(s, dict) and "steps" in s and isinstance(s["steps"], list) and len(s["steps"]) > 5:
                    s["steps"] = s["steps"][:3] + [f"... ({len(s['steps'])} steps total)"]
                    
    # 3. Truncate large output_files or script results in L7 Turing
    elif delta_key == "L7_turing":
        if "scripts_run" in d and isinstance(d["scripts_run"], list):
            for s in d["scripts_run"]:
                if isinstance(s, dict) and "output_files" in s and isinstance(s["output_files"], list) and len(s["output_files"]) > 5:
                    s["output_files"] = s["output_files"][:3] + [f"... ({len(s['output_files'])} output files total)"]
                    
    # 4. Truncate evidence verified list in L8 Curie
    elif delta_key == "L8_curie":
        if "evidence_verified" in d and isinstance(d["evidence_verified"], list) and len(d["evidence_verified"]) > 10:
            d["evidence_verified"] = d["evidence_verified"][:5] + [f"... ({len(d['evidence_verified'])} files audited in total)"]

    # 5. Truncate long paper abstracts in L8.5 (Curie literature verification)
    elif delta_key == "L8.5_curie":
        if "papers" in d and isinstance(d["papers"], list):
            for p in d["papers"]:
                if isinstance(p, dict) and "abstract" in p and isinstance(p["abstract"], str) and len(p["abstract"]) > 150:
                    p["abstract"] = p["abstract"][:150] + "... (truncated abstract)"
                    
    # 6. Truncate huge gene lists in L9b Darwin module interpretations
    elif delta_key == "L9b_darwin":
        if "module_interpretations" in d and isinstance(d["module_interpretations"], list):
            for m in d["module_interpretations"]:
                if isinstance(m, dict) and "genes" in m and isinstance(m["genes"], list) and len(m["genes"]) > 5:
                    m["genes"] = m["genes"][:5] + [f"... ({len(m['genes'])} genes total)"]
                    
    return d

def _generate_contract(node_info, project_dir):
    """Generate compact template contract for cognitive nodes."""
    node_id = node_info["node"]
    persona = node_info["persona"]
    title = node_info.get("title", PERSONA_TITLE.get(persona, ""))
    schema_key = f"{node_id}_{persona.lower()}"
    schema = DELTA_SCHEMAS.get(schema_key, {})
    kb = node_info.get("knowledge_base", "none")
    lines = []
    lines.append(f"=== CONTRACT: {node_id} | {persona} | {title} ===")
    if persona == "Oppenheimer":
        lines.append("AUTHORITY: Can change candidate status (decision/triage).")
    elif node_info.get("is_execution"):
        lines.append("AUTHORITY: Can execute code in prepared Turing workspace only.")
    else:
        lines.append("AUTHORITY: No status changes, no code execution.")
    inputs = node_info.get("context_inputs", [])
    lines.append(f"INPUT SCOPE: {', '.join(inputs)}")
    if kb == "read-write":
        lines.append("KB: read-write")
    elif kb == "read":
        lines.append("KB: read-only")
    must = node_info.get("must", [])
    if must:
        lines.append("MUST:")
        for m in must:
            lines.append(f"  - {m}")
    must_not = node_info.get("must_not", [])
    if must_not:
        lines.append("MUST NOT:")
        for mn in must_not:
            lines.append(f"  - {mn}")
    stop = node_info.get("stop_conditions", [])
    if stop:
        lines.append("STOP IF:")
        for s in stop:
            lines.append(f"  - {s}")
    lines.append(f"OUTPUT: {schema_key} -- {list(schema.keys())}")
    lines.append(f"ACTION: {node_info.get('action_hint', '')}")
    return lines

def cmd_assemble_context(args):
    """Path B core: assemble context text for a DAG node."""
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2

    node_id = args.node
    if node_id not in NODE_MAP:
        print(f"ERROR: unknown node {node_id}", file=sys.stderr)
        return 2

    node_info = NODE_MAP[node_id]
    inputs = node_info["context_inputs"]

    # --- L0 structured input-contract gate (strict-on-reaching-L0) -----------
    # Fail closed BEFORE any context is rendered/printed: an invalid L0 input
    # contract yields rc=3 and empty stdout (never a partial prompt). This is
    # the assemble-side call of the ONE validator (gates._audit_l0_contract);
    # emit-delta L0 calls the same validator.
    l0_contract_obj = None
    if node_id == "L0":
        ok, reason = _audit_l0_contract(project_dir, args.cand_id)
        if not ok:
            print(f"ERROR: L0 input-contract gate -- {reason}", file=sys.stderr)
            print("Fix the candidate's l0_input.yaml (see "
                  ".claude/plan/l0-input-contract.md §10).", file=sys.stderr)
            return 3
        l0_contract_obj, _ap, _raw = l0_contract.load_contract(
            project_dir, args.cand_id)

    kb = node_info.get("knowledge_base", "none")
    sections = []
    directive = ("ISOLATION DIRECTIVE: Your entire input is below. Work only with "
                 "the information provided; do not access the filesystem")
    if kb == "read-write":
        directive += (", EXCEPT the external knowledge base 09_Literature_Database/, "
                      "which you MAY read AND add to (via manage_literature_db.py).")
    elif kb == "read":
        directive += (", EXCEPT the external knowledge base 09_Literature_Database/, "
                      "which you MAY READ to cite existing papers (Obsidian "
                      "wikilinks) -- you may NOT add to it.")
    else:
        directive += (". You have NO knowledge-base access; cite only papers "
                      "already present in your context.")
    sections.append(directive)
    sections.append("")

    injected = []  # audit: deltas actually embedded {delta_key, sha256, path}

    for inp in inputs:
        if inp == "candidate_frontmatter":
            # L0 (input verification) sees the real source_input path; every
            # other cognitive node sees only the path-free alias.
            fm = strip_candidate_to_frontmatter(
                cf, include_source_path=(node_id == "L0"))
            lines = ["=== CANDIDATE FRONTMATTER ==="]
            for k, v in fm.items():
                lines.append(f"  {k}: {v}")
            sections.append("\n".join(lines))
            sections.append("")
            # L0 (and only L0) physically receives the structured input contract
            # in its rendered context -> it flows into the provider prompt. The
            # scientific_question / source_input / previous_round fields are
            # L0-only, exactly like the source_input path exception above.
            if node_id == "L0" and l0_contract_obj is not None:
                sections.append(l0_contract.render_contract_block(l0_contract_obj))
                sections.append("")
        elif inp == "ALL":
            # L10c: read all deltas
            for delta_key in DELTA_DAG_ORDER:
                df = _delta_for_candidate(project_dir, delta_key, args.cand_id)
                if df and df.exists():
                    try:
                        data = json.loads(df.read_text(encoding="utf-8"))
                        lines = [f"=== DELTA: {delta_key} ==="]
                        condensed = _condense_delta(delta_key, data)
                        lines.append(json.dumps(condensed, indent=2, ensure_ascii=False))
                        sections.append("\n".join(lines))
                        sections.append("")
                        injected.append({"delta_key": delta_key,
                                         "sha256": _sha256(df), "path": str(df)})
                    except json.JSONDecodeError:
                        sections.append(f"=== DELTA: {delta_key} (parse error) ===")
                        sections.append("")
        else:
            # Delta reference (e.g. "L0", "L1", "L9a"): scan for the delta
            # whose key matches this node id (e.g. "L1" -> "L1_einstein") and
            # embed it as text.
            found = False
            corrupt = False
            for dk in DELTA_DAG_ORDER:
                if dk.startswith(inp + "_"):
                    df = _delta_for_candidate(project_dir, dk, args.cand_id)
                    if df and df.exists():
                        try:
                            data = json.loads(df.read_text(encoding="utf-8"))
                            lines = [f"=== DELTA: {dk} ==="]
                            condensed = _condense_delta(dk, data)
                            lines.append(json.dumps(condensed, indent=2, ensure_ascii=False))
                            sections.append("\n".join(lines))
                            sections.append("")
                            injected.append({"delta_key": dk,
                                             "sha256": _sha256(df), "path": str(df)})
                            found = True
                        except json.JSONDecodeError:
                            # File exists but is unreadable -- surface it as an
                            # error rather than silently reporting "not emitted".
                            sections.append(f"=== DELTA: {dk} (parse error) ===")
                            sections.append("")
                            corrupt = True
            if not found and not corrupt:
                sections.append(f"=== DELTA: {inp} (not yet emitted) ===")
                sections.append("")

    # --- V0.7 deep-research gate + pre-research injection --------------------
    # CANONICAL V0.7 RUNTIME: the literature deep-research stages (L1, L4) are
    # MANDATORY. assemble-context fails closed (rc=3) when their artifact is
    # missing, empty, a NOT YET RUN placeholder, or lacks a `## Runtime digest`
    # with a DOI/PMID/URL — it NEVER emits a NOT YET RUN section as a successful
    # context for them. Non-literature pre-research (L7 code_search) keeps its
    # prior soft note.
    pre_research_meta = None
    pr_cfg = PRE_RESEARCH_MAP.get(node_id)
    if pr_cfg:
        prf = _pre_research_file(project_dir, node_id)
        is_lit = pr_cfg.get("type") in _LIT_PRE_RESEARCH_TYPES
        if is_lit:
            ok, reason = _audit_pre_research(project_dir, node_id, pr_cfg)
            if not ok:
                print(f"ERROR: V0.7 deep-research gate -- {node_id} pre-research "
                      f"invalid: {reason}", file=sys.stderr)
                print(f"Run real deep research and write a valid artifact to "
                      f"{prf.as_posix()} first (no 'NOT YET RUN' placeholder).",
                      file=sys.stderr)
                return 3
            # v0.6 divergence + branch-coverage gates (L1, from_memory only)
            if node_id == "L1":
                dok, dreason = _audit_divergence(project_dir, node_id, args.cand_id)
                if not dok:
                    print(f"ERROR: {dreason}", file=sys.stderr)
                    return 3
                bok, breason = _audit_branch_coverage(project_dir, args.cand_id)
                if not bok:
                    print(f"ERROR: {breason}", file=sys.stderr)
                    return 3
        if prf.exists():
            pr_sections, pre_research_meta = _inject_pre_research(
                prf, pr_cfg, args, node_id)
            if pre_research_meta.get("error"):
                print(f"ERROR: pre-research injection failed closed for "
                      f"{node_id}: {pre_research_meta['error']}",
                      file=sys.stderr)
                return 2
            sections.extend(pr_sections)
        else:
            # Non-literature node (e.g. L7 code_search): soft, not a hard gate.
            sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}): NOT YET RUN ===")
            sections.append(
                f"Run first: python research_loop_v04.py pre-research "
                f"{project_dir} {args.cand_id} --node {node_id}")
            sections.append("")
            pre_research_meta = {"type": pr_cfg["type"], "present": False}

    # --- pitfall cards: only THIS node's confirmed/promoted pitfalls (project +
    # global), never the whole history -> no context pollution. ---
    pitfall_meta = []
    node_pitfalls = pl.scan_pitfalls(project_dir, node=node_id)
    if node_pitfalls:
        sections.append(pl.format_pitfall_cards(project_dir, node=node_id))
        sections.append("")
        pitfall_meta = [{"id": r["id"], "severity": r["severity"],
                         "category": r.get("category"),
                         "source": r.get("source", "project")}
                        for r in node_pitfalls]
    if node_id == "L0":
        # v0.6: inject compact prior-loop memory (IDs + directions only, no full text)
        try:
            _cf0 = _candidate_file(project_dir, args.cand_id)
            _fm0 = _load_yaml_front(_cf0) if _cf0 and _cf0.exists() else {}
            if _fm0.get("from_memory") and _fm0.get("memory_file"):
                _mp = Path(_fm0["memory_file"])
                if _mp.exists():
                    _mem = json.loads(_mp.read_text(encoding="utf-8"))
                    sections.append("=== PRIOR LOOP MEMORY (divergence contract) ===")
                    sections.append(f"loop_type: {_fm0.get('loop_type', '')}")
                    sections.append(f"prior_candidate: {_mem.get('source_candidate_id', '')}")
                    sections.append(f"previous_hypothesis: {_mem.get('previous_hypothesis', '')}")
                    sections.append(f"final_decision: {_mem.get('terminal_decision', '')}")
                    sections.append(f"next_round_hypothesis: {_mem.get('next_round_hypothesis', '')}")
                    _dirs = _mem.get("required_new_search_directions", []) or []
                    sections.append("required_new_search_directions: " + "; ".join(str(x) for x in _dirs))
                    _unexp = [b.get("id") for b in (_mem.get("unexplored_branches", []) or []) if b.get("id")]
                    sections.append("prior_unexplored_branches (must be statused): " + ", ".join(_unexp))
                    _unused = _mem.get("data_modalities_available_unused", []) or []
                    sections.append("data_modalities_available_unused: " + ", ".join(str(x) for x in _unused))
                    sections.append("Your L0 delta MUST include a `prior_loop_memory` object "
                                    f"with memory_hash={_fm0.get('memory_hash', '')}.")
                    sections.append("")
        except Exception:
            pass
        gate_candidates = pl.list_pitfalls(
            project_dir, status="draft", node="L0",
            category="preflight_gate_candidate")
        if gate_candidates:
            sections.append("=== L0 PREFLIGHT GATE CANDIDATES (draft) ===")
            sections.append("Review these L7-derived candidates. Confirm one "
                            "to activate the L0 hard-stop gate, or mark it "
                            "obsolete/false_positive if resolved.")
            for pit in gate_candidates:
                sections.append(f"[{pit['id']}] severity={pit['severity']} "
                                f"promoted_to={pit.get('promoted_to', '')}")
                sections.append(f"  Symptom: {pit.get('symptom', '')}")
                sections.append(f"  Root cause: {pit.get('root_cause', '')}")
                sections.append("  Prevention: "
                                f"{pit.get('prevention_rule', '')}")
            sections.append("")
            pitfall_meta.extend(
                {"id": p["id"], "severity": p["severity"],
                 "category": p.get("category"), "status": p.get("status"),
                 "promoted_to": p.get("promoted_to")}
                for p in gate_candidates)

    # --- template contract (V0.7) ---
    #   contract (default): compact authority/scope/must/schema; NO template body.
    #   refs: path+sha256 only -- LEGAL ONLY for filesystem (execution) nodes. A
    #     no-fs cognitive node must never run blind to its template, so refs on a
    #     no-fs node fails closed.
    #   full: contract + entire persona/layer bodies (debug only).
    template_mode = getattr(args, "template_mode", "contract")
    is_exec = node_info.get("is_execution", False)
    persona = node_info["persona"]
    if template_mode == "refs" and not is_exec:
        print(f"ERROR: --template-mode refs is not allowed for the no-fs "
              f"cognitive node {node_id} (tools_policy="
              f"{node_info.get('tools_policy')}). refs only applies to execution "
              f"(workspace-fs) nodes; use contract.", file=sys.stderr)
        return 2

    contract_text = "\n".join(_generate_contract(node_info, project_dir))
    contract_hash = hashlib.sha256(contract_text.encode("utf-8")).hexdigest()
    sections.append(contract_text)
    sections.append("")

    _script_dir = Path(__file__).resolve().parent.parent
    ptpl = _script_dir / _persona_template_path(persona)
    ltpl = _script_dir / _layer_template_path(node_id)
    full_templates_injected = False
    contract_hashes = {
        "contract": contract_hash,
        "persona_template": _sha256(ptpl) or "missing",
        "layer_template": _sha256(ltpl) or "missing",
    }
    if template_mode == "full":
        for label, tpl in (("persona", ptpl), ("layer", ltpl)):
            sections.append(f"--- [full] {label} template ({tpl.name}) "
                            f"sha256:{_sha256(tpl) or 'missing'} ---")
            sections.append(tpl.read_text(encoding="utf-8") if tpl.exists()
                            else "(template file not found on disk)")
            sections.append("")
            full_templates_injected = True
    elif template_mode == "refs":
        for label, tpl in (("persona", ptpl), ("layer", ltpl)):
            sections.append(f"--- [refs] {label} template: {tpl} "
                            f"sha256:{_sha256(tpl) or 'missing'} ---")
        sections.append("")
    # contract mode: the CONTRACT block above is the entire template view.

    # --- bilingual directive: only the reporting nodes (L10a/L10b/L10c) ---
    if node_id in ("L10a", "L10b", "L10c"):
        sections.append("=== BILINGUAL OUTPUT DIRECTIVE ===")
        sections.append("Your delta JSON must include a \"cn\" key with Chinese "
                        "translations of all")
        sections.append("human-readable field values (verdicts, reasons, "
                        "interpretations, headlines,")
        sections.append("next steps). Top-level English fields stay the canonical "
                        "machine-readable")
        sections.append("values; \"cn\" feeds FINAL_REPORT_CN.md generation.")
        sections.append("")

    # --- audit: context_manifest declaring template_mode + every injected
    # artifact (emit-delta --receipt verifies the injected_deltas hashes). ---
    project_id = project_dir.name
    workspaces = sorted(project_dir.glob("_turing_workspace_*"))
    manifest_id = _stamp()
    context_text = "\n".join(sections)
    context_text, caveman_meta = _caveman_lite(
        context_text, required_literals=[args.cand_id, node_id, persona])
    context_budget = getattr(args, "context_token_budget", 8000)
    est_context_tokens = _estimate_tokens(context_text)
    if context_budget and est_context_tokens > context_budget:
        print(f"ERROR: context token budget exceeded "
              f"(~{est_context_tokens} > {context_budget}). "
              f"Reduce injected context or raise --context-token-budget.",
              file=sys.stderr)
        return 2
    manifest = {
        "manifest_id": manifest_id,
        "candidate_id": args.cand_id,
        "node": node_id,
        "persona": persona,
        "timestamp": _now(),
        "template_mode": template_mode,
        "contract_hash": contract_hash,
        "contract_hashes": contract_hashes,
        "full_templates_injected": full_templates_injected,
        "allowed_inputs": list(inputs),
        "injected_deltas": injected,
        "tools_policy": node_info.get("tools_policy"),
        "everos_read_scopes": _everos_scopes_for(node_info, project_id),
        "knowledge_base": node_info.get("knowledge_base"),
        "workspace": (str(workspaces[-1])
                      if (is_exec and workspaces) else None),
        "pre_research": pre_research_meta,
        "pitfalls_injected": pitfall_meta,
        **caveman_meta,
    }
    mpath = (_audit_dir(project_dir)
             / f"context_manifest_{node_id}_{manifest_id}.json")
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                     encoding="utf-8")

    print(context_text)
    print(f"[audit] context manifest: {mpath}", file=sys.stderr)
    return 0

def _caveman_required_literals(text, extra=None):
    """Collect identifiers that derived lite compression must preserve."""
    required = list(extra or [])
    patterns = (
        r"https?://\S+",
        r"10\.\d{4,9}/\S+",
        r"PMID:?\s*\d+",
        r"\bC\d{8,}\b",
    )
    for pattern in patterns:
        required.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if ("python " in lower or "fail closed" in lower
                or "do not fabricate" in lower or stripped.startswith("OUTPUT:")):
            required.append(stripped)
    return list(dict.fromkeys(str(x) for x in required if str(x)))

def _caveman_lite(text, required_literals=None):
    """Deterministically pack derived context text without mutating its source."""
    original_tokens = _estimate_tokens(text)
    required = _caveman_required_literals(text, required_literals)
    if any(literal not in text for literal in required):
        return text, {
            "caveman_mode": "lite",
            "original_est_tokens": original_tokens,
            "compressed_est_tokens": original_tokens,
            "compression_applied": False,
            "required_fields_preserved": False,
        }

    source_lines = text.splitlines()
    derived_lines = []
    i = 0
    while i < len(source_lines):
        line = source_lines[i]
        derived_lines.append(line)
        if line.startswith("=== DELTA:") and i + 1 < len(source_lines):
            start = i + 1
            if source_lines[start].strip() == "{":
                for end in range(start + 1, len(source_lines) + 1):
                    candidate = "\n".join(source_lines[start:end])
                    try:
                        data = json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
                    derived_lines.append(json.dumps(
                        data, ensure_ascii=False, separators=(", ", ": ")))
                    i = end - 1
                    break
        i += 1

    packed_lines = []
    previous = None
    blank = False
    in_code = False
    for line in derived_lines:
        stripped = line.rstrip()
        if stripped.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code and not stripped:
            if blank:
                continue
            blank = True
        else:
            blank = False
        is_prose = bool(stripped) and not stripped.lstrip().startswith(
            ("#", "-", "*", ">", "{", "}", "[", "]", '"', "```"))
        if not in_code and is_prose and stripped == previous:
            continue
        packed_lines.append(stripped)
        previous = stripped if stripped else previous
    packed = "\n".join(packed_lines)
    if text.endswith("\n"):
        packed += "\n"

    preserved = all(literal in packed for literal in required)
    if not preserved:
        packed = text
    compressed_tokens = _estimate_tokens(packed)
    applied = preserved and packed != text and compressed_tokens < original_tokens
    return packed, {
        "caveman_mode": "lite",
        "original_est_tokens": original_tokens,
        "compressed_est_tokens": compressed_tokens,
        "compression_applied": applied,
        "required_fields_preserved": preserved,
    }

def _inject_pre_research(prf, pr_cfg, args, node_id):
    # Return (sections_to_append, pre_research_meta_dict).
    # Modes: digest (default), excerpt, full, none.
    mode = getattr(args, "pre_research_mode", "digest")
    budget = getattr(args, "pre_research_token_budget", None)
    if budget is None:
        budget = pr_cfg.get("budget", 800)
    full_text = prf.read_text(encoding="utf-8")
    est_full = _estimate_tokens(full_text)
    sections = []
    injected_text = ""
    warns = []
    fatal_error = None
    digest = _extract_section(full_text, "Runtime digest")
    archived_only = False
    omitted_reason = None

    if (budget == 0
            and pr_cfg.get("type") not in _LIT_PRE_RESEARCH_TYPES):
        archived_only = True
        omitted_reason = "budget=0 / archived-only"
        mode = "archived-only"
        sections.append(
            f"=== PRE-RESEARCH ({pr_cfg['type']}): ARCHIVED ONLY "
            "(budget=0; omitted) ===")
        injected_text = ""

    elif mode == "none":
        sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}): ARCHIVED ONLY ===")
        injected_text = "(not injected)"

    elif mode == "full":
        sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}) [FULL] ===")
        sections.append(full_text)
        injected_text = full_text

    elif mode == "excerpt":
        if est_full <= budget:
            sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}) ===")
            sections.append(full_text)
            injected_text = full_text
        else:
            # Deterministic: keep headers + first lines per section
            limit = budget * 2  # char budget (rough)
            truncated = full_text[:limit]
            if "\n## " in truncated:
                truncated = truncated[:truncated.rfind("\n## ")]
            sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}) [excerpt] ===")
            sections.append(truncated)
            sections.append(f"(truncated from ~{est_full} to ~{_estimate_tokens(truncated)} tokens)")
            injected_text = truncated
            warns.append("excerpt_may_omit_caveats")

    else:  # digest (default)
        if digest:
            est_digest = _estimate_tokens(digest)
            if est_digest > budget:
                msg = _runtime_digest_budget_error(est_digest, budget)
                sections.append(f"=== PRE-RESEARCH ERROR: {msg} ===")
                sections.append("")
                injected_text = "(rejected: over budget)"
                fatal_error = msg
            else:
                sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}) [digest] ===")
                sections.append(digest)
                injected_text = digest
        else:
            if est_full <= budget:
                sections.append(f"=== PRE-RESEARCH ({pr_cfg['type']}) [fallback: full under budget] ===")
                sections.append(full_text)
                injected_text = full_text
            else:
                msg = (f"No ## Runtime digest section and full text exceeds "
                       f"budget ({est_full} > {budget})")
                sections.append(f"=== PRE-RESEARCH ERROR: {msg} ===")
                sections.append("Fix: add '## Runtime digest' section to the pre-research file, or use --pre-research-mode full/excerpt.")
                sections.append("")
                injected_text = "(rejected: no digest, over budget)"
                fatal_error = msg

    sections.append("")

    provenance = _parse_pre_research_provenance(full_text)
    meta = {
        "pre_research_path": str(prf),
        "pre_research_sha256": _sha256(prf),
        "pre_research_chars": len(full_text),
        "estimated_tokens": est_full,
        "injected_mode": mode,
        "injected_tokens_est": _estimate_tokens(injected_text) if injected_text and not injected_text.startswith("(") else 0,
        "full_text_injected": mode == "full" or (mode == "digest" and _extract_section(full_text, "Runtime digest") == "" and est_full <= budget),
        "archived_only": archived_only,
        "digest_present": bool(digest),
        "digest_tokens_est": _estimate_tokens(digest) if digest else 0,
        "omitted_reason": omitted_reason,
        # V0.6 provenance (parsed + persisted; enforced in PR2)
        "query_log": provenance["query_log"],
        "tool_receipt": provenance["tool_receipt"],
        "source_count": provenance["source_count"],
        "source_count_declared": provenance["source_count_declared"],
    }
    if warns:
        meta["warnings"] = warns
    if fatal_error:
        meta["error"] = fatal_error

    return sections, meta
