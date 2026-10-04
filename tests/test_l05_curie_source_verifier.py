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


def test_independent_source_verifier_preserves_paperqa2_runtime_provenance():
    candidate = _candidate()
    candidate["retrieval"]["runtime"] = {
        "schema_version": "PaperQA2Runtime/v1",
        "package": "paper-qa",
        "version": "2026.8.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
    }
    candidate["retrieval"]["paperqa2"] = {
        "chunk_locator": "Positive pages 1-1",
        "chunk_sha256": "a" * 64,
    }
    extract = ExactTextSourceVerifier().verify(
        candidate,
        source_bytes=b"Calcium handling differed under exercise.",
        role="CONTEXT",
    )
    assert extract["retrieval"]["runtime"]["upstream_commit"].startswith("57e89f")
    assert extract["retrieval"]["paperqa2"]["chunk_locator"] == "Positive pages 1-1"


def test_independent_source_verifier_fails_when_exact_text_has_ambiguous_locations():
    text = b"Calcium handling differed under exercise."
    with pytest.raises(curie.CurieContractError, match="ambiguous|multiple|location"):
        ExactTextSourceVerifier().verify(
            _candidate(), source_bytes=text + b" spacer " + text, role="CONTEXT"
        )


def _jats_candidate(locator="sec:1/p:1", text="same", section="A"):
    from research_loop.l05_curie.europepmc import EVIDENCE_CANDIDATE_SCHEMA_VERSION
    return {"schema_version": EVIDENCE_CANDIDATE_SCHEMA_VERSION, "candidate_extract_id": "EC1",
            "paper_id": "P1", "locator": locator, "text": text, "section": section,
            "role": "CONTEXT", "verification_status": "UNVERIFIED", "retrieval": {}}


def test_v1_ancestor_locator_still_verifies():
    from research_loop.l05_curie.europepmc import verify_jats_candidates
    raw = b'<article><body><sec><title>A</title><sec><title>B</title><p>same</p></sec></sec></body></article>'
    assert verify_jats_candidates(raw, [_jats_candidate()], paper_id="P1")[0]["locator"] == "sec:1/p:1"
    assert verify_jats_candidates(raw, [_jats_candidate("sec:2/p:1", section="B")], paper_id="P1",
                                  parser_profile="jats-paragraphs/v2")[0]["locator"] == "sec:2/p:1"


@pytest.mark.parametrize("field,value", [("locator", "missing"), ("text", "wrong"), ("section", "wrong")])
def test_v2_only_known_source_mismatch_is_local(field, value):
    from research_loop.l05_curie import europepmc
    mismatch = getattr(europepmc, "JatsSourceMismatchError", None)
    assert isinstance(mismatch, type), "missing planned typed mismatch"
    raw = b'<article><body><sec><title>A</title><p>same</p></sec></body></article>'
    candidate = _jats_candidate()
    candidate[field] = value
    with pytest.raises(mismatch):
        europepmc.verify_jats_candidates(raw, [candidate], paper_id="P1", parser_profile="jats-paragraphs/v2")
    candidate["paper_id"] = "OTHER"
    with pytest.raises(curie.CurieContractError) as caught:
        europepmc.verify_jats_candidates(raw, [candidate], paper_id="P1", parser_profile="jats-paragraphs/v2")
    assert not isinstance(caught.value, mismatch)
