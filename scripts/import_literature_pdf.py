#!/usr/bin/env python3
"""Register a legally obtained PDF as a candidate-scoped literature source."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop.user_sources import UserSourceError, register_pdf  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Register a user-supplied PDF. Registration records provenance "
                     "but does not by itself satisfy the L4 evidence gate."),
    )
    parser.add_argument("project_dir")
    parser.add_argument("candidate_id")
    parser.add_argument("--file", required=True, dest="source_file")
    identifiers = parser.add_mutually_exclusive_group()
    identifiers.add_argument("--doi", default="")
    identifiers.add_argument("--pmid", default="")
    identifiers.add_argument("--url", default="")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        record = register_pdf(
            args.project_dir,
            args.candidate_id,
            args.source_file,
            doi=args.doi,
            pmid=args.pmid,
            url=args.url,
        )
    except UserSourceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
