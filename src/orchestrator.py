"""RLR orchestration layer — COMPAT SHIM (Phase 4).

The provider implementations moved to research_loop/providers/. This module
re-exports the full historical top-level surface so `import orchestrator as
orch` keeps working byte-for-byte. New code should import
research_loop.providers directly.
"""
from research_loop.providers import (  # noqa: F401  (re-export shim)
    ProviderError, _scalar, _mini_yaml, load_config, ProviderConfig,
    AgentProvider, _schema_repr, _compose_auto_prompt, ManualProvider,
    _run_command_agent, run_text_command, CommandProvider, HeadlessProvider,
    make_provider, RunReceipt, now,
)
