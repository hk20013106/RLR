"""Compatibility shim for the retired ``providers.main_agent`` import path.

Configuration parsing moved to :mod:`research_loop.providers.config`. The
historical module remains importable so existing callers do not break, but it
contains no orchestration or provider authority.
"""

from research_loop.providers.config import (  # noqa: F401
    ProviderConfig,
    _mini_yaml,
    _scalar,
    load_config,
)


__all__ = ["_scalar", "_mini_yaml", "load_config", "ProviderConfig"]
