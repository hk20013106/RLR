import json
import os
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
    assert "PaperQA2" in result.stderr + result.stdout
    receipt = json.loads(
        (project / "00_Preflight" / "preflight_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["readiness"]["status"] != "PASS"
    assert receipt["readiness"]["code"] == "PROJECT_NOT_READY"


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
