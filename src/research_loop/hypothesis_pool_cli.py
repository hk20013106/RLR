"""Thin CLI extension for hypothesis-pool projection and recall."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research_loop.commands.ledger import _ledger_for
from research_loop.hypothesis_ledger import LedgerError
from research_loop.hypothesis_pool import build_pool, search_pool
from research_loop.hypothesis_recall import create_recall, recall_path


_ELIGIBILITY = (
    "ELIGIBLE",
    "ELIGIBLE_WITH_BASIS",
    "REQUIRES_EXPLICIT_OVERRIDE",
    "BLOCKED_FALSIFIED",
)


def _print(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_hypothesis_pool_list(args) -> int:
    ledger = _ledger_for(args.project_dir, args.knowledge_store)
    payload = search_pool(
        ledger,
        as_of=args.as_of,
        eligibility=set(args.eligibility or ()),
        epistemic_status=set(args.epistemic_status or ()),
        workflow_status=set(args.workflow_status or ()),
        limit=args.limit,
    )
    return _print(payload)


def cmd_hypothesis_pool_search(args) -> int:
    ledger = _ledger_for(args.project_dir, args.knowledge_store)
    payload = search_pool(
        ledger,
        text=args.text,
        as_of=args.as_of,
        eligibility=set(args.eligibility or ()),
        epistemic_status=set(args.epistemic_status or ()),
        workflow_status=set(args.workflow_status or ()),
        limit=args.limit,
    )
    return _print(payload)


def cmd_hypothesis_pool_show(args) -> int:
    ledger = _ledger_for(args.project_dir, args.knowledge_store)
    pool = build_pool(ledger, as_of=args.as_of)
    record = next(
        (
            item for item in pool["records"]
            if item["hypothesis_id"] == args.hypothesis_id
        ),
        None,
    )
    if record is None:
        raise LedgerError(f"unknown hypothesis_id: {args.hypothesis_id}")
    return _print({
        "schema_version": pool["schema_version"],
        "store_id": pool["store_id"],
        "as_of_commit_seq": pool["as_of_commit_seq"],
        "record": record,
        "projection_hash": pool["projection_hash"],
    })


def cmd_hypothesis_recall(args) -> int:
    ledger = _ledger_for(args.project_dir, args.knowledge_store)
    artifact = create_recall(
        ledger,
        args.project_dir,
        args.candidate_id,
        args.round_id,
        query_text=args.query,
        limit=args.limit,
        as_of=args.as_of,
    )
    return _print({
        "artifact_path": str(
            recall_path(args.project_dir, args.candidate_id, args.round_id)
        ),
        "artifact": artifact,
    })


def _add_common_pool_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_dir")
    parser.add_argument("--as-of", type=int, default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--eligibility", action="append", choices=_ELIGIBILITY, default=None
    )
    parser.add_argument("--epistemic-status", action="append", default=None)
    parser.add_argument("--workflow-status", action="append", default=None)
    parser.add_argument("--knowledge-store", dest="knowledge_store", default=None)


def install(cli_module) -> None:
    """Install commands without duplicating the canonical parser implementation."""
    if getattr(cli_module, "_hypothesis_pool_cli_installed", False):
        return
    original_build_parser = cli_module.build_parser

    def build_parser():
        parser = original_build_parser()
        subparsers = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        command = subparsers.add_parser(
            "hypothesis-pool-list",
            help="list long-lived hypothesis-pool records",
        )
        _add_common_pool_options(command)
        command.set_defaults(func=cmd_hypothesis_pool_list)

        command = subparsers.add_parser(
            "hypothesis-pool-search",
            help="search long-lived hypothesis-pool records",
        )
        _add_common_pool_options(command)
        command.add_argument("--text", required=True)
        command.set_defaults(func=cmd_hypothesis_pool_search)

        command = subparsers.add_parser(
            "hypothesis-pool-show",
            help="show one long-lived hypothesis-pool record",
        )
        command.add_argument("project_dir")
        command.add_argument("hypothesis_id")
        command.add_argument("--as-of", type=int, default=None)
        command.add_argument("--knowledge-store", dest="knowledge_store", default=None)
        command.set_defaults(func=cmd_hypothesis_pool_show)

        command = subparsers.add_parser(
            "hypothesis-recall",
            help="create an immutable historical hypothesis recall artifact",
        )
        command.add_argument("project_dir")
        command.add_argument("candidate_id")
        command.add_argument("--round-id", required=True)
        command.add_argument("--query", required=True)
        command.add_argument("--limit", type=int, default=50)
        command.add_argument("--as-of", type=int, default=None)
        command.add_argument("--knowledge-store", dest="knowledge_store", default=None)
        command.set_defaults(func=cmd_hypothesis_recall)

        return parser

    cli_module.build_parser = build_parser
    cli_module._hypothesis_pool_cli_installed = True
