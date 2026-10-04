"""Selected runner configuration must reach ordinary L0.5 semantic admission."""

import json

import pytest

import run_loop


@pytest.mark.parametrize("case", ["missing-settings", "invalid-mode", "invalid-budget"])
def test_runtime_binding_validates_explicit_corpus_at_unique_config_owner(tmp_path, monkeypatch, case):
    from research_loop import deep_research
    from research_loop.l05_curie import europepmc_runtime as owner
    from test_l05_curie_corpus_replay import corpus_host_project
    project, seed, config = corpus_host_project(tmp_path, monkeypatch)
    if case == "missing-settings": config.pop("settings")
    elif case == "invalid-mode": config["worker_mode"] = "unknown"
    else: config["acquisition_budget"] = {"max_acquisition_attempts": True}
    path = deep_research.runtime_config_path(project)
    owner._atomic_json(path, {"backend": "codex", "paperqa2": config})
    raw = path.read_bytes()
    with pytest.raises(deep_research.DeepResearchError): deep_research.load_runtime_spec(project)
    assert path.read_bytes() == raw


def test_legacy_commands_cannot_take_corpus_owner_or_fallback(tmp_path, monkeypatch):
    from research_loop.l05_curie import europepmc_runtime as owner, paperqa2_runtime as worker
    from test_l05_curie_corpus_replay import corpus_host_project
    project, seed, config = corpus_host_project(tmp_path, monkeypatch)
    pending = owner.prepare_acquisition_host_step(project, "C001", run_id="owned-corpus")
    path = project / "01_Candidates/C001.md"; raw = path.read_bytes()
    monkeypatch.setattr(owner, "_prepare_europepmc_acquisition", lambda *_a, **_kw: pytest.fail("legacy discovery took corpus owner"))
    with pytest.raises(owner.CurieContractError, match="corpus"):
        owner.run_paperqa2_europepmc_acquisition(project, "C001", paperqa_runtime=worker.runtime_from_config(config),
            pdf_paths={}, semantic_assessor=lambda **_: {}, run_id="legacy-attempt")
    assert path.read_bytes() == raw


def test_corpus_path_never_calls_retired_scientific_helpers(tmp_path, monkeypatch):
    from research_loop.l05_curie import europepmc_runtime as owner, europepmc, paperqa2_runtime as worker
    from test_l05_curie_corpus_integration import drive
    def retired(*_a, **_kw): pytest.fail("retired per-paper retrieval, alignment or structural coverage")
    for module, name in [(owner, "_europepmc_selector_score"), (owner, "_paperqa2_retrieval_query"),
        (owner, "_coverage_for"), (worker, "align_paperqa2_chunks"), (europepmc, "_parse_target_paragraphs")]:
        monkeypatch.setattr(module, name, retired)
    project, seed, result, calls = drive(tmp_path, monkeypatch, rounds=1)
    assert result["kind"] == "FROZEN" and calls["worker"] == [30]
from research_loop import l05_curie_cli
from research_loop.providers import ProviderConfig


@pytest.mark.parametrize("node_override", [False, True])
def test_selected_config_command_and_timeout_reach_l05_cli(tmp_path, node_override, monkeypatch):
    cfg_path = tmp_path / "selected.json"
    data = {
        "provider": {
            "default": {"type": "command", "command": "default {prompt_file} {output_file}", "timeout": 41},
            "nodes": {"L0.5": {"command": "node {prompt_file} {output_file}", "timeout": 19}}
            if node_override else {},
        },
    }
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    cfg = ProviderConfig.load(cfg_path)
    command = run_loop._l05_command("PROJECT", "C1", cfg)
    expected = "node" if node_override else "default"
    assert command[-4:] == [
        "--semantic-assessor-command", f"{expected} {{prompt_file}} {{output_file}}",
        "--semantic-assessor-timeout", "19" if node_override else "41",
    ]
    seen = {}
    def fake_assessor(command, *, run_dir, timeout):
        seen.update(command=command, assessor_timeout=timeout)
        return lambda **_: {}, "fixture-assessor/v1"

    monkeypatch.setattr(l05_curie_cli, "_semantic_assessor_from_command", fake_assessor)
    monkeypatch.setattr(l05_curie_cli, "run_europepmc_acquisition",
                        lambda *_args, **kwargs: seen.update(kwargs) or {"status": "INSUFFICIENT_STOP"})
    import research_loop_v04 as cli
    args = cli.build_parser().parse_args([*command])
    assert l05_curie_cli.cmd_l05_acquire_europepmc(args) == 0
    assert seen["command"] == f"{expected} {{prompt_file}} {{output_file}}"
    assert seen["assessor_timeout"] == (19 if node_override else 41)
    assert callable(seen["semantic_assessor"])
    assert seen["semantic_assessor_id"] == "fixture-assessor/v1"


def test_missing_assessor_configuration_fails_before_controller(monkeypatch):
    monkeypatch.delenv("RLR_HEADLESS_CMD", raising=False)
    monkeypatch.delenv("RLR_HOST_AGENT_CMD", raising=False)
    cfg = ProviderConfig({"provider": {"default": {"type": "command", "command": ""}}})
    monkeypatch.setattr(run_loop, "_ctl", lambda *_args: pytest.fail("controller must not run"))
    result = run_loop.exec_l05("PROJECT", "C1", {}, cfg, None, "RUN", 1)
    assert result["terminal_status"] == "ERROR"
    assert result["error_category"] == "CONTRACT_ERROR"


def test_headless_environment_command_uses_existing_provider_resolution(monkeypatch):
    monkeypatch.setenv("RLR_HEADLESS_CMD", "headless {prompt_file} {output_file}")
    cfg = ProviderConfig({"provider": {"default": {"type": "headless", "timeout": 25}}})
    command = run_loop._l05_command("PROJECT", "C1", cfg)
    assert command[-4:] == [
        "--semantic-assessor-command", "headless {prompt_file} {output_file}",
        "--semantic-assessor-timeout", "25",
    ]


@pytest.mark.parametrize("template,timeout", [
    ("broken {unknown}", 30),
    ("missing-output {prompt_file}", 30),
    ("valid {prompt_file} {output_file}", -1),
])
def test_direct_cli_invalid_assessor_configuration_stops_before_acquisition(
    monkeypatch, capsys, template, timeout,
):
    monkeypatch.setattr(l05_curie_cli, "run_europepmc_acquisition",
                        lambda *_args, **_kwargs: pytest.fail("invalid assessor reached acquisition"))
    import research_loop_v04 as cli
    args = cli.build_parser().parse_args([
        "l05-acquire-europepmc", "PROJECT", "C1",
        "--semantic-assessor-command", template,
        "--semantic-assessor-timeout", str(timeout),
    ])
    assert l05_curie_cli.cmd_l05_acquire_europepmc(args) == 2
    assert json.loads(capsys.readouterr().out)["error_category"] == "CONTRACT_ERROR"
