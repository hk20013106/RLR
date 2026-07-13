# -*- coding: utf-8 -*-
"""Focused regressions for derived caveman-lite context and archived L7 input."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RL = str(HERE.parent / "research_loop_v04.py")
sys.path.insert(0, str(HERE))
import research_loop_v04 as rl


def _run(*args):
    return subprocess.run(
        [sys.executable, RL] + list(args), capture_output=True, text=True,
        timeout=15, encoding="utf-8", errors="replace")


def _project():
    root = Path(tempfile.mkdtemp(prefix="rlr_caveman_"))
    candidates = root / "01_Candidates"
    candidates.mkdir(parents=True)
    (candidates / "C20260705000000000001.md").write_text(
        "---\ncandidate_id: C20260705000000000001\n"
        "current_status: NEEDS_EXECUTION\ncurrent_owner: Turing\n---\n",
        encoding="utf-8")
    return root


def test_caveman_lite_preserves_required_fields_and_canonical_file():
    root = _project()
    canonical = root / "canonical.md"
    original = (
        "# L7 | Turing\n\n"
        "candidate_id: C20260705000000000001\n"
        "Run: python research_loop_v04.py next-step D:/research_loop/project C1\n"
        "DOI: 10.1000/example PMID: 12345 https://example.org/paper\n"
        "Source count: 3\nFAIL CLOSED. Do not fabricate results.\n\n"
        "Repeated explanatory prose that is not a required field.\n"
        "Repeated explanatory prose that is not a required field.\n"
        "Repeated explanatory prose that is not a required field.\n")
    canonical.write_text(original, encoding="utf-8")
    before = canonical.read_bytes()
    packed, meta = rl._caveman_lite(original, required_literals=[
        "C20260705000000000001", "L7", "Turing", "D:/research_loop/project",
        "python research_loop_v04.py next-step", "10.1000/example",
        "PMID: 12345", "https://example.org/paper", "Source count: 3",
        "FAIL CLOSED", "Do not fabricate results",
    ])
    assert canonical.read_bytes() == before
    for literal in (
            "C20260705000000000001", "L7", "Turing",
            "D:/research_loop/project", "python research_loop_v04.py next-step",
            "10.1000/example", "PMID: 12345", "https://example.org/paper",
            "Source count: 3", "FAIL CLOSED", "Do not fabricate results"):
        assert literal in packed
    assert meta["caveman_mode"] == "lite"
    assert meta["compression_applied"] is True
    assert meta["compressed_est_tokens"] < meta["original_est_tokens"]
    assert meta["compressed_est_tokens"] <= meta["original_est_tokens"] * 0.85
    assert meta["required_fields_preserved"] is True


def test_caveman_lite_skips_when_required_literal_is_absent():
    original = "# Context\n\nordinary prose\nordinary prose\n"
    packed, meta = rl._caveman_lite(
        original, required_literals=["candidate_id: C_MISSING"])
    assert packed == original
    assert meta["compression_applied"] is False
    assert meta["required_fields_preserved"] is False


def test_caveman_lite_packs_derived_delta_json_but_not_schema_or_code_blocks():
    delta = json.dumps({
        "candidate_id": "C20260705000000000001",
        "node": "L6",
        "path": "D:/research_loop/project/input.csv",
        "values": [f"derived context value {i}" for i in range(20)],
    }, indent=2)
    original = (
        "=== DELTA: L6_oppenheimer ===\n" + delta + "\n\n"
        "=== CONTRACT: L7 | Turing ===\n"
        "OUTPUT: L7_turing -- ['scripts_run', 'key_results', 'warnings', 'failures']\n"
        "```json\n{\n  \"schema_field\": \"must remain formatted\"\n}\n```\n")
    code_block = "```json\n{\n  \"schema_field\": \"must remain formatted\"\n}\n```"
    packed, meta = rl._caveman_lite(original, required_literals=[
        "C20260705000000000001", "L6", "L7", "Turing",
        "D:/research_loop/project/input.csv",
        "OUTPUT: L7_turing -- ['scripts_run', 'key_results', 'warnings', 'failures']",
    ])
    assert meta["compression_applied"] is True, meta
    assert meta["compressed_est_tokens"] < meta["original_est_tokens"], meta
    assert meta["compressed_est_tokens"] <= meta["original_est_tokens"] * 0.90, meta
    assert code_block in packed, packed
    assert "OUTPUT: L7_turing -- ['scripts_run', 'key_results', 'warnings', 'failures']" in packed
    assert '"candidate_id": "C20260705000000000001"' in packed


def test_l7_budget_zero_archives_digest_and_records_manifest_metadata():
    root = _project()
    pr = root / "02_Agent_Notes" / "_pre_research"
    pr.mkdir(parents=True)
    marker = "UNIQUE_L7_DIGEST_MUST_NOT_REACH_RUNTIME_CONTEXT"
    artifact = (
        "# L7 code search\n\n## Runtime digest\n- " + marker +
        " https://example.org/code\n\n## Query log\n- query\n\n"
        "## Tool receipt\n- local search, 1 hit\n\n## Source count\n1\n")
    target = pr / "L7_research.md"
    target.write_text(artifact, encoding="utf-8")
    before = target.read_bytes()

    result = _run("assemble-context", str(root), "C20260705000000000001",
                  "--node", "L7")
    assert result.returncode == 0, result.stderr
    assert marker not in result.stdout
    assert target.read_bytes() == before

    manifest_path = Path(result.stderr.split("context manifest:", 1)[1].strip())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pre = manifest["pre_research"]
    assert pre["archived_only"] is True
    assert pre["digest_present"] is True
    assert pre["digest_tokens_est"] > 0
    assert pre["injected_tokens_est"] == 0
    assert pre["omitted_reason"] == "budget=0 / archived-only"
    assert manifest["caveman_mode"] == "lite"
    assert "original_est_tokens" in manifest
    assert "compressed_est_tokens" in manifest
    assert "compression_applied" in manifest
    assert "required_fields_preserved" in manifest

    delta = root / "l7.json"
    delta.write_text(json.dumps({
        "scripts_run": [], "key_results": {},
        "warnings": ["test fixture"], "failures": [],
    }), encoding="utf-8")
    emitted = _run(
        "emit-delta", str(root), "C20260705000000000001",
        "--node", "L7", "--persona", "Turing", "--file", str(delta),
        "--receipt", str(manifest_path))
    assert emitted.returncode == 0, emitted.stderr
    receipts = list((root / "08_Audit").glob("run_receipt_L7_*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["pre_research"]["archived_only"] is True
    assert receipt["pre_research"]["digest_tokens_est"] > 0
    assert receipt["pre_research"]["omitted_reason"] == (
        "budget=0 / archived-only")


def _run_as_script():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
