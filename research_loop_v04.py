"""research_loop_v04.py — COMPAT SHIM (Phase 6).

The engine body moved to `research_loop/engine.py`; CLI dispatch is
`research_loop/cli.py`. This shim preserves the historical entry points
byte-for-byte:

  * `python research_loop_v04.py <cmd>` still runs the full CLI (delegates to
    research_loop.cli:main).
  * `import research_loop_v04 as rl` still exposes the ENTIRE engine surface —
    public names AND the `_private` helpers run_loop/tests reach for
    (`rl._candidate_file`, `rl.DELTA_SCHEMAS`, `rl.NODE_MAP`, …) — via PEP 562
    module `__getattr__`, which delegates every attribute lookup to the engine
    module. No name enumeration, so nothing can drift out of sync.

New code should import `research_loop.engine` / `research_loop.cli` / the typed
`research_loop.api.EngineAPI` directly; this shim exists only for backward compat.
"""
import sys

from research_loop.cli import main  # noqa: F401  (re-export: python …_v04.py <cmd>)
from research_loop import engine as _engine


def __getattr__(name):
    # PEP 562: called only for attributes not defined on this shim module, so
    # every `rl.<name>` (public or _private) resolves to the engine body.
    return getattr(_engine, name)


if __name__ == "__main__":
    sys.exit(main())
