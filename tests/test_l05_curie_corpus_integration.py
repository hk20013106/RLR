"""Offline first-owner closure through actual worker and host transports."""
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from research_loop import research_seed
from research_loop.l05_curie import europepmc_runtime as owner, paperqa2_runtime, query_planner
from research_loop.l05_curie.store import load_frozen_evidence_pack
from test_l05_curie_corpus_replay import corpus_host_project
from test_l05_curie_europepmc_runtime import (_host_planner_plan, _planner_schema_plan,
    _search_record, _search_payload, XML, _GOOD_TITLE)
from test_l05_curie_p1_planning import _anchor
from test_l05_curie_scientific_coverage import answer_for


RUN = "corpus-integration"


def _acceptance_protocol_fixture(tmp_path, monkeypatch):
    """Control only CLI transport; keep the public RLR controller real."""
    import subprocess
    import run_loop
    import paperqa2_corpus_acceptance as acceptance
    from types import SimpleNamespace

    assert callable(getattr(acceptance, "run_live_step", None)), (
        "live-corpus acceptance must expose its existing host-next step"
    )
    project, seed, _ = corpus_host_project(tmp_path, monkeypatch, child_mode="one-context")
    commands = []
    monkeypatch.setattr(run_loop, "current_action", lambda *args: {"kind": "l05"})

    def cli_transport(command, **kwargs):
        commands.append(command)
        action = run_loop.host_protocol_next(
            project, "C001", None, SimpleNamespace(no_review=True), "1", {}
        )
        return subprocess.CompletedProcess(command, 0, json.dumps(action).encode(), b"")

    monkeypatch.setattr(acceptance.subprocess, "run", cli_transport)
    return acceptance, project, seed, commands


def _authorized_test_credential(project, value="TEST_ONLY_TASK11_CREDENTIAL"):
    path = project / "authorized_test.env"
    path.write_text(f"DEEPSEEK_API_KEY={value}\n", encoding="utf-8")
    return path


def test_acceptance_driver_uses_public_protocol(tmp_path, monkeypatch):
    acceptance, project, _, commands = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    binding = project / "00_Preflight/deep_research_runtime.json"
    step = acceptance.run_live_step(binding, "C001", _authorized_test_credential(project))
    assert step["status"] == "NEEDS_HOST" and step["real_e2e"] == "PENDING"
    assert len(commands) == 1 and "host-next" in commands[0] and "--resume" in commands[0]
    assert step["host_provider_calls"] == 0
    request = json.loads(Path(step["action"]["request_path"]).read_bytes())
    assert request["identity"]["stage"] == "planner"
    assert step["action"]["request_sha256"] == hashlib.sha256(
        Path(step["action"]["request_path"]).read_bytes()
    ).hexdigest()


def test_needs_host_pauses_and_resumes_same_request(tmp_path, monkeypatch):
    import run_loop

    acceptance, project, seed, _ = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    binding = project / "00_Preflight/deep_research_runtime.json"
    credential_file = _authorized_test_credential(project)
    first = acceptance.run_live_step(binding, "C001", credential_file)
    paused = acceptance.run_live_step(binding, "C001", credential_file)
    assert paused["action"]["request_id"] == first["action"]["request_id"]

    request = json.loads(Path(first["action"]["request_path"]).read_bytes())
    response = project / "planner-answer.json"
    owner._atomic_json(
        response,
        {
            "status": "PLAN",
            "reason": "Offline controlled host response",
            "plan": _planner_schema_plan(_host_planner_plan(seed)),
        },
    )
    http_calls, worker_calls = [], []

    def http_get(url, timeout):
        http_calls.append(url)
        return _search_payload(records=[_search_record()]) if "/search?" in url else XML

    monkeypatch.setattr(owner, "_default_http_get", http_get)
    worker = owner._worker_for_attempt

    def counted(*args, **kwargs):
        backend = kwargs["backend"]
        execute = backend.execute_corpus

        def counted_execute(**call_kwargs):
            worker_calls.append(call_kwargs["task"]["task_id"])
            return execute(**call_kwargs)

        backend.execute_corpus = counted_execute
        try:
            return worker(*args, **kwargs)
        finally:
            backend.execute_corpus = execute

    monkeypatch.setattr(owner, "_worker_for_attempt", counted)
    committed = run_loop.host_protocol_submit(project, "C001", request["request_id"], response)
    assert committed["status"] == "committed"
    credential_file = _authorized_test_credential(project)
    resumed = acceptance.run_live_step(binding, "C001", credential_file)
    before = (list(http_calls), list(worker_calls))
    repeated = acceptance.run_live_step(binding, "C001", credential_file)
    assert resumed["action"]["request_id"] == repeated["action"]["request_id"]
    assert repeated["action"]["request_id"] == committed["continuation"]["request_id"]
    assert repeated["host_provider_calls"] == 0 and len(worker_calls) == 1
    assert (http_calls, worker_calls) == before


def test_first_blocker_marks_later_stages_not_attempted(tmp_path, monkeypatch):
    import subprocess

    acceptance, project, _, commands = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    error = b"Original worker failure; controlled offline transport\n"

    def blocked(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, b"", error)

    monkeypatch.setattr(acceptance.subprocess, "run", blocked)
    binding = project / "00_Preflight/deep_research_runtime.json"
    step = acceptance.run_live_step(binding, "C001", _authorized_test_credential(project))
    assert step["status"] == "BLOCKED" and step["real_e2e"] == "BLOCKED"
    assert step["coverage"]["status"] == step["l1"]["status"] == "NOT ATTEMPTED"
    raw_error = Path(step["raw_error_path"]).read_bytes()
    assert b"=== stdout ===\n" in raw_error and b"=== stderr ===\n" in raw_error
    assert error.rstrip() in raw_error and len(commands) == 1
    assert step["host_provider_calls"] == 0


def test_live_acceptance_child_environment_is_minimal(tmp_path, monkeypatch):
    import subprocess

    acceptance, project, _, _ = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "PARENT_ENV_MUST_NOT_AUTHORIZE_LIVE_CHILD")
    monkeypatch.setenv("UNAPPROVED_TEST_SECRET", "NONSECRET_TEST_SENTINEL")
    monkeypatch.setenv("OBSIDIAN_VAULT", "C:/approved-vault")
    observed = []
    action = {"status": "needs_host", "request_id": "REQ1"}
    credential_file = _authorized_test_credential(project, "FILE_AUTHORIZED_SENTINEL")

    def controlled_cli(command, **kwargs):
        observed.append(kwargs)
        return subprocess.CompletedProcess(command, 0, json.dumps(action).encode(), b"")

    monkeypatch.setattr(acceptance.subprocess, "run", controlled_cli)
    binding = project / "00_Preflight/deep_research_runtime.json"
    step = acceptance.run_live_step(binding, "C001", credential_file)
    child_env = observed[0]["env"]
    assert step["status"] == "NEEDS_HOST"
    assert child_env["DEEPSEEK_API_KEY"] == "FILE_AUTHORIZED_SENTINEL"
    assert child_env["OBSIDIAN_VAULT"] == "C:/approved-vault"
    assert "UNAPPROVED_TEST_SECRET" not in child_env


def test_live_host_next_requires_explicit_authorized_credential_file(tmp_path, monkeypatch):
    acceptance, project, _, commands = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "PARENT_ENV_MUST_NOT_AUTHORIZE_LIVE_CHILD")
    binding = project / "00_Preflight/deep_research_runtime.json"

    with pytest.raises(ValueError, match="requires the authorized credential file"):
        acceptance.run_live_step(binding, "C001")

    assert commands == []


def test_credential_probe_child_sees_authorized_key_and_offline_flags(tmp_path, monkeypatch):
    import subprocess

    real_run = subprocess.run
    acceptance, project, _, _ = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "PARENT_ENV_MUST_NOT_WIN")
    monkeypatch.setenv("UNAPPROVED_PARENT_SECRET", "MUST_NOT_FORWARD")
    credential_file = tmp_path / "hermes.env"
    credential_file.write_text(
        "UNAPPROVED_SECRET=DO_NOT_FORWARD\nDEEPSEEK_API_KEY=FAKE_TASK11_SENTINEL\n",
        encoding="utf-8",
    )
    binding = project / "00_Preflight/deep_research_runtime.json"

    def probe_child(command, **kwargs):
        child_env = kwargs["env"]
        assert child_env["DEEPSEEK_API_KEY"] == "FAKE_TASK11_SENTINEL"
        assert child_env["HF_HUB_OFFLINE"] == "1"
        assert child_env["TRANSFORMERS_OFFLINE"] == "1"
        assert "UNAPPROVED_SECRET" not in child_env
        assert "UNAPPROVED_PARENT_SECRET" not in child_env
        return real_run(command, **kwargs)

    monkeypatch.setattr(acceptance.subprocess, "run", probe_child)
    result = acceptance.run_credential_probe(binding, credential_file)

    assert result == "PAPERQA2_DEEPSEEK_CREDENTIAL=AVAILABLE"


def test_actual_host_submit_child_forwards_key_and_offline_flags_to_worker(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    real_run = subprocess.run
    acceptance, project, _, _ = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "PARENT_ENV_MUST_NOT_WIN")
    monkeypatch.setenv("UNAPPROVED_PARENT_SECRET", "MUST_NOT_FORWARD")
    credential = "FAKE_TASK11_HOST_SUBMIT_SENTINEL"
    credential_file = tmp_path / "hermes.env"
    credential_file.write_text(f"DEEPSEEK_API_KEY={credential}\n", encoding="utf-8")
    response = project / "host-response.json"
    response.write_text('{"status":"controlled"}\n', encoding="utf-8")
    child_observations = []

    def execute_host_submit_child(command, **kwargs):
        assert "host-submit" in command
        assert "REQ_TEST" in command
        child_env = kwargs["env"]
        assert child_env["DEEPSEEK_API_KEY"] == credential
        assert child_env["HF_HUB_OFFLINE"] == "1"
        assert child_env["TRANSFORMERS_OFFLINE"] == "1"
        assert "UNAPPROVED_PARENT_SECRET" not in child_env
        worker_code = (
            "import json, os; print(json.dumps({"
            "'credential': 'AVAILABLE' if os.getenv('DEEPSEEK_API_KEY') else 'MISSING',"
            "'hf_offline': os.getenv('HF_HUB_OFFLINE'),"
            "'transformers_offline': os.getenv('TRANSFORMERS_OFFLINE')}))"
        )
        host_submit_code = (
            "import json, os, sys; "
            "from research_loop.process_runner import ProcessRunner; "
            f"worker = ProcessRunner().run([sys.executable, '-c', {worker_code!r}], "
            "timeout=30, env=os.environ.copy(), encoding='utf-8', errors='strict'); "
            "print(json.dumps({'host_credential': 'AVAILABLE' if os.getenv('DEEPSEEK_API_KEY') "
            "else 'MISSING', 'worker': json.loads(worker.stdout), "
            "'worker_returncode': worker.returncode}))"
        )
        host_submit = real_run(
            [sys.executable, "-c", host_submit_code], env=child_env,
            capture_output=True, check=False,
        )
        child_observations.append(json.loads(host_submit.stdout))
        stdout = json.dumps({"status": "committed"}).encode("utf-8") + b"\n"
        return subprocess.CompletedProcess(command, host_submit.returncode, stdout, host_submit.stderr)

    monkeypatch.setattr(acceptance.subprocess, "run", execute_host_submit_child)
    binding = project / "00_Preflight/deep_research_runtime.json"

    result = acceptance.main([
        "--case", "live-host-submit",
        "--binding-file", str(binding),
        "--credential-file", str(credential_file),
        "--request-id", "REQ_TEST",
        "--response-file", str(response),
    ])

    assert result == 0
    assert child_observations == [{
        "host_credential": "AVAILABLE",
        "worker": {
            "credential": "AVAILABLE",
            "hf_offline": "1",
            "transformers_offline": "1",
        },
        "worker_returncode": 0,
    }]
    assert os.environ.get("DEEPSEEK_API_KEY") == "PARENT_ENV_MUST_NOT_WIN"
    assert os.environ["DEEPSEEK_API_KEY"] != credential


def test_public_host_submit_process_receives_file_credential_and_offline_flags(tmp_path, monkeypatch):
    import os
    import subprocess

    real_run = subprocess.run
    acceptance, project, _, _ = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(acceptance.subprocess, "run", real_run)
    credential = "FAKE_TASK11_REAL_HOST_SUBMIT_SENTINEL"
    credential_file = tmp_path / "authorized.env"
    credential_file.write_text(f"DEEPSEEK_API_KEY={credential}\n", encoding="utf-8")
    response = tmp_path / "host-response.json"
    response.write_text("{}\n", encoding="utf-8")
    observation = tmp_path / "host-submit-environment.json"
    site_dir = tmp_path / "sitecustomize"
    site_dir.mkdir()
    site_code = (
        "import json, os; from pathlib import Path; "
        f"Path({str(observation)!r}).write_text(json.dumps({{"
        "'credential_available': bool(os.environ.get('DEEPSEEK_API_KEY')), "
        "'hf_hub_offline': os.environ.get('HF_HUB_OFFLINE'), "
        "'transformers_offline': os.environ.get('TRANSFORMERS_OFFLINE')}), "
        "encoding='utf-8')"
    )
    (site_dir / "sitecustomize.py").write_text(site_code, encoding="utf-8")
    repo_src = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(site_dir), str(repo_src))))
    binding = project / "00_Preflight/deep_research_runtime.json"

    result = acceptance.run_live_submit(
        binding, "C001", "REQ_NO_PENDING_TEST", response, credential_file,
    )

    assert result["status"] == "BLOCKED"
    assert json.loads(observation.read_text(encoding="utf-8")) == {
        "credential_available": True,
        "hf_hub_offline": "1",
        "transformers_offline": "1",
    }
    assert credential not in json.dumps(result)
    assert credential.encode("utf-8") not in Path(result["raw_error_path"]).read_bytes()


def test_file_loaded_credential_is_redacted_from_host_submit_artifacts(tmp_path, monkeypatch):
    import subprocess

    acceptance, project, _, _ = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    credential = "FAKE_TASK11_PERSISTENCE_SENTINEL"
    credential_file = tmp_path / "hermes.env"
    credential_file.write_text(f"DEEPSEEK_API_KEY={credential}\n", encoding="utf-8")
    response = project / "host-response.json"
    response.write_text('{"status":"controlled"}\n', encoding="utf-8")

    def failed_host_submit(command, **kwargs):
        assert "host-submit" in command
        return subprocess.CompletedProcess(
            command, 1, f"unexpected {credential}".encode("utf-8"), b"controlled failure",
        )

    monkeypatch.setattr(acceptance.subprocess, "run", failed_host_submit)
    binding = project / "00_Preflight/deep_research_runtime.json"

    result = acceptance.run_live_submit(
        binding, "C001", "REQ_TEST", response, credential_file,
    )

    assert result["status"] == "BLOCKED"
    for path in project.rglob("*"):
        if path.is_file():
            assert credential.encode("utf-8") not in path.read_bytes()
    assert credential not in json.dumps(result)


def test_first_blocker_retains_both_output_streams_and_redacts_authorized_key(
    tmp_path, monkeypatch,
):
    import subprocess

    acceptance, project, _, _ = _acceptance_protocol_fixture(tmp_path, monkeypatch)
    secret_sentinel = b"NONSECRET_TEST_SENTINEL"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    stdout = b"controller output " + secret_sentinel + b"\n"
    stderr = b"worker traceback\n"

    def blocked(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout, stderr)

    monkeypatch.setattr(acceptance.subprocess, "run", blocked)
    binding = project / "00_Preflight/deep_research_runtime.json"
    step = acceptance.run_live_step(
        binding, "C001", _authorized_test_credential(project, secret_sentinel.decode()),
    )
    raw_error = Path(step["raw_error_path"]).read_bytes()
    assert b"=== stdout ===\n" in raw_error and b"=== stderr ===\n" in raw_error
    assert b"controller output [REDACTED]" in raw_error
    assert b"worker traceback" in raw_error
    assert secret_sentinel not in raw_error


def proposal(seed, request):
    index = request["identity"]["attempt"] - 1
    plan = _host_planner_plan(seed)
    terms = [("scientific_question", "yeast"), ("scientific_question", "sensed"),
             ("hypothesis_seed", "regulates"), ("hypothesis_seed", "transcriptional"),
             ("hypothesis_seed", "response"), ("scientific_question", "How")][index*2:index*2+2]
    plan["optional_concepts"] = [_anchor(seed, field, term, f"optional-{i}")
                                 for i, (field, term) in enumerate(terms)]
    plan["intents"] = [{"intent_id": f"intent-{i}", "core_concept_ids": ["carbon-dioxide", "rca1p"],
        "optional_concept_ids": [f"optional-{i}"]} for i in range(2)]
    # Source-bound PLAN proposals use the existing validator, never a test planner.
    plan["reformulation_index"] = index
    return {"status": "PLAN", "reason": "Controlled source-bound discovery intents",
            "plan": _planner_schema_plan(plan)}


def drive(tmp_path, monkeypatch, *, rounds=3, interrupt=None, empty=False, no_new=False, submitter=None):
    project, seed, _ = corpus_host_project(tmp_path, monkeypatch, child_mode="one-context")
    calls = {"http": [], "worker": [], "host": []}
    original_worker = owner._worker_for_attempt
    def counted_worker(*args, **kwargs):
        # Count actual child executions, rather than replay entry calls.
        backend = kwargs["backend"]
        native = backend.execute_corpus
        def execute(**kw):
            calls["worker"].append(len(kw["task"]["corpus"]))
            return native(**kw)
        backend.execute_corpus = execute
        try:
            return original_worker(*args, **kwargs)
        finally:
            backend.execute_corpus = native
    monkeypatch.setattr(owner, "_worker_for_attempt", counted_worker)
    def http_get(url, timeout):
        calls["http"].append(url)
        if "/search?" not in url:
            return XML
        if empty:
            return b'{"hitCount":0,"resultList":{"result":[]}}'
        query = parse_qs(urlparse(url).query)["query"][0]
        order = ["yeast", "sensed", "regulates", "transcriptional", "response", "how"]
        batch = next(i for i, term in enumerate(order) if f"({term})" in query.lower())
        if no_new and batch >= 2: batch %= 2
        assert parse_qs(urlparse(url).query)["pageSize"] == ["25"]
        records = [_search_record(pmid=str(900000+i), pmcid=f"PMC{900000+i}",
            doi=f"10.1234/corpus-{i}", title=f"{_GOOD_TITLE} controlled paper {i}")
            for i in range(batch*15, batch*15+15)]
        return _search_payload(records=records)
    monkeypatch.setattr(owner, "_default_http_get", http_get)
    step = owner.prepare_acquisition_host_step(project, "C001", run_id=RUN)
    while step["kind"] == "needs_host":
        request = step["request"]
        stage = request["identity"]["stage"]
        calls["host"].append(stage)
        if stage == "planner":
            answer = proposal(seed, request)
        elif stage.startswith("semantic:"):
            answer = {"entailment": "CONTRADICTED", "scope_match": True,
                "context_preserved": True, "qualification_preserved": True,
                "reason": "Controlled counterevidence, not a scientific acceptance"}
        else:
            assert stage.startswith("coverage:")
            answer = answer_for(request, sufficient=not empty and int(stage.split(":")[1]) == rounds)
        response = project / (step["request_id"] + "-answer.json")
        owner._atomic_json(response, answer)
        if submitter is not None:
            step = submitter(project, seed, step, response)
            continue
        owner.submit_acquisition_host_response(project, "C001", step["request_id"], response)
        if interrupt and stage == f"coverage:{rounds}":
            interrupt(project, seed, calls)
        step = owner.continue_acquisition(project, "C001", run_id=RUN)
    return project, seed, step, calls


def canonical_result(step):
    return {k: v for k, v in step.items() if k != "kind"}


@pytest.mark.parametrize("inherit_corpus", [False, True])
def test_frozen_corpus_initial_pack_supports_existing_authorized_retry(tmp_path, monkeypatch, inherit_corpus):
    import research_loop.l05_curie as curie
    from research_loop.l05_curie.native_runtime import run_authorized_retry
    import test_l05_curie_native_runtime as retry_fixture

    project, seed, step, _ = drive(tmp_path, monkeypatch, rounds=1)
    first = step["evidence_pack"]
    owner.bind_initial_curie_pack(project, seed, first, RUN)
    initial_bytes = (project / first["artifact_path"]).read_bytes()
    parent = load_frozen_evidence_pack(project, first, candidate_id="C001", round_id="1",
        seed_sha256=research_seed.seed_sha256(seed))
    request = retry_fixture._gap(project, seed, first, "G1")
    monkeypatch.setattr(retry_fixture, "_seed", lambda: seed)

    def acquire(auth):
        if not inherit_corpus:
            return retry_fixture._freeze(project, version=auth["next_version"], run_id="CURIE002",
                parent=auth["parent_pack_sha256"], gap_id=auth["source_gap_request_id"])
        plans = copy.deepcopy(parent["query_plans"])
        for plan in plans:
            plan["round_index"] = auth["next_version"]
        coverage = curie.judge_coverage({"covered": ["verified_full_text_source"], "gaps": []},
                                      round_index=auth["next_version"], max_rounds=3)
        pack = curie.build_evidence_pack(candidate_id="C001", round_id="1",
            seed_sha256=research_seed.seed_sha256(seed), version=auth["next_version"],
            query_plans=plans, discovery_receipts=parent["discovery_receipts"],
            selected_papers=parent["selected_papers"], evidence=parent["evidence"],
            semantic_verifications=parent["semantic_verifications"], coverage=coverage, gaps=[],
            source_run_id="CURIE002", parent_pack_sha256=auth["parent_pack_sha256"],
            source_gap_request_id=auth["source_gap_request_id"])
        return curie.freeze_evidence_pack(project, pack)

    result = run_authorized_retry(project, seed, first, request["request_id"], "CURIE002", acquire)
    assert result["binding"]["evidence_pack_version"] == 2
    assert research_seed.active_l1_native_evidence_run_id(project, seed) == "CURIE002"
    assert (project / first["artifact_path"]).read_bytes() == initial_bytes
    # Retry lineage must continue to validate the actual corpus parent, not bypass its proof.
    paths = owner._acquisition_paths(project, "C001", "1", RUN)
    paths["checkpoint"].unlink()
    with pytest.raises(research_seed.ResearchSeedError):
        research_seed.load_l1_native_evidence_binding(project, seed, "CURIE002")


def test_historical_frozen_pack_coexists_with_different_active_first_owner(tmp_path, monkeypatch):
    import test_l05_curie_native_runtime as retry_fixture
    seed = retry_fixture._seed()
    first = retry_fixture._freeze(tmp_path, version=1, run_id="CURIE001")
    paths = owner._acquisition_paths(tmp_path, "C001", "1", "OTHER-RUN")
    owner._atomic_json(paths["owner"], {"schema_version": "L05FirstAcquisitionOwner/v1",
        "candidate_id": "C001", "round_id": "1", "seed_sha256": research_seed.seed_sha256(seed),
        "acquisition_run_id": "OTHER-RUN"})
    binding = owner.bind_initial_curie_pack(tmp_path, seed, first, "CURIE001")
    assert binding["evidence_pack_version"] == 1


def _start_keyword_batch(tmp_path, monkeypatch, proposals):
    from research_loop import deep_research
    from research_loop.process_runner import ProcessResult

    project, seed, config = corpus_host_project(tmp_path, monkeypatch, child_mode="one-context")
    config["query_generation"] = "paperqa2-keyword-proposals-v1"
    owner._atomic_json(deep_research.runtime_config_path(project), {"backend": "codex", "paperqa2": config})
    helper_calls = []
    admitted = 1 <= len(proposals) <= 3
    repo = Path(config["paperqa_repo"]).resolve()

    class QueryBackend:
        def execute_search_queries(self, *, question, count, settings, expected_runtime):
            helper_calls.append((question, count, copy.deepcopy(settings)))
            runtime = {
                **expected_runtime,
                "module_path": str(repo / "src" / "paperqa" / "agents" / "helpers.py"),
                "clean_checkout": True,
                "generation_year": 2026,
            }
            stdout = json.dumps({"proposals": proposals, "runtime": runtime}, sort_keys=True)
            process = ProcessResult(
                returncode=0, terminal_state="completed", stdout=stdout, stderr="",
                stdout_truncated=False, stderr_truncated=False,
                stdout_bytes=len(stdout.encode("utf-8")), stderr_bytes=0,
                timeout_seconds=300,
                process_tree_cleanup={"attempted": False, "targeted_pids": [],
                    "terminated_pids": [], "killed_pids": [], "errors": [], "alive_after_cleanup": False},
            )
            return process, {"proposals": proposals, "runtime": runtime}

    monkeypatch.setattr(paperqa2_runtime, "corpus_backend_from_config", lambda _config: QueryBackend())
    checkpoint_path = owner._acquisition_paths(project, "C001", "1", RUN)["checkpoint"]
    http_calls = []

    def http_get(url, timeout):
        if "/search?" in url:
            http_calls.append(url)
            assert admitted, "invalid keyword batch reached Europe PMC"
            checkpoint = owner._read_object(checkpoint_path)
            ref = checkpoint.get("query_plan_refs", {}).get("1")
            assert isinstance(ref, dict), "Europe PMC ran before the keyword QueryPlan was receipted"
            plan_path = project / ref["path"]
            assert hashlib.sha256(plan_path.read_bytes()).hexdigest() == ref["sha256"]
            plan = json.loads(plan_path.read_bytes())
            assert plan["schema_version"] == "L05QueryPlan/v2"
            assert [row["query"] for row in plan["queries"]] == proposals
            return b'{"hitCount":0,"resultList":{"result":[]}}'
        pytest.fail(f"unexpected full-text request after zero-hit discovery: {url}")

    monkeypatch.setattr(owner, "_default_http_get", http_get)
    step = owner.prepare_acquisition_host_step(project, "C001", run_id=RUN)
    request = step["request"]
    response = project / "planner-answer.json"
    owner._atomic_json(response, {
        "status": "PLAN", "reason": "Controlled source-bound intent",
        "plan": _planner_schema_plan(_host_planner_plan(seed)),
    })
    owner.submit_acquisition_host_response(project, "C001", step["request_id"], response)
    return project, seed, config, helper_calls, http_calls, checkpoint_path


@pytest.mark.parametrize(("proposals", "admitted"), [
    (["single yeast query"], True),
    (["broad yeast evidence", "narrow yeast mechanism"], True),
    (["broad yeast evidence", "narrow yeast mechanism", "comparative yeast study"], True),
    ([], False),
    (["query one", "query two", "query three", "query four"], False),
])
def test_keyword_batch_is_persisted_before_first_europepmc_request(
    tmp_path, monkeypatch, proposals, admitted,
):
    project, seed, config, helper_calls, http_calls, checkpoint_path = _start_keyword_batch(
        tmp_path, monkeypatch, proposals,
    )

    if admitted:
        next_step = owner.continue_acquisition(project, "C001", run_id=RUN)
        assert next_step["kind"] == "needs_host"
        assert next_step["request"]["identity"]["stage"] == "coverage:1"
        assert len(http_calls) == len(proposals)
        coverage_response = project / "keyword-coverage-answer.json"
        owner._atomic_json(coverage_response, answer_for(next_step["request"], sufficient=False))
        owner.submit_acquisition_host_response(
            project, "C001", next_step["request_id"], coverage_response,
        )
        helper_calls_before_resume = len(helper_calls)
        http_calls_before_resume = list(http_calls)
        terminal = owner.continue_acquisition(project, "C001", run_id=RUN)
        assert terminal["status"] == "INSUFFICIENT_STOP"
        assert len(helper_calls) == helper_calls_before_resume == 1
        assert http_calls == http_calls_before_resume
        canonical_terminal = canonical_result(terminal)
        assert owner.validate_europepmc_acquisition_result(
            project, "C001", canonical_terminal,
        ) == canonical_terminal
        assert owner.continue_acquisition(project, "C001", run_id=RUN) == terminal
        assert len(helper_calls) == 1 and http_calls == http_calls_before_resume
    else:
        with pytest.raises(owner.CurieAcquisitionError, match="MODEL_CONTRACT_ERROR"):
            owner.continue_acquisition(project, "C001", run_id=RUN)
        checkpoint = owner._read_object(checkpoint_path)
        assert checkpoint["external_error"]["category"] == "MODEL_CONTRACT_ERROR"
        with pytest.raises(owner.CurieAcquisitionError, match="MODEL_CONTRACT_ERROR"):
            owner.continue_acquisition(project, "C001", run_id=RUN)
        assert http_calls == []
    assert len(helper_calls) == 1 and helper_calls[0][1] == 3
    assert helper_calls[0][0].startswith("Scientific question:\n" + seed["scientific_question"])
    assert helper_calls[0][2] == config["settings"]


@pytest.mark.parametrize("failure_window", ["inflight-missing-plan", "plan-before-pointer"])
def test_keyword_query_checkpoint_replay_recovers_or_blocks_without_redispatch(
    tmp_path, monkeypatch, failure_window,
):
    proposals = ["broad yeast evidence", "narrow yeast mechanism"]
    project, _seed, _config, helper_calls, http_calls, checkpoint_path = _start_keyword_batch(
        tmp_path, monkeypatch, proposals,
    )
    pending = owner.continue_acquisition(project, "C001", run_id=RUN)
    assert pending["kind"] == "needs_host"
    assert pending["request"]["identity"]["stage"] == "coverage:1"
    assert len(helper_calls) == 1
    http_before_replay = list(http_calls)

    checkpoint = owner._read_object(checkpoint_path)
    original_ref = checkpoint["query_plan_refs"]["1"]
    plan_path = project / original_ref["path"]
    plan = owner._read_object(plan_path)
    generation = plan["planning_provenance"]["keyword_generation"]
    checkpoint["query_plan_refs"].pop("1")
    checkpoint.update({
        "external_state": "QUERY_IN_FLIGHT",
        "external_request": {
            "operation": "search-query-v1",
            "attempt_index": 1,
            "invocation_sha256": generation["invocation_sha256"],
            "bridge_sha256": generation["bridge_sha256"],
        },
        "phase": "QUERY_IN_FLIGHT",
    })
    if failure_window == "inflight-missing-plan":
        plan_path.unlink()
    owner._save_acquisition_checkpoint(checkpoint_path, checkpoint)

    coverage_response = project / "keyword-coverage-answer.json"
    owner._atomic_json(coverage_response, answer_for(pending["request"], sufficient=False))
    owner.submit_acquisition_host_response(
        project, "C001", pending["request_id"], coverage_response,
    )

    replayed = owner.continue_acquisition(project, "C001", run_id=RUN)
    assert len(helper_calls) == 1
    assert http_calls == http_before_replay
    recovered_checkpoint = owner._read_object(checkpoint_path)
    if failure_window == "inflight-missing-plan":
        assert replayed["kind"] == "blocked"
        assert replayed["reason"] == "uncertain_external_result"
        assert recovered_checkpoint["external_state"] == "uncertain_external_result"
        assert "1" not in recovered_checkpoint["query_plan_refs"]
        assert not plan_path.exists()
    else:
        assert replayed["status"] == "INSUFFICIENT_STOP"
        assert recovered_checkpoint["external_state"] is None
        assert recovered_checkpoint["query_plan_refs"]["1"] == original_ref
        assert plan_path.is_file()


def test_attempt_two_inflight_does_not_conflict_with_attempt_one_success_ref(tmp_path, monkeypatch):
    project, _seed, config = corpus_host_project(tmp_path, monkeypatch, child_mode="one-context")
    config["query_generation"] = "paperqa2-keyword-proposals-v1"
    invocation = {"attempt_index": 2, "bridge_sha256": "b" * 64}
    marker = {
        "operation": "search-query-v1",
        "attempt_index": 2,
        "invocation_sha256": owner._query_planner_sha(invocation),
        "bridge_sha256": invocation["bridge_sha256"],
    }
    base_plan = {
        "candidate_id": "C001", "round_id": "1", "planning": {},
        "providers": ["europe-pmc"], "queries": [{"providers": ["europe-pmc"]}],
    }
    monkeypatch.setattr(owner, "validate_query_plan", lambda value, **_kwargs: value)
    monkeypatch.setattr(
        owner, "_keyword_invocation",
        lambda *_args, **_kwargs: ("question", {}, invocation),
    )
    checkpoint = {
        "schema_version": owner.CORPUS_CHECKPOINT_SCHEMA_VERSION,
        "query_plan_refs": {"1": {
            "path": "08_Audit/l05_acquisition/C001/run/attempt_001/query_plan.json",
            "sha256": "a" * 64,
        }},
        "external_state": "QUERY_IN_FLIGHT",
        "external_request": marker,
        "phase": "QUERY_IN_FLIGHT",
    }
    checkpoint_path = project / "08_Audit/l05_acquisition/C001/run/host_checkpoint.json"
    owner._save_acquisition_checkpoint(checkpoint_path, checkpoint)

    class UncalledBackend:
        def execute_search_queries(self, **_kwargs):
            pytest.fail("attempt 2 uncertainty must not redispatch the helper")

    with pytest.raises(owner.CurieAcquisitionError, match="uncertain_external_result"):
        owner._keyword_query_plan_for_attempt(
            project, seed={"candidate_id": "C001", "round_id": "1"},
            base_plan=base_plan, feedback=None, prior_plans=[], attempt_index=2,
            run_id="run", run_root=checkpoint_path.parent, config=config,
            backend=UncalledBackend(), checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
        )

    replayed = owner._read_object(checkpoint_path)
    assert replayed["external_state"] == "uncertain_external_result"
    assert replayed["query_plan_refs"]["1"] == checkpoint["query_plan_refs"]["1"]


def test_sequential_replay_scopes_inflight_state_to_its_attempt(tmp_path, monkeypatch):
    proposals = ["broad yeast evidence", "narrow yeast mechanism"]
    from research_loop import deep_research
    from research_loop.process_runner import ProcessResult

    project, seed, config = corpus_host_project(tmp_path, monkeypatch, child_mode="one-context")
    config["query_generation"] = "paperqa2-keyword-proposals-v1"
    owner._atomic_json(deep_research.runtime_config_path(project),
                       {"backend": "codex", "paperqa2": config})
    checkpoint_path = owner._acquisition_paths(project, "C001", "1", RUN)["checkpoint"]
    http_calls = []
    helper_attempts = []
    search_index = 0

    def http_get(url, timeout):
        nonlocal search_index
        http_calls.append(url)
        if "/search?" not in url:
            return XML
        batch = search_index
        search_index += 1
        assert parse_qs(urlparse(url).query)["pageSize"] == ["25"]
        records = [_search_record(pmid=str(900000+i), pmcid=f"PMC{900000+i}",
            doi=f"10.1234/corpus-{i}", title=f"{_GOOD_TITLE} controlled paper {i}")
            for i in range(batch*15, batch*15+15)]
        return _search_payload(records=records)

    monkeypatch.setattr(owner, "_default_http_get", http_get)
    real_backend_factory = paperqa2_runtime.corpus_backend_from_config

    class QueryBackend:
        def __init__(self):
            self.corpus_backend = real_backend_factory(config)

        def execute_corpus(self, **kwargs):
            return self.corpus_backend.execute_corpus(**kwargs)

        def execute_search_queries(self, *, question, count, settings, expected_runtime):
            checkpoint = owner._read_object(checkpoint_path)
            attempt_index = checkpoint["external_request"]["attempt_index"]
            helper_attempts.append(attempt_index)
            if attempt_index == 2:
                assert checkpoint["external_state"] == "QUERY_IN_FLIGHT"
                raise SystemExit("simulated process interruption after durable marker")
            assert attempt_index == 1
            runtime = {**expected_runtime, "generation_year": 2026}
            payload = {"proposals": proposals, "runtime": runtime}
            stdout = json.dumps(payload, sort_keys=True)
            process = ProcessResult(
                returncode=0, terminal_state="completed", stdout=stdout, stderr="",
                stdout_truncated=False, stderr_truncated=False,
                stdout_bytes=len(stdout.encode("utf-8")), stderr_bytes=0,
                timeout_seconds=300,
                process_tree_cleanup={"attempted": False, "targeted_pids": [],
                    "terminated_pids": [], "killed_pids": [], "errors": [], "alive_after_cleanup": False},
            )
            assert count == 3 and settings == config["settings"] and question
            return process, payload

    monkeypatch.setattr(paperqa2_runtime, "corpus_backend_from_config", lambda _config: QueryBackend())
    step = owner.prepare_acquisition_host_step(project, "C001", run_id=RUN)
    while step["kind"] == "needs_host":
        request = step["request"]
        stage = request["identity"]["stage"]
        if stage == "planner" and request["identity"]["attempt"] == 2:
            break
        if stage == "planner":
            answer = proposal(seed, request)
        elif stage.startswith("semantic:"):
            answer = {"entailment": "CONTRADICTED", "scope_match": True,
                "context_preserved": True, "qualification_preserved": True,
                "reason": "Controlled counterevidence for replay fixture"}
        else:
            assert stage == "coverage:1"
            answer = answer_for(request, sufficient=False)
        response = project / (step["request_id"] + "-answer.json")
        owner._atomic_json(response, answer)
        owner.submit_acquisition_host_response(project, "C001", step["request_id"], response)
        step = owner.continue_acquisition(project, "C001", run_id=RUN)

    assert step["kind"] == "needs_host", step
    assert step["request"]["identity"]["stage"] == "planner"
    assert step["request"]["identity"]["attempt"] == 2
    planner_response = project / "attempt-two-planner-answer.json"
    owner._atomic_json(planner_response, proposal(seed, step["request"]))
    owner.submit_acquisition_host_response(project, "C001", step["request_id"], planner_response)

    checkpoint = owner._read_object(checkpoint_path)
    first_plan_ref = checkpoint["query_plan_refs"]["1"]
    assert len(helper_attempts) == 1 and helper_attempts == [1]
    http_calls_before_resume = list(http_calls)
    with pytest.raises(SystemExit, match="simulated process interruption"):
        owner.continue_acquisition(project, "C001", run_id=RUN)

    checkpoint = owner._read_object(checkpoint_path)
    first_http_responses = copy.deepcopy(checkpoint["http_responses"])
    assert checkpoint["external_state"] == "QUERY_IN_FLIGHT"
    assert checkpoint["external_request"]["attempt_index"] == 2
    assert checkpoint["query_plan_refs"]["1"] == first_plan_ref
    assert len(helper_attempts) == 2 and helper_attempts == [1, 2]
    assert http_calls == http_calls_before_resume

    resumed = owner.continue_acquisition(project, "C001", run_id=RUN)

    assert resumed["kind"] == "blocked"
    assert resumed["reason"] == "uncertain_external_result"
    checkpoint = owner._read_object(checkpoint_path)
    assert checkpoint["external_state"] == "uncertain_external_result"
    assert checkpoint["external_request"]["attempt_index"] == 2
    assert checkpoint["query_plan_refs"]["1"] == first_plan_ref
    assert checkpoint["http_responses"] == first_http_responses
    assert helper_attempts == [1, 2]
    assert http_calls == http_calls_before_resume


def test_headless_keyword_manifest_reconstructs_bound_query_config(tmp_path, monkeypatch):
    from research_loop import deep_research

    project, seed, config = corpus_host_project(tmp_path, monkeypatch, child_mode="one-context")
    config["query_generation"] = "paperqa2-keyword-proposals-v1"
    owner._atomic_json(
        deep_research.runtime_config_path(project),
        {"backend": "codex", "paperqa2": config},
    )
    run_id = "HEADLESS_KEYWORD"
    owner._atomic_json(
        project / "08_Audit/l05_acquisition/C001/first_1.json",
        {"schema_version": "L05FirstAcquisitionOwner/v1", "candidate_id": "C001",
         "round_id": "1", "seed_sha256": research_seed.seed_sha256(seed),
         "acquisition_run_id": run_id},
        immutable=True,
    )
    planning = {"schema_version": owner.SCIENTIFIC_QUERY_PLAN_V2}
    query_plan = {"schema_version": "L05QueryPlan/v2", "planning": planning}
    manifest = {
        "schema_version": owner.AUDIT_SCHEMA_VERSION,
        "candidate_id": "C001", "round_id": "1",
        "seed_sha256": research_seed.seed_sha256(seed),
        "acquisition_run_id": run_id,
        "target_pack_version": 1, "max_attempts": 3,
        "attempts": [{"attempt_index": 1, "query_plan": query_plan}],
    }
    monkeypatch.setattr(owner, "validate_query_plan", lambda value, **_kwargs: value)
    monkeypatch.setattr(owner, "validate_scientific_query_plan", lambda value, **_kwargs: value)
    observed = {}

    class ReachedKeywordInvocation(Exception):
        pass

    def capture_query_config(*_args, config, **_kwargs):
        observed["config"] = config
        raise ReachedKeywordInvocation

    monkeypatch.setattr(owner, "_keyword_invocation", capture_query_config)
    with pytest.raises(ReachedKeywordInvocation):
        owner._validate_acquisition_manifest(
            project, manifest, candidate_id="C001", round_id="1",
            seed_sha256=research_seed.seed_sha256(seed), run_id=run_id, seed=seed,
        )
    assert observed["config"]["query_generation"] == config["query_generation"]
    assert observed["config"]["settings"] == config["settings"]


@pytest.mark.parametrize("tamper", ["missing", "bytes"])
def test_terminal_keyword_manifest_revalidates_query_plan_artifact(tmp_path, monkeypatch, tamper):
    proposals = ["broad yeast evidence", "narrow yeast mechanism"]
    project, _seed, _config, _helper_calls, _http_calls, _checkpoint_path = _start_keyword_batch(
        tmp_path, monkeypatch, proposals,
    )
    pending = owner.continue_acquisition(project, "C001", run_id=RUN)
    response = project / "keyword-coverage-answer.json"
    owner._atomic_json(response, answer_for(pending["request"], sufficient=False))
    owner.submit_acquisition_host_response(project, "C001", pending["request_id"], response)
    terminal = owner.continue_acquisition(project, "C001", run_id=RUN)

    manifest = owner._read_object(project / terminal["acquisition_manifest_path"])
    plan_ref = manifest["attempts"][0]["query_plan_ref"]
    plan_path = project / plan_ref["path"]
    assert plan_path.is_file()
    if tamper == "missing":
        plan_path.unlink()
    else:
        plan_path.write_bytes(plan_path.read_bytes() + b"\n")

    with pytest.raises(owner.CurieAcquisitionError, match="QueryPlan artifact"):
        owner.validate_europepmc_acquisition_result(project, "C001", canonical_result(terminal))


def test_three_attempts_freeze_one_v1_pack(tmp_path, monkeypatch):
    project, seed, step, calls = drive(tmp_path, monkeypatch)
    assert calls["worker"] == [30, 60, 90]
    assert sum(s.startswith("semantic:") for s in calls["host"]) == 1
    assert sum(s.startswith("coverage:") for s in calls["host"]) == 3
    assert step["schema_version"] == "L05EuropePmcAcquisitionResult/v2"
    manifest = owner._read_object(project / step["acquisition_manifest_path"])
    assert manifest["schema_version"] == "L05EuropePmcAcquisitionManifest/v3"
    assert [len(a["source_snapshots"]) for a in manifest["attempts"]] == [30, 30, 30]
    assert [len(a["cumulative_corpus"]) for a in manifest["attempts"]] == [30, 60, 90]
    assert all(a["coverage_facts"]["round_index"] == 1 for a in manifest["attempts"])
    pack = load_frozen_evidence_pack(project, step["evidence_pack"], candidate_id="C001", round_id="1",
        seed_sha256=research_seed.seed_sha256(seed))
    assert pack["version"] == 1 and len(pack["selected_papers"]) == 90
    assert owner.validate_europepmc_acquisition_result(project, "C001", canonical_result(step)) == canonical_result(step)
    assert owner.validate_corpus_acquisition_for_pack(project, seed=seed, pack=pack) == canonical_result(step)
    before = copy.deepcopy(calls)
    assert owner.continue_acquisition(project, "C001", run_id=RUN) == step
    assert calls == before


@pytest.mark.parametrize("target", ["task", "focus", "completion", "settings", "corpus-order", "budget", "semantic", "coverage"])
def test_manifest_tampering_blocks_l1(tmp_path, monkeypatch, target):
    from research_loop import l05_native_binding
    project, seed, step, _ = drive(tmp_path, monkeypatch, rounds=1)
    manifest = owner._read_object(project / step["acquisition_manifest_path"])
    attempt = manifest["attempts"][0]
    if target in {"task", "focus", "completion", "settings"}:
        name = "task" if target == "focus" else target
        path = project / attempt["worker"][name + "_ref"]["path"]
        value = owner._read_object(path)
        if target == "focus": value["evidence_focus"] = {"illegal": "unverified focus"}
        else: value["tampered"] = True
    elif target in {"corpus-order", "budget"}:
        path = project / attempt["artifact"]["path"]
        value = owner._read_object(path)
        if target == "corpus-order": value["cumulative_corpus"].reverse()
        else: value["acquisition_state"]["corpus_count"] = 900
    else:
        if target == "coverage":
            binding = attempt["scientific_coverage"]["binding"]
            cp = owner._read_object(project / "08_Audit/l05_acquisition/C001" / RUN / "host_checkpoint.json")
            receipt = cp["coverage_responses"][binding["request_id"]]
        else: receipt = attempt["semantic_host_receipts"][0]["host_response_receipt"]
        path = Path(receipt["raw_response_path"])
        value = json.loads(path.read_bytes()); value["reason"] = "tampered"
    owner._atomic_json(path, value)
    with pytest.raises((research_seed.ResearchSeedError, owner.CurieContractError, OSError)):
        l05_native_binding._load_pack(project, seed, step["evidence_pack"], research_seed)


@pytest.mark.parametrize("window", ["freeze-input", "pack", "manifest", "committed"])
def test_freeze_crash_windows_recover_without_external_calls(tmp_path, monkeypatch, window):
    once = {"done": False}
    def install(project, seed, calls):
        names = {"freeze-input": "freeze_evidence_pack", "pack": "_validate_acquisition_manifest",
                 "manifest": "_save_acquisition_checkpoint", "committed": "_save_acquisition_checkpoint"}
        name = names[window]; original = getattr(owner, name)
        def crash(*args, **kwargs):
            applicable = name != "_save_acquisition_checkpoint" or args[1].get("phase") == "COMMITTED"
            if applicable and not once["done"]:
                once["done"] = True
                if window == "committed": original(*args, **kwargs)
                raise RuntimeError("controlled freeze interruption")
            return original(*args, **kwargs)
        monkeypatch.setattr(owner, name, crash)
    with pytest.raises(RuntimeError, match="controlled freeze interruption"):
        drive(tmp_path, monkeypatch, rounds=1, interrupt=install)
    project = tmp_path / "project"
    # Failed call counts are available from on-disk logical receipts and child invocations.
    cp_path = project / "08_Audit/l05_acquisition/C001" / RUN / "host_checkpoint.json"
    cp = owner._read_object(cp_path)
    originals = {p: p.read_bytes() for p in project.rglob("*.log")}
    monkeypatch.setattr(owner, "_default_http_get", lambda *_: pytest.fail("network replay"))
    from research_loop.l05_curie import paperqa2_runtime
    monkeypatch.setattr(paperqa2_runtime.PaperQA2SubprocessBackend, "execute_corpus", lambda *_a, **_kw: pytest.fail("worker replay"))
    step = owner.continue_acquisition(project, "C001", run_id=RUN)
    assert step["kind"] == "FROZEN"
    assert owner._read_object(cp_path)["phase"] == "COMMITTED"
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert owner._read_object(cp_path)["coverage_responses"] == cp["coverage_responses"]


@pytest.mark.parametrize("missing", ["manifest", "checkpoint", "all-mode-markers"])
def test_missing_new_provenance_never_legacy_fallback(tmp_path, monkeypatch, missing):
    from research_loop import l05_native_binding
    project, seed, step, _ = drive(tmp_path, monkeypatch, rounds=1)
    root = project / "08_Audit/l05_acquisition/C001" / RUN
    if missing == "manifest": (root / "acquisition_manifest.json").unlink()
    elif missing == "checkpoint": (root / "host_checkpoint.json").unlink()
    else:
        for path in root.rglob("*"):
            if path.is_file(): path.unlink()
        (root.parent / "first_1.json").unlink()
    with pytest.raises((research_seed.ResearchSeedError, owner.CurieContractError, OSError)):
        l05_native_binding._load_pack(project, seed, step["evidence_pack"], research_seed)


@pytest.mark.parametrize("entry", ["continue_acquisition", "prepare_acquisition_host_step"])
def test_committed_reentry_revalidates(tmp_path, monkeypatch, entry):
    project, seed, step, _ = drive(tmp_path, monkeypatch, rounds=1)
    path = project / step["acquisition_manifest_path"]
    raw = path.read_bytes(); path.write_bytes(raw + b" ")
    with pytest.raises(owner.CurieContractError):
        getattr(owner, entry)(project, "C001", run_id=RUN)


@pytest.mark.parametrize("empty", [True, False])
def test_no_new_sources_preserves_origin_without_empty_worker(tmp_path, monkeypatch, empty):
    project, seed, step, calls = drive(tmp_path, monkeypatch, empty=empty, no_new=True)
    assert step["kind"] == "INSUFFICIENT_STOP" and step["terminal_reason"] == "no_new_sources"
    assert step["evidence_pack"] is None
    manifest = owner._read_object(project / step["acquisition_manifest_path"])
    last = manifest["attempts"][-1]
    assert last["worker"] == {"status": "NOT_ATTEMPTED", "reason": "no_new_sources"}
    assert calls["worker"] == ([] if empty else [30])
    assert len([s for s in calls["host"] if s.startswith("coverage:")]) == 1
    assert last["scientific_coverage"]["binding"]["origin_attempt"] == 1


def test_binding_crash_reentry_uses_same_validated_pack(tmp_path, monkeypatch):
    project, seed, step, calls = drive(tmp_path, monkeypatch, rounds=1)
    before = copy.deepcopy(calls)
    activate = research_seed.activate_l1_native_evidence_binding
    def crash(*_args, **_kw): raise RuntimeError("controlled binding interruption")
    monkeypatch.setattr(research_seed, "activate_l1_native_evidence_binding", crash)
    with pytest.raises(RuntimeError, match="controlled binding interruption"):
        owner.bind_initial_curie_pack(project, seed, step["evidence_pack"], RUN)
    monkeypatch.setattr(research_seed, "activate_l1_native_evidence_binding", activate)
    owner.bind_initial_curie_pack(project, seed, step["evidence_pack"], RUN)
    assert research_seed.active_l1_native_evidence_run_id(project, seed) == RUN
    assert calls == before
