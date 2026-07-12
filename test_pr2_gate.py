# -*- coding: utf-8 -*-
"""PR2: L1/L4 pre-research gate enforces PR1 provenance (fail closed rc=3).

For literature nodes the artifact must carry, on top of the V0.5 checks
(artifact present, non-empty, not NOT YET RUN, `## Runtime digest` with a
DOI/PMID/URL): a non-empty `## Query log`, a non-empty `## Tool receipt`, and an
explicit `## Source count` >= 1.
"""
import sys
import subprocess
import tempfile
from pathlib import Path
from research_loop import deep_research as dr

HERE = Path(__file__).resolve().parent
RL = str(HERE / "research_loop_v04.py")

_DIGEST = ("## Runtime digest\n"
           "- [[09_Literature_Database/smith2020|Smith 2020]] doi:10.1000/abc123 "
           "— finding A.\n")
_QLOG = "## Query log\n- X association Y mechanism\n"
_TREC = "## Tool receipt\n- tool: pubmed | time: 2026-07-05T10:00:00 | summary: 1 hit\n"
_SCOUNT = "## Source count\n1\n"


def _art(*parts):
    return "# L1 deep research\n\n" + "\n".join(parts) + "\n"


def _run(*args):
    return subprocess.run([sys.executable, RL] + list(args),
                          capture_output=True, text=True, timeout=15,
                          encoding="utf-8", errors="replace")


def _mkproj():
    d = tempfile.mkdtemp(prefix="rlr_pr2_")
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


def _assemble_l1(d, artifact):
    return _assemble_node(d, "L1", artifact)


def _assemble_node(d, node, artifact):
    pr = Path(d) / "02_Agent_Notes" / "_pre_research"
    pr.mkdir(parents=True, exist_ok=True)
    (pr / f"{node}_research.md").write_text(artifact, encoding="utf-8")
    extracts = [{"section": "Results", "text": "result", "locator": "Results"},
                {"section": "Discussion", "text": "discussion", "locator": "Discussion"},
                {"section": "Conclusion", "text": "conclusion", "locator": "Conclusion"},
                {"section": "Methods", "text": "method", "locator": "Methods"}]
    payload = {"schema_version": dr.SCHEMA_VERSION, "queries": ["q"],
               "papers": [{"doi": "10.1000/abc123", "title": "Paper", "source_database": "PubMed",
                           "metadata": {}, "source_metadata_response": {"id": "abc123"},
                           "open_access": False, "extracts": extracts}]}
    if node == "L4":
        payload["review_search"] = {"query": "review q", "status": "none_found", "receipt": "PubMed 0"}
    dr.persist_run(d, "C1", node, payload,
                   dr.skill_receipt("codex", ["codex", "exec"], "prompt", "0.1.9"))
    return _run("assemble-context", d, "C1", "--node", node)


def _digest_with_estimated_tokens(tokens, identifier="doi:10.1000/abc123"):
    prefix = f"- Smith 2020 {identifier} finding. "
    body = prefix + ("x" * max(0, tokens * 4 - len(prefix)))
    return f"## Runtime digest\n{body}\n"


def _fail(artifact, needle):
    r = _assemble_l1(_mkproj(), artifact)
    assert r.returncode == 3, f"expected rc=3, got {r.returncode}: {r.stderr}"
    assert needle in r.stderr.lower(), f"want '{needle}' in stderr: {r.stderr}"


# 1. missing Query log
def test_missing_query_log_fails():
    _fail(_art(_DIGEST, _TREC, _SCOUNT), "query log")


# 2. empty Query log (header, no bullets)
def test_empty_query_log_fails():
    _fail(_art(_DIGEST, "## Query log\n(none)\n", _TREC, _SCOUNT), "query log")


# 3. missing Tool receipt
def test_missing_tool_receipt_fails():
    _fail(_art(_DIGEST, _QLOG, _SCOUNT), "tool receipt")


# 4. empty Tool receipt
def test_empty_tool_receipt_fails():
    _fail(_art(_DIGEST, _QLOG, "## Tool receipt\n(none)\n", _SCOUNT), "tool receipt")


# 5. missing Source count even though digest has DOI
def test_missing_source_count_fails():
    _fail(_art(_DIGEST, _QLOG, _TREC), "source count")


# 6. Source count 0
def test_source_count_zero_fails():
    _fail(_art(_DIGEST, _QLOG, _TREC, "## Source count\n0\n"), "< 1")


# 7. valid: all sections present -> passes
def test_valid_full_provenance_passes():
    r = _assemble_l1(_mkproj(), _art(_DIGEST, _QLOG, _TREC, _SCOUNT))
    assert r.returncode == 0, f"expected rc=0, got {r.returncode}: {r.stderr}"


# 8. NOT YET RUN still fails (V0.5 check preserved)
def test_not_yet_run_still_fails():
    _fail("=== PRE-RESEARCH (deep_research): NOT YET RUN ===\n", "not yet run")


def test_l4_digest_near_781_tokens_passes_under_literature_budget():
    artifact = _art(
        _digest_with_estimated_tokens(781), _QLOG, _TREC, _SCOUNT)
    r = _assemble_node(_mkproj(), "L4", artifact)
    assert r.returncode == 0, f"expected rc=0, got {r.returncode}: {r.stderr}"


def test_digest_over_1000_tokens_fails_with_actionable_compression_message():
    artifact = _art(
        _digest_with_estimated_tokens(1001), _QLOG, _TREC, _SCOUNT)
    r = _assemble_node(_mkproj(), "L4", artifact)
    assert r.returncode == 3, f"expected rc=3, got {r.returncode}: {r.stderr}"
    message = r.stderr.lower()
    assert "1001" in message and "1000" in message
    assert "caveman" in message
    assert "provenance-preserving" in message
    for required in ("query log", "tool receipt", "source count", "doi/pmid/url"):
        assert required in message


def test_missing_identifier_still_fails():
    artifact = _art(
        _digest_with_estimated_tokens(20, identifier="no identifier"),
        _QLOG, _TREC, _SCOUNT)
    _fail(artifact, "doi/pmid/url")


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
