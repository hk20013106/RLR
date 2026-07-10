"""Phase 4 acceptance: provider dispatch + orchestrator compat-shim parity.

Guards the split of orchestrator.py -> research_loop.providers:
  * make_provider dispatches type -> correct class,
  * main-agent mode has NO python provider (type none/None raises; Rev-2 C1),
  * every provider subclasses AgentProvider and exposes run_agent,
  * `import orchestrator as orch` still exposes the full historical surface,
    and those names ARE the research_loop.providers objects (identity).
"""
import pytest

import orchestrator as orch
import research_loop.providers as providers


COMPAT_SURFACE = [
    "ProviderError", "AgentProvider", "ProviderConfig", "load_config",
    "ManualProvider", "CommandProvider", "HeadlessProvider", "make_provider",
    "RunReceipt", "now", "run_text_command",
]


@pytest.mark.parametrize("name", COMPAT_SURFACE)
def test_orchestrator_shim_reexports_providers(name):
    assert hasattr(orch, name), f"orchestrator lost {name}"
    assert getattr(orch, name) is getattr(providers, name), f"{name} identity drift"


def test_make_provider_manual():
    p = orch.make_provider({"type": "manual"})
    assert isinstance(p, orch.ManualProvider)
    assert isinstance(p, orch.AgentProvider)
    assert hasattr(p, "run_agent")


def test_make_provider_command():
    p = orch.make_provider({"type": "command",
                            "command": "run {prompt_file} {output_file}"})
    assert isinstance(p, orch.CommandProvider)
    assert isinstance(p, orch.AgentProvider)


def test_make_provider_headless_aliases():
    for t in ("headless", "host", "auto"):
        p = orch.make_provider({"type": t,
                                "command": "cli {prompt_file} {output_file}"})
        assert isinstance(p, orch.HeadlessProvider), t


def test_override_type_forces_class():
    p = orch.make_provider({"type": "command", "command": "x"},
                           override_type="manual")
    assert isinstance(p, orch.ManualProvider)


@pytest.mark.parametrize("spec", [{"type": "none"}, {"type": None}, {},
                                  {"type": "weird"}])
def test_main_agent_and_unknown_have_no_provider(spec):
    """type none/None (main-agent default) and unknown types must raise, never
    silently fall back to a provider (Rev-2 C1: host agent IS the orchestrator)."""
    with pytest.raises(orch.ProviderError):
        orch.make_provider(spec)


def test_command_provider_requires_command():
    with pytest.raises(orch.ProviderError):
        orch.make_provider({"type": "command"})


def test_provider_config_defaults_to_main_agent():
    cfg = orch.ProviderConfig({})
    assert cfg.mode == "main_agent"
    assert cfg.for_node("L1") == {"type": "none"}
