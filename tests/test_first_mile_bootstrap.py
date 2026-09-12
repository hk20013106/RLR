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
