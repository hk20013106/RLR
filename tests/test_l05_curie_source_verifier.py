import pytest

import research_loop.l05_curie as curie
from research_loop.l05_curie.paperqa2 import PaperQA2Retriever
from research_loop.l05_curie.source_verifier import ExactTextSourceVerifier


def _candidate():
    paper = {
        "paper_id": "P1",
        "title": "Paper",
        "identifiers": {"doi": "10.1000/a"},
    }
    backend = lambda **_kwargs: [{
        "text": "Calcium handling differed under exercise.",
        "section": "Results",
        "locator": "Results p2",
    }]
    return PaperQA2Retriever(backend=backend).retrieve(paper=paper, question="q")[0]


def test_independent_source_verifier_promotes_only_exact_located_candidate():
    verifier = ExactTextSourceVerifier()
    extract = verifier.verify(
        _candidate(),
        source_bytes=b"Introduction. Calcium handling differed under exercise. Discussion.",
        role="CONTEXT",
    )
    assert extract["schema_version"] == curie.EVIDENCE_EXTRACT_SCHEMA_VERSION
    assert extract["verification_status"] == "LOCATED"
    assert extract["role"] == "CONTEXT"
    assert extract["locator"].startswith("char:")
    assert extract["retrieval"]["upstream_locator"] == "Results p2"
    assert len(extract["retrieval"]["source_sha256"]) == 64
    assert extract["retrieval"]["upstream_engine"] == "paperqa2"
    curie.validate_evidence_extract(extract)


def test_independent_source_verifier_fails_when_candidate_text_is_not_in_source():
    with pytest.raises(curie.CurieContractError, match="not located|source"):
        ExactTextSourceVerifier().verify(
            _candidate(), source_bytes=b"A different source text.", role="CONTEXT"
        )


def test_independent_source_verifier_requires_unverified_candidate():
    candidate = _candidate()
    candidate["verification_status"] = "LOCATED"
    with pytest.raises(curie.CurieContractError, match="UNVERIFIED"):
        ExactTextSourceVerifier().verify(candidate, source_bytes=b"Calcium handling differed under exercise.")


def test_independent_source_verifier_preserves_contradictory_role():
    extract = ExactTextSourceVerifier().verify(
        _candidate(),
        source_bytes=b"Calcium handling differed under exercise.",
        role="CONTRADICTORY",
    )
    assert extract["role"] == "CONTRADICTORY"


def test_independent_source_verifier_fails_when_exact_text_has_ambiguous_locations():
    text = b"Calcium handling differed under exercise."
    with pytest.raises(curie.CurieContractError, match="ambiguous|multiple|location"):
        ExactTextSourceVerifier().verify(
            _candidate(), source_bytes=text + b" spacer " + text, role="CONTEXT"
        )
