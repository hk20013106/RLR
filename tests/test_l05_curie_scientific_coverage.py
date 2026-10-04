"""Scientific coverage is a validated current-host proposal, not section counts."""
import copy
from pathlib import Path

import pytest

from research_loop.l05_curie import contracts, europepmc_runtime as owner
from research_loop.l05_curie.semantic_verifier import SemanticEvidenceVerifier
from test_l05_curie_corpus_contracts import api
from test_l05_curie_corpus_semantics import fixture, verify
from test_l05_curie_corpus_replay import corpus_host_project

GAP = {"gap_id": "G1", "topic": "SCIENTIFIC_QUESTION", "reason": "Scientific scope missing", "search_directions": ["scope"]}


def state(**changes):
    return {"attempt_index": 1, "max_attempts": 3, "corpus_count": 1, "corpus_limit": 90,
        "terminal_reason": None, **changes}


@pytest.mark.parametrize("facts, gaps, expected", [
    (state(), [GAP], "INSUFFICIENT_RETRY"),
    (state(attempt_index=3, corpus_count=90, terminal_reason="attempt_budget_exhausted"), [GAP], "INSUFFICIENT_STOP"),
    (state(attempt_index=3, corpus_count=90, terminal_reason="attempt_budget_exhausted"), [], "PASS"),
    (state(corpus_count=90, terminal_reason="corpus_budget_exhausted"), [GAP], "INSUFFICIENT_STOP"),
    (state(attempt_index=2, terminal_reason="no_new_sources"), [GAP], "INSUFFICIENT_STOP"),
])
def test_budget_routes_without_pack_round_forgery(facts, gaps, expected):
    decision = contracts.judge_coverage({"covered": [] if gaps else ["SCIENTIFIC_QUESTION", "HYPOTHESIS_EVALUABILITY"],
        "gaps": gaps}, round_index=1, acquisition_state=facts)
    assert decision["verdict"] == expected and decision["round_index"] == 1 and decision["max_rounds"] == 3


@pytest.mark.parametrize("facts", [state(attempt_index=True), state(max_attempts=4), state(corpus_count=91),
    state(corpus_limit=0), state(terminal_reason="budget_exhausted"), state(terminal_reason="attempt_budget_exhausted"),
    state(terminal_reason="corpus_budget_exhausted"), state(unexpected=True), state(corpus_count=True)])
def test_invalid_budget_facts_rejected(facts):
    with pytest.raises(contracts.CurieContractError):
        contracts.judge_coverage({"covered": [], "gaps": [GAP]}, round_index=1, acquisition_state=facts)


def context(tmp_path, monkeypatch, *, empty=False):
    project, seed, entry, task, result = fixture(tmp_path, monkeypatch)
    corpus_host_project(tmp_path, monkeypatch, project_seed=(project, seed))
    extracts = verify(project, entry, task, result)["located"]
    verifier = SemanticEvidenceVerifier(assessor=lambda **_: {"entailment": "CONTRADICTED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True, "reason": "Counterevidence"}, assessor_id="host")
    semantics = [verifier.verify(e, claim=task["question"]) for e in extracts]
    cp, path = owner._host_checkpoint(project, "C001", "1", "coverage-run", seed)
    inputs = api(owner, "_coverage_inputs")(seed, attempt_index=1, cumulative_corpus=[] if empty else [entry],
        admitted_extracts=[] if empty else extracts, semantic_refs=[] if empty else semantics,
        previous_gaps=[], acquisition_state=state(corpus_count=0 if empty else 1))
    return project, seed, cp, path, inputs


def pending(project, seed, cp, path, inputs, attempt=1):
    with pytest.raises(owner._AcquisitionHostPending) as caught:
        api(owner, "_coverage_for_attempt")(project, seed, cp, checkpoint_path=path, attempt_index=attempt, inputs=inputs)
    return caught.value.result


def answer_for(request, *, sufficient):
    ids = [e["evidence_id"] for e in request["inputs"]["admitted_evidence"]]
    return {"schema_version": "L05ScientificCoverageAssessment/v1", "request_sha256": request["request_sha256"],
        "dimensions": [{"dimension_id": name, "sufficient": sufficient, "reason": "Scope evaluated including counterevidence",
            "admitted_evidence_ids": ids if sufficient else []} for name in ("SCIENTIFIC_QUESTION", "HYPOTHESIS_EVALUABILITY")],
        "gaps": [] if sufficient else [{**GAP, "gap_id": f"G{index}", "topic": name} for index, name in enumerate(
            ("SCIENTIFIC_QUESTION", "HYPOTHESIS_EVALUABILITY"), 1)]}


def submit_answer(project, cp, step, answer):
    answer_path = project / (step["request_id"] + "-answer.json")
    owner._atomic_json(answer_path, answer)
    return owner.submit_acquisition_host_response(project, "C001", step["request_id"], answer_path)


def test_results_section_not_scientific_coverage(tmp_path, monkeypatch):
    project, seed, cp, path, inputs = context(tmp_path, monkeypatch)
    assert any(e["section"] == "Results" for e in inputs["admitted_evidence"])
    step = pending(project, seed, cp, path, inputs)
    assert step["request"]["identity"]["stage"] == "coverage:1"
    assert "complete" in step["request"]["tools_policy"].lower()
    submit_answer(project, cp, step, answer_for(step["request"], sufficient=False))
    cp = owner._read_object(path)
    binding = api(owner, "_coverage_for_attempt")(project, seed, cp, checkpoint_path=path, attempt_index=1, inputs=inputs)
    assessment = binding["assessment"]
    decision = contracts.judge_coverage({"covered": [], "gaps": assessment["gaps"]}, round_index=1, acquisition_state=state())
    assert decision["verdict"] == "INSUFFICIENT_RETRY"


def test_counterevidence_can_be_sufficient(tmp_path, monkeypatch):
    project, seed, cp, path, inputs = context(tmp_path, monkeypatch)
    step = pending(project, seed, cp, path, inputs)
    submit_answer(project, cp, step, answer_for(step["request"], sufficient=True))
    cp = owner._read_object(path)
    binding = api(owner, "_coverage_for_attempt")(project, seed, cp, checkpoint_path=path, attempt_index=1, inputs=inputs)
    decision = contracts.judge_coverage({"covered": [d["dimension_id"] for d in binding["assessment"]["dimensions"]], "gaps": []},
        round_index=1, acquisition_state=state(attempt_index=3, terminal_reason="attempt_budget_exhausted"))
    assert decision["verdict"] == "PASS"


@pytest.mark.parametrize("mutation", ["missing-dimension", "extra-dimension", "duplicate-gap", "false-no-gap", "true-no-ref",
    "unadmitted-ref", "request-hash", "authority-extra", "duplicate-raw"])
def test_invalid_coverage_rejected_before_immutable_receipt(tmp_path, monkeypatch, mutation):
    project, seed, cp, path, inputs = context(tmp_path, monkeypatch)
    step = pending(project, seed, cp, path, inputs)
    answer = answer_for(step["request"], sufficient=False)
    if mutation == "missing-dimension": answer["dimensions"].pop()
    elif mutation == "extra-dimension": answer["dimensions"].append(answer["dimensions"][0])
    elif mutation == "duplicate-gap": answer["gaps"].append(answer["gaps"][0])
    elif mutation == "false-no-gap": answer["gaps"] = []
    elif mutation == "true-no-ref": answer = answer_for(step["request"], sufficient=True); answer["dimensions"][0]["admitted_evidence_ids"] = []
    elif mutation == "unadmitted-ref": answer["dimensions"][0]["admitted_evidence_ids"] = ["UNADMITTED_AUTHORITY_SENTINEL"]
    elif mutation == "request-hash": answer["request_sha256"] = "f" * 64
    elif mutation == "authority-extra": answer["verdict"] = "PASS"
    receipt_path = project / "08_Audit/host_handoff/responses" / (step["request_id"] + ".json")
    if mutation == "duplicate-raw":
        from research_loop.l05_curie.paperqa2 import canonical_corpus_bytes
        raw = canonical_corpus_bytes(answer).replace(b'{', b'{"schema_version":"L05ScientificCoverageAssessment/v1",', 1)
        raw_path = project / "bad-raw.json"; raw_path.write_bytes(raw)
        with pytest.raises(owner.CurieContractError): owner.submit_acquisition_host_response(project, "C001", step["request_id"], raw_path)
    else:
        with pytest.raises(owner.CurieContractError): submit_answer(project, cp, step, answer)
    assert not receipt_path.exists()


def test_no_new_sources_reuses_origin_assessment(tmp_path, monkeypatch):
    project, seed, cp, path, inputs = context(tmp_path, monkeypatch)
    first = pending(project, seed, cp, path, inputs)
    submit_answer(project, cp, first, answer_for(first["request"], sufficient=False))
    cp = owner._read_object(path)
    coverage = api(owner, "_coverage_for_attempt")
    origin = coverage(project, seed, cp, checkpoint_path=path, attempt_index=1, inputs=inputs)
    revised = {**inputs, "attempt_index": 2, "acquisition_state": state(attempt_index=2, terminal_reason="no_new_sources")}
    later = coverage(project, seed, cp, checkpoint_path=path, attempt_index=2, inputs=revised)
    assert later == origin
    assert len(cp["coverage_requests"]) == 1
    decision = contracts.judge_coverage({"covered": [], "gaps": later["assessment"]["gaps"]}, round_index=1,
        acquisition_state=revised["acquisition_state"])
    assert decision["verdict"] == "INSUFFICIENT_STOP" and cp["current_coverage_binding"]["origin_attempt"] == 1


def test_scientific_fingerprint_excludes_budget_and_attempt(tmp_path, monkeypatch):
    project, seed, cp, path, inputs = context(tmp_path, monkeypatch)
    fingerprint = api(owner, "_coverage_scientific_input_sha256")
    assert fingerprint(inputs) == fingerprint({**inputs, "attempt_index": 3, "acquisition_state": state(attempt_index=3), "previous_gaps": [GAP]})
    changed = copy.deepcopy(inputs); changed["admitted_evidence"].pop(); changed["semantic_verifications"].pop()
    assert fingerprint(inputs) != fingerprint(changed)
    assert "contextual_summary" not in str(inputs)


def test_first_empty_corpus_requires_real_host_gaps(tmp_path, monkeypatch):
    project, seed, cp, path, inputs = context(tmp_path, monkeypatch, empty=True)
    step = pending(project, seed, cp, path, inputs)
    assert step["request"]["inputs"]["admitted_evidence"] == []
    assert cp["worker_attempts"] == {}
    with pytest.raises(owner.CurieContractError): submit_answer(project, cp, step, answer_for(step["request"], sufficient=True))


@pytest.mark.parametrize("empty", [False, True])
def test_public_controller_uses_scientific_host_coverage(tmp_path, monkeypatch, empty):
    from test_l05_curie_europepmc_runtime import _host_planner_plan, _planner_schema_plan, _search_record, _search_payload, _GOOD_TITLE, XML
    project, seed, _ = corpus_host_project(tmp_path, monkeypatch)
    first = owner.prepare_acquisition_host_step(project, "C001", run_id="public-coverage")
    plan_path = project / "plan.json"
    owner._atomic_json(plan_path, {"status": "PLAN", "reason": "fixture", "plan": _planner_schema_plan(_host_planner_plan(seed))})
    owner.submit_acquisition_host_response(project, "C001", first["request_id"], plan_path)
    paper = _search_record(title=_GOOD_TITLE)
    calls = []
    def http_get(url, timeout):
        calls.append(url)
        if "/search?" in url:
            return b'{"hitCount":0,"resultList":{"result":[]}}' if empty else _search_payload(records=[paper])
        return XML
    monkeypatch.setattr(owner, "_default_http_get", http_get)
    monkeypatch.setattr(owner, "_coverage_for", lambda *_args, **_kw: pytest.fail("structural section coverage is retired for corpus"))
    step = owner.continue_acquisition(project, "C001", run_id="public-coverage")
    while step["kind"] == "needs_host" and step["request"]["identity"]["stage"].startswith("semantic:"):
        answer_path = project / (step["request_id"] + "-semantic.json")
        owner._atomic_json(answer_path, {"entailment": "CONTRADICTED", "scope_match": True, "context_preserved": True,
            "qualification_preserved": True, "reason": "controlled counterevidence"})
        owner.submit_acquisition_host_response(project, "C001", step["request_id"], answer_path)
        step = owner.continue_acquisition(project, "C001", run_id="public-coverage")
    assert step["kind"] == "needs_host" and step["request"]["identity"]["stage"] == "coverage:1"
    before = len(calls)
    replay = owner.continue_acquisition(project, "C001", run_id="public-coverage")
    assert replay["request_id"] == step["request_id"] and len(calls) == before
    assert "contextual_summary" not in str(step["request"]["inputs"])
    assert bool(step["checkpoint"]["worker_attempts"]) is not empty
    if empty: assert step["request"]["inputs"]["acquisition_state"]["terminal_reason"] == "no_new_sources"
