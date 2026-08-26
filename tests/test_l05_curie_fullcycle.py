from pathlib import Path
from types import SimpleNamespace

from research_loop import context, l0_contract, research_seed
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger
import research_loop.l05_curie as curie
from research_loop.l05_curie.multisource import (
    build_multisource_query_plan,
    canonicalize_crossref_record,
    canonicalize_pubmed_record,
    run_multisource_discovery,
)
from research_loop.l05_curie.native_runtime import (
    bind_initial_curie_pack,
    run_authorized_retry,
)
from research_loop.l05_curie.paperqa2 import PaperQA2Retriever
from research_loop.l05_curie.selector import select_candidates
from research_loop.l05_curie.semantic_verifier import (
    SemanticEvidenceVerifier,
    admit_reasoning_evidence,
)
from research_loop.l05_curie.source_verifier import ExactTextSourceVerifier


def _project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    source_input = l0_contract.build_source_input(
        input_type="inline", description="full-cycle fixture", fmt="text"
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            "C001", "1", "Why can bats sustain high heart rates?", source_input,
            "Cardiac calcium handling includes adaptive mechanisms.",
        )
    )
    contract_path, contract_hash = l0_contract.write_contract(project, "C001", contract)
    (candidate_dir / "C001.md").write_text(
        "---\n"
        "candidate_id: C001\n"
        "title: Full-cycle fixture\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"schema_version: {contract['schema_version']}\n"
        f"input_contract_path: {contract_path.relative_to(project).as_posix()}\n"
        f"input_contract_hash: {contract_hash}\n"
        "---\n",
        encoding="utf-8",
    )
    return project, store, research_seed.load_l1_research_seed(project, "C001")


class _StaticTransport:
    def __init__(self, provider, records):
        self.provider = provider
        self.records = records

    def handshake(self):
        return {
            "schema_version": curie.DISCOVERY_TRANSPORT_SCHEMA_VERSION,
            "provider": self.provider,
            "capabilities": ["search:fixture"],
        }

    def search(self, request):
        return {
            "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": self.provider,
            "query_id": request["query_id"],
            "receipt": {"request_sha256": "1" * 64, "response_sha256": "2" * 64},
            "records": self.records,
        }


def _acquire_round(project, seed, *, version, run_id, text, parent=None, gap_id=None):
    seed_hash = research_seed.seed_sha256(seed)
    plan = build_multisource_query_plan(
        seed,
        seed_sha256=seed_hash,
        round_index=version,
        explicit_queries=["bat cardiac calcium handling"],
        providers=["pubmed", "crossref"],
    )
    pubmed_record = canonicalize_pubmed_record({
        "uid": "123",
        "title": "Bat cardiac calcium physiology",
        "articleids": [
            {"idtype": "pubmed", "value": "123"},
            {"idtype": "doi", "value": "10.1000/bat"},
            {"idtype": "pmc", "value": "PMC123"},
        ],
    })
    pubmed_record["metadata"]["is_open_access"] = True
    pubmed_record["metadata"]["in_europe_pmc"] = True
    pubmed_record["provenance"]["originating_query_ids"] = ["Q001"]
    crossref_record = canonicalize_crossref_record({
        "DOI": "10.1000/bat",
        "title": ["Bat cardiac calcium physiology"],
        "published": {"date-parts": [[2025]]},
    })
    crossref_record["provenance"]["originating_query_ids"] = ["Q001"]
    discovery = run_multisource_discovery(
        plan,
        {
            "pubmed": _StaticTransport("pubmed", [pubmed_record]),
            "crossref": _StaticTransport("crossref", [crossref_record]),
        },
        seed_sha256=seed_hash,
    )
    assert len(discovery["records"]) == 1
    record = discovery["records"][0]
    record["provenance"]["originating_query_ids"] = ["Q001"]

    selection = select_candidates(
        [record],
        seed=seed,
        scorer=lambda _record, _seed: {
            "relevance": 1.0,
            "directness": 1.0,
            "methodological_value": 0.7,
            "contradiction_value": 0.2,
            "evidence_diversity": 0.6,
            "reason": "Direct mechanistic evidence.",
        },
        eligibility=lambda _record: (True, ""),
        max_papers=1,
        query_ids={"Q001"},
    )
    selected_decision = next(
        item for item in selection["decisions"] if item["decision"] == "INCLUDE"
    )

    paperqa = PaperQA2Retriever(
        backend=lambda **_kwargs: [{
            "text": text,
            "section": "Results",
            "locator": f"Results round {version}",
            "score": 0.95,
        }],
        backend_id="paperqa2-fullcycle-fixture/v1",
    )
    candidate = paperqa.retrieve(
        paper=record, question=seed["scientific_question"]
    )[0]
    located = ExactTextSourceVerifier().verify(
        candidate,
        source_bytes=("Source snapshot. " + text + " End source.").encode("utf-8"),
        role="CONTEXT",
    )
    semantic = SemanticEvidenceVerifier(
        assessor=lambda **_kwargs: {
            "entailment": "SUPPORTED",
            "scope_match": True,
            "context_preserved": True,
            "qualification_preserved": True,
            "reason": "The located result directly supports the scoped claim.",
        }
    ).verify(located, claim="Cardiac calcium handling is adaptively modified.")
    evidence = admit_reasoning_evidence([located], [semantic])
    assert [item["evidence_id"] for item in evidence] == [located["evidence_id"]]

    coverage = curie.judge_coverage(
        {"covered": ["verified_full_text_source", "semantic_mechanism_evidence"], "gaps": []},
        round_index=version,
        max_rounds=3,
    )
    pack = curie.build_evidence_pack(
        candidate_id="C001",
        round_id="1",
        seed_sha256=seed_hash,
        version=version,
        query_plans=[plan],
        discovery_receipts=discovery["batches"],
        selected_papers=[{
            "paper_id": record["paper_id"],
            "title": record["title"],
            "identifiers": record["identifiers"],
            "selection": selected_decision,
        }],
        evidence=evidence,
        coverage=coverage,
        gaps=[],
        source_run_id=run_id,
        parent_pack_sha256=parent,
        source_gap_request_id=gap_id,
    )
    return curie.freeze_evidence_pack(project, pack)


def _context_args(project, store):
    return SimpleNamespace(
        project_dir=str(project),
        cand_id="C001",
        node="L1",
        authorization_id=None,
        knowledge_store=str(store),
        template_mode="contract",
        pre_research_mode="full",
        pre_research_token_budget=4000,
        context_token_budget=12000,
        evidence_run_id=None,
    )


def test_full_cycle_v1_einstein_gap_v2_einstein_without_legacy_acquisition(
    tmp_path, monkeypatch, capsys
):
    project, store, seed = _project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    monkeypatch.setenv("RLR_AUTO_HYPOTHESIS_RECALL", "1")

    v1_text = "V1_SENTINEL: calcium handling differs under exercise."
    v1 = _acquire_round(
        project, seed, version=1, run_id="CURIE001", text=v1_text
    )
    bind_initial_curie_pack(project, seed, v1, "CURIE001")

    assert context.cmd_assemble_context(_context_args(project, store)) == 0
    first_context = capsys.readouterr().out
    assert v1_text in first_context
    assert "PRE-RESEARCH (deep_research)" not in first_context

    gap = curie.open_gap_request(
        project,
        seed,
        v1,
        gaps=[{
            "gap_id": "G1",
            "topic": "calcium mechanism",
            "reason": "Need more direct mechanism evidence.",
            "search_directions": ["direct bat cardiac calcium mechanism"],
        }],
    )
    v2_text = "V2_SENTINEL: direct calcium mechanism evidence resolves the gap."
    retry = run_authorized_retry(
        project,
        seed,
        v1,
        gap["request_id"],
        "CURIE002",
        lambda auth: _acquire_round(
            project,
            seed,
            version=auth["next_version"],
            run_id="CURIE002",
            text=v2_text,
            parent=auth["parent_pack_sha256"],
            gap_id=auth["source_gap_request_id"],
        ),
    )
    assert retry["binding"]["evidence_pack_version"] == 2
    assert research_seed.active_l1_native_evidence_run_id(project, seed) == "CURIE002"

    assert context.cmd_assemble_context(_context_args(project, store)) == 0
    second_context = capsys.readouterr().out
    assert v2_text in second_context
    assert v1_text not in second_context
    assert "PRE-RESEARCH (deep_research)" not in second_context
    assert not (project / "08_Audit" / "deep_research").exists()
    assert not (project / "02_Agent_Notes" / "_pre_research" / "L1_research.md").exists()
