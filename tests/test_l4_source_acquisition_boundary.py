import hashlib
import io
import json
import urllib.error

import pytest

from research_loop import l4_closed_corpus as cc
from research_loop.l05_curie import selector


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


def _score(_record, _seed):
    return {
        "relevance": 1.0,
        "directness": 1.0,
        "methodological_value": 1.0,
        "contradiction_value": 0.0,
        "evidence_diversity": 1.0,
        "reason": "Would be highly ranked if it were a paper-level source.",
    }


def _seed_frozen_paper(project, *, valid_hash=True):
    raw = METHOD_XML.encode("utf-8")
    sources = project / "09_Literature_Database/evidence_packs/sources"
    papers = project / "09_Literature_Database/evidence_packs/papers"
    sources.mkdir(parents=True, exist_ok=True)
    papers.mkdir(parents=True, exist_ok=True)
    source_path = sources / "existing.xml"
    source_path.write_bytes(raw)
    relative = source_path.relative_to(project).as_posix()
    record = {
        "paper_id": "existing-paper",
        "doi": "10.1234/example.method",
        "pmid": "",
        "url": "https://doi.org/10.1234/example.method",
        "retrieved_at": "2026-09-01T00:00:00+00:00",
        "content_hash": (
            hashlib.sha256(raw).hexdigest()
            if valid_hash
            else hashlib.sha256(b"different bytes").hexdigest()
        ),
        "source_payload_path": relative,
    }
    (papers / "existing-paper.json").write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return source_path


def test_curie_selector_excludes_crossref_component_before_scoring():
    calls = []

    def scorer(record, seed):
        calls.append((record, seed))
        return _score(record, seed)

    result = selector.select_candidates_strict(
        [_component_record()],
        seed={},
        scorer=scorer,
        eligibility=lambda _record: (True, "CALLER_ALLOWED"),
        max_papers=1,
        query_ids={"Q001"},
    )

    assert result["included_paper_ids"] == []
    assert result["decisions"][0]["decision"] == "EXCLUDE"
    assert result["decisions"][0]["reason_code"] == "NON_PAPER_COMPONENT_SOURCE"
    assert calls == []


def test_next_run_reuses_existing_frozen_source_without_network(tmp_path):
    project = tmp_path / "project"
    source_path = _seed_frozen_paper(project)
    calls = []

    def no_network(url):
        calls.append(url)
        raise OSError("network should not be used when a frozen source exists")

    result = cc.resolve_contract(
        project,
        cc._internal_contract(_asset()),
        fetcher=no_network,
    )

    assert result["status"] == "resolved"
    assert result["receipt"]["retrieval_method"] == "registered_local_payload"
    assert result["source_bytes"] == METHOD_XML.encode("utf-8")
    assert result["local_path"] == str(source_path.resolve())
    assert calls == []


def test_corrupt_frozen_source_is_not_reused(tmp_path):
    project = tmp_path / "project"
    _seed_frozen_paper(project, valid_hash=False)
    calls = []

    def network(url):
        calls.append(url)
        return _response(url)

    result = cc.resolve_contract(
        project,
        cc._internal_contract(_asset()),
        fetcher=network,
    )

    assert result["status"] == "resolved"
    assert result["receipt"]["retrieval_method"] != "registered_local_payload"
    assert calls


def test_doi_only_contract_enriches_pmcid_before_publisher(tmp_path):
    calls = []
    lookup_calls = []

    def identifier_resolver(*, doi="", pmid=""):
        lookup_calls.append((doi, pmid))
        return {
            "doi": "10.1234/example.method",
            "pmid": "25516281",
            "pmcid": "PMC4302049",
        }

    def fetcher(url):
        calls.append(url)
        return _response(url)

    result = cc.resolve_contract(
        tmp_path,
        cc._internal_contract(_asset()),
        fetcher=fetcher,
        identifier_resolver=identifier_resolver,
    )

    assert lookup_calls == [("10.1234/example.method", "")]
    assert calls == [
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4302049/fullTextXML"
    ]
    assert result["status"] == "resolved"
    assert result["contract"]["pmcid"] == "PMC4302049"
    assert result["receipt"]["retrieval_method"] == "europe_pmc_fulltext_xml"


class _Response:
    def __init__(self, url, body):
        self._url = url
        self._body = body
        self.status = 200
        self.headers = {"Content-Type": "application/xml"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit):
        return self._body

    def geturl(self):
        return self._url


class _RetryOpener:
    def __init__(self, url, *, status):
        self.url = url
        self.status = status
        self.calls = 0

    def open(self, request, timeout=30):
        del timeout
        self.calls += 1
        if self.calls == 1 or self.status == 403:
            raise urllib.error.HTTPError(
                self.url,
                self.status,
                "blocked",
                {"Retry-After": "0"},
                io.BytesIO(b"blocked"),
            )
        return _Response(self.url, METHOD_XML.encode("utf-8"))


def test_default_fetch_retries_429_and_honors_retry_after(monkeypatch):
    url = "https://example.org/paper"
    opener = _RetryOpener(url, status=429)
    sleeps = []
    monkeypatch.setattr(cc.urllib.request, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(cc.time, "sleep", lambda seconds: sleeps.append(seconds))

    response = cc._fetch(url)

    assert response["http_status"] == 200
    assert opener.calls == 2
    assert sleeps == [0.0]


def test_default_fetch_does_not_retry_403(monkeypatch):
    url = "https://example.org/paper"
    opener = _RetryOpener(url, status=403)
    sleeps = []
    monkeypatch.setattr(cc.urllib.request, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(cc.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        cc._fetch(url)

    assert exc_info.value.code == 403
    assert opener.calls == 1
    assert sleeps == []
