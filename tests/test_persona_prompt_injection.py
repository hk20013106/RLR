"""Phase 7 follow-up: PHYSICAL persona-injection & isolation tests.

`test_context_isolation.py` asserts on the context_manifest's `allowed_inputs`
-- the STRUCTURAL truth of what a node may see -- and its docstring notes it
"deliberately do NOT string-grep the rendered context". Rev-2 C4 warns that the
ContextAssembler is a SECURITY boundary where physical absence can weaken while
the manifest still looks filtered. This module closes that gap: it asserts on

  (a) the ACTUAL rendered context  (assemble-context stdout), and
  (b) the FINAL provider prompt file the model receives
      (research_loop.providers.command.CommandProvider -> {node}_{persona}_prompt.txt),

using UNIQUE sentinels planted in forbidden deltas. A sentinel in a forbidden
delta's DATA sidesteps the persona-name false-positive the sibling file cites
(a node's context can legitimately mention a downstream persona's name as branch
metadata; it must never contain a forbidden delta's actual payload).

Chain mirrored: run_loop.run_node does `ctx = assemble_context(...)` then
`prov.run_agent(node, persona, ctx, ...)`. We reproduce exactly that two stages.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

from research_loop.providers.command import CommandProvider  # noqa: E402
from research_loop import deep_research as dr  # noqa: E402

RL = str(HERE / "research_loop_v04.py")

# Force UTF-8 on the child (it prints templates that contain smart quotes) and
# decode with UTF-8 here, so the pipe never trips the Windows locale (GBK) codec.
# This is a capture-harness concern only: the real runtime assembles context
# in-process (EngineAPI, StringIO), not through a locale-decoded subprocess pipe.
_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

FORBID = "ZZZSENTINEL_L9B_FORBIDDEN_PAYLOAD"  # planted only in the L9b delta
# body-only line from templates/personas/02_Einstein.md (NOT in NODE_MAP,
# so it can ONLY appear if the persona template file itself is injected):
EINSTEIN_BODY = "Imaginative but disciplined."


def _run(*args):
    return subprocess.run([sys.executable, RL, *args], capture_output=True,
                          text=True, encoding="utf-8", env=_ENV)


def _assemble(proj, cand, node, *extra):
    """Return (rc, rendered_context_text, stderr) -- assemble-context prints the
    context to stdout and the manifest path to stderr."""
    r = _run("assemble-context", str(proj), cand, "--node", node, *extra)
    return r.returncode, r.stdout, r.stderr


def _new_project(tmp_path):
    r = _run("new-project", str(tmp_path / "P"), "T")
    assert r.returncode == 0, r.stderr
    return tmp_path / "P"


def _new_candidate(proj):
    r = _run("new-candidate", str(proj), "--title", "T", "--question", "Q",
             "--claim", "C", "--input", "in")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[0]


def _drop(proj, persona, key, obj, cand):
    d = proj / "02_Agent_Notes" / persona
    d.mkdir(parents=True, exist_ok=True)
    obj = {**obj, "candidate_id": cand}
    (d / f"{cand}_{key}_delta.json").write_text(json.dumps(obj), encoding="utf-8")


def _seed_l0(proj, cand):
    _drop(proj, "Linnaeus", "L0_linnaeus",
          {"skills_found": [], "skills_gaps": [], "input_verified": {},
           "environment": {}, "skill_use_plan": [], "forbidden_shortcuts": []}, cand)


def _seed_forbidden_l9b(proj, cand):
    _drop(proj, "Darwin", "L9b_darwin",
          {"module_interpretations": [{"module": FORBID, "genes": ["g"]}]}, cand)


def _write_l1_preresearch(proj, cand):
    """Create the verified evidence artifact now required before L1."""
    payload = {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["test hypothesis"],
        "papers": [{
            "doi": "10.1000/persona-test", "pmid": "123456", "url": "https://example.org/paper",
            "title": "Persona context fixture", "source_database": "Europe PMC",
            "metadata": {"year": 2026}, "source_metadata_response": {"id": "123456"},
            "open_access": False,
            "extracts": [
                {"section": "Results", "text": "Observed result.", "locator": "Results 1"},
                {"section": "Discussion", "text": "Discussed result.", "locator": "Discussion 1"},
                {"section": "Conclusion", "text": "Concluded result.", "locator": "Conclusion 1"},
            ],
        }],
    }
    artifact = dr.persist_run(
        proj, cand, "L1", payload,
        dr.skill_receipt("codex", ["codex", "exec"], "fixture", "test"),
    )
    target = proj / "02_Agent_Notes" / "_pre_research" / "L1_research.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dr.render_pre_research_markdown(artifact), encoding="utf-8")


def _prompt_via_provider(node, persona, ctx, run_dir):
    """Feed the REAL rendered context through the REAL CommandProvider and return
    the final provider prompt text it wrote to {node}_{persona}_prompt.txt."""
    run_dir.mkdir(parents=True, exist_ok=True)
    py = sys.executable.replace("\\", "/")
    # writer.py writes a minimal `{}` delta; its `{}` lives in file CONTENT so the
    # command template's .format() (which fills {prompt_file}/{output_file}) never
    # sees a stray brace.
    writer = run_dir / "_writer.py"
    writer.write_text(
        "import sys,pathlib;pathlib.Path(sys.argv[2]).write_text('{}')",
        encoding="utf-8")
    cmd = f"{py} {writer.as_posix()} {{prompt_file}} {{output_file}}"
    prov = CommandProvider({"command": cmd})
    prov.run_agent(node, persona, ctx, run_dir=str(run_dir))
    return Path(prov.last_prompt_file).read_text(encoding="utf-8")


# --- 1. persona identity physically reaches rendered context AND prompt --------

def test_persona_identity_in_rendered_context_and_provider_prompt(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_candidate(proj)
    _seed_l0(proj, cand)
    _write_l1_preresearch(proj, cand)

    rc, ctx, err = _assemble(proj, cand, "L1")
    assert rc == 0, err
    # rendered context carries the persona identity (contract mode = real default)
    assert "=== CONTRACT: L1 | Einstein" in ctx
    assert "Generate testable scientific hypotheses" in ctx  # NODE_MAP MUST rule

    prompt = _prompt_via_provider("L1", "Einstein", ctx, tmp_path / "run1")
    # the FINAL prompt the model receives carries the persona twice over:
    assert "persona=Einstein" in prompt              # provider header
    assert "=== CONTRACT: L1 | Einstein" in prompt   # embedded contract block
    assert "Generate testable scientific hypotheses" in prompt


# --- 2. full mode actually injects the persona template file (not saved-and-dead)

def test_full_mode_injects_persona_template_body(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_candidate(proj)
    _seed_l0(proj, cand)
    _write_l1_preresearch(proj, cand)

    rc, ctx, err = _assemble(proj, cand, "L1", "--template-mode", "full")
    assert rc == 0, err
    assert "[full] persona template (02_Einstein.md)" in ctx
    assert EINSTEIN_BODY in ctx, "full mode must inject the persona template body"


# --- 3. forbidden downstream delta payload is PHYSICALLY absent (ctx + prompt) --

def test_forbidden_downstream_delta_absent_from_context_and_prompt(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_candidate(proj)
    _seed_l0(proj, cand)
    _write_l1_preresearch(proj, cand)
    _seed_forbidden_l9b(proj, cand)  # L1 must never see L9b

    rc, ctx, err = _assemble(proj, cand, "L1")
    assert rc == 0, err
    assert FORBID not in ctx, "L9b payload leaked into L1 rendered context"

    prompt = _prompt_via_provider("L1", "Einstein", ctx, tmp_path / "run3")
    assert FORBID not in prompt, "L9b payload leaked into the L1 provider prompt"


# --- 4. parallel-node isolation at the PHYSICAL layer (L9a must not see L9b) ----

def test_parallel_node_l9a_physically_excludes_l9b_payload(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_candidate(proj)
    _seed_l0(proj, cand)
    _seed_forbidden_l9b(proj, cand)
    # L9a context_inputs = [L1, L7, L8, L8.5]; L9b is a sibling it must not read.
    rc, ctx, err = _assemble(proj, cand, "L9a")
    assert rc == 0, err
    assert "=== CONTRACT: L9a | Feynman" in ctx
    assert FORBID not in ctx, "L9a rendered context leaked its sibling L9b payload"

    prompt = _prompt_via_provider("L9a", "Feynman", ctx, tmp_path / "run4")
    assert FORBID not in prompt


# --- 5. the CONTRACT binds each node to its OWN persona, not another's ----------

def test_contract_persona_is_bound_to_the_node(tmp_path):
    proj = _new_project(tmp_path)
    cand = _new_candidate(proj)
    _seed_l0(proj, cand)
    # seed an L1 delta so L2 (inputs: candidate_frontmatter, L1) assembles
    _drop(proj, "Einstein", "L1_einstein",
          {"hypotheses": [{"id": "H1", "text": "h", "testable": True, "rationale": "r"}],
           "key_uncertainty": "u", "primary_hypothesis": "H1"}, cand)

    rc, ctx, err = _assemble(proj, cand, "L2")
    assert rc == 0, err
    # L2's operative persona is Feynman -- the contract must say so, and must NOT
    # bind L2 to Einstein (even though the embedded L1 delta key contains
    # "einstein", the CONTRACT header is the authority on node<->persona binding).
    assert "=== CONTRACT: L2 | Feynman" in ctx
    assert "=== CONTRACT: L2 | Einstein" not in ctx
