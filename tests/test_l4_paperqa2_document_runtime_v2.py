import hashlib
import json
import sys

from research_loop import l4_closed_corpus as cc
from research_loop.l05_curie.paperqa2 import PaperQA2Retriever, validate_paperqa2_candidate
from research_loop.l05_curie.paperqa2_runtime import PaperQA2SubprocessBackend


PINNED_COMMIT = "57e89f7223b0960d5ee5ea048c69e3c47e088572"


def _runtime_v2(document_path, document_sha256, media_type="application/xml"):
    return {
        "schema_version": "PaperQA2Runtime/v2",
        "package": "paper-qa",
        "version": "2026.8.12",
        "upstream_repo": "https://github.com/Future-House/paper-qa",
        "upstream_tag": "v2026.08.12",
        "upstream_commit": PINNED_COMMIT,
        "fork_repo": "https://github.com/hk20013106/paper-qa",
        "python_executable": sys.executable,
        "paperqa_repo": ".",
        "pqa_home": ".",
        "document_path": str(document_path),
        "document_sha256": document_sha256,
        "media_type": media_type,
    }


def test_paperqa2_candidate_accepts_document_neutral_runtime_v2(tmp_path):
    document = tmp_path / "paper.xml"
    document.write_text("<article><body>Methods text</body></article>", encoding="utf-8")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    candidate = {
        "schema_version": "L05PaperQA2Candidate/v1",
        "evidence_id": "E1",
        "paper_id": "P1",
        "section": "PaperQA2",
        "text": "Methods text",
        "locator": "P1 chunk 1",
        "verification_status": "UNVERIFIED",
        "retrieval": {
            "engine": "paperqa2",
            "backend_id": "paperqa2-fork-v2026.08.12/sparse-docs-v1",
            "source_identity": {"pmcid": "PMC1"},
            "runtime": _runtime_v2(document, digest),
        },
    }

    validated = validate_paperqa2_candidate(candidate)

    assert validated["retrieval"]["runtime"]["schema_version"] == "PaperQA2Runtime/v2"
    assert validated["retrieval"]["runtime"]["document_sha256"] == digest
    assert "pdf_path" not in validated["retrieval"]["runtime"]


def test_existing_paperqa2_backend_reuses_same_path_for_frozen_xml_document(tmp_path):
    document = tmp_path / "paper.xml"
    document.write_text(
        "<article><body><sec><title>EXPERIMENTAL PROCEDURES</title>"
        "<p>Exact method details.</p></sec></body></article>",
        encoding="utf-8",
    )
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        f'''\nimport json\nimport sys\nrequest = json.load(sys.stdin)\nassert request["document_path"].endswith("paper.xml")\nassert request["media_type"] == "application/xml"\nprint(json.dumps({{\n    "engine": "paperqa2",\n    "runtime": {{\n        "schema_version": "PaperQA2Runtime/v2",\n        "package": "paper-qa",\n        "version": "2026.8.12",\n        "upstream_repo": "https://github.com/Future-House/paper-qa",\n        "upstream_tag": "v2026.08.12",\n        "upstream_commit": "{PINNED_COMMIT}",\n        "fork_repo": "https://github.com/hk20013106/paper-qa",\n        "document_sha256": "{digest}",\n        "media_type": "application/xml"\n    }},\n    "hits": [{{\n        "text": "Exact method details.",\n        "locator": "P1 chunk 1",\n        "section": "PaperQA2",\n        "score": 0.9\n    }}]\n}}))\n''',
        encoding="utf-8",
    )
    backend = PaperQA2SubprocessBackend(
        python_executable=sys.executable,
        bridge_script=bridge,
        paperqa_repo=tmp_path,
        pqa_home=tmp_path / "pqa-home",
    )
    paper = {
        "paper_id": "P1",
        "title": "Method paper",
        "identifiers": {"pmcid": "PMC1"},
        "document_path": str(document),
        "media_type": "application/xml",
    }

    item = PaperQA2Retriever(
        backend=backend,
        backend_id="paperqa2-fork-v2026.08.12/sparse-docs-v1",
    ).retrieve(paper=paper, question="Locate the experimental procedure.")[0]

    runtime = item["retrieval"]["runtime"]
    assert runtime["schema_version"] == "PaperQA2Runtime/v2"
    assert runtime["document_path"] == str(document.resolve())
    assert runtime["document_sha256"] == digest
    assert runtime["media_type"] == "application/xml"
    assert item["verification_status"] == "UNVERIFIED"


def test_exact_source_resolution_does_not_fail_when_legacy_heading_parser_misses_methods(tmp_path):
    method_text = "The experimental procedure specifies exact reproducible steps. " * 20
    payload = (
        "<article><front><article-meta><article-id pub-id-type='doi'>"
        "10.1000/procedure</article-id></article-meta></front>"
        "<body><sec id='procedure'><title>EXPERIMENTAL PROCEDURES</title>"
        f"<p>{method_text}</p></sec></body></article>"
    )
    asset = {
        "asset_id": "A1",
        "doi": "10.1000/procedure",
        "pmid": "12345678",
        "url": "https://doi.org/10.1000/procedure",
        "title": "Procedure paper",
        "role": "method",
        "source_metadata_response": {},
        "full_text_status": "available_oa",
        "full_text_locations": ["https://doi.org/10.1000/procedure"],
    }
    contract = cc.build_retrieval_contract(asset)

    result = cc.resolve_contract(
        tmp_path,
        contract,
        fetcher=lambda url: {
            "requested_url": url,
            "resolved_url": url,
            "redirect_chain": [],
            "http_status": 200,
            "content_type": "application/xml",
            "body": payload.encode("utf-8"),
        },
    )

    assert result["status"] == "resolved"
    assert result["source_bytes"] == payload.encode("utf-8")
    assert result["methods_section"] is None
    assert result["receipt"]["parser"] == "payload-only"
    assert result["receipt"]["failure_reason"] == ""
