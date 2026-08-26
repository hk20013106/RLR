import research_loop.l05_curie as curie
from research_loop.l05_curie import europepmc_runtime
from research_loop.l05_curie.paperqa2_runtime import (
    MIN_SOURCE_TOKEN_COVERAGE,
    align_paperqa2_chunks,
)


def _located(evidence_id: str, text: str, locator: str) -> dict:
    return {
        "schema_version": curie.EVIDENCE_EXTRACT_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "paper_id": "P1",
        "section": "Results",
        "text": text,
        "locator": locator,
        "role": "CONTEXT",
        "verification_status": "LOCATED",
        "retrieval": {"engine": "fixture", "source_sha256": "a" * 64},
    }


def test_alignment_keeps_strongest_chunk_per_locator_and_versions_provenance():
    chunks = [
        {
            "text": "WGCNA pseudocell unrelated filler",
            "locator": "PDF chunk 0",
            "score": 0.6,
        },
        {
            "text": "WGCNA pseudocell module detection",
            "locator": "PDF chunk 1",
            "score": 0.9,
        },
    ]
    source_candidates = [{
        "paper_id": "P1",
        "text": "WGCNA pseudocell module detection",
        "section": "Methods",
        "locator": "sec:7/p:7",
    }]

    aligned = align_paperqa2_chunks(chunks=chunks, source_candidates=source_candidates)

    assert len(aligned) == 1
    assert aligned[0]["source_alignment"]["chunk_index"] == 1
    assert aligned[0]["source_alignment"]["source_token_coverage"] == 1.0
    assert aligned[0]["source_alignment"]["method"] == "token-coverage-multimatch/v2"


def test_confusable_above_threshold_extract_requires_real_semantic_authorization():
    helper = getattr(europepmc_runtime, "_admit_paperqa2_semantic_evidence", None)
    assert callable(helper), (
        "production PaperQA2 acquisition must have an explicit semantic-admission helper "
        "instead of self-claiming each LOCATED extract"
    )

    source_candidates = [
        {
            "paper_id": "P1",
            "text": "WGCNA pseudocells were constructed before module detection and GO enrichment.",
            "section": "Methods",
            "locator": "sec:7/p:7",
        },
        {
            "paper_id": "P1",
            "text": (
                "WGCNA modules were visualized in a generic network figure without "
                "describing the pseudocell workflow."
            ),
            "section": "Results",
            "locator": "sec:7/p:9",
        },
    ]
    aligned = align_paperqa2_chunks(
        chunks=[{
            "text": (
                "WGCNA pseudocells were constructed before module detection and GO enrichment. "
                "WGCNA modules were visualized in a generic network figure."
            ),
            "locator": "PDF pages 7-9",
            "score": 0.9,
        }],
        source_candidates=source_candidates,
    )
    assert [item["locator"] for item in aligned] == ["sec:7/p:7", "sec:7/p:9"]
    assert all(
        item["source_alignment"]["source_token_coverage"] >= MIN_SOURCE_TOKEN_COVERAGE
        for item in aligned
    )

    target = _located("E_target", aligned[0]["text"], aligned[0]["locator"])
    confusable = _located("E_confusable", aligned[1]["text"], aligned[1]["locator"])
    semantic_target = (
        "Scientific question: How was the scWGCNA workflow implemented?\n"
        "Hypothesis seed: The workflow constructs pseudocells before WGCNA module detection."
    )
    seen_claims = []

    def assessor(*, extract, claim):
        seen_claims.append((extract["evidence_id"], claim))
        if extract["evidence_id"] == "E_target":
            return {
                "entailment": "SUPPORTED",
                "scope_match": True,
                "context_preserved": True,
                "qualification_preserved": True,
                "reason": "The methods paragraph directly describes the requested workflow.",
            }
        return {
            "entailment": "UNRELATED",
            "scope_match": True,
            "context_preserved": True,
            "qualification_preserved": True,
            "reason": "Shared WGCNA vocabulary does not make the figure paragraph evidence for the workflow.",
        }

    admitted, admitted_semantics, all_semantics = helper(
        [target, confusable],
        semantic_target=semantic_target,
        assessor=assessor,
        assessor_id="fixture-semantic-assessor/v1",
    )

    assert [item["evidence_id"] for item in admitted] == ["E_target"]
    assert [item["evidence_id"] for item in admitted_semantics] == ["E_target"]
    assert {item["evidence_id"] for item in all_semantics} == {"E_target", "E_confusable"}
    assert all(claim == semantic_target for _evidence_id, claim in seen_claims)
    assert all(claim != extract["text"] for extract, (_evidence_id, claim) in zip(
        [target, confusable], seen_claims, strict=True
    ))
