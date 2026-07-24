"""Enable opt-in coverage collection in CLI subprocesses.

Integration tests launch the public commands in separate Python processes.
Normal application execution is unchanged because coverage starts only when
the test session explicitly supplies ``COVERAGE_PROCESS_START``.
"""
from __future__ import annotations

import os


if os.environ.get("COVERAGE_PROCESS_START"):
    import coverage

    coverage.process_startup()
