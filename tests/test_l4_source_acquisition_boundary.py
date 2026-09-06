import hashlib
import json

from research_loop import l4_closed_corpus as cc
from research_loop.l4_contextual_literature import _contextual_candidate_eligibility


METHOD_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    "<article><body><sec id='methods'><title>Materials and methods</title><p>"
    + "The method source contains a reproducible implementation description. " * 20
    + "</p></sec></body></article>\n"
)


def _component_record():
    return {
        "paper_id": "P_component",
        "title": "Figure 5",
        "identifiers": {"doi": "10.7717/peerj.20761/fig-5"},
        "metadata": {
            "authors": "",
            "year": "2026",
            "journal": "PeerJ",
            "abstract": "A figure component returned by Crossref.",
            "publication_types": ["component"],
            "is_open_access": True,
        },
        "provenance": {
            "provider": "crossref",
            "originating_query_ids": ["Q001"],
        },
    }


def _asset():
    return {
        "asset_id": "P_method",
        "doi": "10.1234/example.method",
        "pmid": "",
        "url": "https://doi.org/10.1234/example.method",
        "title": "Example method paper",
        "year": 2024,
        "role": "method",
        "journal": "Methods Journal",
        "abstract": "Metadata only.",
        "source_database": "l05_curie_multisource",
        "source_metadata_response": {"id": "P_method"},
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": ["https://doi.org/10.1234/example.method"],
        "selection_status": "selected",
        "method_component_hints": [],
    }


def _response(url):
    return {
        "requested_url": url,
        "resolved_url": url,
        "redirect_chain": [],
        "http_status": 200,
        "content_type": "application/xml",
        "body": METHOD_XML.encode("utf-8"),
    }


def test_l4a_excludes_crossref_component_before_method_ranking():
    allowed, reason = _contextual_candidate_eligibility(_component_record())

    assert allowed is False
    assert reason == "NON_PAPER_COMPONENT_SOURCE"


def test_resolved_source_is_frozen_in_shared_evidence_source_store(tmp_path):
    project = tmp_path / "project"
    work = tmp_path / "work"

    state = cc.resolve_manifest(
        project,
        "C1",
        {"path": "manifest.json", "manifest_sha256": "abc"},
        work,
        selected_assets=[_asset()],
        fetcher=_response,
    )

    result = state["resolutions"][0]
    local = result["local_path"]
    assert result["status"] == "resolved"
    assert local
    local_path = project / result["persisted_source_path"]
    assert local_path.resolve().as_posix() == local.replace("\\", "/")
    assert "/09_Literature_Database/evidence_packs/sources/" in local_path.resolve().as_posix()
    assert local_path.read_bytes() == METHOD_XML.encode("utf-8")
    assert local_path.stem == hashlib.sha256(METHOD_XML.encode("utf-8")).hexdigest()
    assert not (work / "l4b_resolved_sources").exists()


def test_next_run_reuses_frozen_source_without_network(tmp_path):
    project = tmp_path / "project"
    first_state = cc.resolve_manifest(
        project,
        "C1",
        {"path": "manifest.json", "manifest_sha256": "abc"},
        tmp_path / "work-1",
        selected_assets=[_asset()],
        fetcher=_response,
    )
    first_result = first_state["resolutions"][0]

    artifact = {"run_id": "R1", "papers": []}
    cc.persist_debug_evidence(project, artifact, first_state)

    receipt = json.loads(
        next(
            (project / "09_Literature_Database/evidence_packs/retrieval_receipts/R1").glob("*.json")
        ).read_text(encoding="utf-8")
    )
    assert receipt["local_payload_path"] == first_result["persisted_source_path"]

    calls = []

    def no_network(url):
        calls.append(url)
        raise OSError("network should not be used when a frozen source exists")

    second_state = cc.resolve_manifest(
        project,
        "C1",
        {"path": "manifest.json", "manifest_sha256": "def"},
        tmp_path / "work-2",
        selected_assets=[_asset()],
        fetcher=no_network,
    )

    second_result = second_state["resolutions"][0]
    assert second_result["status"] == "resolved"
    assert second_result["receipt"]["retrieval_method"] == "registered_local_payload"
    assert second_result["persisted_source_path"] == first_result["persisted_source_path"]
    assert calls == []
