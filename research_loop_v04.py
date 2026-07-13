"""Compatibility entry point for the relocated ``src`` implementation."""

import sys
from pathlib import Path


SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

from research_loop.cli import main  # noqa: E402,F401
from research_loop import engine as _engine  # noqa: E402


def __getattr__(name):
    return getattr(_engine, name)


if __name__ == "__main__":
    sys.exit(main())
