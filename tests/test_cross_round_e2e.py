"""Phase 7 cross-round integration: real loop-memory continuity across rounds.

Plan §4 Phase 7 names one integration gap that no existing test covers:

    emit-loop-memory  ->  new-candidate --from-memory  ->  L0 gate  ->  L1 divergence

`test_v06_divergence.py` exercises each gate in ISOLATION, seeding the
from_memory candidate from a hand-written `_write_seed(...)` dict. That proves
the gates' logic but NOT that round N's terminal artifact is exactly what round
N+1 consumes. This module closes that gap: it drives a real terminal candidate
through `emit-loop-memory`, feeds the PRODUCED seed into `new-candidate
--from-memory`, and then asserts the seed threads all the way into the L0
memory-hash gate and the L1 divergence gate ON THE SAME CANDIDATE.

Two of the assertions additionally go through the real CLI (`assemble-context`)
rather than calling `_audit_*` directly, so they also guard gate WIRING (that
context.py actually invokes the divergence gate and maps its failure to rc=3) --
which the direct-audit tests in test_v06_divergence do not.
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from deep_research_fixtures import persist_synthetic_evidence
from native_v2_helpers import write_catalog_emission_receipts
from research_loop import deep_research

RL = str(Path(__file__).resolve().parent.parent / "research_loop_v04.py")


def _run(*args):
    return subprocess.run([sys.executable, RL, *args], capture_output=True, text=True)


def _rl_module():
    """Import the engine surface via the compat shim for direct-audit calls
    (same idiom as test_v06_divergence -- env-independent gate checks)."""
    rl_dir = str(Path(RL).resolve().parent)
    if rl_dir not in sys.path:
        sys.path.insert(0, rl_dir)
    spec = importlib.util.spec_from_file_location("rl_cross_round", RL)
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    return rl


def _new_project(tmp_path):
    r = _run("new-project", str(tmp_path / "P"), "Test")
    assert r.returncode == 0, r.stderr
    return tmp_path / "P"


def _seed_terminal_candidate(proj, loop_type="divergent"):
    """Round N: a candidate carrying the L1 + L10b deltas that _build_loop_memory
    reads, with a NON-EMPTY next_steps so the produced seed satisfies the L0
    gate's `required_new_search_directions` requirement."""
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q0",
             "--claim", "C", "--input", "in")
    assert r.returncode == 0, r.stderr
    cand = r.stdout.strip().splitlines()[0]
    source_dir = proj / "08_Audit" / "test_sources"
    source_dir.mkdir(parents=True, exist_ok=True)

    def emit(node, persona, obj):
        source = source_dir / f"{cand}_{node}.json"
        source.write_text(json.dumps({"schema_version": "2.1", **obj}), encoding="utf-8")
        manifest, receipt = write_catalog_emission_receipts(proj, cand, node, persona, source)
        result = _run("emit-delta", str(proj), cand, "--node", node,
                      "--persona", persona, "--file", str(source),
                      "--context-manifest", str(manifest),
                      "--provider-receipt", str(receipt))
        assert result.returncode == 0, result.stderr

    emit("L1", "Einstein", {
        "hypotheses": [
            {"proposal_key": "H1", "statement": "h",
             "operationalization": "measure h",
             "falsification_criteria": ["h absent"], "rationale": "r"},
            {"proposal_key": "H2", "statement": "alternative h 1",
             "operationalization": "measure alternative 1",
             "falsification_criteria": ["alternative 1 absent"], "rationale": "r"},
            {"proposal_key": "H3", "statement": "alternative h 2",
             "operationalization": "measure alternative 2",
             "falsification_criteria": ["alternative 2 absent"], "rationale": "r"},
        ],
        "primary_proposal_key": "H1", "key_uncertainty": "u",
        "candidate_branches": [{"id": "b1", "description": "d"}],
    })
    l1_path = next((proj / "02_Agent_Notes" / "Einstein").glob(f"{cand}_*_delta.v2.json"))
    l1 = json.loads(l1_path.read_text(encoding="utf-8"))
    hid = l1["primary_hypothesis_id"]
    emit("L2", "Feynman", {
        "attacks": [], "confounders": [], "diagnostic_tests": [],
        "verdicts": [{
            "hypothesis_id": item["hypothesis_id"],
            "outcome": "SURVIVES" if item["hypothesis_id"] == hid else "REJECT",
            "reason": "r",
        } for item in l1["hypotheses"]],
    })
    emit("L3", "Oppenheimer", {
        "triage": [{
            "hypothesis_id": item["hypothesis_id"],
            "disposition": (
                "SELECTED" if item["hypothesis_id"] == hid else "REJECTED"
            ),
            "reason_code": (
                "TESTABLE" if item["hypothesis_id"] == hid else "LOW_IMPACT"
            ),
            "reason": "r",
            "assessments": {
                criterion: {
                    "verdict": (
                        "PASS" if item["hypothesis_id"] == hid else "FAIL"
                    ),
                    "evidence": "fixture",
                }
                for criterion in (
                    "testability", "novelty", "feasibility", "impact"
                )
            },
        } for item in l1["hypotheses"]],
        "route_to": "Fisher",
    })
    emit("L4", "Fisher", {"strategies": [{"strategy_id": "S1",
         "hypothesis_ids": [hid], "name": "m", "steps": ["measure"]}]})
    emit("L5", "Tukey", {
         "attacks": [{"attack_id": "A1", "strategy_id": "S1", "hypothesis_ids": [hid],
                      "severity": "HIGH", "text": "attack"}],
         "qc_checkpoints": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                             "name": "QC", "criterion": "pass"}],
         "failure_stop_rules": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                 "name": "Stop", "condition": "failure", "reason": "r"}],
    })
    emit("L6", "Oppenheimer", {"analysis_plan": [{"strategy_id": "S1",
         "hypothesis_ids": [hid], "scripts": [], "parameters": {}, "outputs": [],
         "feasibility_assessment": {"verdict": "PASS", "evidence": "fixture"},
         "attack_resolutions": [{"attack_id": "A1", "verdict": "RESOLVED", "evidence": "fixture"}]}],
         "method_decision": "APPROVE", "reason": "r"})
    emit("L7", "Turing", {"results": [{"result_key": "R1",
         "hypothesis_ids": [hid], "summary": "result", "artifact_refs": [{
             "path": "04_Analysis_Outputs/result.json", "sha256": "a" * 64}]}],
         "scripts_run": [], "warnings": [], "failures": []})
    l7_path = next((proj / "02_Agent_Notes" / "Turing").glob(f"{cand}_*_delta.v2.json"))
    evidence_id = json.loads(l7_path.read_text(encoding="utf-8"))["results"][0]["evidence_id"]
    emit("L8", "Tukey", {"evidence_assessments": [{"evidence_id": evidence_id,
         "verification": "VERIFIED", "relations": [{"hypothesis_id": hid,
             "outcome": "SUPPORTS", "reason": "r"}]}]})
    emit("L9a", "Feynman", {"assessments": [{"hypothesis_id": hid,
         "epistemic_status": "PROVISIONALLY_SUPPORTED", "reason": "r",
         "evidence_ids": [evidence_id]}]})
    # L10b is authorized to cite hypothesis-stage (L1) and result-verification
    # (L8.5) evidence, not method-design (L4) evidence.
    literature_ids = deep_research.evidence_ids(proj, cand, ["L1"])
    emit("L10b", "Oppenheimer", {
        "decision": "REVISE", "reason": "because",
        "next_steps": ["explore atrial chamber", "add Hi-C contact data"],
        "hypothesis_decisions": [{"hypothesis_id": hid,
             "disposition": "REVISE", "reason": "r"}],
        "literature_evidence_ids": literature_ids,
        "next_round_proposal": {"proposal_key": "H2", "statement": "H_next",
             "operationalization": "measure next", "falsification_criteria": ["next absent"],
             "relationship": "DERIVED_FROM", "parent_hypothesis_ids": [hid],
             "loop_type": loop_type, "reason": "r"},
    })
    return cand


def _round_n_plus_1(tmp_path, loop_type="divergent"):
    """Build the full chain and return (proj, cand_n, seed_path, cand_n1)."""
    proj = _new_project(tmp_path)
    cand_n = _seed_terminal_candidate(proj, loop_type)

    r = _run("emit-loop-memory", str(proj), cand_n)
    assert r.returncode == 0, r.stderr
    seed = proj / "08_Audit" / "loop_memory" / f"{cand_n}_next_loop_memory.json"
    assert seed.exists(), "emit-loop-memory did not write the seed JSON"

    r2 = _run("new-candidate", str(proj), "--title", "T2", "--question", "Q2",
              "--claim", "C2", "--input", "in2",
              "--from-memory", str(seed), "--loop-type", loop_type)
    assert r2.returncode == 0, r2.stderr
    cand_n1 = r2.stdout.strip().splitlines()[0]
    return proj, cand_n, seed, cand_n1


def _candidate_text(proj, cand):
    matches = list((proj / "01_Candidates").glob(f"{cand}*.md"))
    assert matches, f"candidate file for {cand} not found"
    return matches[0].read_text(encoding="utf-8")


# --- 1. seed continuity: round N output IS round N+1 input --------------------

def test_emit_loop_memory_seed_threads_into_next_candidate(tmp_path):
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path)

    mem = json.loads(seed.read_text(encoding="utf-8"))
    # the seed is the REAL product of _build_loop_memory over round N's deltas
    assert mem["source_candidate_id"] == cand_n
    assert mem["previous_hypothesis"] == "h"           # v2 primary statement summary
    assert mem["next_round_hypothesis"] == "H_next"    # from L10b
    assert mem["required_new_search_directions"] == [
        "explore atrial chamber", "add Hi-C contact data"]  # from L10b next_steps

    # new-candidate must have threaded the seed into the round N+1 frontmatter
    txt = _candidate_text(proj, cand_n1)
    assert "from_memory: true" in txt
    assert "loop_type: divergent" in txt
    assert f"prior_candidate: {cand_n}" in txt
    expected_hash = hashlib.sha256(seed.read_bytes()).hexdigest()
    assert expected_hash in txt, "frontmatter memory_hash != sha256 of the real seed"


# --- 2. L0 memory-hash gate honours the threaded seed hash --------------------

def test_l0_gate_accepts_prior_memory_from_real_seed(tmp_path):
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path)
    mem = json.loads(seed.read_text(encoding="utf-8"))
    real_hash = hashlib.sha256(seed.read_bytes()).hexdigest()

    # prior_loop_memory reconstructed from the REAL seed the prior round wrote.
    delta = {"skills_found": [], "skills_gaps": [], "input_verified": {},
             "environment": {}, "skill_use_plan": [], "forbidden_shortcuts": [],
             "prior_loop_memory": {
                 "source_candidate_id": mem["source_candidate_id"],
                 "loaded_from": str(seed), "memory_hash": real_hash,
                 "previous_hypothesis": mem["previous_hypothesis"],
                 "next_round_hypothesis": mem["next_round_hypothesis"],
                 "required_new_search_directions": mem["required_new_search_directions"]},
             "candidate_id": cand_n1}
    ok, reason = _rl_module()._audit_l0_memory(str(proj), cand_n1, delta)
    assert ok is True, reason


def test_l0_gate_rejects_hash_that_does_not_match_threaded_seed(tmp_path):
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path)
    mem = json.loads(seed.read_text(encoding="utf-8"))
    delta = {"prior_loop_memory": {
                 "memory_hash": "deadbeef",  # != frontmatter hash from real seed
                 "previous_hypothesis": mem["previous_hypothesis"],
                 "next_round_hypothesis": mem["next_round_hypothesis"],
                 "required_new_search_directions": mem["required_new_search_directions"]},
             "candidate_id": cand_n1}
    ok, reason = _rl_module()._audit_l0_memory(str(proj), cand_n1, delta)
    assert ok is False and "mismatch" in reason


# --- 3. L1 divergence gate is WIRED into assemble-context for the threaded cand -

def _write_l1_research_fixture(proj, cand_id, queries):
    persist_synthetic_evidence(proj, cand_id, "L1", queries)


def _seed_family_cache(proj, families):
    p = proj / "09_Literature_Database" / "query_families.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"families": families}), encoding="utf-8")


def test_l1_divergence_gate_blocks_reused_families_via_cli(tmp_path):
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path)
    _seed_family_cache(proj, ["col6a1 collagen", "collagen enhancer vi"])
    _write_l1_research_fixture(proj, cand_n1, ["COL6A1 collagen", "collagen VI enhancer"])
    r = _run("assemble-context", str(proj), cand_n1, "--node", "L1")
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert "new query" in r.stderr.lower()  # divergence gate message, wired -> rc=3


def test_l1_divergence_gate_passes_with_two_new_families_via_cli(tmp_path):
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path)
    _seed_family_cache(proj, ["col6a1 collagen"])
    _write_l1_research_fixture(
        proj, cand_n1, ["cardiac tissue stiffness AFM", "myocardial passive compliance measurement"])
    r = _run("assemble-context", str(proj), cand_n1, "--node", "L1")
    assert r.returncode == 0, r.stderr


def test_divergence_gate_bypassed_for_correction_loop_via_cli(tmp_path):
    # non-divergent loop types thread the same seed but skip the family requirement
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path, loop_type="correction")
    _seed_family_cache(proj, ["col6a1 collagen"])
    _write_l1_research_fixture(proj, cand_n1, ["col6a1 collagen"])  # reused, but correction bypasses
    r = _run("assemble-context", str(proj), cand_n1, "--node", "L1")
    assert r.returncode == 0, r.stderr
