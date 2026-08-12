import json
from pathlib import Path

from research_loop.l0_preflight import (
    ProbeResult,
    required_pubmed_tools,
    run_preflight_probes,
    write_preflight_receipt,
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "P"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: P\n---\n", encoding="utf-8"
    )
    return project


def _by_component(results):
    return {item.component: item for item in results}


def test_probe_result_serializes_exact_component_contract():
    result = ProbeResult(
        component="research.pubmed_mcp",
        status="FAIL",
        code="L0_RESEARCH_PUBMED_MCP_REQUIRED_TOOL_MISSING",
        detail="missing pubmed_fetch_fulltext",
        consumer="literature discovery/full-text retrieval",
    )
    assert result.to_dict() == {
        "component": "research.pubmed_mcp",
        "status": "FAIL",
        "code": "L0_RESEARCH_PUBMED_MCP_REQUIRED_TOOL_MISSING",
        "detail": "missing pubmed_fetch_fulltext",
        "consumer": "literature discovery/full-text retrieval",
        "enforcement": "blocking",
    }


def test_pubmed_required_tools_match_canonical_transport_capabilities():
    assert required_pubmed_tools() == {
        "pubmed_search_articles",
        "pubmed_fetch_articles",
        "pubmed_fetch_fulltext",
    }


def test_granular_probes_report_individual_failures(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path / "not-a-vault"))
    monkeypatch.delenv("RLR_ZOTERO", raising=False)
    monkeypatch.delenv("RLR_OBSIDIAN", raising=False)
    monkeypatch.delenv("RLR_PUBMED_MCP", raising=False)
    monkeypatch.setattr(
        "research_loop.l0_preflight._academic_research_probe",
        lambda project_dir: ProbeResult(
            "research.academic_research", "FAIL", "L0_RESEARCH_ARS_UNAVAILABLE",
            "runtime unavailable", "L1/L4/L8.5 research reasoning"),
    )
    monkeypatch.setattr(
        "research_loop.l0_preflight._zotero_probe",
        lambda: ProbeResult(
            "research.zotero", "FAIL", "L0_RESEARCH_ZOTERO_UNREACHABLE",
            "local API unavailable", "selected literature/PDF management"),
    )
    monkeypatch.setattr(
        "research_loop.l0_preflight._pubmed_mcp_probe",
        lambda project_dir: ProbeResult(
            "research.pubmed_mcp", "FAIL", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            "stdio server unavailable", "literature discovery/full-text retrieval"),
    )

    results = _by_component(run_preflight_probes(project))

    assert results["research.academic_research"].code == "L0_RESEARCH_ARS_UNAVAILABLE"
    assert results["research.pubmed_mcp"].code == "L0_RESEARCH_PUBMED_MCP_START_FAILED"
    assert results["research.zotero"].code == "L0_RESEARCH_ZOTERO_UNREACHABLE"
    assert results["state.obsidian"].code == "L0_STATE_OBSIDIAN_INVALID_VAULT"
    assert results["state.evidence_store"].component == "state.evidence_store"
    assert results["core.filesystem"].component == "core.filesystem"


def test_obsidian_probe_requires_real_vault_and_writability(tmp_path, monkeypatch):
    project = _project(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    monkeypatch.setattr(
        "research_loop.l0_preflight._academic_research_probe",
        lambda project_dir: ProbeResult("research.academic_research", "PASS", "OK", "", "x"),
    )
    monkeypatch.setattr(
        "research_loop.l0_preflight._zotero_probe",
        lambda: ProbeResult("research.zotero", "PASS", "OK", "", "x"),
    )
    monkeypatch.setattr(
        "research_loop.l0_preflight._pubmed_mcp_probe",
        lambda project_dir: ProbeResult("research.pubmed_mcp", "PASS", "OK", "", "x"),
    )

    bad = _by_component(run_preflight_probes(project))["state.obsidian"]
    assert bad.code == "L0_STATE_OBSIDIAN_INVALID_VAULT"

    (vault / ".obsidian").mkdir()
    good = _by_component(run_preflight_probes(project))["state.obsidian"]
    assert good.status == "PASS"


def test_preflight_receipt_persists_each_component_result(tmp_path):
    project = _project(tmp_path)
    results = [
        ProbeResult("core.filesystem", "PASS", "OK", "project writable", "runtime"),
        ProbeResult("research.zotero", "FAIL", "L0_RESEARCH_ZOTERO_UNREACHABLE",
                    "not running", "reference manager"),
    ]

    path = write_preflight_receipt(project, results)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "L0PreflightReceipt/v1"
    assert payload["overall_status"] == "FAIL"
    assert payload["results"] == [item.to_dict() for item in results]
