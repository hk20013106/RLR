#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Minimal tests for the RLR v0.5b literature-gated branch.

Run:  python test_rlr_v05b.py
Each test sets up a throwaway fixture project in a temp dir and exercises the
real CLI via rlr_v05b.main(argv). Asserts exit codes / side effects only.
"""
import json
import sys
import tempfile
from pathlib import Path

import rlr_v05b as v
import research_loop_v04 as rl

PASS, FAIL = [], []


def _check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def _mkproj():
    d = Path(tempfile.mkdtemp(prefix="v05b_"))
    (d / "02_Agent_Notes" / "_pre_research").mkdir(parents=True, exist_ok=True)
    (d / "09_Literature_Database").mkdir(parents=True, exist_ok=True)
    (d / "01_Candidates").mkdir(parents=True, exist_ok=True)
    (d / "08_Audit").mkdir(parents=True, exist_ok=True)
    return d


GOOD_DIGEST = """# L1 Pre-Research

## Runtime digest
- citekey: smith2024_cardiac
  doi: 10.1016/j.cell.2024.01.001
  pmid: 38123456
  url: https://pubmed.ncbi.nlm.nih.gov/38123456/
  title: Convergent cardiac enhancer remodeling
  year: 2024
  core finding: high-HR species share enhancer activation at MYC targets
  relevance: directly motivates H1 enhancer-gain hypothesis
  downstream implication: test RNA_up vs enhancer_gain concordance
  caveat: species-level, not chamber-specific
  limitation: no Hi-C contact data

See [[09_Literature_Database/smith2024_cardiac|Convergent cardiac enhancer remodeling]].
"""


def _write_research(d, node_out, text):
    (d / "02_Agent_Notes" / "_pre_research" / node_out).write_text(
        text, encoding="utf-8")


def _emit(d, node, payload):
    f = d / "_tmp_delta.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return v.main(["emit-delta", str(d), "C001", "--node", node,
                   "--persona", "X", "--file", str(f)])


# --- Test 1: next-step L1 reports pre_research_required: true ----------------
def test1():
    d = _mkproj()
    # seed an L0 delta so next_node advances to L1
    l0 = v._delta_path(d, "L0_linnaeus")
    Path(l0).parent.mkdir(parents=True, exist_ok=True)
    Path(l0).write_text("{}", encoding="utf-8")
    # capture stdout
    import io
    buf = io.StringIO(); old = sys.stdout; sys.stdout = buf
    try:
        v.main(["next-step", str(d), "C001"])
    finally:
        sys.stdout = old
    out = json.loads(buf.getvalue())
    _check("1 next-step L1 pre_research_required=true",
           out.get("next_node") == "L1" and out.get("pre_research_required") is True
           and out.get("pre_research_skill") == "academic-research-suite")


# --- Test 2: assemble-context L1 FAILS when research missing -----------------
def test2():
    d = _mkproj()
    rc = v.main(["assemble-context", str(d), "C001", "--node", "L1"])
    _check("2 assemble-context L1 fails (rc=3) when L1_research.md missing", rc == 3)


# --- Test 3: assemble-context L1 SUCCEEDS with valid Runtime digest ----------
def test3():
    d = _mkproj()
    (d / "09_Literature_Database" / "smith2024_cardiac.md").write_text(
        "stub", encoding="utf-8")
    _write_research(d, "L1_research.md", GOOD_DIGEST)
    rc = v.main(["assemble-context", str(d), "C001", "--node", "L1"])
    _check("3 assemble-context L1 succeeds (rc=0) with Runtime digest", rc == 0)


# --- Test 4: L1 emit-delta REJECTS hypothesis delta without literature_used --
def test4():
    d = _mkproj()
    hyp = {"id": "H1", "text": "t", "testable": True, "rationale": "r",
           "data_basis": "db", "literature_basis": [], "expected_signal": "s",
           "falsification_condition": "f"}
    rc = _emit(d, "L1", {"hypotheses": [hyp], "literature_used": [],
                         "primary_hypothesis": "H1", "key_uncertainty": "u"})
    _check("4 L1 emit-delta rejects empty literature_used (rc=2)", rc == 2)


# --- Test 5: L4a assemble-context FAILS when research missing ----------------
def test5():
    d = _mkproj()
    rc = v.main(["assemble-context", str(d), "C001", "--node", "L4a"])
    _check("5 assemble-context L4a fails (rc=3) when L4a_research.md missing", rc == 3)


# --- Test 6: L4a emit-delta REJECTS without method_literature_digest ---------
def test6():
    d = _mkproj()
    rc = _emit(d, "L4a", {"method_literature_digest": [],
                          "recommended_method_constraints": [],
                          "methods_to_avoid": []})
    _check("6 L4a emit-delta rejects empty method_literature_digest (rc=2)", rc == 2)


# --- Test 7: L4b REJECTS when it does not consume both L1 and L4a ------------
def test7():
    d = _mkproj()
    idea = {"id": "A1", "name": "concordance", "category": "direct",
            "suitable": True, "rationale": "r", "idea_provenance": ["L1:H1"]}
    rc = _emit(d, "L4b", {"analysis_ideas": [idea],
                          "consumes": {"L1": [], "L4a": []}, "summary": "s"})
    _check("7 L4b rejects when L1/L4a not consumed (rc=2)", rc == 2)


# --- Test 8: L5 REJECTS plans without complete analysis_plan -----------------
def test8():
    d = _mkproj()
    rc = _emit(d, "L5", {"analysis_plan": {"selected_analyses": ["x"]},
                         "reason": "r"})  # missing most required fields
    _check("8 L5 rejects incomplete analysis_plan (rc=2)", rc == 2)


# --- Test 9: v0.4.5 still importable & schemas unchanged ---------------------
def test9():
    ok = (hasattr(rl, "DELTA_SCHEMAS")
          and "L1_einstein" in rl.DELTA_SCHEMAS
          and "literature_used" not in rl.DELTA_SCHEMAS["L1_einstein"]  # v04 unchanged
          and "L2_feynman" in rl.DELTA_SCHEMAS)  # v04 still has L2/L3
    _check("9 v0.4.5 reference intact (L1 schema unchanged, L2 present)", ok)


# --- bonus: full happy-path L4b acceptance when L1+L4a deltas exist ----------
def test10():
    d = _mkproj()
    (d / "09_Literature_Database" / "smith2024_cardiac.md").write_text("s", encoding="utf-8")
    # seed valid L1 + L4a deltas
    hyp = {"id": "H1", "text": "t", "testable": True, "rationale": "r",
           "data_basis": "db", "literature_basis": ["smith2024_cardiac"],
           "expected_signal": "s", "falsification_condition": "f"}
    _emit(d, "L1", {"hypotheses": [hyp],
                    "literature_used": [{"citekey": "smith2024_cardiac",
                                         "doi_or_url": "10.x", "finding_used": "x",
                                         "supports_hypothesis_id": "H1",
                                         "use_type": "mechanism"}],
                    "primary_hypothesis": "H1", "key_uncertainty": "u"})
    _emit(d, "L4a", {"method_literature_digest": [
        {"citekey": "smith2024_cardiac", "doi_or_url": "10.x",
         "method_or_principle": "logistic", "assumption": "a", "pitfall": "p",
         "relevance_to_current_data": "r"}],
        "recommended_method_constraints": [], "methods_to_avoid": []})
    idea = {"id": "A1", "name": "concordance", "category": "direct",
            "suitable": True, "rationale": "r",
            "idea_provenance": ["L1:H1", "L4a:smith2024_cardiac"]}
    rc = _emit(d, "L4b", {"analysis_ideas": [idea],
                          "consumes": {"L1": ["H1"], "L4a": ["smith2024_cardiac"]},
                          "summary": "s"})
    _check("10 L4b accepted (rc=0) when L1+L4a consumed correctly", rc == 0)


if __name__ == "__main__":
    for t in [test1, test2, test3, test4, test5, test6, test7, test8, test9, test10]:
        try:
            t()
        except Exception as e:
            _check(f"{t.__name__} raised {type(e).__name__}: {e}", False)
    print(f"\n=== {len(PASS)} passed, {len(FAIL)} failed ===")
    sys.exit(1 if FAIL else 0)
