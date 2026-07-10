"""research_loop.providers: provider-neutral agent invocation (Phase 4).

Split out of the historical orchestrator.py. `orchestrator` remains as a
compat shim re-exporting this surface. Providers never import the engine.
"""
from research_loop.providers.base import (
    ProviderError, AgentProvider, _schema_repr, _compose_auto_prompt,
    _run_command_agent, run_text_command, RunReceipt, now,
)
from research_loop.providers.main_agent import (
    _scalar, _mini_yaml, load_config, ProviderConfig,
)
from research_loop.providers.manual import ManualProvider
from research_loop.providers.command import CommandProvider
from research_loop.providers.headless import HeadlessProvider


def make_provider(spec, override_type=None):
    """Construct a python provider from a spec dict (optionally forcing a type).
    No silent default. Note: main-agent mode uses NO python provider -- the host
    agent itself orchestrates; do not call this for it."""
    t = override_type or (spec or {}).get("type")
    if t in ("headless", "host", "auto"):
        return HeadlessProvider(spec)
    if t == "command":
        return CommandProvider(spec)
    if t == "manual":
        return ManualProvider(spec)
    if t in (None, "none"):
        raise ProviderError(
            "no python provider for this mode. main-agent mode is the default "
            "and uses NO python provider (the host agent orchestrates). For "
            "unattended runs set mode=headless + a command; manual is debug-only.")
    raise ProviderError(f"unknown provider type: {t!r}")


__all__ = [
    "ProviderError", "AgentProvider", "ProviderConfig", "load_config",
    "ManualProvider", "CommandProvider", "HeadlessProvider", "make_provider",
    "RunReceipt", "now", "run_text_command",
]
