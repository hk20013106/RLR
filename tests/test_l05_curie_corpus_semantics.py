"""Stable source identity, origin semantic receipts and cumulative admission."""
import copy
import hashlib
from pathlib import Path

import pytest

from research_loop import host_handoff, research_seed
from research_loop.l05_curie import europepmc_runtime as owner
from research_loop.l05_curie.europepmc import EuropePmcEvidenceRetriever
from research_loop.l05_curie.paperqa2 import canonical_corpus_bytes
from research_loop.l05_curie.paperqa2_runtime import build_corpus_task, materialize_corpus_question
from research_loop.l05_curie.semantic_verifier import (SEMANTIC_CONTRACT_SHA256, SemanticEvidenceVerifier,
    admit_reasoning_evidence, evidence_extract_sha256)
from test_l05_curie_corpus_allocation import record
from test_l05_curie_corpus_contracts import api, SETTINGS, result_fixture
from test_l05_curie_europepmc_runtime import _host_project, XML
from test_l05_curie_corpus_replay import corpus_host_project


def fixture(tmp_path, monkeypatch):
    project, seed = _host_project(tmp_path, monkeypatch)
    paper = record("A")
    retrieval = EuropePmcEvidenceRetriever(project, candidate_id="C001", run_id="source-run_A1", http_get=lambda *_: XML).retrieve(
        paper, seed=seed, parser_profile="jats-paragraphs/v2")
    entry = {"paper": paper, "origin_attempt": 1, "snapshot": retrieval["snapshot"], "source_units": [
        {"source_locator": u["locator"], "section": u["section"], "source_text": u["text"]} for u in retrieval["candidates"]]}
    task = build_corpus_task(acquisition_run_id="source-run", attempt_index=1, seed=seed,
        settings_sha256=hashlib.sha256(canonical_corpus_bytes(SETTINGS)).hexdigest(), evidence_k=60, evidence_focus=None,
        corpus=[{"paper_id": "A", "title": paper["title"], "document_path": entry["snapshot"]["artifact_path"],
            "document_sha256": entry["snapshot"]["artifact_sha256"], "media_type": "application/xml", "source_units": entry["source_units"]}])
    result = result_fixture(task)
    result["execution"]["ingested_text_count"] = len(entry["source_units"])
    result["evidence"] = [{"paper_id": "A", **{k: u[k] for k in ("source_locator", "source_text")},
        "relevance_score": 5, "contextual_summary": "SUMMARY_AUTHORITY_SENTINEL"} for u in entry["source_units"]]
    return project, seed, entry, task, result


def verify(project, entry, task, result):
    return api(owner, "_verify_corpus_proposals")(project, task=task, result=result, cumulative_corpus=[entry])


def test_same_source_different_summary_score_same_extract_bytes(tmp_path, monkeypatch):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    first = verify(project, entry, task, result)
    task2 = build_corpus_task(acquisition_run_id="source-run", attempt_index=2, seed=seed,
        settings_sha256=task["settings_sha256"], evidence_k=60, evidence_focus=None, corpus=task["corpus"])
    changed = copy.deepcopy(result); changed["task_id"] = task2["task_id"]
    changed["task_sha256"] = hashlib.sha256(canonical_corpus_bytes(task2)).hexdigest()
    for row in changed["evidence"]: row.update(relevance_score=10, contextual_summary="DIFFERENT_SUMMARY")
    second = verify(project, entry, task2, changed)
    assert first["located"] == second["located"]
    assert canonical_corpus_bytes(first["located"]) == canonical_corpus_bytes(second["located"])
    assert first["proposal_refs"] != second["proposal_refs"]
    assert "SUMMARY_AUTHORITY_SENTINEL" not in str(first["located"])
    assert all(e["role"] == "CONTEXT" and "relevance_score" not in e["retrieval"] for e in first["located"])


@pytest.mark.parametrize("failure", ["all-mismatch", "unknown-paper", "profile", "source-hash"])
def test_systemic_source_failure_blocks(tmp_path, monkeypatch, failure):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    if failure == "all-mismatch":
        for e in result["evidence"]: e["source_text"] = "Not original source"
    elif failure == "unknown-paper": result["evidence"][0]["paper_id"] = "UNKNOWN"
    elif failure == "profile": task["parser_profile"] = "jats-paragraphs/v1"
    else: (project / entry["snapshot"]["artifact_path"]).write_bytes(b"changed")
    with pytest.raises(owner.CurieContractError): verify(project, entry, task, result)


def test_single_local_source_mismatch_rejects_only_one_proposal(tmp_path, monkeypatch):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    result["evidence"][0]["source_text"] = "Not original source"
    actual = verify(project, entry, task, result)
    assert len(actual["located"]) == 2 and len(actual["rejected"]) == 1
    assert actual["rejected"][0]["reason_code"] == "SOURCE_MISMATCH"


def test_empty_worker_contexts_is_valid_source_stage(tmp_path, monkeypatch):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    result["evidence"] = []
    assert verify(project, entry, task, result) == {"located": [], "rejected": [], "proposal_refs": []}


def test_empty_contexts_cannot_hide_broken_snapshot(tmp_path, monkeypatch):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    result["evidence"] = []
    (project / entry["snapshot"]["artifact_path"]).write_bytes(b"changed")
    with pytest.raises(owner.CurieContractError): verify(project, entry, task, result)


def test_corpus_semantic_raw_duplicate_key_rejected_before_persistence(tmp_path, monkeypatch):
    from test_l05_curie_europepmc_runtime import _host_planner_plan, _planner_schema_plan, _search_record, _search_payload, _GOOD_TITLE
    project, seed, _ = corpus_host_project(tmp_path, monkeypatch)
    step = owner.prepare_acquisition_host_step(project, "C001", run_id="semantic-duplicate")
    plan_path = project / "plan.json"
    owner._atomic_json(plan_path, {"status": "PLAN", "reason": "fixture", "plan": _planner_schema_plan(_host_planner_plan(seed))})
    owner.submit_acquisition_host_response(project, "C001", step["request_id"], plan_path)
    paper = _search_record(title=_GOOD_TITLE)
    monkeypatch.setattr(owner, "_default_http_get", lambda url, _: _search_payload(records=[paper]) if "/search?" in url else XML)
    pending = owner.continue_acquisition(project, "C001", run_id="semantic-duplicate")
    assert pending["request"]["identity"]["stage"].startswith("semantic:")
    raw = b'{"entailment":"SUPPORTED","entailment":"SUPPORTED","scope_match":true,"context_preserved":true,"qualification_preserved":true,"reason":"duplicate"}'
    answer = project / "bad-semantic.json"; answer.write_bytes(raw)
    with pytest.raises(owner.CurieContractError):
        owner.submit_acquisition_host_response(project, "C001", pending["request_id"], answer)
    assert not (project / "08_Audit/host_handoff/responses" / (pending["request_id"] + ".json")).exists()


def test_existing_stable_extract_collision_blocks(tmp_path, monkeypatch):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    first = verify(project, entry, task, result)
    extract = first["located"][0]
    paths = list(project.rglob(extract["evidence_id"] + ".json"))
    assert len(paths) == 1
    paths[0].write_bytes(canonical_corpus_bytes({**extract, "text": "different bytes"}))
    with pytest.raises(owner.CurieContractError): verify(project, entry, task, result)


@pytest.mark.parametrize("dimension", ["extract", "claim", "contract", "assessor"])
def test_semantic_reuse_key_binds_all_four_inputs(tmp_path, monkeypatch, dimension):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    extract = verify(project, entry, task, result)["located"][0]
    args = {"claim": materialize_corpus_question(seed, evidence_focus=None),
        "contract_sha256": SEMANTIC_CONTRACT_SHA256, "assessor_id": "host"}
    key = api(owner, "_semantic_reuse_key")(extract, **args)
    if dimension == "extract": extract = {**extract, "role": "SUPPORTING"}
    elif dimension == "contract": args["contract_sha256"] = "f" * 64
    else: args[dimension if dimension != "assessor" else "assessor_id"] += " changed"
    assert api(owner, "_semantic_reuse_key")(extract, **args) != key


def test_semantic_replay_uses_base_claim_and_origin_receipt(tmp_path, monkeypatch):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    extract = verify(project, entry, task, result)["located"][0]
    cp, path = owner._host_checkpoint(project, "C001", "1", "source-run", seed)
    claim = materialize_corpus_question(seed, evidence_focus=None)
    calls = []
    def assessor(*, extract, claim):
        calls.append(claim)
        request = owner._host_request(project, candidate_id="C001", round_id="1", attempt_index=1,
            stage=f"semantic:{extract['evidence_id']}", persona="Semantic", inputs={"extract": extract,
                "extract_sha256": evidence_extract_sha256(extract), "claim": claim,
                "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(), "source_sha256": entry["snapshot"]["artifact_sha256"]},
            output_contract={"type": "object"})
        answer = {"entailment": "CONTRADICTED", "scope_match": True, "context_preserved": True,
            "qualification_preserved": True, "reason": "Counterevidence preserved"}
        answer_path = project / "semantic-answer.json"; owner._atomic_json(answer_path, answer, immutable=True)
        receipt = host_handoff.submit_response(project, request["request_id"], answer_path, expected_cursor=request["identity"]["cursor"])
        cp["semantic_host_receipts"][f"1:{extract['evidence_id']}"] = {"evidence_id": extract["evidence_id"],
            "host_request": {k: request[k] for k in ("request_id", "request_path", "request_sha256")},
            "host_response_receipt": receipt, "extract_sha256": evidence_extract_sha256(extract),
            "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(), "source_sha256": entry["snapshot"]["artifact_sha256"]}
        return answer
    verifier = SemanticEvidenceVerifier(assessor=assessor, assessor_id="host")
    plan = {"planning_provenance": {"receipt": {"schema_version": owner.PLANNER_HOST_RECEIPT_SCHEMA_VERSION}}}
    semantic = api(owner, "_semantic_for_corpus_extract")
    first = semantic(project, cp, checkpoint_path=path, extract=extract, claim=claim, verifier=verifier,
        attempt_index=1, query_plan=plan, cumulative_corpus=[entry], seed=seed)
    second = semantic(project, cp, checkpoint_path=path, extract=extract, claim=claim, verifier=verifier,
        attempt_index=2, query_plan=plan, cumulative_corpus=[entry], seed=seed)
    assert first == second and calls == [claim]
    assert cp["semantic_host_receipts"][f"2:{extract['evidence_id']}"]["origin_attempt"] == 1
    assert admit_reasoning_evidence([extract], [second]) == [extract]
    receipt_file = project / "08_Audit/host_handoff/responses" / (cp["semantic_host_receipts"][f"1:{extract['evidence_id']}"]["host_request"]["request_id"] + ".json")
    receipt_file.unlink()
    with pytest.raises(owner.CurieContractError):
        semantic(project, cp, checkpoint_path=path, extract=extract, claim=claim, verifier=verifier,
            attempt_index=2, query_plan=plan, cumulative_corpus=[entry], seed=seed)
    assert calls == [claim]


def test_cumulative_preserves_unreturned_counterevidence(tmp_path, monkeypatch):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    extracts = verify(project, entry, task, result)["located"]
    results = [SemanticEvidenceVerifier(assessor=lambda **_: {"entailment": relation, "scope_match": True,
        "context_preserved": True, "qualification_preserved": True, "reason": "fixture"}, assessor_id="host").verify(
            extract, claim=task["question"]) for extract, relation in zip(extracts, ["CONTRADICTED", "AMBIGUOUS", "UNRELATED"])]
    admitted = admit_reasoning_evidence(extracts, results)
    assert admitted == [extracts[0]]
    result["evidence"] = []
    next_located = verify(project, entry, task, result)["located"]
    assert admitted + admit_reasoning_evidence(next_located, []) == admitted
