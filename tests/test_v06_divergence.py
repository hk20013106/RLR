"""v0.6 divergence-contract tests. See docs/superpowers/plans/2026-07-06-v06-divergence-contract.md.

All gates hard-fail only for `from_memory` candidates; legacy candidates must be unaffected.
"""
import json
import subprocess
import sys
import hashlib
import importlib.util
from pathlib import Path

RL = str(Path(__file__).resolve().parent.parent / "research_loop_v04.py")


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, RL, *args], capture_output=True, text=True, cwd=cwd)


def _new_project(tmp_path):
    r = _run("new-project", str(tmp_path / "P"), "Test")
    assert r.returncode == 0, r.stderr
    return tmp_path / "P"


def _rl_module():
    rl_dir = str(Path(RL).resolve().parent)
    if rl_dir not in sys.path:
        sys.path.insert(0, rl_dir)
    spec = importlib.util.spec_from_file_location("rl_under_test", RL)
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    return rl


def _write_seed(proj, cand="C_prev"):
    d = proj / "08_Audit" / "loop_memory"
    d.mkdir(parents=True, exist_ok=True)
    seed = {
        "source_candidate_id": cand, "terminal_node": "L10c", "terminal_decision": "DOWNGRADE",
        "original_question": "Q0", "previous_hypothesis": "H_prev", "final_reason": "R",
        "next_round_hypothesis": "H_next", "required_new_search_directions": ["dir_a", "dir_b"],
        "evidence_kept": [], "evidence_dropped": [], "explored_branches": ["b1"],
        "unexplored_branches": [{"id": "b_atrial", "why": "deferred", "data_available": True,
                                 "data_path": "x/atrial.csv"}],
        "data_modalities_used": ["transcriptomic_DEG"], "data_modalities_available_unused": ["atrial_DEG"],
        "paper_card_ids": [], "method_card_ids": [], "hashes": {},
    }
    p = d / f"{cand}_next_loop_memory.json"
    p.write_text(json.dumps(seed), encoding="utf-8")
    return p


def _new_from_memory(proj, seed, loop_type="divergent"):
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", loop_type)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[0]


def _seed_candidate_with_deltas(proj):
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q0",
             "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    notes = proj / "02_Agent_Notes"

    def drop(persona, key, obj):
        d = notes / persona
        d.mkdir(parents=True, exist_ok=True)
        obj = {**obj, "candidate_id": cand}
        (d / f"{cand}_{key}_delta.json").write_text(json.dumps(obj), encoding="utf-8")

    drop("Einstein", "L1_einstein", {"hypotheses": [{"id": "H1", "text": "h", "testable": True, "rationale": "r"}],
         "key_uncertainty": "u", "primary_hypothesis": "H1",
         "candidate_branches": [{"id": "b1", "description": "d"}]})
    drop("Oppenheimer", "L10b_oppenheimer", {"decision": "DOWNGRADE", "evidence_level": "weak",
         "reason": "because", "next_steps": [], "next_round_hypothesis": "H_next"})
    return cand


def _write_pre_research(proj, node, queries, ident="PMID: 111"):
    d = proj / "02_Agent_Notes" / "_pre_research"
    d.mkdir(parents=True, exist_ok=True)
    ql = "\n".join(f"- {q}" for q in queries)
    txt = (f"# {node} research\n\n## Runtime digest\nfindings {ident}\n\n"
           f"## Query log\n{ql}\n\n## Tool receipt\n- pubmed 2020 ok\n\n## Source count\n2\n")
    (d / f"{node}_research.md").write_text(txt, encoding="utf-8")


def _emit_l4(proj, cand, scripts):
    d = proj / "02_Agent_Notes" / "Fisher"
    d.mkdir(parents=True, exist_ok=True)
    obj = {"strategies": [{"id": "s1", "name": "n", "steps": [], "samples": 3, "status": "ok"}],
           "recommended": "s1", "scripts_needed": scripts, "key_decisions": [], "candidate_id": cand}
    f = proj / f"l4_{cand}.json"
    f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), cand, "--node", "L4", "--persona", "Fisher", "--file", str(f))


def _emit_l6(proj, cand, scripts):
    d = proj / "02_Agent_Notes" / "Oppenheimer"
    d.mkdir(parents=True, exist_ok=True)
    obj = {"approved_strategy": "s1", "modifications": [], "reason": "r",
           "analysis_plan": {"scripts": scripts, "parameters": {}, "outputs": ["o.json"]},
           "candidate_id": cand}
    f = proj / f"l6_{cand}.json"
    f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), cand, "--node", "L6", "--persona", "Oppenheimer", "--file", str(f))


def _emit_l6_ok(proj, cand):
    d = proj / "02_Agent_Notes" / "Feynman"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cand}_L2_feynman_delta.json").write_text(json.dumps({"attacks": [{"hypothesis_id": "H1",
        "severity": "high", "text": "no multiple-testing correction"}], "confounders": [],
        "diagnostic_tests": [], "verdict": "v", "candidate_id": cand}), encoding="utf-8")
    return _emit_l6(proj, cand, [{"name": "bh.py", "purpose": "correction", "branch_id": "b1",
        "data_modality": "stat", "grounding": {"type": "internal_critique",
        "critique_delta_ref": "L2_feynman#0"}}])


def _emit_l10b(proj, cand, obj):
    d = proj / "02_Agent_Notes" / "Oppenheimer"
    d.mkdir(parents=True, exist_ok=True)
    obj = {**obj, "candidate_id": cand}
    f = proj / f"l10b_{cand}.json"
    f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), cand, "--node", "L10b", "--persona", "Oppenheimer", "--file", str(f))


# --- Task 1 -----------------------------------------------------------------

def test_new_candidate_from_memory_records_hash_and_loop_type(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand_id = _new_from_memory(proj, seed)
    cf = next(proj.rglob(f"{cand_id}.md"))
    txt = cf.read_text(encoding="utf-8")
    assert "from_memory: true" in txt
    assert "loop_type: divergent" in txt
    assert "prior_candidate: C_prev" in txt
    assert hashlib.sha256(seed.read_bytes()).hexdigest() in txt


def test_new_candidate_from_memory_rejects_missing_seed(tmp_path):
    proj = _new_project(tmp_path)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(proj / "nope.json"),
             "--loop-type", "divergent")
    assert r.returncode != 0
    assert "seed" in (r.stderr + r.stdout).lower()


def test_new_candidate_from_memory_requires_loop_type(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed))
    assert r.returncode != 0


# --- Task 2 -----------------------------------------------------------------

def test_emit_loop_memory_deterministic_and_schema(tmp_path):
    proj = _new_project(tmp_path)
    cand = _seed_candidate_with_deltas(proj)
    r1 = _run("emit-loop-memory", str(proj), cand)
    assert r1.returncode == 0, r1.stderr
    seed = proj / "08_Audit" / "loop_memory" / f"{cand}_next_loop_memory.json"
    md = proj / "08_Audit" / "loop_memory" / f"{cand}_next_loop_memory.md"
    assert seed.exists() and md.exists()
    data = json.loads(seed.read_text(encoding="utf-8"))
    assert data["source_candidate_id"] == cand
    assert data["next_round_hypothesis"] == "H_next"
    assert data["terminal_decision"] == "DOWNGRADE"
    assert data["original_question"] == "Q0"
    for k in ("required_new_search_directions", "unexplored_branches",
              "data_modalities_used", "paper_card_ids", "hashes"):
        assert k in data
    first = seed.read_text(encoding="utf-8")
    _run("emit-loop-memory", str(proj), cand)
    assert seed.read_text(encoding="utf-8") == first


# --- Task 3 -----------------------------------------------------------------

# L0 emit-delta CLI is environment-gated (OBSIDIAN_VAULT/Zotero/academic-suite),
# so the memory gate is tested directly on the gate function.

def test_l0_memory_gate_rejects_missing_prior_memory(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    delta = {"skills_found": [], "skills_gaps": [], "input_verified": {}, "environment": {},
             "skill_use_plan": [], "forbidden_shortcuts": [], "candidate_id": cand}
    ok, reason = _rl_module()._audit_l0_memory(str(proj), cand, delta)
    assert ok is False
    assert "prior_loop_memory" in reason


def test_l0_memory_gate_accepts_matching_hash(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    h = hashlib.sha256(seed.read_bytes()).hexdigest()
    delta = {"skills_found": [], "skills_gaps": [], "input_verified": {}, "environment": {},
             "skill_use_plan": [], "forbidden_shortcuts": [],
             "prior_loop_memory": {"source_candidate_id": "C_prev", "loaded_from": str(seed),
                 "memory_hash": h, "previous_hypothesis": "H_prev", "final_decision": "DOWNGRADE",
                 "next_round_hypothesis": "H_next", "required_new_search_directions": ["dir_a", "dir_b"],
                 "evidence_kept": [], "evidence_dropped": [], "unexplored_branches": [],
                 "data_modalities_available_unused": []},
             "candidate_id": cand}
    ok, reason = _rl_module()._audit_l0_memory(str(proj), cand, delta)
    assert ok is True, reason


def test_l0_memory_gate_rejects_hash_mismatch(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    delta = {"prior_loop_memory": {"memory_hash": "deadbeef", "previous_hypothesis": "x",
             "next_round_hypothesis": "y", "required_new_search_directions": ["z"]},
             "candidate_id": cand}
    ok, reason = _rl_module()._audit_l0_memory(str(proj), cand, delta)
    assert ok is False and "mismatch" in reason


# --- Task 4 -----------------------------------------------------------------

def _aca():
    rl_dir = str(Path(RL).resolve().parent)
    if rl_dir not in sys.path:
        sys.path.insert(0, rl_dir)
    import ars_card_adapter as aca
    return aca


def test_paper_card_round_trip_no_abstract_in_card(tmp_path):
    proj = _new_project(tmp_path)
    aca = _aca()
    cid = aca.write_paper_card(proj, {"pmid": "12345678", "doi": "10.1/x", "url": "http://x",
        "title": "Paper A", "year": 2020, "journal": "J", "one_line": "relevant",
        "claims_used": ["c1"], "query_family_id": "qf1"})
    p = proj / "09_Literature_Database" / "paper_cards" / f"{cid}.json"
    assert p.exists()
    card = json.loads(p.read_text(encoding="utf-8"))
    assert card["pmid"] == "12345678"
    assert "abstract" not in card
    assert card["one_line"] == "relevant"


def test_ars_output_to_cards_strips_prose(tmp_path):
    proj = _new_project(tmp_path)
    aca = _aca()
    payload = {"papers": [{"pmid": "999", "doi": "10.9/y", "title": "P", "year": 2019,
                "journal": "J2", "url": "u", "apa": "Long APA prose ...", "relevance": "one line"}],
               "methods": [{"source_pmid": "999", "method_name": "AFM", "measurement_type": "mechanical",
                "data_modality": "tissue_mechanics", "key_parameters": {"probe": "x"},
                "applicability": "direct", "extracted_from": "full_text", "full_text_fetched": True}]}
    out = aca.ars_output_to_cards(proj, payload)
    assert len(out["paper_cards"]) == 1 and len(out["method_cards"]) == 1
    mc_id = out["method_cards"][0]
    mc = json.loads((proj / "09_Literature_Database" / "method_cards" / f"{mc_id}.json").read_text(encoding="utf-8"))
    assert mc["extracted_from"] == "full_text" and "apa" not in mc


# --- Task 5 -----------------------------------------------------------------

def _divergence(proj, node, cand):
    return _rl_module()._audit_divergence(str(proj), node, cand)


def test_divergence_gate_fails_on_reused_families_divergent(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cache = proj / "09_Literature_Database" / "query_families.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"families": ["col6a1 collagen", "collagen enhancer vi"]}), encoding="utf-8")
    cand = _new_from_memory(proj, seed)
    _write_pre_research(proj, "L1", ["COL6A1 collagen", "collagen VI enhancer"])
    ok, reason = _divergence(proj, "L1", cand)
    assert ok is False and "new query" in reason.lower()


def test_divergence_gate_passes_with_two_new_families(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cache = proj / "09_Literature_Database" / "query_families.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"families": ["col6a1 collagen"]}), encoding="utf-8")
    cand = _new_from_memory(proj, seed)
    _write_pre_research(proj, "L1", ["cardiac tissue stiffness AFM", "myocardial passive compliance measurement"])
    ok, reason = _divergence(proj, "L1", cand)
    assert ok is True, reason


def test_divergence_gate_bypassed_for_correction_loop(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed, loop_type="correction")
    _write_pre_research(proj, "L1", ["COL6A1 collagen"])
    ok, reason = _divergence(proj, "L1", cand)
    assert ok is True, reason


# --- Task 6 -----------------------------------------------------------------

def test_l4_method_gate_fails_without_fulltext_method_card(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l4(proj, cand, [{"name": "afm.py", "purpose": "measure stiffness", "status": "planned",
                                "grounded_in_method_card_ids": ["nonexistent"]}])
    assert r2.returncode != 0 and "method_card" in (r2.stderr + r2.stdout)


def test_l4_method_gate_allows_internally_motivated(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l4(proj, cand, [{"name": "bh_fdr.py", "purpose": "correction", "status": "internally_motivated"}])
    assert r2.returncode == 0, r2.stderr


def test_l4_method_gate_accepts_real_fulltext_card(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    aca = _aca()
    mc = aca.write_method_card(proj, {"source_paper_card_id": "p1", "method_name": "AFM",
        "measurement_type": "mechanical", "data_modality": "tissue", "key_parameters": {},
        "applicability": "direct", "extracted_from": "full_text", "full_text_fetched": True})
    r2 = _emit_l4(proj, cand, [{"name": "afm.py", "purpose": "stiffness", "status": "planned",
                                "grounded_in_method_card_ids": [mc]}])
    assert r2.returncode == 0, r2.stderr


# --- Task 7 -----------------------------------------------------------------

def test_l6_gate_fails_ungrounded_script(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l6(proj, cand, [{"name": "x.py", "purpose": "p", "branch_id": "b1",
                                "data_modality": "dm", "grounding": {}}])
    assert r2.returncode != 0 and "grounding" in (r2.stderr + r2.stdout)


def test_l6_gate_accepts_internal_critique_with_ref(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l6_ok(proj, cand)
    assert r2.returncode == 0, r2.stderr


# --- Task 8 -----------------------------------------------------------------

def test_l7_manifest_gate_requires_branch_and_l6_map(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    _emit_l6_ok(proj, cand)
    d = proj / "02_Agent_Notes" / "Turing"
    d.mkdir(parents=True, exist_ok=True)
    bad = {"scripts_run": [{"name": "bh.py", "exit_code": 0, "output_files": ["o.json"]}],
           "key_results": {}, "warnings": [], "failures": [], "candidate_id": cand}
    f = proj / "l7bad.json"
    f.write_text(json.dumps(bad), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), cand, "--node", "L7", "--persona", "Turing", "--file", str(f))
    assert r2.returncode != 0 and "branch" in (r2.stderr + r2.stdout).lower()


def test_l7_manifest_written_on_valid(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    _emit_l6_ok(proj, cand)
    d = proj / "02_Agent_Notes" / "Turing"
    d.mkdir(parents=True, exist_ok=True)
    good = {"scripts_run": [{"name": "bh.py", "exit_code": 0, "output_files": ["o.json"],
            "branch_id": "b1", "method_card_ids": [], "grounded_by": "bh.py",
            "input_hashes": ["h1"], "output_hashes": ["h2"]}],
            "key_results": {}, "warnings": [], "failures": [], "candidate_id": cand}
    f = proj / "l7ok.json"
    f.write_text(json.dumps(good), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), cand, "--node", "L7", "--persona", "Turing", "--file", str(f))
    assert r2.returncode == 0, r2.stderr
    man = proj / "04_Analysis_Outputs" / "_exec_manifest" / f"{cand}_L7.json"
    assert man.exists()
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["scripts"][0]["branch_id"] == "b1"


# --- Task 9 -----------------------------------------------------------------

def test_l10b_gate_requires_literature_changed_direction(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l10b(proj, cand, {"decision": "DOWNGRADE", "evidence_level": "weak",
        "reason": "r", "next_steps": [], "next_round_hypothesis": "H"})
    assert r2.returncode != 0 and "literature_changed_direction" in (r2.stderr + r2.stdout)


def test_l10b_gate_accepts_full_traceability(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l10b(proj, cand, {"decision": "DOWNGRADE", "evidence_level": "weak", "reason": "r",
        "next_steps": [], "next_round_hypothesis": "H", "literature_changed_direction": False,
        "decision_grounding": {"paper_card_ids": [], "method_card_ids": [], "branch_ids": ["b1"]},
        "evidence_kept": [], "evidence_dropped": []})
    assert r2.returncode == 0, r2.stderr


# --- Task 10 ----------------------------------------------------------------

def test_branch_gate_requires_prior_unexplored_statused(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    rl = _rl_module()
    ok, reason = rl._audit_branch_coverage(str(proj), cand)
    assert ok is False and "b_atrial" in reason
    _run("branch-status", str(proj), cand, "--branch", "b_atrial", "--status", "ignored",
         "--why", "still no protein data")
    ok2, _ = rl._audit_branch_coverage(str(proj), cand)
    assert ok2 is True


def test_modality_scan_detects_unused(tmp_path):
    proj = _new_project(tmp_path)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _run("modality-scan", str(proj), cand, "--used", "transcriptomic_DEG",
              "--available", "transcriptomic_DEG", "--available", "atrial_DEG")
    assert r2.returncode == 0
    ml = json.loads((proj / "08_Audit" / "modality_ledger" / f"{cand}.json").read_text(encoding="utf-8"))
    assert "atrial_DEG" in ml["available_unused"]


# --- Task 11 ----------------------------------------------------------------

def test_aggregate_report_no_silent_clobber(tmp_path):
    proj = _new_project(tmp_path)
    c1 = _seed_candidate_with_deltas(proj)
    assert _run("aggregate-report", str(proj), c1).returncode == 0
    c2 = _seed_candidate_with_deltas(proj)
    assert _run("aggregate-report", str(proj), c2).returncode == 0
    r1 = (proj / f"FINAL_REPORT_{c1}.md").read_text(encoding="utf-8")
    r2 = (proj / f"FINAL_REPORT_{c2}.md").read_text(encoding="utf-8")
    assert c1 in r1 and c2 in r2
    shared = (proj / "FINAL_REPORT.md").read_text(encoding="utf-8")
    assert c2 in shared
    idx = (proj / "00_Reports_Index.md").read_text(encoding="utf-8")
    assert c1 in idx and c2 in idx


# --- Task 12 ----------------------------------------------------------------

def test_legacy_delta_without_new_fields_still_validates(tmp_path):
    proj = _new_project(tmp_path)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    r2 = _emit_l6(proj, cand, ["s1.py", "s2.py"])
    assert r2.returncode == 0, r2.stderr
    # legacy (non-from_memory) candidate: memory gate must no-op even with no prior_loop_memory
    rl = _rl_module()
    l0 = {"skills_found": [], "skills_gaps": [], "input_verified": {}, "environment": {},
          "skill_use_plan": [], "forbidden_shortcuts": [], "candidate_id": cand}
    ok, _ = rl._audit_l0_memory(str(proj), cand, l0)
    assert ok is True
