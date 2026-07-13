# -*- coding: utf-8 -*-
"""PR3: tests for the pre-research artifact templates and producers.

Ensures that:
1. Running `pre-research` creates placeholder files with the required sections
   and they fail the PR2 gate with rc=3.
2. Generating synthetic artifacts with `--write-synthetic` includes real-looking
   provenance and passes the gate.
3. L7 nodes are not gated by literature provenance.
4. Existing test gates and digests are preserved.
"""
import json
import sys
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RL = str(HERE.parent / "research_loop_v04.py")


def _run(*args):
    return subprocess.run([sys.executable, RL] + list(args),
                          capture_output=True, text=True, timeout=15,
                          encoding="utf-8", errors="replace")


def _mkproj():
    d = tempfile.mkdtemp(prefix="rlr_pr3_")
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


# 1. Running pre-research node L1 creates a placeholder that contains sections
#    and fails closed with rc=3.
def test_l1_placeholder_fails_gate():
    d = _mkproj()
    # Execute pre-research to write placeholder
    r = _run("pre-research", d, "C1", "--node", "L1")
    assert r.returncode == 0, f"expected rc=0 for pre-research, got {r.returncode}: {r.stderr}"

    target = Path(d) / "02_Agent_Notes" / "_pre_research" / "L1_research.md"
    assert target.exists(), "L1_research.md was not written"
    text = target.read_text(encoding="utf-8")

    assert "## Query log" in text
    assert "## Tool receipt" in text
    assert "## Source count" in text
    assert "NOT YET RUN" in text

    # Assemble context on L1 must fail closed with rc=3 due to placeholder/NOT YET RUN
    r_assem = _run("assemble-context", d, "C1", "--node", "L1")
    assert r_assem.returncode == 3, f"expected rc=3, got {r_assem.returncode}: {r_assem.stderr}"
    assert "gate" in r_assem.stderr.lower() or "not yet run" in r_assem.stderr.lower()


# 2. Running pre-research node L4 creates a placeholder that contains sections
#    and fails closed with rc=3.
def test_l4_placeholder_fails_gate():
    d = _mkproj()
    # Execute pre-research to write placeholder
    r = _run("pre-research", d, "C1", "--node", "L4")
    assert r.returncode == 0, f"expected rc=0 for pre-research, got {r.returncode}: {r.stderr}"

    target = Path(d) / "02_Agent_Notes" / "_pre_research" / "L4_research.md"
    assert target.exists(), "L4_research.md was not written"
    text = target.read_text(encoding="utf-8")

    assert "## Query log" in text
    assert "## Tool receipt" in text
    assert "## Source count" in text
    assert "NOT YET RUN" in text

    # Assemble context on L4 must fail closed with rc=3 due to placeholder/NOT YET RUN
    r_assem = _run("assemble-context", d, "C1", "--node", "L4")
    assert r_assem.returncode == 3, f"expected rc=3, got {r_assem.returncode}: {r_assem.stderr}"
    assert "gate" in r_assem.stderr.lower() or "not yet run" in r_assem.stderr.lower()


# 3. Running pre-research with --write-synthetic creates valid completed artifact
#    and passes the gate.
def test_write_synthetic_passes_gate():
    d = _mkproj()
    
    # Write synthetic L1 pre-research
    r = _run("pre-research", d, "C1", "--node", "L1", "--write-synthetic")
    assert r.returncode == 0, f"expected rc=0 for pre-research, got {r.returncode}: {r.stderr}"

    target = Path(d) / "02_Agent_Notes" / "_pre_research" / "L1_research.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "NOT YET RUN" not in text
    assert "## Source count\n1" in text

    # Register the smith2020 paper in the literature database so Obsidian Wikilink resolves
    lit_dir = Path(d) / "09_Literature_Database"
    lit_dir.mkdir(parents=True, exist_ok=True)
    (lit_dir / "smith2020.md").write_text("Title: Smith 2020", encoding="utf-8")

    # Assemble context must succeed (rc=0)
    r_assem = _run("assemble-context", d, "C1", "--node", "L1")
    assert r_assem.returncode == 0, f"expected rc=0, got {r_assem.returncode}: {r_assem.stderr}"


# 4. L7 pre-research node is not gated by literature provenance checks
def test_l7_pre_research_not_gated():
    d = _mkproj()
    
    # Running pre-research L7. By default it is "code_search", which is not a literature node.
    r = _run("pre-research", d, "C1", "--node", "L7")
    assert r.returncode == 0

    # L7 is not a literature node, so even without L7_research.md or if it is empty/placeholder,
    # assemble-context for L7 should succeed (it's a soft gate).
    r_assem = _run("assemble-context", d, "C1", "--node", "L7")
    assert r_assem.returncode == 0, f"expected rc=0 for L7 assemble-context, got {r_assem.returncode}: {r_assem.stderr}"


# 5. Existing pre-research files (even with placeholders) are not overwritten unless requested
def test_existing_file_not_overwritten():
    d = _mkproj()
    pr = Path(d) / "02_Agent_Notes" / "_pre_research"
    pr.mkdir(parents=True, exist_ok=True)
    target = pr / "L1_research.md"
    
    # Write a custom partial/placeholder text
    custom_text = "## Runtime digest\nNOT YET RUN\n## Custom legacy section\nmy partial work\n"
    target.write_text(custom_text, encoding="utf-8")
    
    # Run pre-research without --write-placeholder. It should NOT overwrite.
    r = _run("pre-research", d, "C1", "--node", "L1")
    assert r.returncode == 0
    assert target.read_text(encoding="utf-8") == custom_text, "file was overwritten silently"
    
    # Run pre-research WITH --write-placeholder. It should overwrite.
    r2 = _run("pre-research", d, "C1", "--node", "L1", "--write-placeholder")
    assert r2.returncode == 0
    new_text = target.read_text(encoding="utf-8")
    assert new_text != custom_text, "file was not overwritten when requested"
    assert "## Query log" in new_text


def _run_as_script():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
