"""Compatibility import for RLR's canonical bounded process engine.

The sole implementation now lives in ``research_loop.providers.executor`` so
maintenance and provider/research callers share identical timeout, output, and
process-tree cleanup semantics.
"""
from research_loop.providers.executor import (
    DEFAULT_MAX_OUTPUT_BYTES,
    BoundedProcessResult,
    run_bounded_process,
)

__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "BoundedProcessResult",
    "run_bounded_process",
]
