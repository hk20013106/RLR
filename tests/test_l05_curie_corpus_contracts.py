"""Pure corpus boundary tests; no provider, filesystem or PaperQA2 calls."""
import copy
import hashlib
import json

import pytest

from research_loop.l05_curie import contracts, paperqa2, paperqa2_runtime as runtime


BASE = "Scientific question:\n原始完整问题?\n\nHypothesis to evaluate:\nFrozen hypothesis."
SEED = {"scientific_question": "原始完整问题?", "hypothesis_seed": "Frozen hypothesis."}
RUN = "run-1"
SHA = "a" * 64
GAPS = [{"gap_id": "G1", "topic": "SCIENTIFIC_QUESTION", "reason": "Missing range",
         "search_directions": ["second", "first"]}]
FOCUS = {"coverage_request_sha256": "b" * 64,
         "coverage_assessment_sha256": "c" * 64, "gaps": GAPS}
SETTINGS = {
    "embedding": "test-embedding", "summary_llm": "test-summary",
    "embedding_config": {}, "summary_llm_config": {},
    "answer": {"evidence_k": 60, "evidence_retrieval": True,
               "evidence_skip_summary": False, "evidence_text_only_fallback": False,
               "max_concurrent_requests": 4},
    "parsing": {"use_doc_details": False, "multimodal": False,
                "doc_filters": [], "defer_embedding": False},
    "texts_index_mmr_lambda": 1.0,
}
PIN = {"package": "paper-qa", "version": "2026.8.12",
       "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
       "upstream_tag": "v2026.08.12", "embedding_model": "test-embedding",
       "summary_llm_model": "test-summary"}
CORPUS = [{"paper_id": "P1", "title": "Frozen title", "document_path": "snapshots/p1.xml",
           "document_sha256": SHA, "media_type": "application/xml",
           "source_units": [{"source_locator": "sec:1/p:1", "section": "Methods",
                             "source_text": "Entire original paragraph."}]}]


def api(module, name):
    method = getattr(module, name, None)
    assert callable(method), f"missing planned behavior: {name}"
    return method


def wire_bytes(value):
    # Independent contract oracle; LF belongs to the artifact, not the question.
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def identify(task, attempt=1):
    body = {k: v for k, v in task.items() if k != "task_id"}
    task["task_id"] = "PQA_" + hashlib.sha256(wire_bytes(
        {"acquisition_run_id": RUN, "attempt_index": attempt, "task": body})).hexdigest()[:24]
    return task


def task_fixture():
    return identify({"schema_version": "PaperQA2CorpusTask/v1", "research_seed_sha256": SHA,
                     "question": BASE, "evidence_focus": None, "parser_profile": "jats-paragraphs/v2",
                     "settings_sha256": hashlib.sha256(wire_bytes(SETTINGS)).hexdigest(),
                     "corpus": copy.deepcopy(CORPUS), "budget": {"evidence_k": 60}})


def result_fixture(task):
    return {"schema_version": "PaperQA2CorpusResult/v1", "task_id": task["task_id"],
            "task_sha256": hashlib.sha256(wire_bytes(task)).hexdigest(),
            "runtime": {**PIN, "settings_sha256": task["settings_sha256"]},
            "execution": {"status": "COMPLETE", "ingested_paper_count": 1,
                          "ingested_text_count": 1, "terminal_context_error_count": 0},
            "evidence": [{"paper_id": "P1", "source_locator": "sec:1/p:1",
                          "source_text": "Entire original paragraph.", "relevance_score": 5,
                          "contextual_summary": "AUDIT_ONLY"}]}


def config_fixture():
    return {"worker_mode": "corpus-evidence-v1", "settings": copy.deepcopy(SETTINGS),
            "timeout_seconds": 300, "python_executable": "bound/python.exe",
            "bridge_script": "bound/bridge.py", "paperqa_repo": "bound/repo", "pqa_home": "bound/home",
            "acquisition_budget": {"max_acquisition_attempts": 3,
                                   "new_papers_per_attempt": 30, "cumulative_paper_limit": 90}}


def set_path(value, path, replacement):
    for component in path[:-1]:
        value = value[component]
    value[path[-1]] = replacement


def test_question_focus_changes_task_identity_not_claim():
    question = api(runtime, "materialize_corpus_question")
    build = api(runtime, "build_corpus_task")
    args = dict(acquisition_run_id=RUN, seed=SEED,
                settings_sha256=hashlib.sha256(wire_bytes(SETTINGS)).hexdigest(),
                corpus=CORPUS, evidence_k=60)
    first = build(**args, attempt_index=1, evidence_focus=None)
    focused = build(**args, attempt_index=2, evidence_focus=FOCUS)
    assert question(SEED, evidence_focus=None) == BASE
    assert first["question"] == BASE and first["evidence_focus"] is None
    suffix = '\n\nEvidence focus:\n[{"gap_id":"G1","reason":"Missing range","search_directions":["second","first"],"topic":"SCIENTIFIC_QUESTION"}]'
    assert focused["question"] == BASE + suffix
    assert first == identify(copy.deepcopy(first))
    assert focused == identify(copy.deepcopy(focused), 2)
    changed = copy.deepcopy(FOCUS)
    changed["coverage_request_sha256"] = "d" * 64
    rebound = build(**args, attempt_index=2, evidence_focus=changed)
    assert focused["task_id"] != rebound["task_id"]
    assert wire_bytes(focused) != wire_bytes(rebound)
    assert focused["question"] == rebound["question"]
    assert question(SEED, evidence_focus=None) == BASE
    with pytest.raises(contracts.CurieContractError):
        build(**args, attempt_index=1, evidence_focus=FOCUS)


@pytest.mark.parametrize("kind", ["missing_focus", "empty_gaps", "extra_focus", "unsorted_gaps",
                                  "duplicate_gap", "extra_gap", "extra_authority", "duplicate_paper",
                                  "duplicate_locator", "surrogate", "nan", "infinity",
                                  "absolute_path", "parent_path", "windows_drive", "windows_parent",
                                  "empty_corpus", "bool_k", "bad_id", "bad_hash"])
def test_task_rejects_missing_focus_and_noncanonical_projection(kind):
    validate = api(paperqa2, "validate_paperqa2_corpus_task")
    task = task_fixture()
    attempt = 2 if "gap" in kind or kind == "extra_focus" else 1
    if attempt == 2:
        task["evidence_focus"] = copy.deepcopy(FOCUS)
    if kind == "missing_focus": del task["evidence_focus"]
    elif kind == "empty_gaps": task["evidence_focus"]["gaps"] = []
    elif kind == "extra_focus": task["evidence_focus"]["claim"] = "rewritten"
    elif kind == "unsorted_gaps": task["evidence_focus"]["gaps"].insert(0, {**GAPS[0], "gap_id": "G2"})
    elif kind == "duplicate_gap": task["evidence_focus"]["gaps"] *= 2
    elif kind == "extra_gap": task["evidence_focus"]["gaps"][0]["verdict"] = "PASS"
    elif kind == "extra_authority": task["candidate_status"] = "READY"
    elif kind == "duplicate_paper": task["corpus"] *= 2
    elif kind == "duplicate_locator": task["corpus"][0]["source_units"] *= 2
    elif kind == "surrogate": task["corpus"][0]["title"] = "\ud800"
    elif kind in ("nan", "infinity"): task["budget"]["evidence_k"] = float(kind if kind == "nan" else "inf")
    elif kind in ("absolute_path", "parent_path", "windows_drive", "windows_parent"):
        task["corpus"][0]["document_path"] = {
            "absolute_path": "/secret.xml", "parent_path": "a/../secret.xml",
            "windows_drive": "C:\\secret.xml", "windows_parent": "a\\..\\secret.xml"}[kind]
    elif kind == "empty_corpus": task["corpus"] = []
    elif kind == "bool_k": task["budget"]["evidence_k"] = True
    elif kind == "bad_hash": task["research_seed_sha256"] = "wrong"
    if kind != "surrogate": identify(task, attempt)
    if kind == "bad_id": task["task_id"] = "PQA_" + "0" * 24
    with pytest.raises(contracts.CurieContractError):
        validate(task, acquisition_run_id=RUN, attempt_index=attempt)


def test_validated_task_is_independent_and_canonical_bytes_reuses_artifact_encoding():
    task = task_fixture()
    validated = api(paperqa2, "validate_paperqa2_corpus_task")(
        task, acquisition_run_id=RUN, attempt_index=1)
    assert validated == task
    validated["corpus"][0]["title"] = "changed"
    assert task["corpus"][0]["title"] == "Frozen title"
    encode = api(paperqa2, "canonical_corpus_bytes")
    assert encode({"z": "中文", "a": [2, 1]}) == b'{"a":[2,1],"z":"\xe4\xb8\xad\xe6\x96\x87"}\n'
    for invalid in (float("nan"), float("inf"), "\ud800"):
        with pytest.raises(contracts.CurieContractError): encode({"value": invalid})


@pytest.mark.parametrize("path,replacement", [
    (("candidate_status",), "READY"), (("evidence", 0, "role"), "SUPPORTING"),
    (("evidence", 0, "paper_id"), "UNKNOWN"), (("task_id",), "wrong"),
    (("task_sha256",), "b" * 64), (("runtime", "settings_sha256"), "b" * 64),
    (("runtime", "version"), "wrong"), (("runtime", "upstream_commit"), "b" * 40),
    (("runtime", "embedding_model"), "wrong"), (("execution", "ingested_paper_count"), 2),
    (("execution", "ingested_text_count"), True), (("execution", "terminal_context_error_count"), 1),
    *(( ("evidence", 0, "relevance_score"), score) for score in (True, -1, 0, 11, 5.0)),
])
def test_result_rejects_authority_runtime_count_and_score_mismatch(path, replacement):
    validate = api(paperqa2, "validate_paperqa2_corpus_result")
    task = task_fixture()
    result = result_fixture(task)
    set_path(result, path, replacement)
    with pytest.raises(contracts.CurieContractError):
        validate(result, task=task, settings=SETTINGS, expected_runtime=PIN)


def test_empty_evidence_accepted_but_over_budget_rejected_and_fidelity_left_to_verifier():
    validate = api(paperqa2, "validate_paperqa2_corpus_result")
    task = task_fixture()
    result = result_fixture(task)
    result["evidence"][0]["source_locator"] = "unresolved-but-known-paper"
    result["evidence"][0]["source_text"] = "proposal for independent source verification"
    assert validate(result, task=task, settings=SETTINGS, expected_runtime=PIN) == result
    result["evidence"] *= 61
    with pytest.raises(contracts.CurieContractError):
        validate(result, task=task, settings=SETTINGS, expected_runtime=PIN)
    result["evidence"] = []
    assert validate(result, task=task, settings=SETTINGS, expected_runtime=PIN)["evidence"] == []


@pytest.mark.parametrize("path,replacement", [
    *(( ("acquisition_budget", "max_acquisition_attempts"), n) for n in (0, 4, True)),
    *(( ("acquisition_budget", "new_papers_per_attempt"), n) for n in (0, 31, True)),
    *(( ("acquisition_budget", "cumulative_paper_limit"), n) for n in (0, 91, True)),
    *(( ("settings", "answer", "max_concurrent_requests"), n) for n in (0, 5, True)),
    (("settings", "answer", "evidence_k"), True), (("timeout_seconds",), True),
    (("timeout_seconds",), 0), (("settings", "answer", "evidence_skip_summary"), True),
    (("settings", "answer", "evidence_retrieval"), False),
    (("settings", "answer", "evidence_text_only_fallback"), True),
    (("settings", "parsing", "multimodal"), True),
    (("settings", "parsing", "use_doc_details"), True),
    (("settings", "parsing", "doc_filters"), [{"title": "filter"}]),
    (("settings", "parsing", "defer_embedding"), "false"),
    (("settings", "texts_index_mmr_lambda"), 0.5),
    (("settings", "embedding_config", "api_key"), "DO_NOT_PERSIST"),
])
def test_settings_budget_and_path_boundaries(path, replacement):
    config = config_fixture()
    set_path(config, path, replacement)
    with pytest.raises(contracts.CurieContractError):
        api(runtime, "validate_corpus_worker_config")(config)


def test_settings_defaults_and_lower_explicit_budgets():
    validate = api(runtime, "validate_corpus_worker_config")
    config = config_fixture()
    del config["acquisition_budget"]
    del config["settings"]["answer"]["evidence_k"]
    del config["settings"]["answer"]["max_concurrent_requests"]
    frozen = validate(config)
    assert frozen["acquisition_budget"] == {
        "max_acquisition_attempts": 3, "new_papers_per_attempt": 30, "cumulative_paper_limit": 90}
    assert frozen["settings"]["answer"]["evidence_k"] == 60
    assert frozen["settings"]["answer"]["max_concurrent_requests"] == 4
    config = config_fixture()
    config["acquisition_budget"] = {"max_acquisition_attempts": 1,
                                    "new_papers_per_attempt": 1, "cumulative_paper_limit": 1}
    config["settings"]["answer"]["max_concurrent_requests"] = 1
    assert validate(config) == config


def assessment_fixture():
    return {"schema_version": "L05ScientificCoverageAssessment/v1", "request_sha256": SHA,
            "dimensions": [
                {"dimension_id": "SCIENTIFIC_QUESTION", "sufficient": False,
                 "reason": "Missing range", "admitted_evidence_ids": []},
                {"dimension_id": "HYPOTHESIS_EVALUABILITY", "sufficient": True,
                 "reason": "Counterevidence suffices", "admitted_evidence_ids": ["E1"]}],
            "gaps": copy.deepcopy(GAPS)}


@pytest.mark.parametrize("kind", ["missing_dimension", "duplicate_dimension", "unknown_dimension",
                                  "true_no_refs", "false_no_gap", "unadmitted", "duplicate_refs",
                                  "duplicate_gap", "extra_gap", "wrong_request", "authority", "bool_type"])
def test_scientific_coverage_rejects_invalid_before_owner_persistence(kind):
    validate = api(contracts, "validate_scientific_coverage_assessment")
    a = assessment_fixture()
    if kind == "missing_dimension": a["dimensions"].pop()
    elif kind == "duplicate_dimension": a["dimensions"][1] = copy.deepcopy(a["dimensions"][0])
    elif kind == "unknown_dimension": a["dimensions"][0]["dimension_id"] = "OTHER"
    elif kind == "true_no_refs": a["dimensions"][1]["admitted_evidence_ids"] = []
    elif kind == "false_no_gap": a["gaps"] = []
    elif kind == "unadmitted": a["dimensions"][1]["admitted_evidence_ids"] = ["E2"]
    elif kind == "duplicate_refs": a["dimensions"][1]["admitted_evidence_ids"] *= 2
    elif kind == "duplicate_gap": a["gaps"] *= 2
    elif kind == "extra_gap": a["gaps"][0]["verdict"] = "PASS"
    elif kind == "wrong_request": a["request_sha256"] = "b" * 64
    elif kind == "authority": a["verdict"] = "PASS"
    elif kind == "bool_type": a["dimensions"][0]["sufficient"] = 0
    with pytest.raises(contracts.CurieContractError):
        validate(a, request_sha256=SHA, admitted_evidence_ids=["E1"])


def test_scientific_coverage_valid_and_empty_evidence_never_sufficient():
    validate = api(contracts, "validate_scientific_coverage_assessment")
    a = assessment_fixture()
    validated = validate(a, request_sha256=SHA, admitted_evidence_ids=["E1"])
    assert validated == a
    validated["gaps"][0]["reason"] = "changed"
    assert a["gaps"][0]["reason"] == "Missing range"
    with pytest.raises(contracts.CurieContractError):
        validate(a, request_sha256=SHA, admitted_evidence_ids=[])


def test_question_rejects_invalid_unicode_as_contract_error():
    seed = {**SEED, "scientific_question": "\ud800"}
    with pytest.raises(contracts.CurieContractError):
        api(runtime, "materialize_corpus_question")(seed, evidence_focus=None)


def test_result_expected_runtime_must_be_complete_and_pinned():
    validate = api(paperqa2, "validate_paperqa2_corpus_result")
    task = task_fixture()
    for expected in ({}, {**PIN, "version": "unpinned"}):
        result = result_fixture(task)
        if expected:
            result["runtime"]["version"] = expected["version"]
        with pytest.raises(contracts.CurieContractError):
            validate(result, task=task, settings=SETTINGS, expected_runtime=expected)


def _keyword_plan_v2_fixture(count):
    proposals = [
        {"proposal": f"keyword evidence {index}", "query": f"keyword evidence {index}",
         "year_start": None, "year_end": None}
        for index in range(1, count + 1)
    ]
    keyword_generation = {
        "mode": "paperqa2-keyword-proposals-v1",
        "invocation_sha256": "1" * 64,
        "bridge_sha256": "2" * 64,
        "settings_sha256": "3" * 64,
        "requested_count": 3,
        "proposals": proposals,
        "runtime": {
            "package": "paper-qa", "version": "2026.8.12",
            "upstream_tag": "v2026.08.12",
            "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
            "module_path": "D:/paper-qa/src/paperqa/agents/helpers.py",
            "clean_checkout": True, "generation_year": 2026,
            "llm_model": "deepseek/deepseek-flash",
        },
        "completion": {
            "terminal_state": "completed", "returncode": 0,
            "stdout_truncated": False, "stderr_truncated": False,
            "process_tree_cleanup": {
                "attempted": False, "targeted_pids": [], "terminated_pids": [],
                "killed_pids": [], "errors": [], "alive_after_cleanup": False,
            },
        },
    }
    queries = [
        {"query_id": f"Q{index:03d}", "intent": "paperqa2_keyword_batch",
         "query": proposal["query"], "concepts": ["anchor-1"],
         "providers": ["europe-pmc"], "query_content_hash": hashlib.sha256(
             json.dumps({"query": proposal["query"]}, sort_keys=True,
                        separators=(",", ":")).encode("utf-8")).hexdigest(),
         "origin": "generated"}
        for index, proposal in enumerate(proposals, 1)
    ]
    return {
        "schema_version": "L05QueryPlan/v2", "candidate_id": "C1", "round_id": "1",
        "seed_sha256": SHA, "plan_id": "QP2", "round_index": 1,
        "planner": "paperqa2-keyword-proposals-v1", "reformulation_index": 0,
        "queries": queries, "planning": {"schema_version": "L05ScientificQueryPlan/v2"},
        "planning_provenance": {"receipt": {"validation_status": "PASS"},
                                "keyword_generation": keyword_generation},
    }


@pytest.mark.parametrize("count", [1, 2, 3])
def test_query_plan_v2_structurally_admits_one_to_three_keyword_proposals(count):
    plan = _keyword_plan_v2_fixture(count)

    validated = contracts.validate_query_plan(plan, seed_sha256=SHA)

    assert validated == plan


def test_query_plan_v1_rejects_keyword_generation_extension():
    plan = {"schema_version": contracts.QUERY_PLAN_SCHEMA_VERSION,
            "candidate_id": "C1", "round_id": "1", "seed_sha256": SHA,
            "plan_id": "QP1", "round_index": 1,
            "queries": [{"query_id": "Q001", "intent": "legacy",
                         "query": "legacy query", "providers": ["pubmed"]}],
            "planning_provenance": {"keyword_generation": {}}}

    with pytest.raises(contracts.CurieContractError):
        contracts.validate_query_plan(plan, seed_sha256=SHA)


@pytest.mark.parametrize("mutation", ["extra_field", "wrong_request_count", "query_count_mismatch"])
def test_query_plan_v2_rejects_open_or_mismatched_keyword_generation(mutation):
    plan = _keyword_plan_v2_fixture(1)
    generation = plan["planning_provenance"]["keyword_generation"]
    if mutation == "extra_field":
        generation["unexpected"] = True
    elif mutation == "wrong_request_count":
        generation["requested_count"] = 2
    else:
        plan["queries"].append(copy.deepcopy(plan["queries"][0]))
        plan["queries"][1]["query_id"] = "Q002"

    with pytest.raises(contracts.CurieContractError):
        contracts.validate_query_plan(plan, seed_sha256=SHA)
