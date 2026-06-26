# -*- coding: utf-8 -*-
"""Pitfall Ledger — record, scan, confirm, and promote runtime pitfalls.

Standalone module; imported by research_loop_v04.py and testable alone.
Does NOT modify DAG, delta schema, context isolation, RunReceipt, or StopPolicy.
"""
import json
import os
import re
import datetime as _dt
import hashlib
from pathlib import Path

# --- schema ------------------------------------------------------------------

PITFALL_FIELDS = {
    "id": str,
    "project_dir": str,
    "cand_id": str,
    "node": str,
    "category": str,
    "symptom": str,
    "root_cause": str,
    "prevention_rule": str,
    "severity": str,       # info | warn | hard_stop
    "status": str,         # draft | confirmed | false_positive | obsolete | promoted
    "evidence": str,       # path to file/log/trace
    "provider": str,       # which provider/agent encountered it
    "created_at": str,
    "confirmed_by": str,
    "confirmed_at": str,
    "promoted_to": str,    # preflight_gate | regression_test | template_rule | provider_rule
    "dedup_key": str,      # sha256(node + category + root_cause) for deduplication
}

VALID_SEVERITIES = ["info", "warn", "hard_stop"]
VALID_STATUSES = ["draft", "confirmed", "false_positive", "obsolete", "promoted"]
VALID_PROMOTIONS = ["preflight_gate", "regression_test", "template_rule", "provider_rule"]

LEDGER_DIR = "10_Pitfall_Ledger"
JSONL_FILE = "pitfalls.jsonl"
RULES_FILE = "promoted_rules.yaml"
TESTS_DIR = "regression_tests"


def ledger_path(project_dir):
    p = Path(project_dir) / LEDGER_DIR
    p.mkdir(parents=True, exist_ok=True)
    (p / TESTS_DIR).mkdir(exist_ok=True)
    return p


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def _dedup_key(node, category, root_cause):
    raw = f"{node}|{category}|{root_cause}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _gen_id():
    return "P" + _dt.datetime.now().strftime("%Y%m%d%H%M%S") + hashlib.sha256(
        os.urandom(4)).hexdigest()[:4]


def record_pitfall(project_dir, cand_id, node, category, symptom,
                   root_cause, prevention_rule, severity="warn",
                   evidence="", provider="unknown", status="draft"):
    """Append a pitfall to the JSONL ledger. Returns the pitfall dict."""
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"invalid severity: {severity}")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")

    dk = _dedup_key(node, category, root_cause)
    existing = list_pitfalls(project_dir)
    for ex in existing:
        if ex.get("dedup_key") == dk and ex.get("status") not in ("obsolete", "false_positive"):
            # Duplicate: update the existing one instead of appending
            ex["symptom"] = symptom
            ex["prevention_rule"] = prevention_rule
            ex["severity"] = severity
            ex["evidence"] = evidence
            ex["last_seen"] = _now()
            _rewrite_jsonl(project_dir, existing)
            return ex

    pitfall = {
        "id": _gen_id(),
        "project_dir": str(project_dir),
        "cand_id": cand_id or "",
        "node": node,
        "category": category,
        "symptom": symptom,
        "root_cause": root_cause,
        "prevention_rule": prevention_rule,
        "severity": severity,
        "status": status,
        "evidence": evidence,
        "provider": provider,
        "created_at": _now(),
        "confirmed_by": "",
        "confirmed_at": "",
        "promoted_to": "",
        "dedup_key": dk,
    }
    lp = ledger_path(project_dir) / JSONL_FILE
    with open(lp, "a", encoding="utf-8") as f:
        f.write(json.dumps(pitfall, ensure_ascii=False) + "\n")
    return pitfall


def _rewrite_jsonl(project_dir, pitfalls):
    lp = ledger_path(project_dir) / JSONL_FILE
    with open(lp, "w", encoding="utf-8") as f:
        for p in pitfalls:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def list_pitfalls(project_dir, status=None, node=None, category=None,
                  severity=None):
    """List pitfalls, optionally filtered."""
    lp = ledger_path(project_dir) / JSONL_FILE
    if not lp.exists():
        return []
    results = []
    with open(lp, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            if status and p.get("status") != status:
                continue
            if node and p.get("node") != node:
                continue
            if category and p.get("category") != category:
                continue
            if severity and p.get("severity") != severity:
                continue
            results.append(p)
    return results


def scan_pitfalls(project_dir, node=None, category=None, provider=None):
    """Scan for active pitfall rules relevant to the current node.

    Only returns confirmed/promoted pitfalls (not draft).
    Filters by node, category, and provider if provided.
    Returns list of prevention_rule strings (with severity prefix).
    """
    rules = []
    for p in list_pitfalls(project_dir):
        if p.get("status") not in ("confirmed", "promoted"):
            continue
        if node and p.get("node") != node:
            continue
        if category and p.get("category") != category:
            continue
        if provider and p.get("provider") != provider:
            continue
        sev = p.get("severity", "warn")
        prefix = f"[{sev.upper()}]"
        rules.append({
            "id": p["id"],
            "prefix": prefix,
            "severity": sev,
            "node": p["node"],
            "category": p["category"],
            "rule": p["prevention_rule"],
            "root_cause": p["root_cause"],
        })
    return rules


def hard_stop_check(project_dir, node=None, category=None, provider=None):
    """Check if any hard_stop confirmed/promoted pitfall applies.

    Returns (passed: bool, blocking_rules: list).
    """
    blocking = []
    for r in scan_pitfalls(project_dir, node=node, category=category, provider=provider):
        if r["severity"] == "hard_stop":
            blocking.append(r)
    return (len(blocking) == 0, blocking)


def confirm_pitfall(project_dir, pitfall_id, status, confirmed_by="Curie"):
    """L8 Curie: confirm/deny a draft pitfall."""
    if status not in ("confirmed", "false_positive", "obsolete"):
        raise ValueError(f"invalid confirmation status: {status}")
    pitfalls = list_pitfalls(project_dir)
    found = False
    for p in pitfalls:
        if p["id"] == pitfall_id:
            p["status"] = status
            p["confirmed_by"] = confirmed_by
            p["confirmed_at"] = _now()
            found = True
            break
    if not found:
        raise KeyError(f"pitfall not found: {pitfall_id}")
    _rewrite_jsonl(project_dir, pitfalls)
    return found


def promote_pitfall(project_dir, pitfall_id, promoted_to):
    """Promote a confirmed pitfall to a structural rule.

    promoted_to: preflight_gate | regression_test | template_rule | provider_rule
    """
    if promoted_to not in VALID_PROMOTIONS:
        raise ValueError(f"invalid promotion: {promoted_to}")
    pitfalls = list_pitfalls(project_dir)
    found = False
    for p in pitfalls:
        if p["id"] == pitfall_id:
            if p["status"] != "confirmed":
                raise ValueError(
                    f"pitfall {pitfall_id} status is {p['status']}; "
                    f"must be 'confirmed' before promoting")
            p["status"] = "promoted"
            p["promoted_to"] = promoted_to
            found = True
            break
    if not found:
        raise KeyError(f"pitfall not found: {pitfall_id}")
    _rewrite_jsonl(project_dir, pitfalls)
    # Also write to promoted_rules.yaml
    _write_promoted_rules(project_dir)
    # regression_test promotion produces a concrete artifact: a pytest stub the
    # human fills in so this exact pitfall gets a guarding test.
    if promoted_to == "regression_test":
        _write_regression_stub(project_dir, pitfall_id)
    return found


def _write_regression_stub(project_dir, pitfall_id):
    """Generate regression_tests/test_<id>.py for a promoted pitfall.
    Skipped-by-default so it never gives false confidence until implemented."""
    pit = next((p for p in list_pitfalls(project_dir)
                if p["id"] == pitfall_id), None)
    if pit is None:
        raise KeyError(f"pitfall not found: {pitfall_id}")
    slug = re.sub(r"[^A-Za-z0-9_]", "_", pitfall_id)
    test_file = ledger_path(project_dir) / TESTS_DIR / f"test_{slug}.py"
    if test_file.exists():
        return str(test_file)
    body = (
        f"# Auto-generated RLR regression test for pitfall {pitfall_id}\n"
        f"# Node: {pit['node']}  Category: {pit['category']}  "
        f"Severity: {pit['severity']}\n"
        f"# Symptom:    {pit['symptom'][:200]}\n"
        f"# Root cause: {pit['root_cause'][:200]}\n"
        f"# Prevention: {pit['prevention_rule'][:200]}\n#\n"
        f"# TODO: replace the skip with a real assertion that reproduces the\n"
        f"# conditions of {pitfall_id} and proves the prevention_rule holds.\n"
        f"import pytest\n\n\n"
        f'@pytest.mark.skip(reason="TODO: implement regression check for '
        f'{pitfall_id}")\n'
        f"def test_regression_{slug}():\n"
        f"    assert True\n"
    )
    test_file.write_text(body, encoding="utf-8")
    return str(test_file)


def _write_promoted_rules(project_dir):
    """Write promoted pitfalls to promoted_rules.yaml (human-readable YAML)."""
    lp = ledger_path(project_dir) / RULES_FILE
    promoted = list_pitfalls(project_dir, status="promoted")
    lines = ["# Promoted Pitfall Rules (auto-generated; do not edit manually)",
             f"# Generated: {_now()}",
             ""]
    for p in promoted:
        lines.append(f"- id: {p['id']}")
        lines.append(f"  node: {p['node']}")
        lines.append(f"  category: {p['category']}")
        lines.append(f"  severity: {p['severity']}")
        lines.append(f"  promoted_to: {p['promoted_to']}")
        lines.append(f"  root_cause: {json.dumps(p['root_cause'], ensure_ascii=False)}")
        lines.append(f"  prevention_rule: {json.dumps(p['prevention_rule'], ensure_ascii=False)}")
        lines.append("")
    lp.write_text("\n".join(lines), encoding="utf-8")


def format_pitfall_cards(project_dir, node=None):
    """Format pitfall cards for injection into assemble-context.

    Only returns confirmed/promoted pitfalls relevant to the given node.
    Returns a formatted text block, or empty string if no pitfalls.
    """
    rules = scan_pitfalls(project_dir, node=node)
    if not rules:
        return ""
    lines = ["=== PITFALL CARDS (relevant to this node) ===",
             "The following pitfalls were encountered in prior runs and are now confirmed.",
             "Follow each prevention rule. severity=hard_stop rules MUST be satisfied.",
             ""]
    for r in rules:
        lines.append(f"{r['prefix']} [{r['id']}] Node={r['node']} Category={r['category']}")
        lines.append(f"  Root cause: {r['root_cause']}")
        lines.append(f"  Prevention: {r['rule']}")
        lines.append("")
    lines.append("=== END PITFALL CARDS ===")
    return "\n".join(lines)
