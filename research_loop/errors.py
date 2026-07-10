"""Recoverable user-facing error (Phase 1a leaf extraction)."""

class RLRError(Exception):
    """Recoverable, user-facing error: printed cleanly by main(), no traceback."""
