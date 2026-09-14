import copy

import pytest

from research_loop import deep_research as dr
from research_loop import l4_evidence_bundle as bundle
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p
from research_loop.l05_curie import europepmc
from research_loop.l05_curie.contracts import CurieContractError
from research_loop.l05_curie.paperqa2_runtime import (
    PaperQA2CurieRuntime,
    PaperQA2ExecutionError,
    PaperQA2IntegrityError,
)


METHOD_TEXT = (
    "Single-cell transcriptomes were normalized, homologous cell types were "
    "matched across species, gene co-expression modules were estimated, and "
    "module preservation was evaluated across developmental stages. " * 12
)
XML = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<article><front><article-meta>"
    "<article-id pub-id-type='doi'>10.1002/dvdy.384</article-id>"
    "<article-id pub-id-type='pmid'>34114716</article-id>"
    "<article-id pub-id-type='pmcid'>PMC9545966</article-id>"
    "</article-meta></front><body>"
    "<sec id='procedures'><title>EXPERIMENTAL PROCEDURES</title>"
    f"<p>{METHOD_TEXT}</p></sec>"
    "<sec><title>Results</title><p>Observed developmental patterns.</p></sec>"
    "</body></article>"
)
METHOD_XML = XML.replace("EXPERIMENTAL PROCEDURES", "Materials and methods")


def _receipt():
    return dr.skill_receipt("codex", ["codex", "exec"], "inventory", "test")


def _asset():
    return {
        "asset_id": "L05_P_526704b9fe982d2a0cb7",
        "doi": "10.1002/dvdy.384",
        "pmid": "34114716",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9545966/",
        "title": "Assessing evolutionary and developmental transcriptome dynamics in homologous cell types",
        "year": 2021,
        "role": "method",
        "journal": "Developmental Dynamics",
        "abstract": "",
        "source_database": "frozen_l05_evidence_pack",
        "source_metadata_response": {
            "paper_id": "P_526704b9fe982d2a0cb7",
            "pmcid": "PMC9545966",
        },
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": [
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9545966/fullTextXML"
        ],
        "relevance_score": 10.0,
        "selection_status": "selected",
        "selection_reason": "Exact source referenced by method inventory.",
        "hypothesis_ids": [],
        "method_component_hints": ["cross_species_single_cell_workflow"],
        "diagnostic_requirements": [],
    }


def _method():
    return {
        "method_id": "cross_species_single_cell_workflow",
        "name": "cross-species single-cell transcriptome workflow",
        "purpose": "Compare homologous cell types and co-expression modules across species.",
        "inventory_reason": "The selected claim requires an auditable cross-species workflow.",
        "source_asset_ids": ["L05_P_526704b9fe982d2a0cb7"],
        "source_hints": [],
    }


def _manifest(project):
    return l4_inventory.persist_discovery(
        l4p,
        dr,
        project,
        "C1",
        {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "queries": [{
                "query_id": "Q1",
                "query": "offline method inventory",
                "purpose": "Inventory only.",
                "status": "completed",
                "receipt": "fixture",
            }],
            "assets": [_asset()],
            "method_inventory": [_method()],
        },
        _receipt(),
        question="How should homologous cell types be compared across species?",
        claim="Cross-species developmental programs can be compared at single-cell resolution.",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )


def _fetch(url, payload=XML):
    return {
        "requested_url": url,
        "resolved_url": url,
        "redirect_chain": [],
        "http_status": 200,
        "content_type": "application/xml",
        "body": payload.encode("utf-8"),
    }


def _completed_l4b_runs(project):
    runs_dir = (
        project / "09_Literature_Database" / "evidence_packs" / "runs"
    )
    return list(runs_dir.glob("*_L4_*.json"))


class _FailingPaperQA2Runtime:
    def __init__(self, failure):
        self.failure = failure

    def retrieve_and_verify(self, **_kwargs):
        raise self.failure


def test_jats_paragraph_owner_exposes_experimental_procedures_without_heading_allowlist():
    paragraphs = europepmc.parse_jats_paragraphs(XML.encode("utf-8"))

    target = next(item for item in paragraphs if item["section"] == "EXPERIMENTAL PROCEDURES")
    assert target["text"] == METHOD_TEXT.strip()
    assert target["locator"].startswith("sec:")


def test_native_l4b_uses_paperqa2_then_independent_jats_verifier(tmp_path, l4_paperqa2_runtime):
    manifest = _manifest(tmp_path)
    runtime, calls = l4_paperqa2_runtime(METHOD_TEXT)

    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        tmp_path,
        "C1",
        manifest,
        tmp_path / "work",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
        fetcher=lambda url: _fetch(url, METHOD_XML),
        paperqa_runtime=runtime,
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["paper"]["paper_id"] == "P_526704b9fe982d2a0cb7"
    assert call["paper"]["media_type"] == "application/xml"
    assert call["paper"]["document_path"].endswith(".xml")
    assert len(artifact["evidence_cards"]) == 1
    card = artifact["evidence_cards"][0]
    assert card["paper_id"] == "P_526704b9fe982d2a0cb7"
    assert card["section"] == "Materials and methods"
    assert artifact["evidence_gaps"] == []
    assert bundle.audit_bundle(l4p, dr, tmp_path, "C1", artifact) == (True, "")


def test_native_l4b_classifies_experimental_procedures_as_methods(tmp_path, l4_paperqa2_runtime):
    manifest = _manifest(tmp_path)
    runtime, calls = l4_paperqa2_runtime(METHOD_TEXT)

    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        tmp_path,
        "C1",
        manifest,
        tmp_path / "work",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
        fetcher=_fetch,
        paperqa_runtime=runtime,
    )

    assert len(calls) == 1
    assert calls[0]["paper"]["paper_id"] == "P_526704b9fe982d2a0cb7"
    assert len(artifact["evidence_cards"]) == 1
    assert artifact["evidence_cards"][0]["section"] == "EXPERIMENTAL PROCEDURES"
    assert artifact["evidence_gaps"] == []
    assert bundle.audit_bundle(l4p, dr, tmp_path, "C1", artifact) == (True, "")


def test_native_l4b_does_not_assign_method_role_to_experimental_results(tmp_path, l4_paperqa2_runtime):
    manifest = _manifest(tmp_path)
    runtime, calls = l4_paperqa2_runtime(METHOD_TEXT)

    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        tmp_path,
        "C1",
        manifest,
        tmp_path / "work",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
        fetcher=lambda url: _fetch(url, XML.replace("EXPERIMENTAL PROCEDURES", "EXPERIMENTAL RESULTS")),
        paperqa_runtime=runtime,
    )

    assert calls == []
    assert artifact["evidence_cards"] == []
    assert len(artifact["evidence_gaps"]) == 1
    assert "Methods" in artifact["evidence_gaps"][0]["failure_reason"]


def test_native_l4b_missing_runtime_fails_before_persistence(tmp_path):
    manifest = _manifest(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    with pytest.raises(dr.DeepResearchError, match="PaperQA2"):
        bundle.run_l4b_evidence(
            l4p,
            dr,
            tmp_path,
            "C1",
            manifest,
            tmp_path / "work",
            project_id="P1",
            round_id="1",
            profile_id="v2.1-catalog-1",
            fetcher=lambda url: _fetch(url, METHOD_XML),
            paperqa_runtime=None,
        )

    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_l4b_source_failure_does_not_block_another_accepted_card(tmp_path):
    source_a = _asset()
    source_b = copy.deepcopy(source_a)
    source_b.update({
        "asset_id": "L05_P_second_source",
        "doi": "10.1000/second-source",
        "pmid": "22222222",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC2222222/",
        "title": "Second exact method source",
        "full_text_locations": [
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC2222222/fullTextXML"
        ],
        "source_metadata_response": {
            "paper_id": "P_second_source",
            "pmcid": "PMC2222222",
        },
    })
    method_a = _method()
    method_a.update({
        "method_id": "source_local_gap",
        "purpose": "Question with no aligned source evidence.",
        "source_asset_ids": [source_a["asset_id"]],
    })
    method_b = _method()
    method_b.update({
        "method_id": "accepted_method",
        "purpose": "Question with aligned Methods evidence.",
        "source_asset_ids": [source_b["asset_id"]],
    })
    manifest = l4_inventory.persist_discovery(
        l4p,
        dr,
        tmp_path,
        "C1",
        {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "queries": [{
                "query_id": "Q1",
                "query": "offline method inventory",
                "purpose": "Inventory only.",
                "status": "completed",
                "receipt": "fixture",
            }],
            "assets": [source_a, source_b],
            "method_inventory": [method_a, method_b],
        },
        _receipt(),
        question="Which exact sources support the two methods?",
        claim="Each method has its own exact source.",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )
    calls = []

    def backend(*, paper, question):
        calls.append({"paper": dict(paper), "question": question})
        text = (
            "This unrelated discussion cannot align to the Methods source."
            if question == method_a["purpose"]
            else METHOD_TEXT
        )
        return [{
            "text": text,
            "section": "PaperQA2",
            "locator": "paperqa2-test/chunk:1",
            "score": 1.0,
        }]

    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        tmp_path,
        "C1",
        manifest,
        tmp_path / "work",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
        fetcher=lambda url: _fetch(url, METHOD_XML),
        paperqa_runtime=PaperQA2CurieRuntime(
            backend=backend,
            backend_id="paperqa2-test/v1",
        ),
    )

    assert len(calls) == 2
    assert [card["method_id"] for card in artifact["evidence_cards"]] == [
        "accepted_method"
    ]
    assert [gap["method_id"] for gap in artifact["evidence_gaps"]] == [
        "source_local_gap"
    ]
    assert artifact["evidence_gaps"][0]["failure_reason"] == (
        "PaperQA2 retrieved chunks could not align to source candidates"
    )
    assert bundle.audit_bundle(l4p, dr, tmp_path, "C1", artifact) == (True, "")


def test_l4b_execution_failure_does_not_become_evidence_gap(tmp_path):
    manifest = _manifest(tmp_path)
    failure = PaperQA2ExecutionError("PaperQA2 process failed")

    with pytest.raises(PaperQA2ExecutionError) as raised:
        bundle.run_l4b_evidence(
            l4p,
            dr,
            tmp_path,
            "C1",
            manifest,
            tmp_path / "work",
            fetcher=lambda url: _fetch(url, METHOD_XML),
            paperqa_runtime=_FailingPaperQA2Runtime(failure),
        )

    assert raised.value is failure
    assert _completed_l4b_runs(tmp_path) == []


def test_l4b_integrity_failure_does_not_become_evidence_gap(tmp_path):
    manifest = _manifest(tmp_path)
    failure = PaperQA2IntegrityError("PaperQA2 document hash mismatch")

    with pytest.raises(PaperQA2IntegrityError) as raised:
        bundle.run_l4b_evidence(
            l4p,
            dr,
            tmp_path,
            "C1",
            manifest,
            tmp_path / "work",
            fetcher=lambda url: _fetch(url, METHOD_XML),
            paperqa_runtime=_FailingPaperQA2Runtime(failure),
        )

    assert raised.value is failure
    assert _completed_l4b_runs(tmp_path) == []


def test_l4b_unknown_contract_failure_does_not_become_evidence_gap(tmp_path):
    manifest = _manifest(tmp_path)
    failure = CurieContractError("unclassified PaperQA2 contract failure")

    with pytest.raises(CurieContractError) as raised:
        bundle.run_l4b_evidence(
            l4p,
            dr,
            tmp_path,
            "C1",
            manifest,
            tmp_path / "work",
            fetcher=lambda url: _fetch(url, METHOD_XML),
            paperqa_runtime=_FailingPaperQA2Runtime(failure),
        )

    assert raised.value is failure
    assert _completed_l4b_runs(tmp_path) == []


def test_l4b_verifier_failure_does_not_become_evidence_gap(
    monkeypatch, tmp_path, l4_paperqa2_runtime
):
    manifest = _manifest(tmp_path)
    failure = RuntimeError("independent verifier failed")

    def fail_verification(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(europepmc, "verify_jats_candidates", fail_verification)
    runtime = l4_paperqa2_runtime(METHOD_TEXT)[0]

    with pytest.raises(RuntimeError) as raised:
        bundle.run_l4b_evidence(
            l4p,
            dr,
            tmp_path,
            "C1",
            manifest,
            tmp_path / "work",
            fetcher=lambda url: _fetch(url, METHOD_XML),
            paperqa_runtime=runtime,
        )

    assert raised.value is failure
    assert _completed_l4b_runs(tmp_path) == []


def test_l4b_available_runtime_can_complete_with_only_truthful_gaps(tmp_path):
    manifest = _manifest(tmp_path)
    calls = []

    def backend(*, paper, question):
        calls.append({"paper": dict(paper), "question": question})
        return [{
            "text": "An unrelated discussion without matching Methods content.",
            "section": "PaperQA2",
            "locator": "paperqa2-test/chunk:1",
            "score": 1.0,
        }]

    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        tmp_path,
        "C1",
        manifest,
        tmp_path / "work",
        fetcher=lambda url: _fetch(url, METHOD_XML),
        paperqa_runtime=PaperQA2CurieRuntime(
            backend=backend,
            backend_id="paperqa2-test/v1",
        ),
    )

    assert len(calls) == 1
    assert artifact["status"] == "completed"
    assert artifact["evidence_cards"] == []
    assert len(artifact["evidence_gaps"]) == 1
    assert artifact["evidence_gaps"][0]["failure_reason"] == (
        "PaperQA2 retrieved chunks could not align to source candidates"
    )
    assert bundle.audit_bundle(l4p, dr, tmp_path, "C1", artifact) == (True, "")
