"""Core runtime engine surface.

This module remains the compatibility aggregation surface while implementation
lives in leaf command modules. Internal helpers that no longer define runtime
contracts are intentionally not re-exported.
"""

# NOTE: the full engine implementation is assembled below by importing the
# extracted leaf modules.  Keep this file's imports aligned with those modules'
# public runtime surface; do not resurrect retired internal authorities merely
# for compatibility.

