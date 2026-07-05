# -*- coding: utf-8 -*-
"""V0.5 deep-research gate — proves the canonical runtime fails closed.

The active runtime (run_loop.py -> research_loop_v04.py) must NOT finish an
L1/L4/L7 literature-dependent node without a valid pre-research artifact:
  1. missing L1 pre-research blocks assemble-context (rc=3)
  2. placeholder (NOT YET RUN) L1 pre-research blocks assemble-context (rc=3)
  3. valid L1 pre-research allows assemble-context (rc=0)
  4. the default runner (run_loop.assemble_context) propagates the gate as a
     hard stop instead of silently continuing
"""
import sys
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RL = str(HERE / "research_loop_v04.py")
sys.path.insert(0, str(HERE))
import run_loop  # noqa: E402  (default runner -> proves gate consumption)

_VALID_L1 = ("# L1 deep research\n\n## Runtime digest\n"
             "- [[09_Literature_Database/smith2020|Smith 2020]] "
             "doi:10.1000/abc123 — core finding: X associates with Y.\n")


def _run(*args):
    return subprocess.run([sys.executable, RL] + list(args),
                          capture_output=True, text=True, timeout=15,
                          encoding="utf-8", errors="replace")


def _mkproj():
    d = tempfile.mkdtemp(prefix="rlr_gate_")
    (Path(d) / "00_Project_Index.md").write_text(
        "---\nproject_name: T\nkind: project_index\n"
        "created_at: 2026-01-01T00:00:00\n---\n# T\n", encoding="utf-8")
    cand = Path(d) / "01_Candidates"
    cand.mkdir(parents=True)
    (cand / "C1.md").write_text(
        "---\ncandidate_id: C1\ntitle: T\nquestion: Does X cause Y?\n"
        "claim: X causes Y\ncurrent_status: NEW\ncurrent_owner: Einstein\n"
        "---\n# C1\n", encoding="utf-8")
    return d


def _write_l1(d, text):
    pr = Path(d) / "02_Agent_Notes" / "_pre_research"
    pr.mkdir(parents=True, exist_ok=True)
    (pr / "L1_research.md").write_text(text, encoding="utf-8")


def test_missing_l1_pre_research_blocks():
    d = _mkproj()
    r = _run("assemble-context", d, "C1", "--node", "L1")
    assert r.returncode == 3, f"expected rc=3, got {r.returncode}: {r.stderr}"
    assert "deep-research gate" in r.stderr.lower(), r.stderr


def test_placeholder_l1_pre_research_blocks():
    d = _mkproj()
    _write_l1(d, "=== PRE-RESEARCH (deep_research): NOT YET RUN ===\n")
    r = _run("assemble-context", d, "C1", "--node", "L1")
    assert r.returncode == 3, f"expected rc=3, got {r.returncode}: {r.stderr}"
    assert "not yet run" in r.stderr.lower(), r.stderr


def test_valid_l1_pre_research_allows():
    d = _mkproj()
    _write_l1(d, _VALID_L1)
    r = _run("assemble-context", d, "C1", "--node", "L1")
    assert r.returncode == 0, f"expected rc=0, got {r.returncode}: {r.stderr}"
    assert "NOT YET RUN" not in r.stdout, "must not emit NOT YET RUN as success"


def test_default_runner_consumes_gate():
    # run_loop.assemble_context (the default runner path) must RAISE on the
    # gate failure, not silently continue.
    d = _mkproj()
    raised = False
    try:
        run_loop.assemble_context(d, "C1", "L1")
    except RuntimeError as e:
        raised = True
        assert "assemble-context L1 failed" in str(e), str(e)
    assert raised, "default runner must fail closed when deep research is absent"


def _run_as_script():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
