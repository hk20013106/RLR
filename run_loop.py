"""Repository-root compatibility entry point for the canonical runner."""

import importlib.util
import sys
from pathlib import Path


SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_SPEC = importlib.util.spec_from_file_location("research_loop_runner", SRC / "run_loop.py")
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - installation guard
    raise RuntimeError("cannot load canonical runner")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
main = _MODULE.main

from rlr_maintenance.autowake_adapter import (  # noqa: E402
    wrap_first_mile_main as _wrap_first_mile_main,
)


if __name__ == "__main__":
    _entry_main = _wrap_first_mile_main(main, entrypoint_name="run_loop.py")
    sys.exit(_entry_main())
