"""L0 structured input-contract: validator matrix + PHYSICAL injection/leak +
gate rc via the REAL CLI and REAL provider prompt path.

Two layers:
  (A) unit tests on the ONE validator (l0_contract.validate_l0_input_contract) —
      the initial/continuation hard-fail matrix, field-precise messages.
  (B) end-to-end tests through `research_loop_v04.py` (real new-candidate,
      assemble-context, emit-delta) and the real CommandProvider prompt file,
      with unique sentinels proving each field physically reaches the L0
      rendered context AND the provider prompt — and that L0-only fields
      (source_input, previous_round) do NOT leak to a cognitive node (L2).

Mirrors the harness in test_persona_prompt_injection.py.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

from research_loop import l0_contract  # noqa: E402
from research_loop.providers.command import CommandProvider  # noqa: E402

RL = str(HERE / "research_loop_v04.py")
_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _run(*args):
    return subprocess.run([sys.executable, RL, *args], capture_output=True,
                          text=True, encoding="utf-8", env=_ENV)


def _assemble(proj, cand, node, *extra):
    r = _run("assemble-context", str(proj), cand, "--node", node, *extra)
    return r.returncode, r.stdout, r.stderr


def _new_project(tmp_path):
    r = _run("new-project", str(tmp_path / "P"), "T")
    assert r.returncode == 0, r.stderr
    return tmp_path / "P"


def _prompt_via_provider(node, persona, ctx, run_dir):
    run_dir.mkdir(parents=True, exist_ok=True)
    py = sys.executable.replace("\\", "/")
    writer = run_dir / "_writer.py"
    writer.write_text(
        "import sys,pathlib;pathlib.Path(sys.argv[2]).write_text('{}')",
        encoding="utf-8")
    cmd = f"{py} {writer.as_posix()} {{prompt_file}} {{output_file}}"
    prov = CommandProvider({"command": cmd})
    prov.run_agent(node, persona, ctx, run_dir=str(run_dir))
    return Path(prov.last_prompt_file).read_text(encoding="utf-8")


# =====================================================================
# (A) validator unit matrix
# =====================================================================

def _valid_initial(tmp_path):
    return l0_contract.build_initial_contract(
        "C1", "1", "Does X track Y?",
        l0_contract.build_source_input(input_type="inline",
                                       description="an inline dataset",
                                       fmt="text"),
        new_hypothesis="X correlates with Y")


def _v(contract, fm=None, project_dir="/nonexistent", cand="C1"):
    return l0_contract.validate_l0_input_contract(
        contract, fm or {}, project_dir, cand)


def test_initial_valid_passes(tmp_path):
    assert _v(_valid_initial(tmp_path)) == []


def test_missing_scientific_question(tmp_path):
    c = _valid_initial(tmp_path)
    c["scientific_question"] = ""
    errs = _v(c)
    assert any("scientific_question" in e for e in errs), errs


def test_placeholder_source_input_description(tmp_path):
    c = _valid_initial(tmp_path)
    c["source_input"]["description"] = "已有数据"
    errs = _v(c)
    assert any("source_input.description" in e for e in errs), errs


def test_source_input_illegal_input_type(tmp_path):
    c = _valid_initial(tmp_path)
    c["source_input"]["input_type"] = "bogus"
    errs = _v(c)
    assert any("input_type" in e for e in errs), errs


def test_source_input_missing_format(tmp_path):
    c = _valid_initial(tmp_path)
    c["source_input"]["format"] = ""
    errs = _v(c)
    assert any("source_input.format" in e for e in errs), errs


def test_source_input_files_not_found_hard_fail(tmp_path):
    c = _valid_initial(tmp_path)
    c["source_input"] = l0_contract.build_source_input(
        input_type="files", files=["nope_missing.csv"],
        description="d", fmt="csv")  # no verified:false marker
    errs = _v(c, project_dir=str(tmp_path))
    assert any("not found and not marked verified:false" in e for e in errs), errs


def test_source_input_files_unverifiable_marker_passes(tmp_path):
    c = _valid_initial(tmp_path)
    c["source_input"] = l0_contract.build_source_input(
        input_type="files", files=["nope_missing.csv"],
        description="d", fmt="csv", verified=False)
    assert _v(c, project_dir=str(tmp_path)) == []


def test_initial_with_previous_round_conflict(tmp_path):
    c = _valid_initial(tmp_path)
    c["previous_round"] = {"hypothesis": "h", "final_decision": "KEEP",
                           "conclusion": "c"}
    errs = _v(c)
    assert any("initial" in e and "prior state" in e for e in errs), errs


def test_missing_current_hypothesis(tmp_path):
    c = _valid_initial(tmp_path)
    c["current_round"]["hypothesis"] = ""
    errs = _v(c)
    assert any("current_round.hypothesis" in e for e in errs), errs


def test_illegal_round_type(tmp_path):
    c = _valid_initial(tmp_path)
    c["round_type"] = "middle"
    errs = _v(c)
    assert any("round_type" in e for e in errs), errs


def test_unsupported_schema_version(tmp_path):
    c = _valid_initial(tmp_path)
    c["schema_version"] = "9.9"
    errs = _v(c)
    assert any("schema_version" in e for e in errs), errs


def test_missing_artifact_is_hard_fail():
    errs = _v(None)
    assert errs and "missing or unparseable" in errs[0]


def _valid_continuation():
    return l0_contract.build_continuation_contract(
        "C2", "2", "1", "C1", "Does X still track Y?",
        l0_contract.build_source_input(input_type="inline",
                                       description="d", fmt="text"),
        previous_round={"hypothesis": "prev hyp",
                        "final_decision": "REVISE",
                        "conclusion": "prev conclusion",
                        "memory_hash": "abc"},
        new_hypothesis="new hyp")


_CONT_FM = {"from_memory": "true", "memory_hash": "abc"}


def test_continuation_valid_passes():
    assert _v(_valid_continuation(), fm=dict(_CONT_FM), cand="C2") == []


@pytest.mark.parametrize("field,label", [
    ("hypothesis", "previous_hypothesis"),
    ("final_decision", "previous_final_decision"),
    ("conclusion", "previous_conclusion"),
])
def test_continuation_missing_each_previous_field(field, label):
    c = _valid_continuation()
    c["previous_round"][field] = ""
    errs = _v(c, fm=dict(_CONT_FM), cand="C2")
    assert any(f"previous_round.{field}" in e for e in errs), errs


def test_continuation_new_hypothesis_missing():
    c = _valid_continuation()
    c["current_round"]["hypothesis"] = ""
    errs = _v(c, fm=dict(_CONT_FM), cand="C2")
    assert any("current_round.hypothesis" in e for e in errs), errs


def test_continuation_illegal_decision_enum():
    c = _valid_continuation()
    c["previous_round"]["final_decision"] = "accept"  # not repo enum
    errs = _v(c, fm=dict(_CONT_FM), cand="C2")
    assert any("final_decision" in e and "illegal" in e for e in errs), errs


def test_continuation_without_from_memory_linkage():
    c = _valid_continuation()
    errs = _v(c, fm={}, cand="C2")  # no from_memory
    assert any("from_memory" in e for e in errs), errs


def test_candidate_id_mismatch():
    c = _valid_continuation()  # candidate_id C2
    errs = _v(c, fm=dict(_CONT_FM), cand="C_OTHER")
    assert any("candidate_id" in e for e in errs), errs


def test_memory_hash_mismatch():
    c = _valid_continuation()  # previous_round.memory_hash == "abc"
    fm = {"from_memory": "true", "memory_hash": "DIFFERENT"}
    errs = _v(c, fm=fm, cand="C2")
    assert any("memory_hash" in e for e in errs), errs


def test_frontmatter_hash_mismatch():
    c = _valid_initial(Path("."))
    raw = b"tampered bytes"
    fm = {"input_contract_hash": "expected_but_wrong"}
    errs = l0_contract.validate_l0_input_contract(
        c, fm, ".", "C1", raw_bytes=raw)
    assert any("input_contract_hash mismatch" in e for e in errs), errs


# =====================================================================
# (B) real CLI + provider: physical injection, leak, gate rc
# =====================================================================

SQ = "ZZZSQ_SENTINEL_QUESTION"
SRC = "ZZZSRC_SENTINEL_SOURCEINPUT"
ALIAS = "cleanalias"


def _new_initial(proj):
    """Structured initial candidate: SQ in question, SRC in source_input desc
    (inline, so no file-existence gate), clean alias so SRC stays L0-only."""
    r = _run("new-candidate", str(proj), "--title", "T",
             "--question", f"Does {SQ} hold?",
             "--claim", "some claim",
             "--input", f"raw data {SRC}",
             "--input-type", "inline", "--input-format", "text",
             "--input-alias", ALIAS)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[0]


def test_initial_assemble_rc0_and_physical_injection(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_initial(proj)
    rc, ctx, err = _assemble(proj, cand, "L0")
    assert rc == 0, err
    assert "=== L0 INPUT CONTRACT ===" in ctx
    assert SQ in ctx and SRC in ctx
    # physically reaches the final provider prompt too
    prompt = _prompt_via_provider("L0", "Linnaeus", ctx, tmp_path / "run_l0")
    assert SQ in prompt and SRC in prompt
    assert "=== L0 INPUT CONTRACT ===" in prompt


def test_source_input_does_not_leak_to_cognitive_node(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_initial(proj)
    rc, ctx, err = _assemble(proj, cand, "L2")
    # L2 assembles fine (may inject 'not yet emitted' delta refs) but must NOT
    # carry the raw source_input sentinel or the L0 contract block.
    assert "=== L0 INPUT CONTRACT ===" not in ctx
    assert SRC not in ctx, "source_input leaked to L2"


def test_missing_contract_artifact_rc3_empty_stdout(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_initial(proj)
    art = proj / "01_Candidates" / f"{cand}.l0_input.yaml"
    art.unlink()
    rc, ctx, err = _assemble(proj, cand, "L0")
    assert rc == 3, (rc, err)
    assert ctx.strip() == "", "invalid L0 must produce empty stdout"
    assert "input-contract gate" in err


def test_tampered_hash_rc3(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_initial(proj)
    art = proj / "01_Candidates" / f"{cand}.l0_input.yaml"
    art.write_bytes(art.read_bytes() + b"\n# tamper\n")
    rc, ctx, err = _assemble(proj, cand, "L0")
    assert rc == 3, (rc, err)
    assert "input_contract_hash mismatch" in err


def test_emit_delta_l0_rejects_missing_contract(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_initial(proj)
    (proj / "01_Candidates" / f"{cand}.l0_input.yaml").unlink()
    delta = {"skills_found": [], "skills_gaps": [],
             "input_verified": {}, "environment": {},
             "skill_use_plan": [], "forbidden_shortcuts": []}
    df = tmp_path / "d.json"
    df.write_text(json.dumps(delta), encoding="utf-8")
    r = _run("emit-delta", str(proj), cand, "--node", "L0",
             "--persona", "Linnaeus", "--file", str(df))
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "input-contract gate" in r.stderr


def test_round_type_conflict_initial_with_from_memory(tmp_path):
    proj = _new_project(tmp_path)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({
        "source_candidate_id": "C_PARENT", "next_round_hypothesis": "n",
        "required_new_search_directions": ["d"]}), encoding="utf-8")
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in", "--from-memory", str(seed),
             "--loop-type", "divergent", "--round-type", "initial")
    assert r.returncode == 2, r.stderr
    assert "conflicts with --from-memory" in r.stderr


# --- continuation end-to-end -------------------------------------------------

PREVHYP = "ZZZPREVHYP_SENTINEL"
PREVCONC = "ZZZPREVCONC_SENTINEL"
NEWHYP = "ZZZNEWHYP_SENTINEL"


def _seed_full(tmp_path, **overrides):
    mem = {
        "source_candidate_id": "C_PARENT_0001",
        "next_round_hypothesis": f"{NEWHYP} next hypothesis",
        "required_new_search_directions": ["dir1", "dir2"],
        "previous_hypothesis": f"{PREVHYP} prior hypothesis",
        "previous_final_decision": "REVISE",
        "previous_conclusion": f"{PREVCONC} prior conclusion",
        "new_hypothesis": f"{NEWHYP} next hypothesis",
        "terminal_decision": "REVISE",
        "final_reason": f"{PREVCONC} prior conclusion",
        "round_id": "2", "parent_round_id": "1",
    }
    mem.update(overrides)
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(mem), encoding="utf-8")
    return p


def _new_continuation(proj, seed):
    r = _run("new-candidate", str(proj), "--title", "T",
             "--question", f"Does {SQ} still hold?",
             "--claim", "cont claim",
             "--input", f"raw {SRC}", "--input-type", "inline",
             "--input-format", "text", "--input-alias", ALIAS,
             "--from-memory", str(seed), "--loop-type", "divergent")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[0]


def test_continuation_full_rc0_physical_injection(tmp_path):
    proj = _new_project(tmp_path)
    seed = _seed_full(tmp_path)
    cand = _new_continuation(proj, seed)
    rc, ctx, err = _assemble(proj, cand, "L0")
    assert rc == 0, err
    for s in (SQ, SRC, PREVHYP, PREVCONC, NEWHYP, "REVISE"):
        assert s in ctx, f"{s} missing from L0 context"
    prompt = _prompt_via_provider("L0", "Linnaeus", ctx, tmp_path / "run_c")
    for s in (PREVHYP, PREVCONC, NEWHYP):
        assert s in prompt, f"{s} missing from provider prompt"


def test_continuation_previous_round_does_not_leak_to_l2(tmp_path):
    proj = _new_project(tmp_path)
    seed = _seed_full(tmp_path)
    cand = _new_continuation(proj, seed)
    rc, ctx, err = _assemble(proj, cand, "L2")
    assert PREVCONC not in ctx, "previous_round.conclusion leaked to L2"
    assert SRC not in ctx, "source_input leaked to L2"


def test_continuation_missing_previous_conclusion_rc3(tmp_path):
    proj = _new_project(tmp_path)
    seed = _seed_full(tmp_path, previous_conclusion="", final_reason="")
    cand = _new_continuation(proj, seed)
    rc, ctx, err = _assemble(proj, cand, "L0")
    assert rc == 3, (rc, err)
    assert "previous_round.conclusion" in err


def test_continuation_illegal_decision_rc3(tmp_path):
    proj = _new_project(tmp_path)
    seed = _seed_full(tmp_path, previous_final_decision="accept",
                      terminal_decision="accept")
    cand = _new_continuation(proj, seed)
    rc, ctx, err = _assemble(proj, cand, "L0")
    assert rc == 3, (rc, err)
    assert "final_decision" in err and "illegal" in err


def test_build_loop_memory_emits_clean_fields(tmp_path):
    """_build_loop_memory must emit separated decision/conclusion + round ids
    (no 'DROP: reason' munge)."""
    import research_loop_v04 as rl
    proj = _new_project(tmp_path)
    cand = _new_initial(proj)
    # minimal L1 + L10b deltas so the builder has something to read
    for persona, key, obj in (
        ("Einstein", "L1_einstein", {"primary_hypothesis": "H0"}),
        ("Oppenheimer", "L10b_oppenheimer",
         {"decision": "REVISE", "reason": "evidence weak",
          "next_round_hypothesis": "H1"}),
    ):
        d = proj / "02_Agent_Notes" / persona
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{cand}_{key}_delta.json").write_text(
            json.dumps({**obj, "candidate_id": cand}), encoding="utf-8")
    mem = rl._build_loop_memory(proj, cand)
    assert mem["previous_final_decision"] == "REVISE"
    assert mem["previous_conclusion"] == "evidence weak"
    assert mem["new_hypothesis"] == "H1"
    assert mem["round_id"] == "2" and mem["parent_round_id"] == "1"
