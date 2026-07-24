"""Pitfall CLI command family (extracted from engine.py)."""

import json
import sys

import pitfall_ledger as pl


def cmd_record_pitfall(args):
    """Record (or dedup-merge) a pitfall. Defaults to status=draft -- only L8
    Curie promotes a draft to confirmed (pitfall-status)."""
    try:
        pit = pl.record_pitfall(
            args.project_dir, args.cand_id, args.node, args.category,
            args.symptom, args.root_cause, args.prevention_rule,
            severity=args.severity, evidence=args.evidence or "",
            provider=args.provider or "unknown", status=args.status,
            scope=args.scope, error_class=args.error_class)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"recorded pitfall {pit['id']} "
          f"(scope={pit.get('scope', 'project')} node={pit['node']} "
          f"category={pit['category']} severity={pit['severity']} "
          f"status={pit['status']})")
    return 0


def cmd_list_pitfalls(args):
    scope = "global" if getattr(args, "global_", False) else "project"
    rows = pl.list_pitfalls(args.project_dir, status=args.status, node=args.node,
                            category=args.category, severity=args.severity,
                            scope=scope)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("(no pitfalls)")
        return 0
    for p in rows:
        print(f"[{p['id']}] {p['status']:<14} {p['severity']:<9} "
              f"node={p['node']:<6} {p['category']}")
        print(f"    symptom: {p['symptom']}")
        if p.get("prevention_rule"):
            print(f"    prevent: {p['prevention_rule']}")
    return 0


def cmd_pitfall_scan(args):
    """Scan confirmed/promoted pitfalls relevant to a node/category/provider.
    --gate makes it a hard_stop gate (non-zero exit if a hard_stop applies)."""
    if args.gate:
        passed, blocking = pl.hard_stop_check(
            args.project_dir, node=args.node, category=args.category,
            provider=args.provider)
        for r in blocking:
            print(f"BLOCK [{r['id']}] {r['category']}: {r['rule']}",
                  file=sys.stderr)
        if not passed:
            print("PITFALL GATE: STOP", file=sys.stderr)
            return 3
        print("PITFALL GATE: PASS")
        return 0
    rules = pl.scan_pitfalls(args.project_dir, node=args.node,
                             category=args.category, provider=args.provider)
    if args.json:
        print(json.dumps(rules, indent=2, ensure_ascii=False))
        return 0
    if not rules:
        print("(no relevant pitfalls)")
        return 0
    print(pl.format_pitfall_cards(args.project_dir, node=args.node)
          if args.node else
          json.dumps(rules, indent=2, ensure_ascii=False))
    return 0


def cmd_pitfall_status(args):
    """L8 Curie: mark a draft pitfall confirmed / false_positive / obsolete."""
    try:
        pl.confirm_pitfall(args.project_dir, args.id, args.status,
                           confirmed_by=args.by)
    except (ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"pitfall {args.id} -> {args.status} (by {args.by})")
    return 0


def cmd_promote_pitfall(args):
    """Promote a confirmed pitfall into a durable rule (project or global)."""
    try:
        pl.promote_pitfall(args.project_dir, args.id, args.to, scope=args.scope)
    except (ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    target_dir = (pl.global_ledger_path() if args.scope == "global"
                  else pl.ledger_path(args.project_dir))
    print(f"promoted pitfall {args.id} -> {args.to} (scope={args.scope})")
    if args.to == "regression_test":
        print(f"  regression stub written under {target_dir / pl.TESTS_DIR}")
    print(f"  rules file: {target_dir / pl.RULES_FILE}")
    return 0
