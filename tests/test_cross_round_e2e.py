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


def _seed_terminal_candidate(proj):
    """Round N: a candidate carrying the L1 + L10b deltas that _build_loop_memory
    reads, with a NON-EMPTY next_steps so the produced seed satisfies the L0
    gate's `required_new_search_directions` requirement."""
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q0",
             "--claim", "C", "--input", "in")
    assert r.returncode == 0, r.stderr
    cand = r.stdout.strip().splitlines()[0]
    notes = proj / "02_Agent_Notes"

    def drop(persona, key, obj):
        d = notes / persona
        d.mkdir(parents=True, exist_ok=True)
        obj = {**obj, "candidate_id": cand}
        (d / f"{cand}_{key}_delta.json").write_text(json.dumps(obj), encoding="utf-8")

    drop("Einstein", "L1_einstein",
         {"hypotheses": [{"id": "H1", "text": "h", "testable": True, "rationale": "r"}],
          "key_uncertainty": "u", "primary_hypothesis": "H1",
          "candidate_branches": [{"id": "b1", "description": "d"}]})
    drop("Oppenheimer", "L10b_oppenheimer",
         {"decision": "DOWNGRADE", "evidence_level": "weak", "reason": "because",
          "next_round_hypothesis": "H_next",
          "next_steps": ["explore atrial chamber", "add Hi-C contact data"]})
    return cand


def _round_n_plus_1(tmp_path, loop_type="divergent"):
    """Build the full chain and return (proj, cand_n, seed_path, cand_n1)."""
    proj = _new_project(tmp_path)
    cand_n = _seed_terminal_candidate(proj)

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
    assert mem["previous_hypothesis"] == "H1"          # from L1 primary_hypothesis
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

def _write_l1_pre_research(proj, queries):
    d = proj / "02_Agent_Notes" / "_pre_research"
    d.mkdir(parents=True, exist_ok=True)
    ql = "\n".join(f"- {q}" for q in queries)
    txt = (f"# L1 research\n\n## Runtime digest\nfindings PMID: 111\n\n"
           f"## Query log\n{ql}\n\n## Tool receipt\n- pubmed 2020 ok\n\n"
           f"## Source count\n2\n")
    (d / "L1_research.md").write_text(txt, encoding="utf-8")


def _seed_family_cache(proj, families):
    p = proj / "09_Literature_Database" / "query_families.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"families": families}), encoding="utf-8")


def test_l1_divergence_gate_blocks_reused_families_via_cli(tmp_path):
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path)
    _seed_family_cache(proj, ["col6a1 collagen", "collagen enhancer vi"])
    _write_l1_pre_research(proj, ["COL6A1 collagen", "collagen VI enhancer"])
    r = _run("assemble-context", str(proj), cand_n1, "--node", "L1")
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert "new query" in r.stderr.lower()  # divergence gate message, wired -> rc=3


def test_l1_divergence_gate_passes_with_two_new_families_via_cli(tmp_path):
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path)
    _seed_family_cache(proj, ["col6a1 collagen"])
    _write_l1_pre_research(
        proj, ["cardiac tissue stiffness AFM", "myocardial passive compliance measurement"])
    r = _run("assemble-context", str(proj), cand_n1, "--node", "L1")
    assert r.returncode == 0, r.stderr


def test_divergence_gate_bypassed_for_correction_loop_via_cli(tmp_path):
    # non-divergent loop types thread the same seed but skip the family requirement
    proj, cand_n, seed, cand_n1 = _round_n_plus_1(tmp_path, loop_type="correction")
    _seed_family_cache(proj, ["col6a1 collagen"])
    _write_l1_pre_research(proj, ["col6a1 collagen"])  # reused, but correction bypasses
    r = _run("assemble-context", str(proj), cand_n1, "--node", "L1")
    assert r.returncode == 0, r.stderr
