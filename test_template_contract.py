# -*- coding: utf-8 -*-
"""Tests for v0.4.5 template contract system in research_loop_v04.py.

Verifies 5 mandated cases:
  1. contract mode does NOT include full template body
  2. full mode includes full template body
  3. refs mode emits only refs/hash
  4. no-fs node default is contract
  5. L10c still receives all required deltas
"""
import json
import os
import sys
import subprocess
import tempfile
from pathlib import Path

RL = str(Path(__file__).resolve().parent / "research_loop_v04.py")

def _run(*args):
    # Decode the child's stdout as UTF-8 (it reconfigures its streams to UTF-8);
    # on Windows the default locale codec (GBK) chokes on template em-dashes /
    # curly quotes in --template-mode full.
    return subprocess.run([sys.executable, RL] + list(args),
                          capture_output=True, text=True, timeout=15,
                          encoding="utf-8", errors="replace")


def _make_project():
    d = tempfile.mkdtemp(prefix="rlr_test_")
    idx = Path(d) / "00_Project_Index.md"
    idx.write_text("""---
project_name: TestProject
kind: project_index
created_at: 2026-01-01T00:00:00
---
# TestProject
""", encoding="utf-8")
    cand = Path(d) / "01_Candidates"
    cand.mkdir(parents=True)
    (cand / "C1.md").write_text("""---
candidate_id: C1
title: Test Candidate
question: Does X cause Y?
claim: X causes Y
current_status: NEW
current_owner: Einstein
---
# C1
""", encoding="utf-8")
    # V0.5 gate: L1/L4/L7 assemble-context requires a valid pre-research
    # artifact. Provide fixtures so template-mode tests exercise templates, not
    # the gate. (Gate behaviour itself is covered by test_v05_gate.py.)
    pr = Path(d) / "02_Agent_Notes" / "_pre_research"
    pr.mkdir(parents=True, exist_ok=True)
    (pr / "L1_research.md").write_text(
        "# L1 deep research\n\n## Runtime digest\n"
        "- [[09_Literature_Database/smith2020|Smith 2020]] doi:10.1000/abc123 "
        "— core finding: X associates with Y.\n", encoding="utf-8")
    return d


# --- 1. contract mode does NOT include full template body ---

def test_contract_mode_no_full_body():
    d = _make_project()
    r = _run("assemble-context", d, "C1", "--node", "L1")
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
    output = r.stdout
    # contract mode must not embed full persona or layer template body
    assert "[full]" not in output, "contract mode must not inject [full] template body"
    assert "=== CONTRACT:" in output, "contract mode must include CONTRACT block"
    # contract must have the key elements
    assert "Einstein" in output
    assert "AUTHORITY:" in output
    assert "INPUT SCOPE:" in output


# --- 2. full mode includes full template body ---

def test_full_mode_includes_body():
    d = _make_project()
    r = _run("assemble-context", d, "C1", "--node", "L1", "--template-mode", "full")
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
    output = r.stdout
    assert "[full]" in output, "full mode must inject [full] template body"
    assert "=== CONTRACT:" in output, "full mode must still include CONTRACT"


# --- 3. refs mode emits only refs/hash ---

def test_refs_mode_emits_only_refs_hash():
    d = _make_project()
    # refs mode needs an execution node (L7 is is_execution=True)
    r = _run("assemble-context", d, "C1", "--node", "L7", "--template-mode", "refs")
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
    output = r.stdout
    assert "[refs]" in output, "refs mode must emit [refs] tag"
    assert "sha256:" in output, "refs mode must include sha256 hash"
    assert "[full]" not in output, "refs mode must NOT inject [full] body"


# --- 4. no-fs node default is contract ---

def test_nofs_node_default_is_contract():
    d = _make_project()
    r = _run("assemble-context", d, "C1", "--node", "L2")
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
    output = r.stdout
    assert "=== CONTRACT:" in output, "no-fs node default must be contract"

    # refs mode on a no-fs cognitive node must be rejected
    r2 = _run("assemble-context", d, "C1", "--node", "L2", "--template-mode", "refs")
    assert r2.returncode != 0, "refs mode on no-fs cognitive node must fail"
    assert "no-fs" in r2.stderr, f"expected no-fs rejection in stderr, got: {r2.stderr}"


# --- 5. L10c still receives all required deltas ---

def test_l10c_receives_all_deltas():
    d = _make_project()
    r = _run("assemble-context", d, "C1", "--node", "L10c")
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
    output = r.stdout
    # L10c must be able to receive all deltas (ALL input)
    assert "=== DELTA:" in output or "ALL" in output or "not yet emitted" in output,\
        "L10c should reference delta information"
    # manifest must be visible in stderr
    assert "context manifest:" in r.stderr, f"manifest missing: {r.stderr}"
    manifest_path = r.stderr.split("context manifest: ")[-1].strip()
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert m["template_mode"] == "contract", f"L10c default template_mode should be contract, got {m['template_mode']}"
    assert "contract_hash" in m, "manifest must include contract_hash"
    assert isinstance(m["full_templates_injected"], bool), "full_templates_injected must be boolean"


def test_manifest_includes_structured_contract_hashes():
    d = _make_project()
    r = _run("assemble-context", d, "C1", "--node", "L1")
    assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
    manifest_path = r.stderr.split("context manifest: ")[-1].strip()
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    assert "contract_hashes" in m, "manifest must include contract_hashes"
    hashes = m["contract_hashes"]
    assert hashes["contract"] == m["contract_hash"]
    assert isinstance(hashes["persona_template"], str) and hashes["persona_template"]
    assert isinstance(hashes["layer_template"], str) and hashes["layer_template"]


def test_context_token_budget_fails_closed():
    d = _make_project()
    r = _run("assemble-context", d, "C1", "--node", "L1",
             "--context-token-budget", "20")
    assert r.returncode != 0, "assemble-context must fail closed over budget"
    assert "token budget" in r.stderr.lower(), r.stderr


def test_pre_research_budget_error_fails_closed():
    d = _make_project()
    pr = Path(d) / "02_Agent_Notes" / "_pre_research"
    pr.mkdir(parents=True, exist_ok=True)
    (pr / "L1_research.md").write_text("No digest here.\n" + ("x" * 2000),
                                       encoding="utf-8")

    r = _run("assemble-context", d, "C1", "--node", "L1",
             "--pre-research-token-budget", "1")
    assert r.returncode != 0, "pre-research injection error must fail closed"
    assert "pre-research" in r.stderr.lower(), r.stderr


# --- runner ---

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
