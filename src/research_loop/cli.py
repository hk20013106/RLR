"""research_loop.cli — CLI dispatch adapter (Phase 6).

Thin, stable surface over the engine's argparse dispatch. `main(argv)` and
`build_parser()` are the engine's, re-exported here so the compat shim
(`research_loop_v04.py`) and any CLI caller import from a dedicated dispatch
module rather than reaching into the engine body. Splitting the 29 `cmd_*`
handlers physically out of the engine is deferred (strangler-fig); this module
is the seam that makes that later split a drop-in.
"""
from research_loop.engine import build_parser, main

__all__ = ["build_parser", "main"]
