import hashlib
import json
from pathlib import Path
import pytest

from research_loop import l4_closed_corpus as cc


METHOD_TEXT = (
    "Materials and methods "
    + "DESeq2 estimates size factors from median ratios, fits negative binomial models, "
      "moderates dispersion estimates, tests coefficients, and reports adjusted probabilities. " * 12
)
A1_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<article><front><article-meta><article-id pub-id-type='doi'>"
    "10.1186/s13059-014-0550-8</article-id></article-meta></front>"
    "<body><sec id='methods'><title>Materials and methods</title>"
    f"<p>{METHOD_TEXT.removeprefix('Materials and methods ')}</p>"
    "</sec><sec><title>Results</title><p>Results text.</p></sec></body></article>"
)


def _asset(**overrides):
    asset = {
        "asset_id": "A1",
        "doi": "10.1186/s13059-014-0550-8",
        "pmid": "25516281",
        "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
        "title": "Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2",
        "year": 2014,
        "role": "method",
        "journal": "Genome Biology",
        "abstract": "Abstract only.",
        "source_database": "PubMed",
        "source_metadata_response": {"pmcid": "PMC4302049", "id": "25516281"},
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": [
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/",
            "https://doi.org/10.1186/s13059-014-0550-8",
        ],
        "selection_status": "selected",
        "method_component_hints": ["MC1", "differential expression"],
    }
    asset.update(overrides)
    return asset


def _response(url, payload=A1_XML, *, resolved_url=None, content_type="application/xml"):
    return {
        "requested_url": url,
        "resolved_url": resolved_url or url,
        "redirect_chain": [] if resolved_url in (None, url) else [resolved_url],
        "http_status": 200,
        "content_type": content_type,
        "body": payload.encode("utf-8"),
    }


def _blocked_payload():
    return {
        "schema_version": "1.0",
        "queries": ["frozen A1"],
        "papers": [{
            "doi": "10.1186/s13059-014-0550-8",
            "pmid": "25516281",
            "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
            "title": _asset()["title"],
            "source_database": "PubMed",
            "metadata": {"year": 2014, "journal": "Genome Biology"},
            "source_metadata_response": {"id": "25516281", "title": _asset()["title"]},
            "open_access": True,
            "content_type": "text/html",
            "source_payload": "",
            "paper_type": "method",
            "user_source_id": "",
            "user_source_sha256": "",
            "extracts": [],
        }],
        "review_search": {
            "query": "frozen catalog",
            "status": "not_retained",
            "receipt": "No selected review.",
        },
        "verification": [],
        "method_components": [{
            "component_id": "MC1",
            "name": "Differential expression model",
            "required": True,
            "rationale": "Required analysis.",
        }],
        "method_candidates": [{
            "method_id": "M1",
            "component_id": "MC1",
            "name": "DESeq2",
            "status": "needs_user_source",
            "purpose": "Estimate differential expression.",
            "applicable_to": ["RNA-seq counts"],
            "implementation_steps": ["Fit the model"],
            "assumptions": [],
            "expected_outputs": ["fold changes"],
            "strengths": [],
            "limitations": [],
            "alternatives": [],
            "rejection_reasons": [],
            "method_anchor_ids": [],
            "missing_source": "User PDF required.",
        }],
    }


def test_contract_is_paper_level_and_closed_corpus():
    contract = cc.build_retrieval_contract(_asset())

    assert contract == {
        "paper_id": "A1",
        "doi": "10.1186/s13059-014-0550-8",
        "pmid": "25516281",
        "pmcid": "PMC4302049",
        "registered_locations": [
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/",
            "https://doi.org/10.1186/s13059-014-0550-8",
            "https://pubmed.ncbi.nlm.nih.gov/25516281/",
        ],
        "full_text_status": "available_oa",
        "retrieval_policy": "closed_corpus_exact_asset_only",
    }


def test_unregistered_and_search_urls_are_rejected():
    contract = cc.build_retrieval_contract(_asset())

    with pytest.raises(ValueError, match="not registered"):
        cc.validate_request_url(contract, "https://example.org/unrelated-paper")
    with pytest.raises(ValueError, match="search URL"):
        cc.validate_request_url(contract, "https://www.google.com/search?q=DESeq2")
    with pytest.raises(ValueError, match="non-public network"):
        cc.validate_request_url(contract, "http://127.0.0.1/PMC4302049")


def test_pmcid_prefers_europe_pmc_xml_and_extracts_contiguous_methods(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    calls = []

    def fetcher(url):
        calls.append(url)
        return _response(url)

    result = cc.resolve_contract(tmp_path, contract, fetcher=fetcher)

    assert calls == [
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4302049/fullTextXML"
    ]
    assert result["status"] == "resolved"
    assert result["methods_section"]["section"] == "Materials and methods"
    assert len(result["methods_section"]["text"].encode("utf-8")) > 500
    assert cc.normalized_source_text(result["methods_section"]["text"]) in cc.normalized_source_text(result["source_payload"])
    assert result["receipt"]["parser"] == "jats-xml"
    assert result["receipt"]["failure_reason"] == ""


def test_pmc_fallback_runs_after_europe_pmc_failure(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    calls = []

    def fetcher(url):
        calls.append(url)
        if "europepmc" in url:
            raise OSError("blocked")
        return _response(url, content_type="text/html", payload=(
            "<html><body><h2>Materials and methods</h2><p>"
            + METHOD_TEXT.removeprefix("Materials and methods ")
            + "</p><h2>Results</h2></body></html>"
        ))

    result = cc.resolve_contract(tmp_path, contract, fetcher=fetcher)

    assert calls[:2] == [
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4302049/fullTextXML",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/",
    ]
    assert result["status"] == "resolved"
    assert result["receipt"]["parser"] == "html-heading"
    assert result["attempts"][0]["failure_reason"] == "blocked"


def test_registered_doi_url_is_used_without_search(tmp_path):
    asset = _asset(source_metadata_response={"id": "25516281"}, full_text_locations=[
        "https://doi.org/10.1186/s13059-014-0550-8"
    ])
    contract = cc.build_retrieval_contract(asset)
    calls = []

    def fetcher(url):
        calls.append(url)
        return _response(url)

    result = cc.resolve_contract(tmp_path, contract, fetcher=fetcher)

    assert calls[0] == "https://doi.org/10.1186/s13059-014-0550-8"
    assert result["status"] == "resolved"


def test_redirect_is_allowed_only_when_payload_preserves_asset_identity(tmp_path):
    contract = cc.build_retrieval_contract(_asset(source_metadata_response={"id": "25516281"}, full_text_locations=[
        "https://doi.org/10.1186/s13059-014-0550-8"
    ]))

    good = cc.resolve_contract(
        tmp_path,
        contract,
        fetcher=lambda url: _response(
            url,
            resolved_url="https://genomebiology.biomedcentral.com/articles/10.1186/s13059-014-0550-8",
        ),
    )
    assert good["status"] == "resolved"
    assert good["receipt"]["redirect_chain"] == [
        "https://genomebiology.biomedcentral.com/articles/10.1186/s13059-014-0550-8"
    ]

    bad = cc.resolve_contract(
        tmp_path,
        contract,
        fetcher=lambda url: _response(
            url,
            payload=A1_XML.replace("10.1186/s13059-014-0550-8", "10.9999/other"),
            resolved_url="https://example.org/other",
        ),
    )
    assert bad["status"] == "failed"
    assert "asset identity" in bad["attempts"][-1]["failure_reason"]


def test_a1_regression_injects_payload_and_accepts_mc1_without_user_pdf(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    resolved = cc.resolve_contract(
        tmp_path, contract,
        fetcher=lambda url: _response(url),
    )
    state = {"contracts": [contract], "resolutions": [resolved]}
    payload = _blocked_payload()

    cc.enrich_provider_payload(payload, state)

    paper = payload["papers"][0]
    candidate = payload["method_candidates"][0]
    extract = paper["extracts"][0]
    assert paper["source_payload"] == A1_XML
    assert candidate["status"] == "eligible"
    assert candidate["missing_source"] == ""
    assert candidate["method_anchor_ids"] == [extract["anchor_id"]]
    assert extract["section"] == "Materials and methods"
    assert extract["source_kind"] == "method_paper"
    assert len(extract["text"].encode("utf-8")) > 500


def test_all_registered_paths_must_fail_before_source_blocked_is_retained(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    result = cc.resolve_contract(
        tmp_path, contract,
        fetcher=lambda url: (_ for _ in ()).throw(OSError("offline")),
    )
    payload = _blocked_payload()

    cc.enrich_provider_payload(payload, {"contracts": [contract], "resolutions": [result]})

    assert result["status"] == "failed"
    assert len(result["attempts"]) >= 4
    assert payload["method_candidates"][0]["status"] == "needs_user_source"


def test_short_abstract_and_discontinuous_text_cannot_become_methods_anchor(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    abstract_xml = (
        "<article><body><sec><title>Abstract</title><p>"
        + "short abstract " * 50
        + "</p></sec></body></article>"
    )
    result = cc.resolve_contract(
        tmp_path, contract,
        fetcher=lambda url: _response(url, payload=abstract_xml),
    )
    assert result["status"] == "failed"
    assert all(item["section_locator"] == "" for item in result["attempts"])

    payload = _blocked_payload()
    payload["papers"][0]["source_payload"] = "A" * 600 + "B" * 600
    payload["papers"][0]["extracts"] = [{
        "anchor_id": "bad",
        "section": "Methods",
        "text": "A" * 300 + "B" * 300,
        "locator": "Methods",
        "extraction_method": "source-located",
        "verification_status": "located",
        "method_component_ids": ["MC1"],
        "method_ids": ["M1"],
        "source_kind": "primary_study",
    }]
    assert cc.extract_is_contiguous(payload["papers"][0]["source_payload"], payload["papers"][0]["extracts"][0]["text"])
    payload["papers"][0]["extracts"][0]["text"] = "A" * 300 + "X" + "B" * 300
    assert not cc.extract_is_contiguous(payload["papers"][0]["source_payload"], payload["papers"][0]["extracts"][0]["text"])


def test_registered_local_payload_has_first_priority(tmp_path):
    local = tmp_path / "A1.xml"
    local.write_text(A1_XML, encoding="utf-8")
    asset = _asset(full_text_locations=["A1.xml", "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"])
    contract = cc.build_retrieval_contract(asset)
    calls = []

    result = cc.resolve_contract(
        tmp_path, contract,
        fetcher=lambda url: calls.append(url) or _response(url),
    )

    assert result["status"] == "resolved"
    assert result["receipt"]["retrieval_method"] == "registered_local_payload"
    assert calls == []


def test_normalized_source_text_removes_html_tags_but_preserves_scientific_inequalities():
    normalized = cc.normalized_source_text(
        "<p>Methods: FDR < 0.01; p < 0.05; x > 3.</p>"
    )

    assert "methods" in normalized
    assert "fdr < 0.01" in normalized
    assert "p < 0.05" in normalized
    assert "x > 3" in normalized
    assert "<p>" not in normalized
    assert "</p>" not in normalized


def test_jats_methods_extract_remains_contiguous_with_entities_and_inequalities():
    payload = (
        "<article><body><sec id='methods'><title>Methods</title><p>"
        "We retained genes with FDR&lt;&#x2009;0.01 and p &lt; 0.05 and x &gt; 3. "
        + "The retained method description is substantive and reproducible. " * 20
        + "</p></sec><sec><title>Results</title><p>Results.</p></sec></body></article>"
    )

    methods = cc.extract_methods_section(payload, "application/xml")

    assert methods is not None
    assert "FDR< 0.01" in methods["text"]
    assert "p < 0.05" in methods["text"]
    assert cc.extract_is_contiguous(payload, methods["text"])


def test_resolver_preserves_exact_source_bytes_and_hash_on_persistence(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    raw_payload = A1_XML.replace("><", ">\r\n<").encode("utf-8")

    def fetcher(url):
        return _response(url, payload=raw_payload.decode("utf-8"))

    result = cc.resolve_contract(tmp_path, contract, fetcher=fetcher)

    expected_hash = hashlib.sha256(raw_payload).hexdigest()
    assert result["source_bytes"] == raw_payload
    assert result["receipt"]["content_hash"] == expected_hash

    state = cc.resolve_manifest(
        tmp_path,
        "C1",
        {"path": "", "manifest_sha256": ""},
        tmp_path / "work",
        selected_assets=[_asset()],
        fetcher=fetcher,
    )
    persisted = Path(state["resolutions"][0]["local_path"]).read_bytes()
    assert persisted == raw_payload


def test_payload_under_500_bytes_fails_closed(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    tiny = "<article><body><sec><title>Methods</title><p>tiny</p></sec></body></article>"

    result = cc.resolve_contract(tmp_path, contract, fetcher=lambda url: _response(url, payload=tiny))

    assert result["status"] == "failed"
    assert any("500 bytes" in attempt["failure_reason"] for attempt in result["attempts"])


def test_nonempty_navigation_payload_is_not_discarded():
    payload = _blocked_payload()
    payload["papers"][0]["source_payload"] = "N" * 600
    payload["papers"][0]["extracts"] = [{
        "anchor_id": "",
        "section": "Abstract",
        "text": "N" * 100,
        "locator": "Abstract",
        "extraction_method": "catalog",
        "verification_status": "located",
        "method_component_ids": [],
        "method_ids": [],
        "source_kind": "navigation_only",
    }]

    cc.enrich_provider_payload(payload, {"contracts": [], "resolutions": []})

    assert payload["papers"][0]["source_payload"] == "N" * 600
    assert payload["papers"][0]["extracts"][0]["source_kind"] == "navigation_only"


def test_prompt_distinguishes_search_from_exact_asset_retrieval(tmp_path):
    contract = cc.build_retrieval_contract(_asset())
    resolved = cc.resolve_contract(tmp_path, contract, fetcher=lambda url: _response(url))
    resolved["local_path"] = str(tmp_path / "A1.xml")

    prompt = cc.render_provider_handoff({"contracts": [contract], "resolutions": [resolved]})

    assert "must not search for additional literature" in prompt.lower()
    assert "allowed and required to read" in prompt.lower()
    assert "retrieving a registered selected asset is not literature search" in prompt.lower()
    assert "all permitted registered-asset retrieval paths" in prompt.lower()
    assert json.dumps(str(tmp_path / "A1.xml")) in prompt


def test_receipts_and_provider_response_are_persisted_without_credentials(tmp_path):
    contract = cc.build_retrieval_contract(_asset(full_text_locations=[
        "https://doi.org/10.1186/s13059-014-0550-8?token=secret-value"
    ], source_metadata_response={"id": "25516281"}))
    resolved = cc.resolve_contract(
        tmp_path, contract,
        fetcher=lambda url: _response(url),
    )
    state = {
        "contracts": [contract],
        "resolutions": [resolved],
        "provider_payload": {"schema_version": "1.0", "api_token": "secret-value"},
    }
    project = tmp_path / "project"
    paper_path = project / "09_Literature_Database/evidence_packs/papers/p1.json"
    paper_path.parent.mkdir(parents=True)
    paper_path.write_text(json.dumps({
        "paper_id": "p1", "doi": contract["doi"], "pmid": contract["pmid"],
        "url": _asset()["url"], "source_payload_path": "sources/p1.xml",
    }), encoding="utf-8")
    artifact_path = project / "09_Literature_Database/evidence_packs/runs/RUN.json"
    artifact_path.parent.mkdir(parents=True)
    artifact = {
        "run_id": "RUN", "path": artifact_path.relative_to(project).as_posix(),
        "papers": [{"paper_id": "p1", "path": paper_path.relative_to(project).as_posix(),
                    "doi": contract["doi"], "pmid": contract["pmid"], "url": _asset()["url"]}],
    }

    cc.persist_debug_evidence(project, artifact, state)

    artifact_text = artifact_path.read_text(encoding="utf-8")
    receipt_path = project / artifact["full_text_retrieval"][0]["path"]
    provider_path = project / artifact["provider_response_path"]
    combined = artifact_text + receipt_path.read_text(encoding="utf-8") + provider_path.read_text(encoding="utf-8")
    assert "secret-value" not in combined
    paper_record = json.loads(paper_path.read_text(encoding="utf-8"))
    assert paper_record["retrieval_receipt_path"] == artifact["full_text_retrieval"][0]["path"]
    assert paper_record["retrieval_receipt_sha256"] == artifact["full_text_retrieval"][0]["sha256"]
    assert paper_record["retrieval_section_locator"].startswith("JATS sec")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    selected = receipt["selected_attempt"]
    for field in (
        "requested_url", "resolved_url", "asset_identifier", "retrieval_method",
        "retrieved_at", "http_status", "content_type", "byte_length", "content_hash",
        "redirect_chain", "parser", "section_locator", "failure_reason",
    ):
        assert field in selected


def test_a1_anchor_passes_existing_l4_validator_and_audit(tmp_path):
    from research_loop import deep_research as dr
    from research_loop import l4_pipeline as l4p

    project = tmp_path / "project"
    asset = _asset()
    discovery_asset = dict(asset)
    discovery_asset.update({
        "source_metadata_response": json.dumps(
            asset["source_metadata_response"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        "open_access_status": "open",
        "relevance_score": 10.0,
        "selection_reason": "A1 is the selected DESeq2 method source.",
        "hypothesis_ids": ["H1"],
        "diagnostic_requirements": ["size-factor normalization"],
    })
    discovery_payload = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1", "query": "frozen A1", "purpose": "method source",
            "status": "completed", "receipt": "fixture",
        }],
        "assets": [discovery_asset],
    }
    receipt = dr.skill_receipt("codex", ["codex", "exec"], "fixture", "test")
    manifest = l4p.persist_l4a_discovery(
        project, "C1", discovery_payload, receipt, question="Q", claim="H"
    )
    contract = cc._internal_contract(manifest["assets"][0])
    resolved = cc.resolve_contract(project, contract, fetcher=lambda url: _response(url))
    payload = _blocked_payload()
    cc.enrich_provider_payload(payload, {"contracts": [contract], "resolutions": [resolved]})

    dr._l4b_frozen_manifest_context = (project.resolve(), "C1", manifest)
    try:
        artifact = dr.persist_run(project, "C1", "L4", payload, receipt)
    finally:
        delattr(dr, "_l4b_frozen_manifest_context")

    ok, reason = dr.audit_evidence_pack(project, "C1", "L4", run_id=artifact["run_id"])
    assert (ok, reason) == (True, "")
    assert artifact["method_candidates"][0]["status"] == "eligible"
    assert artifact["method_anchors"][0]["anchor_id"]
