"""Repository-root compatibility entry point for the canonical runner."""

import sys
from pathlib import Path


SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from run_loop import main  # noqa: E402


if __name__ == "__main__":
    main()
