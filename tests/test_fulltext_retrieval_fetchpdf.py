import hashlib
import json
from pathlib import Path

from research_loop import l85_literature_verification as l85
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.fulltext_retrieval import retrieve_selected_fulltext
from research_loop.l05_curie import multisource


XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<article><body>
<sec><title>Results</title><p>The observed response increased after treatment.</p></sec>
<sec><title>Discussion</title><p>The published interpretation supports the observed response.</p></sec>
</body></article>'''


def _seed():
    return {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C1",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "Does treatment increase the observed response?",
        "hypothesis_seed": "Treatment increases the observed response.",
        "l0_contract_path": "00_Preflight/C1.json",
        "l0_contract_sha256": "a" * 64,
    }


def _record():
    return {
        "paper_id": "P_DOI_ONLY",
        "title": "A DOI-only full-text record",
        "identifiers": {"doi": "10.1000/fetchpdf-test"},
        "metadata": {
            "authors": "Example Author",
            "year": "2025",
            "journal": "Example Journal",
            "abstract": "Treatment increased the observed response.",
            "publication_types": ["research-article"],
            "is_open_access": True,
        },
        "provenance": {
            "provider": "crossref",
            "raw_record_sha256": "b" * 64,
            "originating_query_ids": ["Q1"],
        },
    }


def _write_fetchpdf_xml(identifier, save_path, **kwargs):
    assert identifier == "10.1000/fetchpdf-test"
    assert kwargs == {
        "allow_xml_fallback": False,
        "xml_only": True,
        "get_xml_or_html": False,
        "target_task": "extraction",
        "want_provenance": True,
        "verbose": False,
    }
    xml_path = Path(save_path).with_suffix(".xml")
    xml_path.write_bytes(XML)
    xml_path.with_suffix(".provenance.json").write_text(
        json.dumps({
            "schema_version": 2,
            "identifier": identifier,
            "identifiers_resolved": {"doi": identifier},
            "artifacts": [{
                "path": xml_path.name,
                "content_hash": "sha256:" + hashlib.sha256(XML).hexdigest(),
            }],
        }),
        encoding="utf-8",
    )
    return str(xml_path)


def test_l85_doi_only_record_uses_fetchpdf_python_api(monkeypatch, tmp_path):
    binding = tmp_path / "08_Audit" / "hypothesis_store" / "binding.json"
    binding.parent.mkdir(parents=True)
    binding.write_text(
        json.dumps({"profile_id": PROFILE_V21_CATALOG_1}), encoding="utf-8"
    )
    seed = _seed()
    record = _record()
    calls = []

    monkeypatch.setattr(l85, "binding_path", lambda _project: binding)
    monkeypatch.setattr(
        l85.research_seed,
        "load_l1_research_seed",
        lambda _project, _candidate_id: seed,
    )
    monkeypatch.setattr(
        l85,
        "active_findings",
        lambda _l7, _l8: [{
            "finding_id": "H1",
            "text": "The observed response increased after treatment.",
            "sources": ["L7"],
        }],
    )
    monkeypatch.setattr(
        l85,
        "build_query_plan",
        lambda _seed, _findings: {
            "plan_id": "PLAN1",
            "queries": [{"query_id": "Q1"}],
        },
    )
    monkeypatch.setattr(
        multisource,
        "run_multisource_discovery_strict",
        lambda *_args, **_kwargs: {
            "records": [record],
            "batches": [],
            "duplicate_paper_ids": [],
        },
    )

    def fetch_pdf(*args, **kwargs):
        calls.append((args, kwargs))
        return _write_fetchpdf_xml(*args, **kwargs)

    run = l85.run_native_l85(
        tmp_path,
        "C1",
        fetch_pdf_fn=fetch_pdf,
    )

    assert len(calls) == 1
    assert run["schema_version"] == "L85CanonicalLiteratureVerification/v2"
    assert run["selected_paper_ids"] == ["P_DOI_ONLY"]
    assert run["source_snapshots"][0]["provider"] == "fetchpdf"
    assert run["source_snapshots"][0]["artifact_kind"] == "xml"
    assert run["retrieval_attempts"] == [{
        "paper_id": "P_DOI_ONLY",
        "provider": "fetchpdf",
        "status": "retrieved",
        "artifact_path": run["source_snapshots"][0]["artifact_path"],
        "artifact_sha256": run["source_snapshots"][0]["artifact_sha256"],
        "artifact_kind": "xml",
    }]
    assert run["paper_failures"] == []
    assert {item["section"] for item in run["located_evidence"]} == {
        "Results", "Discussion"
    }
    assert all(
        item["retrieval"]["engine"] == "fetchpdf-jats-source-relocator/v1"
        for item in run["located_evidence"]
    )
    ok, reason, audited = l85.audit_run_manifest(
        tmp_path, "C1", run_id=run["run_id"]
    )
    assert (ok, reason, audited["run_id"]) == (True, "", run["run_id"])

    provenance = tmp_path / run["source_snapshots"][0]["provenance_path"]
    provenance.write_text("{}", encoding="utf-8")
    ok, reason, audited = l85.audit_run_manifest(
        tmp_path, "C1", run_id=run["run_id"]
    )
    assert not ok
    assert "provenance hash mismatch" in reason
    assert audited is None


def test_fetchpdf_strict_xml_then_pdf_fallback_preserves_downstream_contract(tmp_path):
    record = _record()
    record["identifiers"]["pmid"] = "12345678"
    calls = []
    pdf_bytes = b"%PDF-1.4\nfetchpdf fallback\n%%EOF\n"

    def fetch_pdf(identifier, save_path, **kwargs):
        calls.append((identifier, Path(save_path), kwargs))
        stem = Path(save_path).with_suffix("")
        if kwargs["xml_only"]:
            assert identifier == "12345678"
            return None
        assert identifier == "10.1000/fetchpdf-test"
        pdf_path = stem.with_suffix(".pdf")
        pdf_path.write_bytes(pdf_bytes)
        pdf_path.with_suffix(".provenance.json").write_text(
            json.dumps({
                "schema_version": 2,
                "identifier": identifier,
                "identifiers_resolved": {
                    "doi": "10.1000/fetchpdf-test",
                    "pmid": "12345678",
                },
                "artifacts": [{
                    "path": pdf_path.name,
                    "content_hash": "sha256:" + hashlib.sha256(pdf_bytes).hexdigest(),
                }],
            }),
            encoding="utf-8",
        )
        return str(pdf_path)

    result = retrieve_selected_fulltext(
        tmp_path,
        candidate_id="C1",
        run_id="RUN1",
        paper=record,
        seed=_seed(),
        stage="l85",
        fetch_pdf_fn=fetch_pdf,
    )

    assert len(calls) == 2
    assert calls[0][0] == "12345678"
    assert calls[0][1].parent.name == "xml"
    assert calls[0][2] == {
        "allow_xml_fallback": False,
        "xml_only": True,
        "get_xml_or_html": False,
        "target_task": "extraction",
        "want_provenance": True,
        "verbose": False,
    }
    assert calls[1][0] == "10.1000/fetchpdf-test"
    assert calls[1][1].parent.name == "fallback"
    assert calls[1][2] == {
        "allow_xml_fallback": True,
        "xml_only": False,
        "get_xml_or_html": True,
        "target_task": "extraction",
        "want_provenance": True,
        "verbose": False,
    }
    assert result["snapshot"]["provider"] == "fetchpdf"
    assert result["snapshot"]["artifact_kind"] == "pdf"
    assert "/fallback/" in result["snapshot"]["artifact_path"]
    assert result["located"] == []
    assert result["paper_failure"]["reason_code"] == "NO_LOCATABLE_EVIDENCE"
    assert result["attempts"] == [{
        "paper_id": "P_DOI_ONLY",
        "provider": "fetchpdf",
        "status": "retrieved",
        "artifact_path": result["snapshot"]["artifact_path"],
        "artifact_sha256": result["snapshot"]["artifact_sha256"],
        "artifact_kind": "pdf",
    }]


def test_fetchpdf_invalid_xml_provenance_fails_closed_without_pdf_fallback(tmp_path):
    calls = []

    def fetch_pdf(identifier, save_path, **kwargs):
        calls.append((identifier, Path(save_path), kwargs))
        xml_path = Path(save_path).with_suffix(".xml")
        xml_path.write_bytes(XML)
        xml_path.with_suffix(".provenance.json").write_text(
            json.dumps({
                "schema_version": 2,
                "identifier": identifier,
                "identifiers_resolved": {"doi": identifier},
                "artifacts": [{
                    "path": xml_path.name,
                    "content_hash": "sha256:" + "0" * 64,
                }],
            }),
            encoding="utf-8",
        )
        return str(xml_path)

    result = retrieve_selected_fulltext(
        tmp_path,
        candidate_id="C1",
        run_id="RUN_INVALID_XML",
        paper=_record(),
        seed=_seed(),
        stage="l85",
        fetch_pdf_fn=fetch_pdf,
    )

    assert len(calls) == 1
    assert calls[0][2]["xml_only"] is True
    assert result["snapshot"] is None
    assert result["paper_failure"]["reason_code"] == "FULLTEXT_UNAVAILABLE"
    assert "provenance artifact hash does not match" in result["attempts"][0]["reason"]
