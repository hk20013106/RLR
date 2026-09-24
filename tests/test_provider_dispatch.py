"""Phase 4 acceptance: provider dispatch + orchestrator compat-shim parity.

Guards the split of orchestrator.py -> research_loop.providers:
  * make_provider dispatches type -> correct class,
  * retired/no-provider values fail rather than silently falling back,
  * every provider subclasses AgentProvider and exposes run_agent,
  * `import orchestrator as orch` still exposes the full historical surface,
    and those names ARE the research_loop.providers objects (identity).
"""
import json
import sys
from types import SimpleNamespace

import pytest

import orchestrator as orch
import run_loop
import research_loop.providers as providers
from research_loop.providers import config as provider_config
from research_loop.providers import main_agent as retired_main_agent
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


@pytest.mark.parametrize(
    "provider_type", ["main_agent", "headless", "host", "auto", "command", "manual"]
)
def test_run_cli_accepts_canonical_and_retired_provider_vocabulary(provider_type):
    args = run_loop.build_parser().parse_args(
        ["run", "PROJECT", "C1", "--provider", provider_type]
    )
    assert args.provider == provider_type


def test_override_type_forces_class():
    p = orch.make_provider({"type": "command", "command": "x"},
                           override_type="manual")
    assert isinstance(p, orch.ManualProvider)


@pytest.mark.parametrize("spec", [{"type": "none"}, {"type": None}, {},
                                  {"type": "main_agent"}, {"type": "weird"}])
def test_main_agent_and_unknown_have_no_provider(spec):
    """Retired, empty, and unknown types never silently select a provider."""
    with pytest.raises(orch.ProviderError):
        orch.make_provider(spec)


def test_command_provider_requires_command():
    with pytest.raises(orch.ProviderError):
        orch.make_provider({"type": "command"})


def test_provider_config_defaults_to_canonical_automatic_provider():
    cfg = orch.ProviderConfig({})
    assert cfg.mode is None
    assert cfg.for_node("L1") == {"type": "headless"}


def _preflight_command(command, provider_type="command"):
    cfg = orch.ProviderConfig({
        "provider": {
            "default": {"type": provider_type, "command": command},
        },
    })
    return run_loop.preflight_providers(cfg, SimpleNamespace(provider=None))


@pytest.mark.parametrize("provider_type", ["command", "headless"])
def test_preflight_accepts_renderable_provider_command_templates(provider_type):
    command = "agent --prompt={prompt_file:>8} --output={output_file!s}"

    assert _preflight_command(command, provider_type)


def test_preflight_rejects_unknown_command_placeholder_for_node_override(capsys):
    cfg = orch.ProviderConfig({
        "provider": {
            "default": {
                "type": "command",
                "command": "agent {prompt_file} {output_file}",
            },
            "nodes": {
                "L1": {
                    "type": "command",
                    "command": "agent {promt} {output_file}",
                },
            },
        },
    })

    assert not run_loop.preflight_providers(
        cfg, SimpleNamespace(provider=None)
    )
    output = capsys.readouterr().out
    assert "provider.nodes.L1" in output
    assert "invalid command template" in output
    assert "promt" in output


def test_preflight_accepts_escaped_braces_in_command_template():
    command = "agent --literal='{{literal}}' {prompt_file} {output_file}"

    assert _preflight_command(command)


def test_preflight_does_not_parse_shell_syntax_in_command_template():
    command = 'PROMPT={prompt_file} && printf "%s" "{node}" | cat > {output_file}'

    assert _preflight_command(command)


def test_preflight_does_not_launch_provider_subprocess(monkeypatch):
    from research_loop.providers import base as provider_base

    def fail_if_executed(*_args, **_kwargs):
        raise AssertionError("provider subprocess executed during preflight")

    monkeypatch.setattr(provider_base.DEFAULT_EXECUTOR, "run", fail_if_executed)

    assert _preflight_command("agent {prompt_file} {output_file}")


@pytest.mark.parametrize(
    "name", ["_scalar", "_mini_yaml", "load_config", "ProviderConfig"]
)
def test_retired_main_agent_module_is_only_a_config_compatibility_shim(name):
    assert getattr(retired_main_agent, name) is getattr(provider_config, name)


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
