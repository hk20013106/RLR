# -*- coding: utf-8 -*-
"""Tests for the RLR Pitfall Ledger (pitfall_ledger.py).

Runs under pytest *or* as a plain script (`python test_pitfall_ledger.py`) so it
works whether or not pytest is installed. Covers the six mandated cases:
  1. JSONL append           4. duplicate deduplication
  2. scan by node           5. UTF-8 pitfall case
  3. hard_stop gate         6. provider-failure draft case
plus a promotion-artifact check.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pitfall_ledger as pl


def _jsonl_lines(d):
    f = pl.ledger_path(d) / pl.JSONL_FILE
    return [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --- 1. JSONL append --------------------------------------------------------

def test_jsonl_append():
    with tempfile.TemporaryDirectory() as d:
        pl.record_pitfall(d, "C1", "L7", "execution_failure",
                          "script crashed", "missing pkg", "install pkg first")
        pl.record_pitfall(d, "C1", "L1", "schema_error",
                          "bad json", "trailing comma", "validate json")
        lines = _jsonl_lines(d)
        assert len(lines) == 2, f"expected 2 appended lines, got {len(lines)}"
        for ln in lines:
            json.loads(ln)  # each line is valid JSON
        assert len(pl.list_pitfalls(d)) == 2


# --- 2. scan by node --------------------------------------------------------

def test_scan_by_node():
    with tempfile.TemporaryDirectory() as d:
        p7 = pl.record_pitfall(d, "C1", "L7", "execution_failure",
                               "crash", "rc7", "rule7")
        p1 = pl.record_pitfall(d, "C1", "L1", "schema_error",
                               "bad", "rc1", "rule1")
        pl.confirm_pitfall(d, p7["id"], "confirmed")
        pl.confirm_pitfall(d, p1["id"], "confirmed")
        l7 = pl.scan_pitfalls(d, node="L7")
        assert len(l7) == 1 and l7[0]["node"] == "L7", l7
        l1 = pl.scan_pitfalls(d, node="L1")
        assert len(l1) == 1 and l1[0]["node"] == "L1", l1
        assert pl.scan_pitfalls(d, node="L4") == []


# --- 3. hard_stop gate ------------------------------------------------------

def test_hard_stop_gate():
    with tempfile.TemporaryDirectory() as d:
        p = pl.record_pitfall(d, "C1", "L0", "dependency",
                              "fatal env", "no GPU", "require GPU",
                              severity="hard_stop")
        # a draft hard_stop must NOT gate (unconfirmed)
        passed, blocking = pl.hard_stop_check(d, node="L0")
        assert passed and not blocking, "draft hard_stop should not block"
        # confirmed hard_stop blocks
        pl.confirm_pitfall(d, p["id"], "confirmed")
        passed, blocking = pl.hard_stop_check(d, node="L0")
        assert not passed and len(blocking) == 1, (passed, blocking)
        # retiring it clears the gate
        pl.confirm_pitfall(d, p["id"], "obsolete")
        passed, blocking = pl.hard_stop_check(d, node="L0")
        assert passed and not blocking, "obsolete hard_stop should not block"


# --- 4. duplicate deduplication ---------------------------------------------

def test_dedup():
    with tempfile.TemporaryDirectory() as d:
        a = pl.record_pitfall(d, "C1", "L7", "execution_failure",
                              "crash v1", "same root cause", "rule")
        b = pl.record_pitfall(d, "C2", "L7", "execution_failure",
                              "crash v2", "same root cause", "rule updated")
        # same node+category+root_cause => deduped to a single record
        assert a["id"] == b["id"], "dedup should return the same id"
        assert len(pl.list_pitfalls(d)) == 1, "ledger must hold one line"
        assert len(_jsonl_lines(d)) == 1
        # a genuinely different root cause is a different pitfall
        pl.record_pitfall(d, "C3", "L7", "execution_failure",
                          "other", "different root cause", "rule")
        assert len(pl.list_pitfalls(d)) == 2


# --- 5. UTF-8 case ----------------------------------------------------------

def test_utf8():
    with tempfile.TemporaryDirectory() as d:
        sym = "脚本崩溃：缺少 R 包 ⇒ 无法继续"
        cause = "依赖未安装（WGCNA）"
        rule = "运行前先 install.packages(\"WGCNA\")"
        pl.record_pitfall(d, "C1", "L7", "execution_failure", sym, cause, rule)
        back = pl.list_pitfalls(d)[0]
        assert back["symptom"] == sym, back["symptom"]
        assert back["root_cause"] == cause
        assert back["prevention_rule"] == rule
        # bytes on disk are real UTF-8, not escaped \uXXXX
        raw = (pl.ledger_path(d) / pl.JSONL_FILE).read_text(encoding="utf-8")
        assert "脚本崩溃" in raw


# --- 6. provider-failure draft case -----------------------------------------

def test_provider_failure_draft():
    with tempfile.TemporaryDirectory() as d:
        p = pl.record_pitfall(d, "C1", "L1", "provider_failure",
                              "headless provider returned non-JSON",
                              "wrapper emitted prose", "",
                              severity="warn", provider="headless",
                              status="draft")
        assert p["status"] == "draft"
        assert p["provider"] == "headless"
        # drafts are invisible to scans/gates until Curie confirms them
        assert pl.scan_pitfalls(d, node="L1") == []
        assert pl.scan_pitfalls(d, node="L1", provider="headless") == []
        # L8 Curie confirms -> now it surfaces, provider-filtered
        pl.confirm_pitfall(d, p["id"], "confirmed", confirmed_by="Curie")
        hit = pl.scan_pitfalls(d, node="L1", provider="headless")
        assert len(hit) == 1 and hit[0]["id"] == p["id"], hit
        # wrong provider filter excludes it
        assert pl.scan_pitfalls(d, node="L1", provider="command") == []


# --- bonus: false_positive is dropped + promotion writes an artifact --------

def test_false_positive_dropped():
    with tempfile.TemporaryDirectory() as d:
        p = pl.record_pitfall(d, "C1", "L7", "execution_failure",
                              "false alarm", "was fine", "none")
        pl.confirm_pitfall(d, p["id"], "false_positive", confirmed_by="Curie")
        assert pl.scan_pitfalls(d, node="L7") == []


def test_promote_regression_test():
    import yaml
    with tempfile.TemporaryDirectory() as d:
        p = pl.record_pitfall(d, "C1", "L7", "execution_failure",
                              "crash", 'root cause with "quotes"', 'prevention with "quotes"')
        pl.confirm_pitfall(d, p["id"], "confirmed")
        pl.promote_pitfall(d, p["id"], "regression_test")
        tests = list((pl.ledger_path(d) / pl.TESTS_DIR).glob("test_*.py"))
        assert tests, "promotion to regression_test must write a stub file"
        rules_path = pl.ledger_path(d) / pl.RULES_FILE
        assert rules_path.exists()
        with open(rules_path, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
        assert len(parsed) == 1
        assert parsed[0]["root_cause"] == 'root cause with "quotes"'
        assert parsed[0]["prevention_rule"] == 'prevention with "quotes"'


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
