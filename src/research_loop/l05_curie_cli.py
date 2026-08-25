"""Thin CLI extension for the L0.5 Europe PMC acquisition runtime."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.europepmc_runtime import (
    run_europepmc_acquisition,
    run_paperqa2_europepmc_acquisition,
)
from research_loop.l05_curie.paperqa2_runtime import (
    PaperQA2CurieRuntime,
    PaperQA2SubprocessBackend,
)


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


def _load_pdf_paths(path: str) -> dict[str, str]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CurieContractError(f"PaperQA2 PDF map is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CurieContractError(f"PaperQA2 PDF map is not JSON: {exc}") from exc
    if not isinstance(value, dict) or not value:
        raise CurieContractError("PaperQA2 PDF map must be a non-empty object")
    paths = {}
    for paper_id, pdf_path in value.items():
        if not str(paper_id).strip() or not isinstance(pdf_path, str) or not pdf_path.strip():
            raise CurieContractError(
                "PaperQA2 PDF map keys and values must be non-empty strings"
            )
        paths[str(paper_id)] = pdf_path
    return paths


def cmd_l05_acquire_paperqa2_europepmc(args) -> int:
    try:
        backend = PaperQA2SubprocessBackend(
            python_executable=args.paperqa_python,
            bridge_script=args.paperqa_bridge,
            paperqa_repo=args.paperqa_repo,
            pqa_home=args.pqa_home,
            timeout_seconds=args.paperqa_timeout,
        )
        runtime = PaperQA2CurieRuntime(
            backend=backend,
            backend_id=backend.backend_id,
        )
        result = run_paperqa2_europepmc_acquisition(
            args.project_dir,
            args.cand_id,
            paperqa_runtime=runtime,
            pdf_paths=_load_pdf_paths(args.pdf_map),
            explicit_queries=args.queries or None,
            max_papers=args.max_papers,
            page_size=args.page_size,
            run_id=args.run_id,
            timeout=args.timeout,
        )
    except CurieContractError as exc:
        print(f"ERROR: L0.5 PaperQA2 Europe PMC acquisition -- {exc}", file=sys.stderr)
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

        paperqa = subparsers.add_parser(
            "l05-acquire-paperqa2-europepmc",
            help="run pinned PaperQA2 retrieval through Europe PMC verification into L1 v1",
        )
        paperqa.add_argument("project_dir")
        paperqa.add_argument("cand_id")
        paperqa.add_argument("--paperqa-python", required=True)
        paperqa.add_argument("--paperqa-bridge", required=True)
        paperqa.add_argument("--paperqa-repo", required=True)
        paperqa.add_argument("--pqa-home", required=True)
        paperqa.add_argument("--pdf-map", required=True)
        paperqa.add_argument(
            "--query", dest="queries", action="append", default=None,
            help="explicit reproducible Europe PMC query (repeatable)",
        )
        paperqa.add_argument("--max-papers", type=int, default=3)
        paperqa.add_argument("--page-size", type=int, default=25)
        paperqa.add_argument("--timeout", type=int, default=20)
        paperqa.add_argument("--paperqa-timeout", type=int, default=300)
        paperqa.add_argument("--run-id", default=None)
        paperqa.set_defaults(func=cmd_l05_acquire_paperqa2_europepmc)
        return parser

    cli_module.build_parser = build_parser
    cli_module._l05_europepmc_cli_installed = True
