from __future__ import annotations

import http.client
import json

from research_loop import external_resilience as resilience
from research_loop import l4_closed_corpus as cc
from research_loop.l05_curie.europepmc import (
    EuropePmcEvidenceRetriever,
    EuropePmcTransport,
    lookup_exact_identifiers,
)
from research_loop.l05_curie.multisource import OpenAlexTransport


def _zero_wait_http_policy(monkeypatch):
    monkeypatch.setattr(
        resilience,
        "HTTP_RETRY_POLICY",
        resilience.RetryPolicy(
            max_attempts=3,
            wait_seconds=(0.0, 0.0),
            max_override_seconds=5.0,
        ),
    )


def test_multisource_transport_uses_shared_http_retry(monkeypatch, tmp_path):
    _zero_wait_http_policy(monkeypatch)
    attempts = 0

    def http_get(_url, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise http.client.IncompleteRead(b"partial", 100)
        return b'{"results":[],"meta":{"count":0}}'

    transport = OpenAlexTransport(
        tmp_path,
        candidate_id="C001",
        run_id="RUN001",
        http_get=http_get,
    )

    batch = transport.search(
        {"query_id": "Q001", "query": "bat cardiac physiology", "page_size": 5}
    )

    assert batch["provider"] == "openalex"
    assert batch["records"] == []
    assert attempts == 2


def test_europepmc_search_uses_shared_http_retry(monkeypatch, tmp_path):
    _zero_wait_http_policy(monkeypatch)
    attempts = 0
    payload = json.dumps(
        {"hitCount": 0, "nextCursorMark": "", "resultList": {"result": []}}
    ).encode("utf-8")

    def http_get(_url, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("temporary reset")
        return payload

    transport = EuropePmcTransport(
        tmp_path,
        candidate_id="C001",
        run_id="RUN001",
        http_get=http_get,
    )

    batch = transport.search(
        {"query_id": "Q001", "query": "bat cardiac physiology", "page_size": 5}
    )

    assert batch["provider"] == "europe-pmc"
    assert batch["records"] == []
    assert attempts == 2


def test_europepmc_exact_lookup_uses_shared_http_retry(monkeypatch):
    _zero_wait_http_policy(monkeypatch)
    attempts = 0
    payload = json.dumps(
        {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "123",
                        "source": "MED",
                        "pmid": "123",
                        "pmcid": "PMC123",
                        "doi": "10.1000/example",
                        "title": "Example paper",
                    }
                ]
            },
        }
    ).encode("utf-8")

    def http_get(_url, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("temporary reset")
        return payload

    resolved = lookup_exact_identifiers(
        doi="10.1000/example",
        http_get=http_get,
    )

    assert resolved["pmcid"] == "PMC123"
    assert attempts == 2


def test_europepmc_fulltext_retriever_retries_from_fresh_bytes(monkeypatch, tmp_path):
    _zero_wait_http_policy(monkeypatch)
    attempts = 0
    xml = b"""<?xml version='1.0'?><article><body><sec><title>Results</title><p>Complete evidence paragraph.</p></sec></body></article>"""

    def http_get(_url, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise http.client.IncompleteRead(b"partial", len(xml))
        return xml

    retriever = EuropePmcEvidenceRetriever(
        tmp_path,
        candidate_id="C001",
        run_id="RUN001",
        http_get=http_get,
    )
    paper = {
        "paper_id": "P1",
        "identifiers": {"pmcid": "PMC123"},
    }
    seed = {
        "scientific_question": "What is the evidence?",
        "hypothesis_seed": "The paper contains relevant evidence.",
    }

    result = retriever.retrieve(paper, seed=seed)

    assert attempts == 2
    assert (tmp_path / result["snapshot"]["artifact_path"]).read_bytes() == xml
    assert result["candidates"][0]["text"] == "Complete evidence paragraph."


def test_l4b_fetch_delegates_retry_mechanics_to_shared_owner(monkeypatch):
    calls = []

    class Response:
        status = 200
        headers = {"Content-Type": "application/xml"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            return b"<article>" + b"x" * 600 + b"</article>"

        def geturl(self):
            return "https://example.org/paper.xml"

    class Opener:
        def open(self, _request, timeout):
            assert timeout == 30
            return Response()

    monkeypatch.setattr(cc.urllib.request, "build_opener", lambda *_args: Opener())
    original = resilience.run_http_with_retry

    def traced(operation, **_kwargs):
        calls.append("shared")
        return original(operation, sleep=lambda _seconds: None)

    monkeypatch.setattr(cc, "run_http_with_retry", traced)

    result = cc._fetch("https://example.org/paper.xml")

    assert result["http_status"] == 200
    assert calls == ["shared"]
    assert not hasattr(cc, "MAX_HTTP_RETRIES")
    assert not hasattr(cc, "MAX_RETRY_AFTER_SECONDS")
    assert not hasattr(cc, "_retry_after_seconds")
