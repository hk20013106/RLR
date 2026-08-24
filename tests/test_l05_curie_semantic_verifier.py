import pytest

import research_loop.l05_curie as curie
from research_loop.l05_curie.semantic_verifier import (
    SEMANTIC_VERIFICATION_SCHEMA_VERSION,
    SemanticEvidenceVerifier,
    reasoning_authorized,
    validate_semantic_verification,
)


def _extract(*, role="CONTEXT", status="LOCATED"):
    return {
        "schema_version": curie.EVIDENCE_EXTRACT_SCHEMA_VERSION,
        "evidence_id": "E1",
        "paper_id": "P1",
        "section": "Results",
        "text": "Calcium handling differed between groups under exercise.",
        "locator": "Results p2",
        "role": role,
        "verification_status": status,
        "retrieval": {"engine": "fixture", "source_sha256": "a" * 64},
    }


def _assessment(**overrides):
    value = {
        "entailment": "SUPPORTED",
        "scope_match": True,
        "context_preserved": True,
        "qualification_preserved": True,
        "reason": "The extract directly states the scoped result.",
    }
    value.update(overrides)
    return value


def test_semantic_verification_is_distinct_from_source_fidelity():
    verifier = SemanticEvidenceVerifier(assessor=lambda **_kwargs: _assessment())
    result = verifier.verify(
        _extract(),
        claim="Cardiac calcium handling differs under exercise.",
    )
    validated = validate_semantic_verification(result)
    assert validated["schema_version"] == SEMANTIC_VERIFICATION_SCHEMA_VERSION
    assert validated["source_fidelity"] == "PASS"
    assert validated["entailment"] == "SUPPORTED"
    assert validated["verdict"] == "PASS"
    assert reasoning_authorized(validated) is True


def test_semantic_verifier_refuses_unlocated_source_before_assessment():
    calls = []
    verifier = SemanticEvidenceVerifier(
        assessor=lambda **kwargs: calls.append(kwargs) or _assessment()
    )
    with pytest.raises(curie.CurieContractError, match="LOCATED|source fidelity"):
        verifier.verify(_extract(status="UNVERIFIED"), claim="claim")
    assert calls == []


def test_scope_or_qualification_loss_is_not_reasoning_authorized():
    verifier = SemanticEvidenceVerifier(
        assessor=lambda **_kwargs: _assessment(
            scope_match=False,
            qualification_preserved=False,
            reason="The source is narrower and qualified.",
        )
    )
    result = verifier.verify(_extract(), claim="Generalized claim")
    assert result["verdict"] == "FAIL"
    assert reasoning_authorized(result) is False


def test_ambiguous_evidence_is_preserved_but_not_authorized():
    verifier = SemanticEvidenceVerifier(
        assessor=lambda **_kwargs: _assessment(
            entailment="AMBIGUOUS",
            reason="The sentence allows multiple interpretations.",
        )
    )
    result = verifier.verify(_extract(), claim="claim")
    assert result["verdict"] == "AMBIGUOUS"
    assert reasoning_authorized(result) is False
    assert result["evidence_id"] == "E1"


def test_contradictory_evidence_can_pass_semantic_verification():
    verifier = SemanticEvidenceVerifier(
        assessor=lambda **_kwargs: _assessment(
            entailment="CONTRADICTED",
            reason="The source directly contradicts the evaluated claim.",
        )
    )
    result = verifier.verify(_extract(role="CONTRADICTORY"), claim="No difference exists.")
    assert result["verdict"] == "PASS"
    assert result["entailment"] == "CONTRADICTED"
    assert reasoning_authorized(result) is True


def test_semantic_assessor_cannot_change_evidence_identity_or_source_fidelity():
    verifier = SemanticEvidenceVerifier(
        assessor=lambda **_kwargs: {
            **_assessment(),
            "evidence_id": "FORGED",
            "source_fidelity": "FAIL",
        }
    )
    with pytest.raises(curie.CurieContractError, match="authority|evidence_id|source_fidelity"):
        verifier.verify(_extract(), claim="claim")
