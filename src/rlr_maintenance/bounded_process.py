"""Compatibility surface over RLR's shared process mechanics."""
from research_loop.process_runner import (
    DEFAULT_MAX_OUTPUT_BYTES,
    ProcessResult as BoundedProcessResult,
    ProcessRunner,
    run_bounded_process,
)

__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "BoundedProcessResult",
    "ProcessRunner",
    "run_bounded_process",
]
