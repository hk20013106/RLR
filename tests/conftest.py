"""Test-only import boundary for the relocated Research Loop source tree."""

import sys
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
