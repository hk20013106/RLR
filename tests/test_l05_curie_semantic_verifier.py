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


def _semantic(extract=None):
    return SemanticEvidenceVerifier(assessor=lambda **_kwargs: _assessment()).verify(
        extract or _extract(), claim="Cardiac calcium handling differs under exercise."
    )


def _pack_kwargs(semantic_verifications):
    return {
        "candidate_id": "C001",
        "round_id": "1",
        "seed_sha256": "b" * 64,
        "version": 1,
        "query_plans": [{
            "schema_version": curie.QUERY_PLAN_SCHEMA_VERSION,
            "candidate_id": "C001",
            "round_id": "1",
            "seed_sha256": "b" * 64,
            "plan_id": "QP1",
            "round_index": 1,
            "queries": [{
                "query_id": "Q1", "intent": "mechanism", "query": "q",
                "providers": ["fixture"],
            }],
        }],
        "discovery_receipts": [{
            "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": "fixture",
            "query_id": "Q1",
            "receipt": {"request_sha256": "1" * 64, "response_sha256": "2" * 64},
            "records": [],
        }],
        "selected_papers": [{
            "paper_id": "P1", "title": "Paper", "identifiers": {"doi": "10.1/a"},
            "selection": {"decision": "INCLUDE", "reason": "direct"},
        }],
        "evidence": [_extract()],
        "semantic_verifications": semantic_verifications,
        "coverage": curie.judge_coverage(
            {"covered": ["mechanism"], "gaps": []}, round_index=1, max_rounds=3
        ),
        "gaps": [],
    }


def test_semantic_verification_is_distinct_from_source_fidelity():
    result = _semantic()
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


def test_semantic_result_binds_policy_assessor_and_content_identity():
    result = _semantic()
    assert result["assessor_id"] == "semantic-assessor/v1"
    assert len(result["contract_sha256"]) == 64
    assert result["verification_id"].startswith("SV_")
    assert len(result["claim_sha256"]) == 64
    validate_semantic_verification(result)


def test_semantic_assessor_cannot_claim_provenance_authority():
    verifier = SemanticEvidenceVerifier(
        assessor=lambda **_kwargs: {
            **_assessment(),
            "assessor_id": "forged-assessor",
            "contract_sha256": "0" * 64,
        }
    )
    with pytest.raises(curie.CurieContractError, match="authority|assessor|contract"):
        verifier.verify(_extract(), claim="claim")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("assessor_id", "forged-assessor"),
        ("contract_sha256", "0" * 64),
        ("claim_sha256", "not-a-sha256"),
        ("verification_id", "SV_FORGED"),
    ],
)
def test_semantic_verification_rejects_tampered_provenance_identity(
    field, replacement
):
    result = _semantic()
    result[field] = replacement
    with pytest.raises(curie.CurieContractError, match="semantic|verification|contract|assessor|sha|identity"):
        validate_semantic_verification(result)


def test_evidence_pack_freezes_exact_semantic_admission_provenance(tmp_path):
    semantic = _semantic()
    pack = curie.build_evidence_pack(**_pack_kwargs([semantic]))
    assert pack["semantic_verifications"] == [semantic]
    manifest = curie.freeze_evidence_pack(tmp_path, pack)
    frozen = curie.load_frozen_evidence_pack(
        tmp_path, manifest, candidate_id="C001", round_id="1", seed_sha256="b" * 64
    )
    assert frozen["semantic_verifications"] == [semantic]


def test_evidence_pack_rejects_semantic_admission_missing_or_not_authorized():
    bad = _semantic()
    bad["verdict"] = "AMBIGUOUS"
    with pytest.raises(curie.CurieContractError, match="semantic|authorized"):
        curie.build_evidence_pack(**_pack_kwargs([bad]))

    other = _semantic()
    other["evidence_id"] = "OTHER"
    with pytest.raises(curie.CurieContractError, match="semantic|evidence"):
        curie.build_evidence_pack(**_pack_kwargs([other]))
