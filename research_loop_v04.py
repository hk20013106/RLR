"""Compatibility entry point for the relocated ``src`` implementation."""

import sys
from pathlib import Path


SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

from research_loop.cli import main  # noqa: E402,F401
from research_loop import deep_research_task as _deep_research_task  # noqa: E402
from research_loop import engine as _engine  # noqa: E402
from rlr_maintenance.autowake_adapter import (  # noqa: E402
    install as _install_maintenance_autowake,
    wrap_first_mile_main as _wrap_first_mile_main,
)

# Maintenance remains an outer composition concern. The RLR scientific package
# is unaware of Meta-RLR/LoopX; repository execution attaches optional bridges.
_install_maintenance_autowake(_deep_research_task)
del _install_maintenance_autowake, _deep_research_task


def __getattr__(name):
    return getattr(_engine, name)


if __name__ == "__main__":
    _entry_main = _wrap_first_mile_main(
        main, entrypoint_name="research_loop_v04.py"
    )
    sys.exit(_entry_main())
