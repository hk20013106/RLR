"""research_loop.providers: provider-neutral agent invocation (Phase 4).

Split out of the historical orchestrator.py. `orchestrator` remains as a
compat shim re-exporting this surface. Providers never import the engine.
"""
from research_loop.providers.executor import (
    DEFAULT_EXECUTOR, ProviderExecutionError, ProviderExecutionResult,
    ProviderExecutor,
)
from research_loop.providers.base import (
    ProviderError, AgentProvider, _schema_repr, _compose_auto_prompt,
    _run_command_agent, run_text_command, RunReceipt, now,
)
from research_loop.providers.config import (
    _scalar, _mini_yaml, load_config, ProviderConfig,
)
from research_loop.providers.manual import ManualProvider
from research_loop.providers.command import CommandProvider
from research_loop.providers.headless import HeadlessProvider


def make_provider(spec, override_type=None):
    """Construct a python provider from a spec dict (optionally forcing a type).
    No silent fallback or second orchestration path."""
    t = override_type or (spec or {}).get("type")
    if t in ("headless", "host", "auto"):
        return HeadlessProvider(spec)
    if t == "command":
        return CommandProvider(spec)
    if t == "manual":
        return ManualProvider(spec)
    if t == "main_agent":
        raise ProviderError(
            "provider type 'main_agent' is retired; configure provider.default "
            "as headless, host, auto, command, or manual"
        )
    if t in (None, "none"):
        raise ProviderError(
            "no automatic provider is configured. Set provider.default.type "
            "to headless/host/auto/command, or explicitly use manual for debug.")
    raise ProviderError(f"unknown provider type: {t!r}")


__all__ = [
    "ProviderError", "AgentProvider", "ProviderConfig", "load_config",
    "ManualProvider", "CommandProvider", "HeadlessProvider", "make_provider",
    "ProviderExecutor", "ProviderExecutionResult", "ProviderExecutionError",
    "DEFAULT_EXECUTOR", "RunReceipt", "now", "run_text_command",
]
