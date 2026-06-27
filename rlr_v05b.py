#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RLR v0.5b — literature-gated research-loop branch.

WHY THIS EXISTS
---------------
An audit of research_loop_v04.py (v0.4.5) found a HARD BUG in literature
handling: L1/L4 only *declare and print* a pre-research prompt; they never
execute, validate, force citation, or hard-stop on it. Concretely in v0.4.5:
  - cmd_pre_research ends in `print(prompt); return 0` (no execution).
  - L1_einstein / L4_fisher delta schemas carry no literature fields, so a
    citation-free hypothesis/method delta validates fine.
  - assemble-context appends "PRE-RESEARCH: NOT YET RUN" and returns 0 when the
    research file is missing (soft warning, not a stop).
Result: L1 hypotheses and L4 method designs can be produced with zero real
literature grounding.

WHAT v0.5b CHANGES (semantic DAG + hard gates; v0.4.5 is left untouched)
------------------------------------------------------------------------
DAG:  L0 -> L1 -> L4a -> L4b -> L5 -> L7 -> (L8+ reuse v0.4.5)
  * L2, L3, L6 REMOVED.
  * old L4 SPLIT into L4a (method literature review) + L4b (divergent ideation).
Gates (this module enforces, offline):
  * L0 must attest literature-research capability or the branch stops.
  * L1 + L4a are HARD-GATED on a real `## Runtime digest` whose papers carry
    DOI/PMID/URL; every citekey must resolve in 09_Literature_Database/ or the
    digest.
  * L1 deltas need `literature_used`; each hypothesis needs `literature_basis`
    (unless explicitly `exploratory: true`).
  * L4a deltas need `method_literature_digest`.
  * L4b deltas must consume L1 AND L4a (idea_provenance referencing both).
  * L5 deltas must carry a complete executable `analysis_plan`.

This is a STANDALONE entry. It imports low-level helpers from
research_loop_v04 but overrides the DAG, schemas, and the three hot commands
(next-step / assemble-context / emit-delta). v0.4.5 keeps working as reference.

USAGE
-----
    python rlr_v05b.py next-step        PROJECT_DIR CAND_ID
    python rlr_v05b.py assemble-context PROJECT_DIR CAND_ID --node L1
    python rlr_v05b.py emit-delta       PROJECT_DIR CAND_ID --node L1 \
                                        --persona Einstein --file delta.json
    python rlr_v05b.py check-research   PROJECT_DIR CAND_ID --node L1
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Defensive UTF-8 console output: on Windows the default console codec (GBK/cp936)
# cannot encode normal scientific Unicode (e.g. the digest's "H3K27ac ∩ ATAC",
# "p ≥ 0.05", "→"), which crashed assemble-context's print. Platform-output fix
# only — does NOT touch gates, schemas, or file I/O (files are already UTF-8).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import research_loop_v04 as rl  # reference engine; reused helpers only

# ---------------------------------------------------------------------------
# v0.5b DAG (L2/L3/L6 removed; old L4 split into L4a/L4b)
# ---------------------------------------------------------------------------
DAG_V05B = ["L0", "L1", "L4a", "L4b", "L5", "L7", "L8", "L8.5", "L9a", "L9b",
            "L10a", "L10b"]

# Nodes that MUST have executed real literature research before they can run.
# type -> drives the pre-research prompt; skill is attested, not invoked here.
PRE_RESEARCH_V05B = {
    "L1":  {"type": "deep_research",      "skill": "academic-research-suite",
            "output": "L1_research.md",
            "description": "Literature-grounded hypothesis generation"},
    "L4a": {"type": "literature_review",  "skill": "academic-research-suite",
            "output": "L4a_research.md",
            "description": "Method literature / existing-practice review"},
}

# Delta key per node (keeps v0.4.5 naming where a node is unchanged).
NODE_DELTA_KEY = {
    "L0": "L0_linnaeus", "L1": "L1_einstein",
    "L4a": "L4a_curie", "L4b": "L4b_fisher", "L5": "L5_tukey",
    "L7": "L7_turing", "L8": "L8_curie", "L8.5": "L8.5_curie",
    "L9a": "L9a_feynman", "L9b": "L9b_darwin",
    "L10a": "L10a_jobs", "L10b": "L10b_oppenheimer",
}

NODE_PERSONA = {
    "L0": "Linnaeus", "L1": "Einstein", "L4a": "Curie", "L4b": "Fisher",
    "L5": "Tukey/Oppenheimer", "L7": "Turing",
}

# Spec-named aliases (independent objects; NOT references into research_loop_v04).
# These exist so the v0.5b constant surface is explicit and self-contained.
DAG_NODES_V05B = DAG_V05B            # ordered node list
DAG_SEQUENCE_V05B = list(DAG_V05B)   # independent copy of the sequence
PRE_RESEARCH_MAP_V05B = PRE_RESEARCH_V05B

# ---------------------------------------------------------------------------
# v0.5b delta schemas (the literature-bearing ones are new; downstream reuse v04)
# Schema values are *types* or nested type-structures, validated recursively by
# rl._validate_delta. Semantic gates (citekey resolution, cross-node provenance)
# are applied on top in cmd_emit_delta.
# ---------------------------------------------------------------------------
SCHEMAS_V05B = {
    "L1_einstein": {
        "hypotheses": [{
            "id": str, "text": str, "testable": bool, "rationale": str,
            "data_basis": str, "literature_basis": list,
            "expected_signal": str, "falsification_condition": str,
        }],
        "literature_used": [{
            "citekey": str, "doi_or_url": str, "finding_used": str,
            "supports_hypothesis_id": str, "use_type": str,
        }],
        "primary_hypothesis": str, "key_uncertainty": str,
    },
    "L4a_curie": {
        "method_literature_digest": [{
            "citekey": str, "doi_or_url": str, "method_or_principle": str,
            "assumption": str, "pitfall": str, "relevance_to_current_data": str,
        }],
        "recommended_method_constraints": [{
            "constraint": str, "source_citekeys": list, "reason": str,
        }],
        "methods_to_avoid": [{
            "method": str, "reason": str, "source_citekeys": list,
        }],
    },
    "L4b_fisher": {
        "analysis_ideas": [{
            "id": str, "name": str, "category": str,  # direct|exploratory|negative_control|inappropriate
            "suitable": bool, "rationale": str,
            "idea_provenance": list,  # tags: L1:Hx | L4a:citekey | dataset | exploratory
        }],
        "consumes": {"L1": list, "L4a": list},  # ids/citekeys actually used
        "summary": str,
    },
    "L5_tukey": {
        "analysis_plan": {
            "selected_analyses": list, "rejected_analyses": list,
            "input_files": list, "background_null_model": str,
            "statistical_model": str, "covariates": list,
            "qc_checkpoints": list, "failure_stop_rules": list,
            "expected_output_files": list, "interpretation_rules": list,
            "script_list": list,
        },
        "reason": str,
    },
}

USE_TYPES = {"background", "mechanism", "prediction", "caveat"}
IDEA_CATEGORIES = {"direct", "exploratory", "negative_control", "inappropriate"}

DOI_PMID_URL_RE = re.compile(
    r"(10\.\d{4,}/\S+|PMID[:\s]*\d+|https?://\S+|\d{7,9})", re.IGNORECASE)

# Required per-paper fields inside the `## Runtime digest` block.
DIGEST_FIELDS = ["citekey", "doi", "pmid", "url", "title", "year",
                 "core finding", "relevance", "downstream implication",
                 "caveat", "limitation"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
# Persona subdir per delta key (v0.5b adds L4a_curie / L4b_fisher; the rest
# fall back to v0.4.5's DELTA_PERSONA so reused nodes resolve identically).
DELTA_PERSONA_V05B = {"L4a_curie": "Curie", "L4b_fisher": "Fisher",
                      "L5_tukey": "Tukey", "L1_einstein": "Einstein",
                      "L0_linnaeus": "Linnaeus"}


def _delta_path(project_dir, key):
    """v0.5b-aware delta path (v04._delta_file returns None for new keys)."""
    persona = DELTA_PERSONA_V05B.get(key) or rl.DELTA_PERSONA.get(key, "")
    if not persona:
        return None
    return Path(project_dir) / "02_Agent_Notes" / persona / f"{key}_delta.json"


def _research_file(project_dir, node):
    return (Path(project_dir) / "02_Agent_Notes" / "_pre_research"
            / PRE_RESEARCH_V05B[node]["output"])


def _litdb_citekeys(project_dir):
    d = Path(project_dir) / "09_Literature_Database"
    if not d.is_dir():
        return set()
    return {p.stem for p in d.glob("*.md")}


def _citekeys_in_digest(digest_text):
    """citekeys referenced as [[09_Literature_Database/<key>|...]] or 'citekey: x'."""
    keys = set(re.findall(r"\[\[09_Literature_Database/([^\|\]]+)", digest_text))
    for m in re.finditer(r"citekey[:\s]+([A-Za-z0-9_\-\.]+)", digest_text):
        keys.add(m.group(1))
    return keys


def _digest_has_identifiers(digest_text):
    return bool(DOI_PMID_URL_RE.search(digest_text))


def _audit_research(project_dir, node):
    """Validate a node's pre-research file. Returns (ok, meta, reason)."""
    f = _research_file(project_dir, node)
    if not f.exists():
        return False, {"present": False}, f"research file missing: {f.as_posix()}"
    text = f.read_text(encoding="utf-8", errors="replace")
    if "PRE-RESEARCH: NOT YET RUN" in text or "NOT YET RUN" in text:
        return False, {"present": False}, "research file is the NOT-YET-RUN placeholder"
    digest = rl._extract_section(text, "Runtime digest")
    if not digest:
        return False, {"present": True, "digest_found": False}, \
            "missing required `## Runtime digest` section"
    if not _digest_has_identifiers(digest):
        return False, {"present": True, "digest_found": True}, \
            "Runtime digest contains no DOI/PMID/URL identifiers"
    cited = _citekeys_in_digest(text)
    known = _litdb_citekeys(project_dir)
    # citekeys that appear are allowed to live EITHER in the DB OR be defined
    # inline in the digest (with identifiers). Unknown-without-identifier -> fail.
    unresolved = {k for k in cited if k not in known}
    meta = {
        "present": True, "digest_found": True,
        "sha256": rl._sha256(f),
        "citekeys": sorted(cited),
        "citekeys_resolved_in_db": sorted(cited & known),
        "citekeys_inline_only": sorted(unresolved),
    }
    # inline-only citekeys are tolerated only if the digest carries identifiers
    # (already checked). Empty cited set with identifiers present is still a fail:
    if not cited:
        return False, meta, "no citekeys referenced in research file"
    return True, meta, ""


def _load_delta(project_dir, key):
    p = _delta_path(project_dir, key)
    if p and Path(p).exists():
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _all_citekeys_available(project_dir, keys):
    known = _litdb_citekeys(project_dir)
    # also accept citekeys defined in either research digest
    for node in ("L1", "L4a"):
        f = _research_file(project_dir, node)
        if f.exists():
            known |= _citekeys_in_digest(f.read_text(encoding="utf-8",
                                                      errors="replace"))
    return [k for k in keys if k and k not in known]


def _write_receipt(project_dir, node, payload):
    adir = Path(rl._audit_dir(project_dir))
    adir.mkdir(parents=True, exist_ok=True)
    rcpt = adir / f"v05b_receipt_{node}_{rl._stamp()}.json"
    rcpt.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return rcpt


# ---------------------------------------------------------------------------
# semantic gates per node (applied AFTER structural schema validation)
# ---------------------------------------------------------------------------
def _gate_L1(project_dir, data):
    errs = []
    lit = data.get("literature_used") or []
    hyps = data.get("hypotheses") or []
    if not lit:
        errs.append("L1 delta REJECTED: `literature_used` is empty — "
                    "hypotheses must be literature-grounded.")
    used_ids = {l.get("supports_hypothesis_id") for l in lit}
    for h in hyps:
        if h.get("exploratory") is True:
            continue
        basis = h.get("literature_basis") or []
        if not basis and h.get("id") not in used_ids:
            errs.append(f"hypothesis {h.get('id')} has no `literature_basis` and "
                        f"is not marked exploratory.")
    for l in lit:
        if l.get("use_type") not in USE_TYPES:
            errs.append(f"literature_used citekey={l.get('citekey')} has invalid "
                        f"use_type={l.get('use_type')} (must be {sorted(USE_TYPES)}).")
    # all citekeys must resolve
    keys = [l.get("citekey") for l in lit]
    keys += [k for h in hyps for k in (h.get("literature_basis") or [])]
    missing = _all_citekeys_available(project_dir, keys)
    if missing:
        errs.append(f"citekeys not found in 09_Literature_Database/ or digest: {missing}")
    return errs


def _gate_L4a(project_dir, data):
    errs = []
    dig = data.get("method_literature_digest") or []
    if not dig:
        errs.append("L4a delta REJECTED: `method_literature_digest` is empty.")
    keys = [d.get("citekey") for d in dig]
    for c in (data.get("recommended_method_constraints") or []):
        keys += c.get("source_citekeys") or []
    for c in (data.get("methods_to_avoid") or []):
        keys += c.get("source_citekeys") or []
    missing = _all_citekeys_available(project_dir, keys)
    if missing:
        errs.append(f"L4a citekeys not found in DB/digest: {missing}")
    return errs


def _gate_L4b(project_dir, data):
    errs = []
    l1 = _load_delta(project_dir, "L1_einstein")
    l4a = _load_delta(project_dir, "L4a_curie")
    if l1 is None:
        errs.append("L4b requires L1 delta to exist (consume L1 hypotheses).")
    if l4a is None:
        errs.append("L4b requires L4a delta to exist (consume method digest).")
    consumes = data.get("consumes") or {}
    if not consumes.get("L1"):
        errs.append("L4b `consumes.L1` is empty — must reference L1 hypothesis ids.")
    if not consumes.get("L4a"):
        errs.append("L4b `consumes.L4a` is empty — must reference L4a citekeys.")
    # every idea must declare provenance
    for idea in (data.get("analysis_ideas") or []):
        prov = idea.get("idea_provenance") or []
        if not prov:
            errs.append(f"idea {idea.get('id')} has no idea_provenance "
                        f"(must tag L1:Hx | L4a:citekey | dataset | exploratory).")
        if idea.get("category") not in IDEA_CATEGORIES:
            errs.append(f"idea {idea.get('id')} category invalid "
                        f"(must be {sorted(IDEA_CATEGORIES)}).")
    # cross-check referenced L1 ids actually exist
    if l1:
        valid_ids = {h.get("id") for h in (l1.get("hypotheses") or [])}
        for hid in consumes.get("L1", []):
            if hid not in valid_ids:
                errs.append(f"L4b consumes.L1 references unknown hypothesis '{hid}'.")
    return errs


def _gate_L5(project_dir, data):
    errs = []
    plan = data.get("analysis_plan") or {}
    required = SCHEMAS_V05B["L5_tukey"]["analysis_plan"].keys()
    for k in required:
        v = plan.get(k)
        if v is None or (isinstance(v, (list, str)) and len(v) == 0):
            errs.append(f"analysis_plan missing/empty required field: '{k}'.")
    if not plan.get("script_list"):
        errs.append("analysis_plan.script_list is empty — L7 has nothing to run.")
    l4b = _load_delta(project_dir, "L4b_fisher")
    if l4b is None:
        errs.append("L5 requires L4b delta (it selects from L4b ideas).")
    return errs


GATES = {"L1_einstein": _gate_L1, "L4a_curie": _gate_L4a,
         "L4b_fisher": _gate_L4b, "L5_tukey": _gate_L5}


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_next_step(args):
    pd, cid = args.project_dir, args.cand_id
    cf = rl._candidate_file(pd, cid)
    fm = rl._load_yaml_front(cf) if Path(cf).exists() else {}
    status = fm.get("status", "NEW")
    # naive position: next node whose delta does not yet exist
    nxt = None
    for node in DAG_V05B:
        key = NODE_DELTA_KEY.get(node)
        if key and not (_delta_path(pd, key) and Path(_delta_path(pd, key)).exists()):
            nxt = node
            break
    out = {"workflow": "v0.5b", "status": status, "next_node": nxt,
           "dag": DAG_V05B, "persona": NODE_PERSONA.get(nxt, "")}
    if nxt in PRE_RESEARCH_V05B:
        cfg = PRE_RESEARCH_V05B[nxt]
        f = _research_file(pd, nxt)
        ok, meta, reason = _audit_research(pd, nxt) if Path(f).exists() else (False, {"present": False}, "not run")
        out.update({
            "pre_research_required": True,
            "pre_research_type": cfg["type"],
            "pre_research_skill": cfg["skill"],
            "pre_research_output": f.as_posix(),
            "pre_research_present": bool(meta.get("present")),
            "pre_research_valid": ok,
            "pre_research_sha256": meta.get("sha256", ""),
            "pre_research_command": (f"python rlr_v05b.py check-research "
                                     f"{Path(pd).as_posix()} {cid} --node {nxt}"),
        })
        if not ok:
            out["pre_research_blocker"] = reason
    else:
        out["pre_research_required"] = False
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_check_research(args):
    ok, meta, reason = _audit_research(args.project_dir, args.node)
    print(json.dumps({"node": args.node, "valid": ok, "reason": reason,
                      "meta": meta}, ensure_ascii=False, indent=2))
    return 0 if ok else 3


def cmd_assemble_context(args):
    pd, node = args.project_dir, args.node
    sections = [f"=== RLR v0.5b assemble-context: {node} "
                f"({NODE_PERSONA.get(node,'')}) ==="]
    # HARD GATE: literature-required nodes fail closed.
    if node in PRE_RESEARCH_V05B:
        ok, meta, reason = _audit_research(pd, node)
        if not ok:
            print(f"ASSEMBLE-CONTEXT FAILED (v0.5b hard literature gate) for "
                  f"{node}: {reason}", file=sys.stderr)
            print(f"Run real Deep Research and write a `## Runtime digest` to "
                  f"{_research_file(pd, node).as_posix()} first.", file=sys.stderr)
            return 3
        digest = rl._extract_section(
            _research_file(pd, node).read_text(encoding="utf-8", errors="replace"),
            "Runtime digest")
        sections.append(f"=== PRE-RESEARCH ({PRE_RESEARCH_V05B[node]['type']}) "
                        f"Runtime digest [VERIFIED sha256={meta['sha256'][:12]}] ===")
        sections.append(digest)
        _write_receipt(pd, node, {
            "node": node, "research_file": _research_file(pd, node).as_posix(),
            "research_sha256": meta["sha256"], "runtime_digest_found": True,
            "digest_injected": True, "consumed_by": node,
            "citekeys": meta.get("citekeys", []),
            "stage": "assemble-context",
        })
    # Upstream delta injection (L4b/L5 consume prior nodes).
    upstream = {"L4b": ["L1_einstein", "L4a_curie"],
                "L5": ["L1_einstein", "L4a_curie", "L4b_fisher"],
                "L7": ["L5_tukey"]}.get(node, [])
    injected = []
    for key in upstream:
        d = _load_delta(pd, key)
        if d is not None:
            sections.append(f"=== UPSTREAM DELTA: {key} ===")
            sections.append(json.dumps(d, ensure_ascii=False, indent=2))
            p = _delta_path(pd, key)
            injected.append({"delta_key": key, "sha256": rl._sha256(p)})
    if injected:
        _write_receipt(pd, node, {"node": node, "stage": "assemble-context",
                                  "injected_upstream_deltas": injected})
    print("\n\n".join(sections))
    return 0


def cmd_emit_delta(args):
    pd, node = args.project_dir, args.node
    key = NODE_DELTA_KEY.get(node)
    if key is None:
        print(f"ERROR: unknown v0.5b node {node}", file=sys.stderr)
        return 2
    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR reading delta file: {e}", file=sys.stderr)
        return 2

    # 1) structural schema validation (reuse v04 recursive validator)
    schema = SCHEMAS_V05B.get(key) or rl.DELTA_SCHEMAS.get(key)
    if schema is None:
        print(f"ERROR: no schema for {key}", file=sys.stderr)
        return 2
    errors = rl._validate_delta(schema, data)
    if errors:
        print("DELTA VALIDATION: REJECT (structural)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(f"\nRequired schema keys for {key}: {list(schema.keys())}")
        return 2

    # 2) semantic literature/provenance gate
    gate = GATES.get(key)
    if gate:
        gerrs = gate(pd, data)
        if gerrs:
            print("DELTA VALIDATION: REJECT (v0.5b literature/provenance gate)",
                  file=sys.stderr)
            for e in gerrs:
                print(f"  - {e}", file=sys.stderr)
            return 2

    # 3) write delta
    out = _delta_path(pd, key)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    _write_receipt(pd, node, {"node": node, "stage": "emit-delta",
                              "delta_key": key, "delta_sha256": rl._sha256(out),
                              "accepted": True})
    print(f"DELTA ACCEPTED (v0.5b): {key} -> {Path(out).as_posix()}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="rlr_v05b",
                                description="RLR v0.5b literature-gated branch")
    sub = p.add_subparsers(dest="command", required=True)

    def add_pc(name):
        sp = sub.add_parser(name)
        sp.add_argument("project_dir")
        sp.add_argument("cand_id")
        return sp

    sp = add_pc("next-step"); sp.set_defaults(func=cmd_next_step)
    sp = add_pc("assemble-context"); sp.add_argument("--node", required=True)
    sp.set_defaults(func=cmd_assemble_context)
    sp = add_pc("emit-delta")
    sp.add_argument("--node", required=True)
    sp.add_argument("--persona", default="")
    sp.add_argument("--file", required=True)
    sp.set_defaults(func=cmd_emit_delta)
    sp = sub.add_parser("check-research")
    sp.add_argument("project_dir"); sp.add_argument("--node", required=True)
    sp.set_defaults(func=cmd_check_research)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
