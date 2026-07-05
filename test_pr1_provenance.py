# -*- coding: utf-8 -*-
"""PR1: pre-research provenance (query_log / tool_receipt / source_count).

PR1 only PARSES + PERSISTS provenance; it does NOT change gate judgement.
These tests prove:
  1-3. `_parse_pre_research_provenance` extracts the fields (and falls back to
       digest identifiers when `## Source count` is absent).
  4.   assemble-context persists the fields into the context manifest.
  5.   the V0.5 gate is unchanged: a valid digest artifact WITHOUT the new
       sections still assembles (rc=0).
"""
import json
import sys
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RL = str(HERE / "research_loop_v04.py")
sys.path.insert(0, str(HERE))
import research_loop_v04 as rl  # noqa: E402

_DIGEST = ("## Runtime digest\n"
           "- [[09_Literature_Database/smith2020|Smith 2020]] doi:10.1000/abc123 "
           "— finding A.\n"
           "- [[09_Literature_Database/lee2021|Lee 2021]] PMID:12345678 — finding B.\n")
_PROV = ("## Query log\n- convergent evolution heart rate\n"
         "- cardiac co-expression bat (0 results)\n\n"
         "## Tool receipt\n"
         "- tool: pubmed | time: 2026-07-05T10:00:00 | summary: 2 hits\n\n"
         "## Source count\n2\n")


def _run(*args):
    return subprocess.run([sys.executable, RL] + list(args),
                          capture_output=True, text=True, timeout=15,
                          encoding="utf-8", errors="replace")


def _mkproj():
    d = tempfile.mkdtemp(prefix="rlr_pr1_")
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


# 1. full provenance parses
def test_parse_full_provenance():
    p = rl._parse_pre_research_provenance("# L1\n\n" + _DIGEST + "\n" + _PROV)
    assert p["query_log"] == ["convergent evolution heart rate",
                              "cardiac co-expression bat (0 results)"], p
    assert len(p["tool_receipt"]) == 1 and "pubmed" in p["tool_receipt"][0]
    assert p["source_count"] == 2 and p["source_count_declared"] is True


# 2. missing Source count -> fallback to distinct identifiers in digest
def test_source_count_fallback_from_digest():
    p = rl._parse_pre_research_provenance("# L1\n\n" + _DIGEST)
    assert p["source_count_declared"] is False
    assert p["source_count"] == 2, p  # doi + pmid = 2 distinct identifiers


# 3. no sections -> empty / zero, never raises
def test_empty_provenance_no_crash():
    p = rl._parse_pre_research_provenance("# nothing here\n")
    assert p["query_log"] == [] and p["tool_receipt"] == []
    assert p["source_count"] == 0 and p["source_count_declared"] is False


# 4. assemble-context persists provenance into the manifest
def test_manifest_persists_provenance():
    d = _mkproj()
    _write_l1(d, "# L1\n\n" + _DIGEST + "\n" + _PROV)
    r = _run("assemble-context", d, "C1", "--node", "L1")
    assert r.returncode == 0, f"rc={r.returncode} {r.stderr}"
    mpath = r.stderr.split("context manifest: ")[-1].strip()
    m = json.loads(Path(mpath).read_text(encoding="utf-8"))
    pr = m["pre_research"]
    assert pr["source_count"] == 2, pr
    assert pr["query_log"] and pr["tool_receipt"], pr
    assert pr["source_count_declared"] is True


# 5. gate UNCHANGED: valid digest artifact without new sections still passes
def test_gate_unchanged_without_new_sections():
    d = _mkproj()
    _write_l1(d, "# L1\n\n" + _DIGEST)  # no Query log / Tool receipt / Source count
    r = _run("assemble-context", d, "C1", "--node", "L1")
    assert r.returncode == 0, f"PR1 must not change gate: rc={r.returncode} {r.stderr}"


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
