import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop import deep_research as dr
from research_loop.user_sources import register_pdf


def _candidate(project: Path, candidate_id: str = "C1") -> None:
    (project / "01_Candidates").mkdir(parents=True, exist_ok=True)
    (project / "01_Candidates" / f"{candidate_id}.md").write_text(
        f"---\ncandidate_id: {candidate_id}\ncurrent_status: IDEA_SELECTED\n---\n",
        encoding="utf-8",
    )


def _source_text(extract: str) -> str:
    return ("<article><section><h2>Methods</h2><p>" + extract + "</p>" +
            "<p>Detailed reproducible procedure and parameter rationale. " * 20 +
            "</p></section></article>")


def _payload(*, source_kind="official_documentation", status="eligible"):
    extract = "Fit the linear model with a species by region interaction and control false discovery rate."
    return {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["limma interaction model heart transcriptome"],
        "method_components": [{
            "component_id": "differential_expression",
            "name": "Differential-expression model",
            "required": True,
            "rationale": "Tests species and region effects.",
        }],
        "method_candidates": [{
            "method_id": "limma_voom",
            "component_id": "differential_expression",
            "name": "limma-voom",
            "status": status,
            "purpose": "Estimate species, region, and interaction effects.",
            "applicable_to": ["continuous expression matrix"],
            "implementation_steps": ["build design matrix", "fit contrasts", "adjust P values"],
            "assumptions": ["independent biological replicates"],
            "expected_outputs": ["effect sizes", "adjusted P values"],
            "strengths": ["supports complex contrasts"],
            "limitations": ["requires valid mean-variance modelling"],
            "alternatives": ["mixed-effects model"],
            "rejection_reasons": [],
            "method_anchor_ids": ["A1"] if status == "eligible" else [],
            "missing_source": "" if status == "eligible" else "Provide the paywalled protocol PDF.",
        }],
        "papers": [{
            "doi": "10.1000/method", "pmid": "", "url": "https://example.org/method",
            "title": "Method guide", "source_database": "official",
            "metadata": {"year": 2026, "journal": "Documentation"},
            "source_metadata_response": {"id": "method", "title": "Method guide"},
            "open_access": True, "content_type": "text/html",
            "source_payload": _source_text(extract), "paper_type": "method",
            "user_source_id": "", "user_source_sha256": "",
            "extracts": [{
                "anchor_id": "A1", "section": "Model fitting", "text": extract,
                "locator": "Model fitting paragraph 1",
                "extraction_method": "source-located", "verification_status": "located",
                "method_component_ids": ["differential_expression"],
                "method_ids": ["limma_voom"], "source_kind": source_kind,
            }],
        }],
        "review_search": {"query": "review", "status": "none_found", "receipt": "Europe PMC 0"},
        "verification": [],
    }


def _receipt():
    return dr.skill_receipt("codex", ["codex", "exec"], "prompt", "test")


def test_l4_runtime_schema_is_method_specific_without_changing_l1():
    l4 = dr._runtime_schema("L4")
    l1 = dr._runtime_schema("L1")

    assert {"method_components", "method_candidates"}.issubset(l4["required"])
    assert "method_components" not in l1["properties"]
    extract = l4["properties"]["papers"]["items"]["properties"]["extracts"]["items"]
    assert {"anchor_id", "method_component_ids", "method_ids", "source_kind"}.issubset(extract["required"])


def test_l4_prompt_lists_registered_user_sources(tmp_path):
    project = tmp_path / "P"
    _candidate(project)
    pdf = tmp_path / "protocol.pdf"
    pdf.write_bytes(b"%PDF-1.7\nmethods\n%%EOF")
    record = register_pdf(project, "C1", pdf, doi="10.1000/paywalled")

    _, prompt = dr.build_invocation(
        dr.RuntimeSpec(backend="codex", executable="codex"),
        "L4", "Q", "H", tmp_path,
        user_sources=[record],
    )

    assert record["user_source_id"] in prompt
    assert record["sha256"] in prompt
    assert record["stored_path"] in prompt
    assert "method components" in prompt.lower()
    assert "registration alone" in prompt.lower()


def test_l4_persists_component_anchors_and_renders_candidate_catalog(tmp_path):
    project = tmp_path / "P"
    _candidate(project)
    artifact = dr.persist_run(project, "C1", "L4", _payload(), _receipt())

    assert artifact["method_components"][0]["component_id"] == "differential_expression"
    assert artifact["method_candidates"][0]["method_id"] == "limma_voom"
    ok, reason = dr.audit_evidence_pack(project, "C1", "L4", run_id=artifact["run_id"])
    assert ok is True, reason
    summary = (project / artifact["summary_path"]).read_text(encoding="utf-8")
    for required in (
        "Method Candidate Catalog", "limma-voom", "Applicable input",
        "Implementation steps", "Assumptions", "Expected outputs", "Limitations",
        "Evidence anchors", "L5", "L6",
    ):
        assert required in summary


def test_l4_rejects_placeholder_or_unverifiable_source_payload(tmp_path):
    project = tmp_path / "P"
    _candidate(project)
    payload = _payload()
    payload["papers"][0]["source_payload"] = (
        "Open-access full text was retrieved; the located Methods extract is retained below."
    )

    with pytest.raises(dr.DeepResearchError, match="placeholder|500|source payload"):
        dr.persist_run(project, "C1", "L4", payload, _receipt())


def test_l4_fails_with_precise_uncovered_component_diagnostic(tmp_path):
    project = tmp_path / "P"
    _candidate(project)
    artifact = dr.persist_run(
        project, "C1", "L4", _payload(status="needs_user_source"), _receipt()
    )

    ok, reason = dr.audit_evidence_pack(project, "C1", "L4", run_id=artifact["run_id"])
    assert ok is False
    assert "differential_expression" in reason
    assert "user" in reason.lower()


def test_user_pdf_anchor_must_match_registered_candidate_hash(tmp_path):
    project = tmp_path / "P"
    _candidate(project)
    pdf = tmp_path / "protocol.pdf"
    pdf.write_bytes(b"%PDF-1.7\nmethods\n%%EOF")
    record = register_pdf(project, "C1", pdf)
    payload = _payload(source_kind="user_supplied_pdf")
    paper = payload["papers"][0]
    paper.update({
        "doi": "", "url": "", "open_access": False,
        "user_source_id": record["user_source_id"],
        "user_source_sha256": "0" * 64,
    })

    with pytest.raises(dr.DeepResearchError, match="SHA256|registered PDF"):
        dr.persist_run(project, "C1", "L4", payload, _receipt())
