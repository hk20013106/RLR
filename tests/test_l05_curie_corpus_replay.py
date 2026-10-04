"""Corpus transactions use actual child output and persisted replay artifacts."""
import copy
import hashlib
import io
from pathlib import Path
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from research_loop import host_handoff, research_seed
from research_loop.l05_curie import europepmc_runtime as owner
from research_loop.l05_curie import paperqa2_runtime as worker
from research_loop.l05_curie.paperqa2 import canonical_corpus_bytes
from test_l05_curie_corpus_contracts import api, SETTINGS, SEED, identify
from test_l05_curie_corpus_process import setup
from test_l05_curie_europepmc_runtime import (_host_project, _host_planner_plan, _planner_schema_plan,
    _search_record, _search_payload, XML, _GOOD_TITLE)


def transaction(tmp_path, mode="normal"):
    project, backend, task, _ = setup(tmp_path, mode=mode)
    task["research_seed_sha256"] = research_seed.seed_sha256(SEED); identify(task)
    checkpoint = {"schema_version": "L05AcquisitionCheckpoint/v2", "worker_mode": "corpus-evidence-v1",
        "candidate_id": "C001", "round_id": "1", "acquisition_run_id": "run-1",
        "seed_sha256": task["research_seed_sha256"], "execution_mode": "agent_native",
        "worker_attempts": {}, "external_state": None, "phase": "VALIDATED", "frozen_seed": copy.deepcopy(SEED)}
    path = project / "08_Audit/l05_acquisition/C001/run-1/host_checkpoint.json"
    calls = []
    native_execute = backend.execute_corpus
    def counted(**kwargs):
        calls.append(kwargs)
        saved = owner._read_object(path)
        assert saved["external_state"] == "WORKER_IN_FLIGHT"
        assert saved["worker_attempts"]["1"]["state"] == "IN_FLIGHT"
        return native_execute(**kwargs)
    backend.execute_corpus = counted
    return project, checkpoint, path, backend, task, calls


def dispatch(project, checkpoint, path, backend, task):
    with owner._first_acquisition_writer(project, checkpoint["candidate_id"], checkpoint["round_id"]):
        return api(owner, "_worker_for_attempt")(project, checkpoint, checkpoint_path=path,
            task=task, settings=copy.deepcopy(SETTINGS), backend=backend, attempt_index=1)


def test_prepared_dispatch_once(tmp_path):
    project, cp, path, backend, task, calls = transaction(tmp_path)
    first = dispatch(project, cp, path, backend, task)
    frozen = (project / first["task_ref"]["path"]).read_bytes()
    second = dispatch(project, cp, path, backend, task)
    assert first == second and len(calls) == 1
    assert frozen == canonical_corpus_bytes(task)
    assert owner._read_object(path)["worker_attempts"]["1"]["state"] == "COMPLETE"


@pytest.mark.parametrize("partial", ["none", "stdout", "result", "complete"])
def test_crash_windows(tmp_path, partial):
    project, cp, path, backend, task, calls = transaction(tmp_path)
    initial = dispatch(project, cp, path, backend, task)
    slot = cp["worker_attempts"]["1"]
    slot["state"] = "IN_FLIGHT"; slot.pop("completion_ref", None); slot.pop("result_ref", None)
    cp["external_state"] = "WORKER_IN_FLIGHT"
    worker_dir = project / initial["task_ref"]["path"]
    worker_dir = worker_dir.parent
    if partial != "complete": (worker_dir / "completion.json").unlink()
    if partial in {"none", "stdout"}: (worker_dir / "result.json").unlink()
    if partial == "none": (worker_dir / "stdout.log").unlink()
    owner._save_acquisition_checkpoint(path, cp)
    result = dispatch(project, cp, path, backend, task)
    assert len(calls) == 1
    if partial == "complete":
        assert result == initial and cp["external_state"] is None
    else:
        assert result["kind"] == "blocked" and result["reason"] == "uncertain_external_result"


def test_known_worker_failure_replays_without_restart(tmp_path):
    project, cp, path, backend, task, calls = transaction(tmp_path, "terminal")
    for _ in range(2):
        with pytest.raises(worker.PaperQA2ExecutionError): dispatch(project, cp, path, backend, task)
    assert len(calls) == 1
    assert cp["worker_attempts"]["1"]["state"] == "KNOWN_FAILURE"
    assert cp["external_state"] is None


def test_worker_replay_rejects_changed_settings_or_task(tmp_path):
    project, cp, path, backend, task, calls = transaction(tmp_path)
    dispatch(project, cp, path, backend, task)
    altered = copy.deepcopy(task); altered["question"] += "changed"
    with pytest.raises(owner.CurieContractError): dispatch(project, cp, path, backend, altered)
    assert len(calls) == 1


def test_worker_single_writer(tmp_path):
    project, cp, path, backend, task, calls = transaction(tmp_path)
    started, release = Event(), Event()
    execute = backend.execute_corpus
    def delayed(**kwargs):
        started.set(); assert release.wait(10); return execute(**kwargs)
    backend.execute_corpus = delayed
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(dispatch, project, cp, path, backend, task)
        assert started.wait(5)
        try:
            with pytest.raises(owner.CurieAcquisitionError, match="active writer"):
                dispatch(project, copy.deepcopy(cp), path, backend, task)
        finally: release.set()
        future.result()
    assert len(calls) == 1


def coverage_binding(tmp_path, monkeypatch):
    project, seed = _host_project(tmp_path, monkeypatch)
    cp, path = owner._host_checkpoint(project, "C001", "1", "focus-run", seed)
    gaps = [{"gap_id": "G1", "topic": "SCIENTIFIC_QUESTION", "reason": "Missing mechanism",
             "search_directions": ["mechanism"]}]
    assessment = {"schema_version": "L05ScientificCoverageAssessment/v1", "dimensions": [
        {"dimension_id": name, "sufficient": False, "reason": "missing", "admitted_evidence_ids": []}
        for name in ("SCIENTIFIC_QUESTION", "HYPOTHESIS_EVALUABILITY")],
        "gaps": gaps + [{**gaps[0], "gap_id": "G2", "topic": "HYPOTHESIS_EVALUABILITY"}]}
    request = owner._host_request(project, candidate_id="C001", round_id="1", attempt_index=1,
        stage="coverage:1", persona="Coverage", inputs={"seed": seed, "seed_sha256": research_seed.seed_sha256(seed),
            "acquisition_run_id": "focus-run", "admitted_evidence": []}, output_contract={"type": "object"})
    assessment["request_sha256"] = request["request_sha256"]
    raw_path = project / "coverage-answer.json"; owner._atomic_json(raw_path, assessment, immutable=True)
    receipt = host_handoff.submit_response(project, request["request_id"], raw_path, expected_cursor=request["identity"]["cursor"])
    ref = {"path": raw_path.relative_to(project).as_posix(), "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()}
    binding = {"origin_attempt": 1, "request_id": request["request_id"], "request_sha256": request["request_sha256"],
        "assessment_ref": ref, "host_response_receipt": receipt}
    cp["coverage_bindings"] = {"1": binding}; cp["current_coverage_binding"] = binding
    focus = {"coverage_request_sha256": request["request_sha256"], "coverage_assessment_sha256": ref["sha256"],
             "gaps": assessment["gaps"]}
    return project, seed, cp, focus, {"coverage_binding": copy.deepcopy(binding), "focus_choice": "validated_gaps"}


def test_focus_replay_uses_freeze_time_binding(tmp_path, monkeypatch):
    project, seed, cp, focus, context = coverage_binding(tmp_path, monkeypatch)
    check = api(owner, "_validate_focus_binding")
    assert check(project, seed, cp, attempt_index=2, evidence_focus=focus, freeze_context=context) == focus
    cp["current_coverage_binding"] = {"request_id": "later-valid-assessment"}
    context["replay"] = True
    assert check(project, seed, cp, attempt_index=2, evidence_focus=focus, freeze_context=context) == focus


@pytest.mark.parametrize("mutation", ["stale", "cross-run", "raw-gap", "missing-receipt", "partial"])
def test_invalid_focus_is_rejected_before_dispatch(tmp_path, monkeypatch, mutation):
    project, seed, cp, focus, context = coverage_binding(tmp_path, monkeypatch)
    if mutation == "stale": cp["current_coverage_binding"] = {}
    elif mutation == "cross-run": cp["acquisition_run_id"] = "other-run"
    elif mutation == "raw-gap": focus["gaps"][0]["reason"] = "unvalidated"
    elif mutation == "missing-receipt": context["coverage_binding"].pop("host_response_receipt")
    else: focus["gaps"].pop()
    with pytest.raises(owner.CurieContractError):
        api(owner, "_validate_focus_binding")(project, seed, cp, attempt_index=2,
            evidence_focus=focus, freeze_context=context)


def test_focus_requires_actual_origin_receipt(tmp_path, monkeypatch):
    project, seed, cp, focus, context = coverage_binding(tmp_path, monkeypatch)
    binding = context["coverage_binding"]
    receipt_path = project / "08_Audit/host_handoff/responses" / (binding["request_id"] + ".json")
    assert receipt_path.exists(); receipt_path.unlink()
    with pytest.raises(owner.CurieContractError):
        api(owner, "_validate_focus_binding")(project, seed, cp, attempt_index=2,
            evidence_focus=focus, freeze_context=context)


@pytest.mark.parametrize("stage", ["semantic:stable-evidence", "coverage:1"])
def test_host_pause_preserves_worker_refs(tmp_path, monkeypatch, stage):
    project, seed, cp, focus, context = coverage_binding(tmp_path, monkeypatch)
    cp["worker_attempts"] = {"1": {"state": "COMPLETE", "task_ref": {"path": "frozen-task", "sha256": "a" * 64}}}
    request = owner._host_request(project, candidate_id="C001", round_id="1", attempt_index=1,
        stage=stage, persona="Pause fixture", inputs={"seed": seed}, output_contract={"type": "object"}) if stage.startswith("semantic") else host_handoff.load_request(project, context["coverage_binding"]["request_id"])
    cp["current_request_id"] = request["request_id"]
    path = project / "08_Audit/l05_acquisition/C001/focus-run/host_checkpoint.json"
    owner._save_acquisition_checkpoint(path, cp)
    before = copy.deepcopy(cp["worker_attempts"])
    for _ in range(2):
        pending = owner._host_pending(project, cp, path)
        assert pending["kind"] == "needs_host" and pending["request_id"] == request["request_id"]
        assert pending["checkpoint"]["worker_attempts"] == before


def test_worker_checkpoint_path_escape_blocks_before_artifacts(tmp_path):
    project, cp, path, backend, task, calls = transaction(tmp_path)
    external = tmp_path / "outside" / "host_checkpoint.json"
    with pytest.raises(owner.CurieContractError): dispatch(project, cp, external, backend, task)
    assert not external.parent.exists() and not calls


def test_save_checkpoint_preserves_explicit_v2(tmp_path):
    project, cp, path, backend, task, calls = transaction(tmp_path)
    assert owner._save_acquisition_checkpoint(path, cp)["schema_version"] == "L05AcquisitionCheckpoint/v2"


def corpus_host_project(tmp_path, monkeypatch, *, project_seed=None, child_mode="normal"):
    project, seed = project_seed if project_seed is not None else _host_project(tmp_path, monkeypatch)
    child_root = tmp_path / "worker-fixture"; child_root.mkdir()
    _, backend, _, _ = setup(child_root, mode=child_mode)
    config = {"worker_mode": "corpus-evidence-v1", "settings": copy.deepcopy(SETTINGS),
        "python_executable": str(backend.python_executable), "bridge_script": str(backend.bridge_script),
        "paperqa_repo": str(backend.paperqa_repo), "pqa_home": str(backend.pqa_home), "timeout_seconds": 5}
    from research_loop import deep_research
    owner._atomic_json(deep_research.runtime_config_path(project), {"backend": "codex", "paperqa2": config})
    return project, seed, config


def test_corpus_checkpoint_freezes_config_once(tmp_path, monkeypatch):
    from research_loop import deep_research
    project, seed, config = corpus_host_project(tmp_path, monkeypatch)
    first, path = owner._host_checkpoint(project, "C001", "1", "config-run", seed)
    assert first["schema_version"] == "L05AcquisitionCheckpoint/v2"
    owner._atomic_json(deep_research.runtime_config_path(project), {"backend": "codex", "paperqa2": {"settings": "changed"}})
    second, _ = owner._host_checkpoint(project, "C001", "1", "config-run", seed)
    assert first["frozen_worker_config"] == second["frozen_worker_config"]
    assert second["frozen_worker_config"]["settings"] == SETTINGS


def test_corpus_config_rejects_unknown_keyword_query_generation_selector(tmp_path, monkeypatch):
    _project, _seed, config = corpus_host_project(tmp_path, monkeypatch)
    config["query_generation"] = "paperqa2-agent-loop"

    with pytest.raises(worker.CurieContractError, match="query_generation"):
        worker.validate_corpus_worker_config(config)


@pytest.mark.parametrize("field", ["worker_mode", "frozen_worker_config", "frozen_seed", "semantic_contract_sha256"])
def test_v2_checkpoint_never_downgrades_when_frozen_binding_is_missing(tmp_path, monkeypatch, field):
    project, seed, _ = corpus_host_project(tmp_path, monkeypatch)
    cp, path = owner._host_checkpoint(project, "C001", "1", "broken-v2", seed)
    cp.pop(field); owner._save_acquisition_checkpoint(path, cp)
    with pytest.raises(owner.CurieContractError):
        owner._host_checkpoint(project, "C001", "1", "broken-v2", seed)


def test_known_404_keeps_http_replay_slot(tmp_path, monkeypatch):
    project, seed, config = corpus_host_project(tmp_path, monkeypatch)
    step = owner.prepare_acquisition_host_step(project, "C001", run_id="HTTP_FAILURE")
    response_path = project / "planner.json"
    owner._atomic_json(response_path, {"status": "PLAN", "reason": "controlled", "plan": _planner_schema_plan(_host_planner_plan(seed))})
    owner.submit_acquisition_host_response(project, "C001", step["request_id"], response_path)
    bad = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1/A", title=_GOOD_TITLE)
    good = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_GOOD_TITLE)
    calls = []
    def http_get(url, timeout):
        calls.append(url)
        if "/search?" in url: return _search_payload(records=[bad, good])
        if "/PMC1111111/" in url: raise HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"missing-original"))
        return XML
    monkeypatch.setattr(owner, "_default_http_get", http_get)
    first = owner.continue_acquisition(project, "C001", run_id="HTTP_FAILURE")
    before = len(calls)
    second = owner.continue_acquisition(project, "C001", run_id="HTTP_FAILURE")
    assert first["kind"] == second["kind"] == "needs_host"
    assert first["request_id"] == second["request_id"] and len(calls) == before
    cp = owner._read_object(project / first["checkpoint_path"])
    failures = [r for r in cp["http_responses"] if r.get("state") == "KNOWN_FAILURE"]
    assert len(failures) == 1 and failures[0]["status"] == 404
    assert (project / failures[0]["path"]).read_bytes() == b"missing-original"
    assert cp["worker_attempts"]["1"]["state"] == "COMPLETE"
