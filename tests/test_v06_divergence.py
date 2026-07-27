"""v0.6 divergence-contract tests. See docs/superpowers/plans/2026-07-06-v06-divergence-contract.md.

All gates hard-fail only for `from_memory` candidates; legacy candidates must be unaffected.
"""
import json
import subprocess
import sys
import hashlib
import importlib.util
import os
import sqlite3
from pathlib import Path
from native_v2_helpers import (
    commit_finalized,
    seed_revise_continuation,
)
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.yamlio import _load_yaml_front

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


def _write_seed(proj, cand="C_prev", loop_type="divergent"):
    return seed_revise_continuation(proj, cand, loop_type=loop_type)


def _new_from_memory(proj, seed, loop_type="divergent"):
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C",
             "--input", "in", "--from-memory", str(seed), "--loop-type", loop_type)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[0]


def _seed_candidate_with_deltas(proj):
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q0",
             "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    seed_revise_continuation(proj, cand, write_memory=False)
    return cand


def _write_pre_research(proj, node, queries, ident="PMID: 111"):
    d = proj / "02_Agent_Notes" / "_pre_research"
    d.mkdir(parents=True, exist_ok=True)
    ql = "\n".join(f"- {q}" for q in queries)
    txt = (f"# {node} research\n\n## Runtime digest\nfindings {ident}\n\n"
           f"## Query log\n{ql}\n\n## Tool receipt\n- pubmed 2020 ok\n\n## Source count\n2\n")
    (d / f"{node}_research.md").write_text(txt, encoding="utf-8")


def _artifact(proj, cand, node, persona):
    key = f"{node}_{persona.lower()}"
    return proj / "02_Agent_Notes" / persona / f"{cand}_{key}_delta.v2.json"


def _receipts(proj, cand, node):
    return list((proj / "08_Audit" / "hypothesis_commits").glob(f"H*_{cand}_{node}.json"))


def _finalization_count(cand, node):
    with sqlite3.connect(os.environ["RLR_HYPOTHESIS_STORE"]) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM emissions e "
            "JOIN committed_emissions c ON c.delta_hash=e.delta_hash "
            "WHERE e.candidate_id=? AND e.node=?",
            (cand, node),
        ).fetchone()
    return int(row[0])


def _assert_finalized(proj, cand, node, persona):
    assert _artifact(proj, cand, node, persona).exists()
    assert _receipts(proj, cand, node)
    assert _finalization_count(cand, node) == 1


def _round_id(proj, cand):
    return str(_load_yaml_front(proj / "01_Candidates" / f"{cand}.md")["round_id"])


def _hypothesis_id(proj, cand):
    with sqlite3.connect(os.environ["RLR_HYPOTHESIS_STORE"]) as conn:
        primary = conn.execute(
            "SELECT e.hypothesis_id FROM events e JOIN emissions m "
            "ON m.commit_seq=e.commit_seq JOIN committed_emissions c "
            "ON c.delta_hash=m.delta_hash WHERE e.candidate_id=? "
            "AND e.round_id=? AND e.node='L1' AND "
            "json_extract(e.payload_json,'$.primary')=1 LIMIT 1",
            (cand, _round_id(proj, cand)),
        ).fetchone()
        if primary:
            return str(primary[0])
        rows = conn.execute(
            "SELECT hypothesis_id FROM occurrences "
            "WHERE candidate_id=? AND round_id=?",
            (cand, _round_id(proj, cand)),
        ).fetchall()
    assert len(rows) == 1
    return str(rows[0][0])


def _hypothesis_ids(proj, cand):
    with sqlite3.connect(os.environ["RLR_HYPOTHESIS_STORE"]) as conn:
        rows = conn.execute(
            "SELECT hypothesis_id FROM occurrences "
            "WHERE candidate_id=? AND round_id=? ORDER BY hypothesis_id",
            (cand, _round_id(proj, cand)),
        ).fetchall()
    return [str(row[0]) for row in rows]


def _schema_version(proj):
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    return "2.1" if ledger.project_profile(proj) == "v2.1" else "2.0"


def _seed_l4_prerequisites(proj, cand):
    hid = _hypothesis_id(proj, cand)
    schema_version = _schema_version(proj)
    if schema_version == "2.1":
        with sqlite3.connect(os.environ["RLR_HYPOTHESIS_STORE"]) as conn:
            version = conn.execute(
                "SELECT statement,operationalization,falsification_criteria_json "
                "FROM versions WHERE hypothesis_id=?", (hid,),
            ).fetchone()
        l1 = commit_finalized(proj, cand, "L1", "Einstein", {
            "schema_version": "2.1",
            "hypotheses": [
                {
                    "proposal_key": "p1",
                    "statement": version[0],
                    "operationalization": version[1],
                    "falsification_criteria": json.loads(version[2]),
                    "rationale": "continued hypothesis",
                },
                {
                    "proposal_key": "p2",
                    "statement": f"{version[0]} alternative A",
                    "operationalization": "measure alternative A",
                    "falsification_criteria": ["alternative A absent"],
                    "rationale": "fixture alternative",
                },
                {
                    "proposal_key": "p3",
                    "statement": f"{version[0]} alternative B",
                    "operationalization": "measure alternative B",
                    "falsification_criteria": ["alternative B absent"],
                    "rationale": "fixture alternative",
                },
            ],
            "primary_proposal_key": "p1",
            "key_uncertainty": "fixture",
        }, round_id=_round_id(proj, cand))
        ids = [
            item["hypothesis_id"] for item in l1.normalized_delta["hypotheses"]
        ]
    else:
        ids = [hid]
    if schema_version == "2.1":
        commit_finalized(proj, cand, "L2", "Feynman", {
            "schema_version": "2.1", "attacks": [{
                "hypothesis_id": hid, "severity": "high",
                "text": "no multiple-testing correction",
            }], "confounders": [],
            "diagnostic_tests": [], "verdicts": [{
                "hypothesis_id": hypothesis_id,
                "outcome": "SURVIVES" if hypothesis_id == hid else "REJECT",
                "reason": "fixture verdict",
            } for hypothesis_id in ids],
        }, round_id=_round_id(proj, cand))
    triage = []
    for hypothesis_id in ids:
        selected = hypothesis_id == hid
        item = {
            "hypothesis_id": hypothesis_id,
            "disposition": "SELECTED" if selected else "REJECTED",
            "reason_code": (
                "TESTABLE" if selected and schema_version == "2.1"
                else "LOW_IMPACT" if schema_version == "2.1" else "TEST"
            ),
            "reason": "testable" if selected else "fixture alternative",
        }
        if schema_version == "2.1":
            item["assessments"] = {
                criterion: {
                    "verdict": "PASS" if selected else "FAIL",
                    "evidence": "fixture",
                }
                for criterion in (
                    "testability", "novelty", "feasibility", "impact"
                )
            }
        triage.append(item)
    commit_finalized(proj, cand, "L3", "Oppenheimer", {
        "schema_version": schema_version,
        "triage": triage,
        "route_to": "Fisher",
    }, round_id=_round_id(proj, cand))
    return hid


def _emit_l4(proj, cand, scripts):
    hid = _seed_l4_prerequisites(proj, cand)
    obj = {
        "schema_version": _schema_version(proj),
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "name": "n",
            "steps": ["run analysis"], "scripts_needed": scripts,
        }],
        "scripts_needed": scripts,
    }
    f = proj / f"l4_{cand}.json"
    f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), cand, "--node", "L4", "--persona", "Fisher", "--file", str(f))


def _emit_l6(proj, cand, scripts):
    hid = _seed_l4_prerequisites(proj, cand)
    schema_version = _schema_version(proj)
    commit_finalized(proj, cand, "L4", "Fisher", {
        "schema_version": schema_version,
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "name": "method",
            "steps": ["run analysis"],
        }],
    }, round_id=_round_id(proj, cand))
    if schema_version == "2.1":
        commit_finalized(proj, cand, "L5", "Tukey", {
            "schema_version": "2.1",
            "attacks": [{"attack_id": "A1", "strategy_id": "S1", "hypothesis_ids": [hid],
                         "severity": "HIGH", "text": "fixture"}],
            "qc_checkpoints": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                "name": "QC", "criterion": "pass"}],
            "failure_stop_rules": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                    "name": "Stop", "condition": "failure", "reason": "fixture"}],
        }, round_id=_round_id(proj, cand))
    obj = {
        "schema_version": schema_version,
        "analysis_plan": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "scripts": scripts,
            "parameters": {}, "outputs": ["o.json"],
            **({
                "feasibility_assessment": {
                    "verdict": "PASS", "evidence": "fixture"
                },
                "attack_resolutions": [{"attack_id": "A1", "verdict": "RESOLVED",
                                        "evidence": "fixture"}],
            } if schema_version == "2.1" else {}),
        }],
        "method_decision": "APPROVE",
        "reason": "r",
    }
    f = proj / f"l6_{cand}.json"
    f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), cand, "--node", "L6", "--persona", "Oppenheimer", "--file", str(f))


def _emit_l6_ok(proj, cand):
    hid = _seed_l4_prerequisites(proj, cand)
    schema_version = _schema_version(proj)
    commit_finalized(proj, cand, "L4", "Fisher", {
        "schema_version": schema_version,
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "name": "method",
            "steps": ["run analysis"],
        }],
    }, round_id=_round_id(proj, cand))
    if schema_version == "2.1":
        commit_finalized(proj, cand, "L5", "Tukey", {
            "schema_version": "2.1",
            "attacks": [{"attack_id": "A1", "strategy_id": "S1", "hypothesis_ids": [hid],
                         "severity": "HIGH", "text": "fixture"}],
            "qc_checkpoints": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                "name": "QC", "criterion": "pass"}],
            "failure_stop_rules": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                    "name": "Stop", "condition": "failure", "reason": "fixture"}],
        }, round_id=_round_id(proj, cand))
    obj = {
        "schema_version": schema_version,
        "analysis_plan": [{
            "strategy_id": "S1", "hypothesis_ids": [hid],
            "scripts": [{"name": "bh.py", "purpose": "correction", "branch_id": "b1",
                         "data_modality": "stat", "grounding": {
                             "type": "internal_critique",
                             "critique_delta_ref": "L2_feynman#0",
                         }}],
            "parameters": {}, "outputs": ["o.json"],
            **({
                "feasibility_assessment": {
                    "verdict": "PASS", "evidence": "fixture"
                },
                "attack_resolutions": [{"attack_id": "A1", "verdict": "RESOLVED",
                                        "evidence": "fixture"}],
            } if schema_version == "2.1" else {}),
        }],
        "method_decision": "APPROVE",
        "reason": "ready",
    }
    f = proj / f"l6_{cand}.json"
    f.write_text(json.dumps(obj), encoding="utf-8")
    return _run("emit-delta", str(proj), cand, "--node", "L6",
                "--persona", "Oppenheimer", "--file", str(f))


def _emit_l10b(proj, cand, obj):
    hid = _seed_l4_prerequisites(proj, cand)
    obj = {
        "schema_version": _schema_version(proj),
        **obj,
        "hypothesis_decisions": [{
            "hypothesis_id": hid, "disposition": "ARCHIVE", "reason": "weak",
        }],
    }
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
    assert data["terminal_decision"] == "REVISE"
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
    seed = _write_seed(proj, loop_type="correction")
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
    assert r2.returncode != 0
    assert "full_text method_card" in (r2.stderr + r2.stdout)
    assert _finalization_count(cand, "L4") == 0


def test_l4_method_gate_allows_internally_motivated(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l4(proj, cand, [{"name": "bh_fdr.py", "purpose": "correction", "status": "internally_motivated"}])
    assert r2.returncode == 0, r2.stderr
    _assert_finalized(proj, cand, "L4", "Fisher")


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
    _assert_finalized(proj, cand, "L4", "Fisher")


# --- Task 7 -----------------------------------------------------------------

def test_l6_gate_fails_ungrounded_script(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l6(proj, cand, [{"name": "x.py", "purpose": "p", "branch_id": "b1",
                                "data_modality": "dm", "grounding": {}}])
    assert r2.returncode != 0
    assert "grounding.type" in (r2.stderr + r2.stdout)
    assert _finalization_count(cand, "L6") == 0


def test_l6_gate_accepts_internal_critique_with_ref(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l6_ok(proj, cand)
    assert r2.returncode == 0, r2.stderr
    _assert_finalized(proj, cand, "L6", "Oppenheimer")


# --- Task 8 -----------------------------------------------------------------

def test_l7_manifest_gate_requires_branch_and_l6_map(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    l6 = _emit_l6_ok(proj, cand)
    assert l6.returncode == 0, l6.stderr
    hid = _hypothesis_id(proj, cand)
    bad = {
        "schema_version": "2.0",
        "results": [{
            "result_key": "r1", "hypothesis_ids": [hid], "summary": "result",
            "artifact_refs": [{"path": "04_Analysis_Outputs/o.json",
                               "sha256": "a" * 64}],
        }],
        "scripts_run": [{"name": "bh.py", "exit_code": 0, "output_files": ["o.json"]}],
        "warnings": [], "failures": [],
    }
    f = proj / "l7bad.json"
    f.write_text(json.dumps(bad), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), cand, "--node", "L7", "--persona", "Turing", "--file", str(f))
    assert r2.returncode != 0
    assert "missing branch_id" in (r2.stderr + r2.stdout)
    assert _finalization_count(cand, "L7") == 0


def test_l7_manifest_written_on_valid(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    l6 = _emit_l6_ok(proj, cand)
    assert l6.returncode == 0, l6.stderr
    hid = _hypothesis_id(proj, cand)
    good = {
        "schema_version": _schema_version(proj),
        "results": [{
            "result_key": "r1", "hypothesis_ids": [hid], "summary": "result",
            "artifact_refs": [{"path": "04_Analysis_Outputs/o.json",
                               "sha256": "a" * 64}],
        }],
        "scripts_run": [{"name": "bh.py", "exit_code": 0, "output_files": ["o.json"],
            "branch_id": "b1", "method_card_ids": [], "grounded_by": "bh.py",
            "input_hashes": ["h1"], "output_hashes": ["h2"]}],
        "warnings": [], "failures": [],
    }
    f = proj / "l7ok.json"
    f.write_text(json.dumps(good), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), cand, "--node", "L7", "--persona", "Turing", "--file", str(f))
    assert r2.returncode == 0, r2.stderr
    _assert_finalized(proj, cand, "L7", "Turing")
    manifest = json.loads(
        (proj / "04_Analysis_Outputs" / "_exec_manifest" / f"{cand}_L7.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["candidate_id"] == cand
    assert manifest["scripts"] == [{
        "name": "bh.py", "branch_id": "b1", "method_card_ids": [],
        "grounded_by": "bh.py", "input_hashes": ["h1"],
        "output_hashes": ["h2"], "output_files": ["o.json"],
    }]


# --- Task 9 -----------------------------------------------------------------

def test_l10b_gate_requires_literature_changed_direction(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l10b(proj, cand, {"decision": "DOWNGRADE", "evidence_level": "weak",
        "reason": "r", "next_steps": [], "next_round_hypothesis": "H"})
    assert r2.returncode != 0
    assert "literature_changed_direction" in (r2.stderr + r2.stdout)
    assert _finalization_count(cand, "L10b") == 0


def test_l10b_gate_accepts_full_traceability(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    r2 = _emit_l10b(proj, cand, {"decision": "DOWNGRADE", "evidence_level": "weak", "reason": "r",
        "next_steps": [], "next_round_hypothesis": "H", "literature_changed_direction": False,
        "decision_grounding": {"paper_card_ids": [], "method_card_ids": [], "branch_ids": ["b1"]},
        "evidence_kept": [], "evidence_dropped": []})
    assert r2.returncode == 0, r2.stderr
    _assert_finalized(proj, cand, "L10b", "Oppenheimer")


# --- Task 10 ----------------------------------------------------------------

def test_branch_gate_noop_when_no_prior_branches(tmp_path):
    proj = _new_project(tmp_path)
    seed = _write_seed(proj)
    cand = _new_from_memory(proj, seed)
    rl = _rl_module()
    # A divergent continuation with no recorded unexplored branches has no
    # branch-status obligation; status entries added later remain harmless.
    ok, reason = rl._audit_branch_coverage(str(proj), cand)
    assert ok is True, reason
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

def test_legacy_delta_without_new_fields_is_blocked_after_cutover(tmp_path):
    proj = _new_project(tmp_path)
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q", "--claim", "C", "--input", "in")
    cand = r.stdout.strip().splitlines()[0]
    legacy = {"approved_strategy": "s1", "modifications": [], "reason": "r",
              "analysis_plan": {"scripts": ["s1.py", "s2.py"], "parameters": {},
                                "outputs": ["o.json"]},
              "candidate_id": cand}
    f = proj / f"legacy_l6_{cand}.json"
    f.write_text(json.dumps(legacy), encoding="utf-8")
    r2 = _run("emit-delta", str(proj), cand, "--node", "L6",
              "--persona", "Oppenheimer", "--file", str(f))
    assert r2.returncode != 0
    assert "only committed delta v2" in (r2.stderr + r2.stdout)
    # legacy (non-from_memory) candidate: memory gate must no-op even with no prior_loop_memory
    rl = _rl_module()
    l0 = {"skills_found": [], "skills_gaps": [], "input_verified": {}, "environment": {},
          "skill_use_plan": [], "forbidden_shortcuts": [], "candidate_id": cand}
    ok, _ = rl._audit_l0_memory(str(proj), cand, l0)
    assert ok is True
