"""Phase 4 acceptance: provider dispatch + orchestrator compat-shim parity.

Guards the split of orchestrator.py -> research_loop.providers:
  * make_provider dispatches type -> correct class,
  * main-agent mode has NO python provider (type none/None raises; Rev-2 C1),
  * every provider subclasses AgentProvider and exposes run_agent,
  * `import orchestrator as orch` still exposes the full historical surface,
    and those names ARE the research_loop.providers objects (identity).
"""
import json
import sys

import pytest

import orchestrator as orch
import research_loop.providers as providers
from research_loop.l05_curie_cli import _semantic_assessor_from_command


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


def test_l05_semantic_assessor_command_adapter_executes_json_contract(tmp_path):
    script = tmp_path / "semantic_agent.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "prompt = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "assert 'ResearchSeed target' in prompt\n"
        "payload = {\n"
        "    'entailment': 'SUPPORTED',\n"
        "    'scope_match': True,\n"
        "    'context_preserved': True,\n"
        "    'qualification_preserved': True,\n"
        "    'reason': 'directly relevant',\n"
        "}\n"
        "pathlib.Path(sys.argv[2]).write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        f'"{sys.executable}" "{script}" '
        '"{prompt_file}" "{output_file}"'
    )
    assessor, assessor_id = _semantic_assessor_from_command(
        command,
        run_dir=tmp_path / "semantic-run",
        timeout=30,
    )

    result = assessor(
        extract={"evidence_id": "E1", "text": "located source paragraph"},
        claim="ResearchSeed target",
    )

    assert result == {
        "entailment": "SUPPORTED",
        "scope_match": True,
        "context_preserved": True,
        "qualification_preserved": True,
        "reason": "directly relevant",
    }
    assert assessor_id.startswith("l05-semantic-command-sha256/")
    run_dir = tmp_path / "semantic-run" / "assessment_0001"
    assert (run_dir / "L0.5_SemanticVerifier_prompt.txt").is_file()
    assert (run_dir / "L0.5_SemanticVerifier_delta.json").is_file()
