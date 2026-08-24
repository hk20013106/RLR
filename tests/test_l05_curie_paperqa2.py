import pytest

import research_loop.l05_curie as curie
from research_loop.l05_curie.paperqa2 import (
    PAPERQA2_CANDIDATE_SCHEMA_VERSION,
    PaperQA2Retriever,
    retrieve_with_declared_fallback,
    validate_paperqa2_candidate,
)


def _paper():
    return {
        "paper_id": "P1",
        "title": "Bat cardiac physiology",
        "identifiers": {"doi": "10.1000/abc", "pmcid": "PMC1"},
        "metadata": {"abstract": "Cardiac calcium handling was measured."},
    }


def test_paperqa2_returns_only_unverified_candidates_with_source_provenance():
    backend = lambda **_kwargs: [
        {"text": "Calcium handling differed.", "locator": "Results p2", "section": "Results", "score": 0.91}
    ]
    retriever = PaperQA2Retriever(backend=backend, backend_id="paperqa2-fixture/v1")
    items = retriever.retrieve(paper=_paper(), question="How is calcium handling adapted?")
    assert len(items) == 1
    item = validate_paperqa2_candidate(items[0])
    assert item["schema_version"] == PAPERQA2_CANDIDATE_SCHEMA_VERSION
    assert item["verification_status"] == "UNVERIFIED"
    assert item["retrieval"]["engine"] == "paperqa2"
    assert item["retrieval"]["backend_id"] == "paperqa2-fixture/v1"
    assert item["retrieval"]["source_identity"]["pmcid"] == "PMC1"
    assert "role" not in item


def test_paperqa2_cannot_self_certify_located_evidence():
    backend = lambda **_kwargs: [
        {
            "text": "Claim.", "locator": "p1", "section": "Results",
            "verification_status": "LOCATED",
        }
    ]
    with pytest.raises(curie.CurieContractError, match="verification|self-certify|UNVERIFIED"):
        PaperQA2Retriever(backend=backend).retrieve(paper=_paper(), question="q")


def test_paperqa2_backend_failure_uses_only_explicit_declared_fallback():
    def failing(**_kwargs):
        raise RuntimeError("backend unavailable")

    fallback_calls = []

    class Fallback:
        def retrieve(self, *, paper, question):
            fallback_calls.append((paper["paper_id"], question))
            return [{
                "schema_version": "L05EvidenceCandidate/v1",
                "evidence_id": "EC_FALLBACK",
                "paper_id": paper["paper_id"],
                "section": "Results",
                "text": "Fallback candidate.",
                "locator": "p1",
                "verification_status": "UNVERIFIED",
                "retrieval": {"engine": "fallback", "source_identity": {"pmcid": "PMC1"}},
            }]

    result = retrieve_with_declared_fallback(
        primary=PaperQA2Retriever(backend=failing),
        fallback=Fallback(),
        paper=_paper(),
        question="q",
    )
    assert result["route"] == "fallback"
    assert result["primary_failure"]["engine"] == "paperqa2"
    assert fallback_calls == [("P1", "q")]
    assert result["candidates"][0]["verification_status"] == "UNVERIFIED"


def test_paperqa2_failure_without_fallback_is_explicit_insufficient_not_silent():
    def failing(**_kwargs):
        raise RuntimeError("backend unavailable")

    result = retrieve_with_declared_fallback(
        primary=PaperQA2Retriever(backend=failing),
        fallback=None,
        paper=_paper(),
        question="q",
    )
    assert result["route"] == "INSUFFICIENT"
    assert result["candidates"] == []
    assert "backend unavailable" in result["primary_failure"]["reason"]


def test_paperqa2_rejects_missing_locator_or_text():
    retriever = PaperQA2Retriever(backend=lambda **_kwargs: [{"text": "Claim"}])
    with pytest.raises(curie.CurieContractError, match="locator"):
        retriever.retrieve(paper=_paper(), question="q")
