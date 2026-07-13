"""End-to-end tests for the natural-language L0 intake CLI."""
import os
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from research_loop import l0_contract
from research_loop.providers.command import CommandProvider


ROOT = Path(__file__).resolve().parents[1]
RL = str(ROOT / "research_loop_v04.py")
_ENV = {**os.environ, "PYTHONPATH": str(ROOT)}


def _run(*args):
    return subprocess.run([sys.executable, RL, *args], capture_output=True,
                          text=True, encoding="utf-8", env=_ENV)


def _new_project(tmp_path):
    project = tmp_path / "P"
    result = _run("new-project", str(project), "L0 intake test")
    assert result.returncode == 0, result.stderr
    return project


def _prompt_via_provider(context, run_dir):
    run_dir.mkdir(parents=True, exist_ok=True)
    writer = run_dir / "writer.py"
    writer.write_text(
        "import pathlib,sys; pathlib.Path(sys.argv[2]).write_text('{}')",
        encoding="utf-8")
    command = f"{sys.executable.replace('\\\\', '/')} {writer.as_posix()} {{prompt_file}} {{output_file}}"
    provider = CommandProvider({"command": command})
    provider.run_agent("L0", "Linnaeus", context, run_dir=str(run_dir))
    return Path(provider.last_prompt_file).read_text(encoding="utf-8")


def test_normalize_initial_request_with_local_directory(tmp_path):
    project = _new_project(tmp_path)
    data_dir = project / "data"
    data_dir.mkdir()
    (data_dir / "samples.vcf").write_text("##fileformat=VCFv4.2\n", encoding="utf-8")
    (data_dir / "trees.nwk").write_text("(A,B);\n", encoding="utf-8")
    request = tmp_path / "request.md"
    request.write_text(
        "科学问题：Mogera sp. 是否与 M. imaizumii 存在古老基因渗入？\n"
        "本轮新假说：两者共同祖先之间存在古老基因渗入。\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(data_dir))

    assert result.returncode == 0, result.stderr
    artifacts = list((project / "01_Candidates").glob("*.l0_input.yaml"))
    assert len(artifacts) == 1
    contract = yaml.safe_load(artifacts[0].read_text(encoding="utf-8"))
    candidate_id = contract["candidate_id"]
    assert contract["round_type"] == "initial"
    assert contract["scientific_question"] == "Mogera sp. 是否与 M. imaizumii 存在古老基因渗入？"
    assert contract["source_input"]["input_type"] == "directory"
    assert set(contract["source_input"]["files"]) == {
        str(data_dir / "samples.vcf"), str(data_dir / "trees.nwk")}
    assert contract["provenance"]["parser_mode"] == "rules-v1"
    assert len(contract["provenance"]["data_inventory"]) == 2
    assert l0_contract.validate_l0_input_contract(
        contract, {}, project, candidate_id) == []
    assert "Contract valid: yes" in result.stdout
    assert f"Written to: 01_Candidates/{candidate_id}.l0_input.yaml" in result.stdout


def test_normalize_continuation_uses_verified_memory_and_reaches_l0_prompt(tmp_path):
    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("sample\tvalue\nA\t1\n", encoding="utf-8")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({
        "source_candidate_id": "C_PARENT_0001",
        "next_round_hypothesis": "unused seed hypothesis",
        "required_new_search_directions": ["direction"],
        "previous_hypothesis": "prior hypothesis",
        "previous_final_decision": "REVISE",
        "previous_conclusion": "prior conclusion",
        "round_id": "2", "parent_round_id": "1",
    }), encoding="utf-8")
    request = tmp_path / "continuation.md"
    request.write_text(
        "Scientific question: Does the ancient signal remain after re-analysis?\n"
        "Previous decision: REVISE\n"
        "Previous conclusion: prior conclusion\n"
        "Current hypothesis: Ancient introgression remains after re-analysis.\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(data_file),
                  "--from-memory", str(seed), "--loop-type", "divergent")

    assert result.returncode == 0, result.stderr
    artifact = next((project / "01_Candidates").glob("*.l0_input.yaml"))
    contract = yaml.safe_load(artifact.read_text(encoding="utf-8"))
    assert contract["round_type"] == "continuation"
    assert contract["previous_round"]["candidate_id"] == "C_PARENT_0001"
    assert contract["previous_round"]["memory_hash"] == hashlib.sha256(seed.read_bytes()).hexdigest()
    candidate_id = contract["candidate_id"]
    assembled = _run("assemble-context", str(project), candidate_id, "--node", "L0")
    assert assembled.returncode == 0, assembled.stderr
    for sentinel in ("prior hypothesis", "prior conclusion", "REVISE",
                     "Ancient introgression remains after re-analysis."):
        assert sentinel in assembled.stdout
    assert "prior conclusion" in _prompt_via_provider(assembled.stdout, tmp_path / "prompt")


def test_missing_question_or_missing_local_data_never_writes_contract(tmp_path):
    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("x\n", encoding="utf-8")
    missing_question = tmp_path / "missing-question.md"
    missing_question.write_text("Current hypothesis: A testable hypothesis.\n", encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(missing_question), "--data", str(data_file))
    assert result.returncode == 2
    assert "- scientific_question" in result.stderr
    assert not list((project / "01_Candidates").glob("*.l0_input.yaml"))

    request = tmp_path / "request.md"
    request.write_text("Scientific question: Q?\nCurrent hypothesis: H.\n", encoding="utf-8")
    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(project / "missing"))
    assert result.returncode == 2
    assert "local path not found" in result.stderr
    assert not list((project / "01_Candidates").glob("*.l0_input.yaml"))


def test_dry_run_and_pending_dataset_do_not_write(tmp_path):
    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("x\n", encoding="utf-8")
    request = tmp_path / "request.md"
    request.write_text("Scientific question: Q?\nCurrent hypothesis: H.\n", encoding="utf-8")

    dry_run = _run("normalize-l0-input", "--project", str(project),
                   "--input", str(request), "--data", str(data_file), "--dry-run")
    assert dry_run.returncode == 0, dry_run.stderr
    assert "schema_version: '1.0'" in dry_run.stdout
    assert not list((project / "01_Candidates").glob("*.l0_input.yaml"))

    pending = _run("normalize-l0-input", "--project", str(project),
                   "--input", str(request), "--dataset", "pending")
    assert pending.returncode == 2
    assert "source_input.location" in pending.stderr
    assert not list((project / "01_Candidates").glob("*.l0_input.yaml"))


def test_continuation_missing_seed_fields_is_reported_without_writing(tmp_path):
    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("x\n", encoding="utf-8")
    seed = tmp_path / "incomplete-seed.json"
    seed.write_text(json.dumps({
        "source_candidate_id": "C_PARENT", "next_round_hypothesis": "seed H",
        "required_new_search_directions": [], "previous_hypothesis": "prior H",
        "previous_final_decision": "REVISE", "previous_conclusion": "",
        "round_id": "2", "parent_round_id": "1",
    }), encoding="utf-8")
    request = tmp_path / "continuation.md"
    request.write_text(
        "Scientific question: Q?\nPrevious decision: REVISE\nCurrent hypothesis: H.\n",
        encoding="utf-8")

    result = _run("normalize-l0-input", "--project", str(project),
                  "--input", str(request), "--data", str(data_file),
                  "--from-memory", str(seed), "--loop-type", "divergent")

    assert result.returncode == 2
    assert "Missing required fields:" in result.stderr
    assert "previous_round.conclusion" in result.stderr
    assert not list((project / "01_Candidates").glob("*.l0_input.yaml"))


def test_validator_rejects_missing_continuation_memory_hash(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text("{}", encoding="utf-8")
    contract = l0_contract.build_continuation_contract(
        "C1", "2", "1", "C_PARENT", "Q?",
        l0_contract.build_source_input(input_type="inline", description="data", fmt="text"),
        {"hypothesis": "H0", "final_decision": "REVISE", "conclusion": "C0", "memory_hash": ""},
        "H1")
    errors = l0_contract.validate_l0_input_contract(
        contract, {"from_memory": True, "memory_file": str(seed), "memory_hash": "abc"},
        tmp_path, "C1")
    assert any("previous_round.memory_hash" in error for error in errors), errors


def test_run_l0_invokes_canonical_runner_with_l0_stop(tmp_path):
    from research_loop import engine

    project = _new_project(tmp_path)
    data_file = project / "data.tsv"
    data_file.write_text("x\n", encoding="utf-8")
    request = tmp_path / "request.md"
    request.write_text("Scientific question: Q?\nCurrent hypothesis: H.\n", encoding="utf-8")
    args = SimpleNamespace(project=str(project), input=str(request), data=str(data_file),
                           dataset=None, from_memory=None, loop_type=None,
                           dry_run=False, run_l0=True)

    with patch("research_loop.engine.subprocess.run",
               return_value=SimpleNamespace(returncode=0)) as run:
        assert engine.cmd_normalize_l0_input(args) == 0

    command = run.call_args.args[0]
    assert command[-2:] == ["--stop-after-node", "L0"]
    assert Path(command[1]).name == "run_loop.py"
