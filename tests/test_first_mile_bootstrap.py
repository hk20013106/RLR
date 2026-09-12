from research_loop import l0_preflight


def test_project_ready_receipt_is_v2_and_rejects_missing_receipt(tmp_path):
    assert l0_preflight.PREFLIGHT_RECEIPT_SCHEMA == "L0PreflightReceipt/v2"
    result = l0_preflight.validate_project_ready(tmp_path)
    assert result["status"] == "FAIL"
    assert result["code"] == "PROJECT_NOT_READY"


def test_native_project_ready_does_not_report_academic_research_as_blocking(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    probe = l0_preflight._academic_research_probe(tmp_path)

    assert probe.component == "research.structured_execution"
    assert probe.code != "L0_RESEARCH_ARS_UNAVAILABLE"
