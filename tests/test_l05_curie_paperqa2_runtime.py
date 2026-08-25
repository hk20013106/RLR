import json
import sys

import pytest

from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.paperqa2 import PaperQA2Retriever
from research_loop.l05_curie.paperqa2_runtime import (
    PaperQA2CurieRuntime,
    PaperQA2SubprocessBackend,
    align_paperqa2_chunks,
)


def _paper(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-real-paper")
    return {
        "paper_id": "P1",
        "title": "Bat TRIM paper",
        "identifiers": {"pmcid": "PMC1", "doi": "10.1000/trim"},
        "pdf_path": str(pdf),
    }


def test_external_backend_requires_real_runtime_paths(tmp_path):
    with pytest.raises(CurieContractError, match="python|bridge|runtime"):
        PaperQA2SubprocessBackend(
            python_executable=tmp_path / "missing-python.exe",
            bridge_script=tmp_path / "missing-bridge.py",
            paperqa_repo=tmp_path,
            pqa_home=tmp_path / "pqa-home",
            expected_commit="57e89f7223b0960d5ee5ea048c69e3c47e088572",
        )


def test_external_backend_preserves_exact_runtime_provenance(tmp_path):
    paper = _paper(tmp_path)
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        """
import json
import sys

request = json.load(sys.stdin)
print(json.dumps({
    "engine": "paperqa2",
    "runtime": {
        "schema_version": "PaperQA2Runtime/v1",
        "package": "paper-qa",
        "version": "2026.8.12",
        "upstream_repo": "https://github.com/Future-House/paper-qa",
        "upstream_tag": "v2026.08.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
        "fork_repo": "https://github.com/hk20013106/paper-qa",
        "pdf_sha256": "c9437bb067d5daab9c8a221cb4986ca4cf08bc0f247411d646e48f83bc1e7efe",
    },
    "hits": [{
        "text": "The bat TRIM family contains 70 members.",
        "locator": "Positive pages 1-1",
        "section": "PaperQA2",
        "score": 0.42,
    }],
}))
""",
        encoding="utf-8",
    )
    backend = PaperQA2SubprocessBackend(
        python_executable=sys.executable,
        bridge_script=bridge,
        paperqa_repo=tmp_path,
        pqa_home=tmp_path / "pqa-home",
        expected_commit="57e89f7223b0960d5ee5ea048c69e3c47e088572",
    )

    item = PaperQA2Retriever(
        backend=backend,
        backend_id="paperqa2-fork-v2026.08.12/sparse-docs-v1",
    ).retrieve(paper=paper, question="What is the bat TRIM family? ")[0]

    assert item["verification_status"] == "UNVERIFIED"
    assert item["retrieval"]["runtime"]["upstream_commit"] == (
        "57e89f7223b0960d5ee5ea048c69e3c47e088572"
    )
    assert item["retrieval"]["backend_id"].startswith("paperqa2-fork")
    assert "role" not in item


def test_source_alignment_emits_unverified_exact_source_candidates_without_role():
    runtime = {
        "schema_version": "PaperQA2Runtime/v1",
        "package": "paper-qa",
        "version": "2026.8.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
    }
    chunks = [{
        "text": "Abstract The bat TRIM family contains 70 members, with 24 under positive selection.",
        "locator": "Positive pages 1-1",
        "section": "PaperQA2",
        "score": 0.42,
        "runtime": runtime,
    }]
    source_candidates = [{
        "paper_id": "P1",
        "text": "The bat TRIM family contains 70 members, with 24 under positive selection.",
        "section": "Abstract",
        "locator": "sec:abstract/p:1",
    }]

    aligned = align_paperqa2_chunks(
        chunks=chunks,
        source_candidates=source_candidates,
    )

    assert aligned[0]["text"] == source_candidates[0]["text"]
    assert aligned[0]["locator"] == "sec:abstract/p:1"
    assert "role" not in aligned[0]
    assert "verification_status" not in aligned[0]
    assert aligned[0]["paperqa2"]["chunk_locator"] == "Positive pages 1-1"
    assert aligned[0]["runtime"] == runtime


def test_curie_runtime_keeps_unverified_boundary_before_verifier():
    paper = {
        "paper_id": "P1",
        "identifiers": {"pmcid": "PMC1"},
    }
    source_candidates = [{
        "text": "The bat TRIM family contains 70 members.",
        "section": "Results",
        "locator": "sec:1/p:1",
    }]
    result = PaperQA2CurieRuntime(
        backend=lambda **_kwargs: [{
            "text": "Results The bat TRIM family contains 70 members.",
            "section": "PaperQA2",
            "locator": "Positive pages 1-1",
            "score": 0.4,
        }],
        backend_id="paperqa2-test/v1",
    ).retrieve_and_verify(
        paper=paper,
        question="q",
        source_candidates=source_candidates,
        verify=lambda candidates: [{
            "verification_status": "LOCATED",
            "evidence_id": candidates[0]["evidence_id"],
        }],
    )

    assert result["unverified"][0]["verification_status"] == "UNVERIFIED"
    assert result["located"][0]["verification_status"] == "LOCATED"
    assert "role" not in result["unverified"][0]
