"""Thin CLI extension for the L0.5 Europe PMC acquisition runtime."""
from __future__ import annotations

import argparse
import json
import sys

from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.europepmc_runtime import run_europepmc_acquisition


def cmd_l05_acquire_europepmc(args) -> int:
    try:
        result = run_europepmc_acquisition(
            args.project_dir,
            args.cand_id,
            explicit_queries=args.queries or None,
            max_papers=args.max_papers,
            page_size=args.page_size,
            run_id=args.run_id,
            timeout=args.timeout,
        )
    except CurieContractError as exc:
        print(f"ERROR: L0.5 Europe PMC acquisition -- {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def install(cli_module) -> None:
    """Install the Europe PMC command without duplicating canonical parser code."""
    if getattr(cli_module, "_l05_europepmc_cli_installed", False):
        return
    original_build_parser = cli_module.build_parser

    def build_parser():
        parser = original_build_parser()
        subparsers = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        command = subparsers.add_parser(
            "l05-acquire-europepmc",
            help="run one auditable L0.5 Europe PMC acquisition round through FREEZE",
        )
        command.add_argument("project_dir")
        command.add_argument("cand_id")
        command.add_argument(
            "--query", dest="queries", action="append", default=None,
            help="explicit reproducible Europe PMC query (repeatable)",
        )
        command.add_argument("--max-papers", type=int, default=3)
        command.add_argument("--page-size", type=int, default=25)
        command.add_argument("--timeout", type=int, default=20)
        command.add_argument("--run-id", default=None)
        command.set_defaults(func=cmd_l05_acquire_europepmc)
        return parser

    cli_module.build_parser = build_parser
    cli_module._l05_europepmc_cli_installed = True
