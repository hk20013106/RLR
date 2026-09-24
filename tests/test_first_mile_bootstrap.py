import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from research_loop import l0_preflight
from research_loop.hypothesis_ledger import binding_path
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger
from native_v2_helpers import bootstrap_project_ready


def test_project_ready_receipt_is_v2_and_rejects_missing_receipt(tmp_path):
    assert l0_preflight.PREFLIGHT_RECEIPT_SCHEMA == "L0PreflightReceipt/v2"
    project = tmp_path / "project"
    project.mkdir()
    (project / "00_Project_Index.md").write_text("# project\n", encoding="utf-8")
    target = binding_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}\n", encoding="utf-8")
    result = l0_preflight.validate_project_ready(project)
    assert result["status"] == "FAIL"
    assert result["code"] == "PROJECT_NOT_READY"


def test_native_project_ready_does_not_report_academic_research_as_blocking(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    probe = l0_preflight._academic_research_probe(tmp_path)

    assert probe.component == "research.structured_execution"
    assert probe.code != "L0_RESEARCH_ARS_UNAVAILABLE"


def test_canonical_project_ready_helper_runs_real_preflight(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: helper-test\nkind: project_index\n"
        "created_at: 2026-01-01T00:00:00\n---\n# helper-test\n",
        encoding="utf-8",
    )
    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir()
    candidate.write_text(
        "---\ncandidate_id: C1\nquestion: Q\nclaim: H\n"
        "current_status: NEW\nround_id: 1\nround_type: initial\n---\n",
        encoding="utf-8",
    )
    store = tmp_path / "hypotheses.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    HypothesisLedger(store).bind_project(
        project, profile_id=DEFAULT_NATIVE_PROFILE
    )

    env = bootstrap_project_ready(
        project,
        Path(__file__).resolve().parents[1] / "research_loop_v04.py",
        extra_env={"RLR_HYPOTHESIS_STORE": str(store)},
    )

    receipt = project / "00_Preflight" / "preflight_receipt.json"
    assert receipt.is_file()
    assert env["OBSIDIAN_VAULT"] != str(project)
    ready = l0_preflight.validate_project_ready(
        project, candidate_path=candidate
    )
    assert ready["status"] == "PASS", ready
    front = candidate.read_text(encoding="utf-8")
    assert "project_ready_receipt_path:" in front
    assert "project_ready_receipt_sha256:" in front


def test_catalog_project_without_paperqa2_binding_is_not_project_ready(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: paperqa2-missing\n---\n",
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    store = tmp_path / "hypotheses.sqlite"
    HypothesisLedger(store).bind_project(project, profile_id="v2.1-catalog-1")
    provider_bin = tmp_path / "provider-bin"
    provider_bin.mkdir()
    executable = provider_bin / ("codex.exe" if os.name == "nt" else "codex")
    executable.write_text("test provider sentinel\n", encoding="utf-8")
    if os.name != "nt":
        executable.chmod(0o755)
    env = {
        **os.environ,
        "RLR_HYPOTHESIS_STORE": str(store),
        "OBSIDIAN_VAULT": str(vault),
        "RLR_HOST_BACKEND": "codex",
        "PATH": str(provider_bin) + os.pathsep + os.environ.get("PATH", ""),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "research_loop_v04.py"),
            "preflight",
            str(project),
            "--backend",
            "codex",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )

    assert result.returncode != 0
    output = result.stderr + result.stdout
    assert "PaperQA2 host capability is not bound" in output
    for flag in (
        "--paperqa-python", "--paperqa-bridge", "--paperqa-repo", "--pqa-home",
    ):
        assert flag in output
    assert not (project / "00_Preflight" / "deep_research_runtime.json").exists()
    assert not (project / "00_Preflight" / "preflight_receipt.json").exists()


def test_project_ready_receipt_records_paperqa2_binding_check(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: paperqa2-present\n---\n",
        encoding="utf-8",
    )
    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir()
    candidate.write_text(
        "---\ncandidate_id: C1\nquestion: Q\nclaim: H\n"
        "current_status: NEW\nround_id: 1\nround_type: initial\n---\n",
        encoding="utf-8",
    )
    store = tmp_path / "hypotheses.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    HypothesisLedger(store).bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)

    bootstrap_project_ready(
        project,
        Path(__file__).resolve().parents[1] / "research_loop_v04.py",
        extra_env={"RLR_HYPOTHESIS_STORE": str(store)},
    )

    receipt = json.loads(
        (project / "00_Preflight" / "preflight_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    check = next(
        item
        for item in receipt["formal_runtime_preflight"]["checks"]
        if item["name"] == "paperqa2_binding"
    )
    assert check["status"] == "PASS"


def test_production_first_mile_out_of_process_acceptance(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    entrypoint = (repo_root / "research_loop_v04.py").resolve()
    isolated_cwd = tmp_path / "production-cli-cwd"
    isolated_cwd.mkdir()
    vault = tmp_path / "operator-vault"
    (vault / ".obsidian").mkdir(parents=True)
    store = tmp_path / "operator-hypotheses.sqlite"
    provider_bin = tmp_path / "provider-bin"
    provider_bin.mkdir()
    provider = provider_bin / ("codex.exe" if os.name == "nt" else "codex")
    provider.write_text("test provider sentinel\n", encoding="utf-8")
    if os.name != "nt":
        provider.chmod(0o755)

    inherited_env = dict(os.environ)
    inherited_env["PYTHONPATH"] = str(repo_root / "tests")
    inherited_env["PQA_HOME"] = str(tmp_path / "must-not-configure-paperqa")
    inherited_env["RLR_PAPERQA_PYTHON"] = str(tmp_path / "must-not-configure-paperqa.exe")
    safe_path = [
        entry
        for entry in inherited_env.get("PATH", "").split(os.pathsep)
        if entry and shutil.which("npx", path=entry) is None
    ]
    env = {
        key: value
        for key, value in inherited_env.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PQA_HOME"}
        and not key.upper().startswith("RLR_PAPERQA")
    }
    env.update({
        "PATH": os.pathsep.join([str(provider_bin), *safe_path]),
        "RLR_HYPOTHESIS_STORE": str(store.resolve()),
        "OBSIDIAN_VAULT": str(vault.resolve()),
        "RLR_HOST_BACKEND": "codex",
    })
    assert not any(key.upper() == "PYTHONPATH" for key in env)
    assert not any(
        key.upper() == "PQA_HOME" or key.upper().startswith("RLR_PAPERQA")
        for key in env
    )
    assert shutil.which("npx", path=env["PATH"]) is None

    def run_cli(*arguments):
        return subprocess.run(
            [sys.executable, "-P", str(entrypoint), *map(str, arguments)],
            cwd=isolated_cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )

    def new_project(name, profile="v2.1-catalog-1"):
        result = run_cli(
            "new-project", name, "PaperQA2 first-mile acceptance",
            "--profile", profile,
            "--knowledge-store", store,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return isolated_cwd / name

    missing_project = new_project("missing-paperqa-binding")
    missing = run_cli("preflight", missing_project, "--backend", "codex")
    missing_output = missing.stderr + missing.stdout
    assert missing.returncode != 0
    assert "PaperQA2 host capability is not bound" in missing_output
    for flag in (
        "--paperqa-python", "--paperqa-bridge", "--paperqa-repo", "--pqa-home",
    ):
        assert flag in missing_output
    assert not (missing_project / "00_Preflight" / "deep_research_runtime.json").exists()
    assert not (missing_project / "00_Preflight" / "preflight_receipt.json").exists()

    non_catalog_project = new_project("non-catalog-project", profile="v2.1")
    non_catalog_ready = run_cli(
        "preflight", non_catalog_project, "--backend", "codex",
    )
    assert non_catalog_ready.returncode == 0, (
        non_catalog_ready.stderr or non_catalog_ready.stdout
    )
    non_catalog_receipt = json.loads(
        (non_catalog_project / "00_Preflight" / "preflight_receipt.json")
        .read_text(encoding="utf-8")
    )
    assert non_catalog_receipt["readiness"]["status"] == "PASS"
    assert not any(
        item["name"] == "paperqa2_binding"
        for item in non_catalog_receipt["formal_runtime_preflight"]["checks"]
    )

    capability_root = tmp_path / "paperqa2-capability"
    capability_root.mkdir()
    bridge = capability_root / "bridge.py"
    bridge.write_text("# inert PaperQA2 bridge fixture\n", encoding="utf-8")
    paperqa_repo = capability_root / "paperqa-repo"
    paperqa_repo.mkdir()
    pqa_home = capability_root / "pqa-home"
    pqa_home.mkdir()
    paperqa_flags = (
        "--paperqa-python", sys.executable,
        "--paperqa-bridge", str(bridge.resolve()),
        "--paperqa-repo", str(paperqa_repo.resolve()),
        "--pqa-home", str(pqa_home.resolve()),
    )

    bound_project = new_project("bound-paperqa-project")
    ready = run_cli(
        "preflight", bound_project, "--backend", "codex", *paperqa_flags,
    )
    assert ready.returncode == 0, ready.stderr or ready.stdout
    receipt_path = bound_project / "00_Preflight" / "preflight_receipt.json"
    runtime_path = bound_project / "00_Preflight" / "deep_research_runtime.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["readiness"]["status"] == "PASS", receipt["readiness"]
    binding_check = next(
        item
        for item in receipt["formal_runtime_preflight"]["checks"]
        if item["name"] == "paperqa2_binding"
    )
    assert binding_check["status"] == "PASS", binding_check
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert runtime["paperqa2"] == {
        "python_executable": str(Path(sys.executable).resolve()),
        "bridge_script": str(bridge.resolve()),
        "paperqa_repo": str(paperqa_repo.resolve()),
        "pqa_home": str(pqa_home.resolve()),
    }

    runtime_before_reuse = runtime_path.read_bytes()
    reused = run_cli("preflight", bound_project, "--backend", "codex")
    assert reused.returncode == 0, reused.stderr or reused.stdout
    assert runtime_path.read_bytes() == runtime_before_reuse

    receipt_before_partial = receipt_path.read_bytes()
    partial = run_cli(
        "preflight", bound_project, "--backend", "codex",
        "--paperqa-python", sys.executable,
        "--paperqa-bridge", str(bridge.resolve()),
        "--paperqa-repo", str(paperqa_repo.resolve()),
    )
    partial_output = partial.stderr + partial.stdout
    assert partial.returncode != 0
    assert "Partial PaperQA2 configuration is forbidden" in partial_output
    for flag in (
        "--paperqa-python", "--paperqa-bridge", "--paperqa-repo", "--pqa-home",
    ):
        assert flag in partial_output
    assert runtime_path.read_bytes() == runtime_before_reuse
    assert receipt_path.read_bytes() == receipt_before_partial

    candidate = run_cli(
        "new-candidate", bound_project,
        "--title", "Synthetic first-mile candidate",
        "--question", "Does the production L0 path accept a valid initial input?",
        "--claim", "A production-created initial contract passes the L0 gate.",
        "--input", "Synthetic inline acceptance input",
    )
    assert candidate.returncode == 0, candidate.stderr or candidate.stdout
    candidate_files = list((bound_project / "01_Candidates").glob("C*.md"))
    assert len(candidate_files) == 1
    candidate_id = candidate_files[0].stem
    sidecar = candidate_files[0].with_suffix(".l0_input.yaml")
    assert sidecar.is_file()

    admitted = run_cli(
        "assemble-context", bound_project, candidate_id, "--node", "L0",
    )
    assert admitted.returncode == 0, admitted.stderr or admitted.stdout
