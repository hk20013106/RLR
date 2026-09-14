import hashlib
import json
import sys
from pathlib import Path

import pytest

from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.paperqa2 import PaperQA2Retriever
from research_loop.l05_curie.paperqa2_runtime import (
    PaperQA2CurieRuntime,
    PaperQA2ExecutionError,
    PaperQA2IntegrityError,
    PaperQA2SourceError,
    PaperQA2SubprocessBackend,
    align_paperqa2_chunks,
)
from research_loop.process_runner import ProcessResult


class _ControlledRunner:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error

    def run(self, *_args, **_kwargs):
        if self.error is not None:
            raise self.error
        return self.result


def _process_result(
    *, returncode=0, terminal_state="completed", stdout="", stderr=""
):
    return ProcessResult(
        returncode=returncode,
        terminal_state=terminal_state,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_bytes=len(stdout.encode("utf-8")),
        stderr_bytes=len(stderr.encode("utf-8")),
        timeout_seconds=300,
        process_tree_cleanup={
            "attempted": False,
            "targeted_pids": [],
            "terminated_pids": [],
            "killed_pids": [],
            "errors": [],
            "alive_after_cleanup": False,
        },
    )


def _backend(tmp_path, runner):
    bridge = tmp_path / "bridge.py"
    bridge.touch()
    return PaperQA2SubprocessBackend(
        python_executable=sys.executable,
        bridge_script=bridge,
        paperqa_repo=tmp_path,
        pqa_home=tmp_path / "pqa-home",
        runner=runner,
    )


def _pdf_payload(paper, **runtime_overrides):
    pdf_sha256 = hashlib.sha256(Path(paper["pdf_path"]).read_bytes()).hexdigest()
    runtime = {
        "schema_version": "PaperQA2Runtime/v1",
        "package": "paper-qa",
        "version": "2026.8.12",
        "upstream_repo": "https://github.com/Future-House/paper-qa",
        "upstream_tag": "v2026.08.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
        "fork_repo": "https://github.com/hk20013106/paper-qa",
        "pdf_sha256": pdf_sha256,
    }
    runtime.update(runtime_overrides)
    return json.dumps({
        "engine": "paperqa2",
        "runtime": runtime,
        "hits": [{
            "text": "The bat TRIM family contains 70 members.",
            "locator": "Positive pages 1-1",
            "section": "PaperQA2",
            "score": 0.42,
        }],
    })


def _document_payload(paper, **runtime_overrides):
    document_sha256 = hashlib.sha256(
        Path(paper["document_path"]).read_bytes()
    ).hexdigest()
    runtime = {
        "schema_version": "PaperQA2Runtime/v2",
        "package": "paper-qa",
        "version": "2026.8.12",
        "upstream_repo": "https://github.com/Future-House/paper-qa",
        "upstream_tag": "v2026.08.12",
        "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
        "fork_repo": "https://github.com/hk20013106/paper-qa",
        "document_sha256": document_sha256,
        "media_type": paper["media_type"],
    }
    runtime.update(runtime_overrides)
    return json.dumps({
        "engine": "paperqa2",
        "runtime": runtime,
        "hits": [{
            "text": "Exact method details.",
            "locator": "P1 chunk 1",
            "section": "PaperQA2",
            "score": 0.9,
        }],
    })


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
        )


def test_backend_start_failure_is_not_source_error(tmp_path):
    backend = _backend(
        tmp_path,
        _ControlledRunner(error=OSError("controlled launch failure")),
    )

    with pytest.raises(CurieContractError) as exc_info:
        backend(paper=_paper(tmp_path), question="Locate the method.")

    assert isinstance(exc_info.value, PaperQA2ExecutionError)
    assert not isinstance(exc_info.value, PaperQA2SourceError)


def test_outer_process_timeout_is_not_source_error(tmp_path):
    backend = _backend(
        tmp_path,
        _ControlledRunner(
            result=_process_result(returncode=None, terminal_state="timed_out")
        ),
    )

    with pytest.raises(CurieContractError) as exc_info:
        backend(paper=_paper(tmp_path), question="Locate the method.")

    assert isinstance(exc_info.value, PaperQA2ExecutionError)
    assert not isinstance(exc_info.value, PaperQA2SourceError)


def test_nonzero_exit_without_valid_response_is_not_source_error(tmp_path):
    backend = _backend(
        tmp_path,
        _ControlledRunner(
            result=_process_result(
                returncode=7,
                stdout="",
                stderr="document-specific wording must not control taxonomy",
            )
        ),
    )

    with pytest.raises(CurieContractError) as exc_info:
        backend(paper=_paper(tmp_path), question="Locate the method.")

    assert isinstance(exc_info.value, PaperQA2ExecutionError)
    assert not isinstance(exc_info.value, PaperQA2SourceError)


def test_invalid_bridge_json_is_not_source_error(tmp_path):
    backend = _backend(
        tmp_path,
        _ControlledRunner(
            result=_process_result(returncode=0, stdout="not-json")
        ),
    )

    with pytest.raises(CurieContractError) as exc_info:
        backend(paper=_paper(tmp_path), question="Locate the method.")

    assert isinstance(exc_info.value, PaperQA2ExecutionError)
    assert not isinstance(exc_info.value, PaperQA2SourceError)


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


def test_pinned_runtime_mismatch_is_integrity_fatal(tmp_path):
    paper = _paper(tmp_path)
    backend = _backend(
        tmp_path,
        _ControlledRunner(
            result=_process_result(
                stdout=_pdf_payload(
                    paper,
                    fork_repo="https://github.com/untrusted/paper-qa",
                )
            )
        ),
    )

    with pytest.raises(CurieContractError, match="fork") as exc_info:
        backend(paper=paper, question="Locate the method.")

    assert isinstance(exc_info.value, PaperQA2IntegrityError)
    assert not isinstance(exc_info.value, PaperQA2SourceError)


@pytest.mark.parametrize(
    ("runtime_overrides", "message"),
    [
        ({"document_sha256": "0" * 64}, "document hash"),
        ({"media_type": "text/plain"}, "media_type"),
    ],
)
def test_document_hash_or_media_type_mismatch_is_integrity_fatal(
    tmp_path,
    runtime_overrides,
    message,
):
    document = tmp_path / "paper.xml"
    document.write_text(
        "<article><body>Exact method details.</body></article>",
        encoding="utf-8",
    )
    paper = {
        "paper_id": "P1",
        "title": "Method paper",
        "identifiers": {"pmcid": "PMC1"},
        "document_path": str(document),
        "media_type": "application/xml",
    }
    backend = _backend(
        tmp_path,
        _ControlledRunner(
            result=_process_result(
                stdout=_document_payload(paper, **runtime_overrides)
            )
        ),
    )

    with pytest.raises(CurieContractError, match=message) as exc_info:
        backend(paper=paper, question="Locate the method.")

    assert isinstance(exc_info.value, PaperQA2IntegrityError)
    assert not isinstance(exc_info.value, PaperQA2SourceError)


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


def test_source_alignment_emits_all_source_candidates_in_one_cross_page_chunk():
    chunks = [{
        "text": (
            "The first workflow paragraph describes WGCNA pseudocells and "
            "the second figure paragraph describes WGCNA module outputs."
        ),
        "locator": "Paper pages 5-6",
        "section": "PaperQA2",
        "score": 0.8,
    }]
    source_candidates = [
        {
            "paper_id": "P1",
            "text": "The first workflow paragraph describes WGCNA pseudocells.",
            "section": "Results",
            "locator": "sec:7/p:7",
        },
        {
            "paper_id": "P1",
            "text": "The second figure paragraph describes WGCNA module outputs.",
            "section": "Results",
            "locator": "sec:7/p:9",
        },
    ]

    aligned = align_paperqa2_chunks(
        chunks=chunks,
        source_candidates=source_candidates,
    )

    assert [item["locator"] for item in aligned] == ["sec:7/p:7", "sec:7/p:9"]


def test_source_alignment_keeps_strongest_chunk_per_locator_and_versions_provenance():
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


def test_source_alignment_drops_below_threshold_candidates():
    chunks = [{"text": "workflow pseudocells module outputs", "locator": "pages 5-6", "score": 0.8}]
    source_candidates = [
        {
            "paper_id": "P1",
            "text": "workflow pseudocells module outputs",
            "section": "Results",
            "locator": "sec:7/p:7",
        },
        {
            "paper_id": "P1",
            "text": "unrelated calcium phenotype",
            "section": "Discussion",
            "locator": "sec:9/p:2",
        },
    ]

    aligned = align_paperqa2_chunks(
        chunks=chunks,
        source_candidates=source_candidates,
    )

    assert [item["locator"] for item in aligned] == ["sec:7/p:7"]


def test_source_alignment_deduplicates_repeated_source_locator():
    chunks = [{"text": "WGCNA pseudocells", "locator": "pages 5-6", "score": 0.8}]
    source_candidates = [
        {
            "paper_id": "P1",
            "text": "WGCNA pseudocells",
            "section": "Results",
            "locator": "sec:7/p:7",
        },
        {
            "paper_id": "P1",
            "text": "WGCNA pseudocells in single cells",
            "section": "Results",
            "locator": "sec:7/p:7",
        },
    ]

    aligned = align_paperqa2_chunks(
        chunks=chunks,
        source_candidates=source_candidates,
    )

    assert [item["locator"] for item in aligned] == ["sec:7/p:7"]


def test_source_alignment_rejects_unrelated_source_candidates():
    chunks = [{"text": "WGCNA pseudocells", "locator": "pages 5-6", "score": 0.8}]
    source_candidates = [{
        "paper_id": "P1",
        "text": "unrelated calcium phenotype",
        "section": "Discussion",
        "locator": "sec:9/p:2",
    }]

    with pytest.raises(CurieContractError, match="could not align"):
        align_paperqa2_chunks(
            chunks=chunks,
            source_candidates=source_candidates,
        )


def test_normal_no_alignment_is_source_error(tmp_path):
    paper = _paper(tmp_path)
    backend = _backend(
        tmp_path,
        _ControlledRunner(
            result=_process_result(stdout=_pdf_payload(paper))
        ),
    )
    runtime = PaperQA2CurieRuntime(
        backend=backend,
        backend_id="paperqa2-fork-v2026.08.12/sparse-docs-v1",
    )

    with pytest.raises(CurieContractError, match="could not align") as exc_info:
        runtime.retrieve_and_verify(
            paper=paper,
            question="Locate the method.",
            source_candidates=[{
                "paper_id": "P1",
                "text": "unrelated calcium phenotype",
                "section": "Discussion",
                "locator": "sec:9/p:2",
            }],
            verify=lambda _candidates: pytest.fail(
                "verifier must not run without an aligned source candidate"
            ),
        )

    assert isinstance(exc_info.value, PaperQA2SourceError)


def test_verifier_failure_is_not_source_error(tmp_path):
    paper = _paper(tmp_path)
    backend = _backend(
        tmp_path,
        _ControlledRunner(
            result=_process_result(stdout=_pdf_payload(paper))
        ),
    )
    runtime = PaperQA2CurieRuntime(
        backend=backend,
        backend_id="paperqa2-fork-v2026.08.12/sparse-docs-v1",
    )
    verifier_failure = CurieContractError("controlled verifier integrity failure")

    def fail_verification(_candidates):
        raise verifier_failure

    with pytest.raises(CurieContractError, match="verifier integrity") as exc_info:
        runtime.retrieve_and_verify(
            paper=paper,
            question="Locate the method.",
            source_candidates=[{
                "paper_id": "P1",
                "text": "The bat TRIM family contains 70 members.",
                "section": "Methods",
                "locator": "sec:methods/p:1",
            }],
            verify=fail_verification,
        )

    assert exc_info.value is verifier_failure
    assert not isinstance(exc_info.value, PaperQA2SourceError)


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
