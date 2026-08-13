"""Repository-root CLI for one local Meta-RLR maintenance turn."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rlr_maintenance.codex_cli import CodexCli
from rlr_maintenance.host import MetaRLRHost
from rlr_maintenance.loopx_cli import LoopXCli
from rlr_maintenance.verification import run_profile
from rlr_maintenance.workspace import GitWorkspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one local Meta-RLR maintenance turn.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_once = subparsers.add_parser("run-once")
    run_once.add_argument("--event", required=True, type=Path)
    run_once.add_argument("--repo", required=True, type=Path)
    run_once.add_argument("--loopx-project", required=True, type=Path)
    run_once.add_argument("--goal-id", required=True)
    run_once.add_argument("--agent-id", required=True)
    run_once.add_argument("--workspace-parent", required=True, type=Path)
    run_once.add_argument("--registry", type=Path)
    run_once.add_argument("--loopx-executable", default="loopx")
    run_once.add_argument("--codex-executable", default="codex")
    run_once.add_argument("--capability", action="append", dest="capabilities")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event = json.loads(args.event.read_text(encoding="utf-8"))
    loopx = LoopXCli(
        executable=args.loopx_executable,
        registry=str(args.registry) if args.registry else None,
    )
    host = MetaRLRHost(
        loopx=loopx,
        codex=CodexCli(executable=args.codex_executable),
        workspace=GitWorkspace(repo_root=args.repo, workspace_parent=args.workspace_parent),
        verifier=run_profile,
        loopx_cwd=args.loopx_project,
        capabilities=tuple(args.capabilities or ["shell"]),
    )
    result = host.run_once(event=event, goal_id=args.goal_id, agent_id=args.agent_id)
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 3 if result.outcome == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
