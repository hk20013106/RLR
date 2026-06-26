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
    "error_class": str,    # agent (model/LLM issue) | system (platform/toolchain issue)
    "created_at": str,
    "confirmed_by": str,
    "confirmed_at": str,
    "promoted_to": str,    # preflight_gate | regression_test | template_rule | provider_rule
    "dedup_key": str,      # sha256(node + category + root_cause) for deduplication
}

VALID_SEVERITIES = ["info", "warn", "hard_stop"]
VALID_STATUSES = ["draft", "confirmed", "false_positive", "obsolete", "promoted"]
VALID_ERROR_CLASSES = ["agent", "system"]  # agent=model/LLM issue, system=platform/toolchain issue
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


# --- two-level ledger -------------------------------------------------------
# The ledger is layered: a PROJECT ledger (<project>/10_Pitfall_Ledger/) plus an
# optional GLOBAL ledger shared across every project (~/.rlr/pitfall_ledger/,
# overridable via $RLR_GLOBAL_LEDGER). A pitfall promoted with scope=global
# protects all future projects. Both layers are plain files on disk -- the global
# layer is NOT a replacement for the project truth source, it is an additional
# shared one (so no single global memory becomes the sole source).
GLOBAL_ENV = "RLR_GLOBAL_LEDGER"


def _global_root():
    """Global ledger dir as a Path. NOT created here (reads must not mint it)."""
    env = os.environ.get(GLOBAL_ENV, "").strip()
    return Path(env) if env else (Path.home() / ".rlr" / "pitfall_ledger")


def global_ledger_path():
    """Global ledger dir, created on demand (use for writes)."""
    p = _global_root()
    p.mkdir(parents=True, exist_ok=True)
    (p / TESTS_DIR).mkdir(exist_ok=True)
    return p


def _read_dir(ldir):
    """All pitfall records in a ledger DIRECTORY (skips blank/corrupt lines)."""
    f = Path(ldir) / JSONL_FILE
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_dir(ldir, items):
    ldir = Path(ldir)
    ldir.mkdir(parents=True, exist_ok=True)
    (ldir / TESTS_DIR).mkdir(exist_ok=True)
    with open(ldir / JSONL_FILE, "w", encoding="utf-8") as fh:
        for p in items:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")


def _append_dir(ldir, item):
    ldir = Path(ldir)
    ldir.mkdir(parents=True, exist_ok=True)
    (ldir / TESTS_DIR).mkdir(exist_ok=True)
    with open(ldir / JSONL_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def _scope_read(project_dir, scope):
    """Records for a single scope. 'global' never creates the dir on read."""
    if scope == "global":
        return _read_dir(_global_root())
    return _read_dir(ledger_path(project_dir))


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
                   evidence="", provider="unknown", status="draft",
                   scope="project", error_class="agent"):
    """Append a pitfall to the chosen ledger (project by default, or global).
    Returns the pitfall dict. Dedup is within that ledger."""
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"invalid severity: {severity}")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if scope not in ("project", "global"):
        raise ValueError(f"invalid scope: {scope}")
    if error_class not in VALID_ERROR_CLASSES:
        raise ValueError(f"invalid error_class: {error_class}")

    ldir = global_ledger_path() if scope == "global" else ledger_path(project_dir)
    dk = _dedup_key(node, category, root_cause)
    existing = _read_dir(ldir)
    for ex in existing:
        if ex.get("dedup_key") == dk and ex.get("status") not in ("obsolete", "false_positive"):
            # Duplicate: update the existing one instead of appending
            ex["symptom"] = symptom
            ex["prevention_rule"] = prevention_rule
            ex["severity"] = severity
            ex["evidence"] = evidence
            ex["last_seen"] = _now()
            _write_dir(ldir, existing)
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
        "error_class": error_class,
        "scope": scope,
        "created_at": _now(),
        "confirmed_by": "",
        "confirmed_at": "",
        "promoted_to": "",
        "dedup_key": dk,
    }
    _append_dir(ldir, pitfall)
    return pitfall


def _rewrite_jsonl(project_dir, pitfalls):
    """Back-compat shim: rewrite the PROJECT ledger."""
    _write_dir(ledger_path(project_dir), pitfalls)


def list_pitfalls(project_dir, status=None, node=None, category=None,
                  severity=None, scope="project"):
    """List pitfalls in one scope ('project' default, or 'global'), filtered."""
    results = []
    for p in _scope_read(project_dir, scope):
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


def scan_pitfalls(project_dir, node=None, category=None, provider=None,
                  include_global=True):
    """Scan for active pitfall rules relevant to the current node.

    MERGES the project ledger with the global ledger (project wins on a tie by
    dedup_key), so a globally-promoted pitfall protects every project. Only
    confirmed/promoted pitfalls are returned (drafts stay invisible). Each card
    carries a "source" of 'project' or 'global'.
    """
    rules = []
    seen = set()

    def _consume(records, source):
        for p in records:
            if p.get("status") not in ("confirmed", "promoted"):
                continue
            if node and p.get("node") != node:
                continue
            if category and p.get("category") != category:
                continue
            if provider and p.get("provider") != provider:
                continue
            key = p.get("dedup_key") or p.get("id")
            if key in seen:
                continue
            seen.add(key)
            sev = p.get("severity", "warn")
            rules.append({
                "id": p["id"],
                "prefix": f"[{sev.upper()}]",
                "severity": sev,
                "error_class": p.get("error_class", "agent"),
                "node": p["node"],
                "category": p["category"],
                "rule": p["prevention_rule"],
                "root_cause": p["root_cause"],
                "source": source,
            })

    _consume(_read_dir(ledger_path(project_dir)), "project")
    if include_global:
        _consume(_read_dir(_global_root()), "global")
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
    """L8 Curie: confirm/deny a pitfall. Searches the project ledger first, then
    the global ledger, and updates whichever holds the pitfall."""
    if status not in ("confirmed", "false_positive", "obsolete"):
        raise ValueError(f"invalid confirmation status: {status}")
    for ldir in (ledger_path(project_dir), _global_root()):
        records = _read_dir(ldir)
        for p in records:
            if p["id"] == pitfall_id:
                p["status"] = status
                p["confirmed_by"] = confirmed_by
                p["confirmed_at"] = _now()
                _write_dir(ldir, records)
                return True
    raise KeyError(f"pitfall not found: {pitfall_id}")


def promote_pitfall(project_dir, pitfall_id, promoted_to, scope="project"):
    """Promote a confirmed pitfall to a structural rule.

    promoted_to: preflight_gate | regression_test | template_rule | provider_rule
    scope:       'project' (default) writes the durable rule into the project
                 ledger; 'global' also copies the pitfall into the global ledger
                 (~/.rlr/pitfall_ledger/) so it protects every future project.
    """
    if promoted_to not in VALID_PROMOTIONS:
        raise ValueError(f"invalid promotion: {promoted_to}")
    if scope not in ("project", "global"):
        raise ValueError(f"invalid scope: {scope}")

    # Locate the pitfall in its home ledger (project first, then global).
    home_dir = None
    for ldir in (ledger_path(project_dir), _global_root()):
        records = _read_dir(ldir)
        for p in records:
            if p["id"] == pitfall_id:
                home_dir, home_records, pit = ldir, records, p
                break
        if home_dir is not None:
            break
    if home_dir is None:
        raise KeyError(f"pitfall not found: {pitfall_id}")
    if pit["status"] not in ("confirmed", "promoted"):
        raise ValueError(
            f"pitfall {pitfall_id} status is {pit['status']}; "
            f"must be 'confirmed' before promoting")

    pit["status"] = "promoted"
    pit["promoted_to"] = promoted_to
    _write_dir(home_dir, home_records)

    # Where the durable rule lands. For global scope, copy the record into the
    # global ledger (if not already there) so future projects inherit it.
    target_dir = global_ledger_path() if scope == "global" else ledger_path(project_dir)
    if scope == "global" and Path(home_dir) != Path(target_dir):
        grecords = _read_dir(target_dir)
        if not any(r["id"] == pitfall_id for r in grecords):
            gp = dict(pit)
            gp["scope"] = "global"
            grecords.append(gp)
            _write_dir(target_dir, grecords)

    _write_promoted_rules_dir(target_dir)
    if promoted_to == "regression_test":
        _write_regression_stub_dir(target_dir, pit)
    return True


def _write_regression_stub_dir(ldir, pit):
    """Generate <ledger>/regression_tests/test_<id>.py for a promoted pitfall.
    Skipped-by-default so it never gives false confidence until implemented."""
    pitfall_id = pit["id"]
    slug = re.sub(r"[^A-Za-z0-9_]", "_", pitfall_id)
    tests_dir = Path(ldir) / TESTS_DIR
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / f"test_{slug}.py"
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


def _write_promoted_rules_dir(ldir):
    """Write a ledger's promoted pitfalls to its promoted_rules.yaml."""
    promoted = [p for p in _read_dir(ldir) if p.get("status") == "promoted"]
    lines = ["# Promoted Pitfall Rules (auto-generated; do not edit manually)",
             f"# Generated: {_now()}",
             ""]
    for p in promoted:
        lines.append(f"- id: {p['id']}")
        lines.append(f"  node: {p['node']}")
        lines.append(f"  category: {p['category']}")
        lines.append(f"  severity: {p['severity']}")
        lines.append(f"  promoted_to: {p['promoted_to']}")
        lines.append(f"  scope: {p.get('scope', 'project')}")
        lines.append(f"  root_cause: {json.dumps(p['root_cause'], ensure_ascii=False)}")
        lines.append(f"  prevention_rule: {json.dumps(p['prevention_rule'], ensure_ascii=False)}")
        lines.append("")
    (Path(ldir) / RULES_FILE).write_text("\n".join(lines), encoding="utf-8")


def _write_promoted_rules(project_dir):
    """Back-compat shim: write the PROJECT ledger's promoted_rules.yaml."""
    _write_promoted_rules_dir(ledger_path(project_dir))



def init_ledger(project_dir):
    """Initialize 10_Pitfall_Ledger/ at project creation time.

    Creates the directory structure and an empty pitfalls.jsonl so the ledger
    exists from the start. Also writes a README explaining how pitfalls flow:
    error -> draft (auto) -> confirmed (L8 Curie) -> promoted (structural rule).
    """
    lp = ledger_path(project_dir)
    jsonl = lp / JSONL_FILE
    if not jsonl.exists():
        jsonl.write_text("", encoding="utf-8")
    readme = lp / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Pitfall Ledger\n\n"
            "Records runtime pitfalls (errors, failures, anti-patterns) encountered\n"
            "during RLR runs. Each pitfall has:\n\n"
            "- **error_class**: `agent` (model/LLM issue) or `system` (platform/toolchain)\n"
            "- **severity**: `info` | `warn` | `hard_stop`\n"
            "- **status**: `draft` (auto-recorded) -> `confirmed` (L8 Curie) -> `promoted` (structural rule)\n\n"
            "Lifecycle: error occurs -> auto-recorded as draft -> L8 Curie confirms ->\n"
            "promote to preflight_gate / regression_test / template_rule / provider_rule.\n\n"
            "Confirmed pitfalls are injected into assemble-context for the relevant node,\n"
            "so the agent avoids repeating the same mistake in the next round.\n",
            encoding="utf-8")
    return lp

def format_pitfall_cards(project_dir, node=None):
    """Format pitfall cards for injection into assemble-context.

    Only returns confirmed/promoted pitfalls relevant to the given node.
    Returns a formatted text block, or empty string if no pitfalls.
    """
    rules = scan_pitfalls(project_dir, node=node)
    if not rules:
        return ""

    # Severity-aware formatting: blocking -> full card (capped), relevant -> one-liner,
    # archival -> skipped (manifest only).
    lines = ["=== PITFALL CARDS ==="]
    blocking = [r for r in rules if r.get("severity") == "hard_stop"]
    relevant = [r for r in rules if r.get("severity") != "hard_stop"]

    if blocking:
        lines.append("BLOCKING (must satisfy):")
        for r in blocking[:5]:  # cap at 5
            lines.append(f"  [{r.get('id','?')}] {r.get('severity','')} "
                         f"{r.get('prevention_rule','')[:200]}")
        lines.append("")

    if relevant:
        lines.append("RELEVANT (one-line rules):")
        for r in relevant[:10]:  # cap at 10
            lines.append(f"  [{r.get('id','?')}] {r.get('prevention_rule','')[:150]}")
        lines.append("")

    return "\n".join(lines) + "\n"
    agent_rules = [r for r in rules if r.get("error_class", "agent") == "agent"]
    system_rules = [r for r in rules if r.get("error_class", "agent") == "system"]

    if agent_rules:
        lines.append("--- AGENT pitfalls (model/LLM issues you MUST avoid) ---")
        for r in agent_rules:
            src = r.get("source", "project").upper()
            lines.append(f"{r['prefix']} [{r['id']}] ({src}) Node={r['node']} "
                         f"Category={r['category']}")
            lines.append(f"  Root cause: {r['root_cause']}")
            lines.append(f"  Prevention: {r['rule']}")
            lines.append("")
    if system_rules:
        lines.append("--- SYSTEM pitfalls (platform/toolchain constraints) ---")
        for r in system_rules:
            src = r.get("source", "project").upper()
            lines.append(f"{r['prefix']} [{r['id']}] ({src}) Node={r['node']} "
                         f"Category={r['category']}")
            lines.append(f"  Root cause: {r['root_cause']}")
            lines.append(f"  Prevention: {r['rule']}")
            lines.append("")
    lines.append("=== END PITFALL CARDS ===")
    return "\n".join(lines)
