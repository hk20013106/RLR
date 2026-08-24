# -*- coding: utf-8 -*-
"""PR3: tests for the pre-research artifact templates and producers.

Ensures that:
1. Running `pre-research` creates placeholder files with the required sections
   and they fail the gate with rc=3.
2. Generating synthetic artifacts with `--write-synthetic` includes real-looking
   provenance; native v2.1 tests explicitly bridge that acquisition through a
   frozen Curie EvidencePack before L1 context is authorized.
3. L7 nodes are not gated by literature provenance.
4. Existing test gates and digests are preserved.
"""
import json
import os
import sys
import subprocess
import tempfile
from pathlib import Path

from research_loop import deep_research, l0_contract, research_seed
import research_loop.l05_curie as curie
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.yamlio import _replace_field

HERE = Path(__file__).resolve().parent
RL = str(HERE.parent / "research_loop_v04.py")


def _run(*args):
    return subprocess.run([sys.executable, RL] + list(args),
                          capture_output=True, text=True, timeout=15,
                          encoding="utf-8", errors="replace")


def _mkproj():
    d = tempfile.mkdtemp(prefix="rlr_pr3_")
    project = Path(d)
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: T\nkind: project_index\n"
        "created_at: 2026-01-01T00:00:00\n---\n# T\n", encoding="utf-8")
    cand = project / "01_Candidates"
    cand.mkdir(parents=True)
    candidate = cand / "C1.md"
    candidate.write_text(
        "---\ncandidate_id: C1\ntitle: T\nquestion: Does X cause Y?\n"
        "claim: X causes Y\ncurrent_status: NEW\ncurrent_owner: Einstein\n"
        "round_id: 1\nround_type: initial\n"
        "---\n# C1\n", encoding="utf-8")

    # This is a native v2.1 fixture. Native L1 is authorized by the L0 sidecar,
    # not by duplicate candidate question/claim fields, so this fixture must
    # satisfy the same canonical contract as a current project.
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="synthetic pre-research fixture input",
        fmt="text",
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            "C1", "1", "Does X cause Y?", source_input, "X causes Y"
        )
    )
    contract_path, contract_hash = l0_contract.write_contract(
        project, "C1", contract
    )
    _replace_field(candidate, "schema_version", contract["schema_version"])
    _replace_field(
        candidate,
        "input_contract_path",
        contract_path.relative_to(project).as_posix(),
    )
    _replace_field(candidate, "input_contract_hash", contract_hash)
    HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"]).bind_project(
        project, profile_id=DEFAULT_NATIVE_PROFILE
    )
    return d


def _bind_synthetic_native_l1(project_dir):
    """Promote the test-only legacy synthetic run through the native authority."""
    project = Path(project_dir)
    seed = research_seed.load_l1_research_seed(project, "C1")
    run_id = deep_research.unique_run_id(project, "C1", "L1")
    assert run_id, "synthetic L1 fixture must create exactly one acquisition run"
    manifest = curie.freeze_l1_deep_research_run(
        project,
        candidate_id="C1",
        round_id=str(seed["round_id"]),
        seed_sha256=research_seed.seed_sha256(seed),
        run_id=run_id,
    )
    research_seed.write_l1_native_evidence_binding(
        project, seed, manifest, run_id
    )
    return run_id


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

    # Native L1 has no Curie binding, so context must fail closed with rc=3.
    r_assem = _run("assemble-context", d, "C1", "--node", "L1")
    assert r_assem.returncode == 3, f"expected rc=3, got {r_assem.returncode}: {r_assem.stderr}"
    assert "native l1 evidence binding" in r_assem.stderr.lower()


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

    # Assemble context on L4 must fail closed with rc=3. Exact-run ambiguity is
    # also an intentional fail-closed outcome and is not a production failure.
    r_assem = _run("assemble-context", d, "C1", "--node", "L4")
    assert r_assem.returncode == 3, f"expected rc=3, got {r_assem.returncode}: {r_assem.stderr}"
    error = r_assem.stderr.lower()
    assert (
        "gate" in error
        or "not yet run" in error
        or "requires --evidence-run-id" in error
    )


# 3. A synthetic legacy acquisition is usable by native L1 only after explicit
#    Curie freeze + native binding.
def test_write_synthetic_passes_gate_after_native_curie_binding():
    d = _mkproj()

    r = _run("pre-research", d, "C1", "--node", "L1", "--write-synthetic")
    assert r.returncode == 0, f"expected rc=0 for pre-research, got {r.returncode}: {r.stderr}"

    target = Path(d) / "02_Agent_Notes" / "_pre_research" / "L1_research.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "NOT YET RUN" not in text
    assert "## Source count\n1" in text

    lit_dir = Path(d) / "09_Literature_Database"
    lit_dir.mkdir(parents=True, exist_ok=True)
    (lit_dir / "smith2020.md").write_text("Title: Smith 2020", encoding="utf-8")

    # Legacy acquisition alone is not L1 authority in native v2.1.
    rejected = _run("assemble-context", d, "C1", "--node", "L1")
    assert rejected.returncode == 3
    assert "native l1 evidence binding" in rejected.stderr.lower()

    _bind_synthetic_native_l1(d)
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

    custom_text = "## Runtime digest\nNOT YET RUN\n## Custom legacy section\nmy partial work\n"
    target.write_text(custom_text, encoding="utf-8")

    r = _run("pre-research", d, "C1", "--node", "L1")
    assert r.returncode == 0
    assert target.read_text(encoding="utf-8") == custom_text, "file was overwritten silently"

    r2 = _run("pre-research", d, "C1", "--node", "L1", "--write-placeholder")
    assert r2.returncode == 0
    new_text = target.read_text(encoding="utf-8")
    assert new_text != custom_text, "file was not overwritten when requested"
    assert "## Query log" in new_text


def test_l1_evidence_is_rejected_after_canonical_research_seed_drift():
    d = _mkproj()
    project = Path(d)

    r = _run("pre-research", d, "C1", "--node", "L1", "--write-synthetic")
    assert r.returncode == 0, r.stderr

    lit_dir = project / "09_Literature_Database"
    lit_dir.mkdir(parents=True, exist_ok=True)
    (lit_dir / "smith2020.md").write_text("Title: Smith 2020", encoding="utf-8")

    # Establish a valid native binding first; otherwise this test would pass for
    # the wrong reason (missing binding rather than ResearchSeed drift).
    _bind_synthetic_native_l1(project)
    before = _run("assemble-context", d, "C1", "--node", "L1")
    assert before.returncode == 0, before.stderr

    contract, _path, _raw = l0_contract.load_contract(project, "C1")
    contract["scientific_question"] = "A different canonical scientific question"
    contract_path, contract_hash = l0_contract.write_contract(project, "C1", contract)
    candidate = project / "01_Candidates" / "C1.md"
    _replace_field(
        candidate,
        "input_contract_path",
        contract_path.relative_to(project).as_posix(),
    )
    _replace_field(candidate, "input_contract_hash", contract_hash)

    r_assem = _run("assemble-context", d, "C1", "--node", "L1")
    assert r_assem.returncode == 3, r_assem.stderr
    assert "research seed" in r_assem.stderr.lower() or "evidence binding" in r_assem.stderr.lower()


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
