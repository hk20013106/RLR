"""Ordinary cognitive-node handoff through the current host session."""
from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_loop
from research_loop.api import EngineAPI
from research_loop.compatibility import PROFILE_V21_CATALOG_1, get_profile
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.persona_catalog import resolve_persona_template
from research_loop.providers.base import AgentProvider, RunReceipt


HOST_STEP_MARKER = "HOST_STEP_MISSING"


def _host_step_api():
    prepare = getattr(run_loop, "prepare_host_step", None)
    assert callable(prepare), f"{HOST_STEP_MARKER}: run_loop.prepare_host_step is missing"
    submit = getattr(run_loop, "submit_host_step", None)
    assert callable(submit), f"{HOST_STEP_MARKER}: run_loop.submit_host_step is missing"
    return prepare, submit


@pytest.fixture
def host_step_fixture(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    store_path = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store_path)
    binding = ledger.bind_project(
        project,
        "PROJECT:agent-native-test",
        profile_id=PROFILE_V21_CATALOG_1,
    )
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store_path))
    cursor = ledger.snapshot_candidate(project, "C1", "1")

    rendered = project / "rendered-context.txt"
    rendered.write_text("AUTHORIZED_L2_SENTINEL\n", encoding="utf-8")
    rendered_hash = hashlib.sha256(rendered.read_bytes()).hexdigest()
    persona = resolve_persona_template(
        get_profile(PROFILE_V21_CATALOG_1), "Oppenheimer"
    )
    manifest = project / "ContextManifest.json"
    manifest_data = {
        "schema_version": "ContextManifest/v2",
        "project_id": binding["project_id"],
        "candidate_id": "C1",
        "round_id": "1",
        "node": "L2",
        "persona": "Oppenheimer",
        "profile_id": PROFILE_V21_CATALOG_1,
        "persona_catalog_sha256": persona.catalog_sha256,
        "persona_catalog_entry_sha256": persona.entry_sha256,
        "persona_template_sha256": persona.template_sha256,
        "persona_body_sha256": persona.body_sha256,
        "rendered_context_path": str(rendered),
        "rendered_context_sha256": rendered_hash,
        "tools_policy": "no-fs",
        "allowed_inputs": ["L1"],
        "injected_deltas": [],
    }
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    config = project / "runner.yaml"
    config.write_text("provider: host_session\n", encoding="utf-8")
    step = {
        "node": "L2",
        "persona": "Oppenheimer",
        "profile_id": PROFILE_V21_CATALOG_1,
        "schema_version": "2.1",
        "advance_command": "triage-idea",
        "tools_policy": "no-fs",
        "output_contract": {"type": "object"},
    }
    events = []
    response_record = {}

    def next_step(*_args):
        events.append("next-step")
        if "advance" in events:
            return {"terminal": True, "status": "DONE"}
        return step

    def assemble_context(*_args, **_kwargs):
        events.append("assemble-context")
        return rendered.read_bytes().decode("utf-8"), str(manifest)

    engine = EngineAPI()
    real_prepare = engine.prepare_host_request
    real_submit = engine.submit_host_response

    def prepare_host_request(*args, **kwargs):
        events.append("host-request")
        return real_prepare(*args, **kwargs)

    def submit_host_response(*args, **kwargs):
        result = real_submit(*args, **kwargs)
        events.append("raw-response")
        response_record.update(result)
        return result

    def emit_delta(*_args, provider_receipt=None, **_kwargs):
        receipt = RunReceipt.read(provider_receipt)
        assert receipt.schema_version == "RunReceipt/v3-host"
        events.extend(["RunReceipt/v3-host", "emit-delta"])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(run_loop, "ENGINE", engine)
    monkeypatch.setattr(engine, "prepare_host_request", prepare_host_request)
    monkeypatch.setattr(engine, "submit_host_response", submit_host_response)
    monkeypatch.setattr(engine, "emit_delta", emit_delta)
    monkeypatch.setattr(run_loop, "next_step", next_step)
    monkeypatch.setattr(run_loop, "assemble_context", assemble_context)
    monkeypatch.setattr(run_loop, "load_delta", lambda *_args: None)
    monkeypatch.setattr(
        run_loop, "_ctl",
        lambda *args: events.append("advance") or SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
    )
    monkeypatch.setattr(
        run_loop, "capture_code_state",
        lambda *_args: {
            "git_head": "1" * 40,
            "git_dirty": False,
            "working_tree_diff_sha256": "2" * 64,
            "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "code_state_id": "3" * 64,
        },
    )

    def forbidden_provider(*_args, **_kwargs):
        pytest.fail("HOST_PROVIDER_FORBIDDEN: agent-native cognition used a provider")

    monkeypatch.setattr(run_loop, "provider_for", forbidden_provider)
    monkeypatch.setattr(AgentProvider, "run_agent", forbidden_provider)
    args = SimpleNamespace(
        mode="agent_native", stop_after_node=None, config=str(config),
        knowledge_store=str(store_path),
    )
    cfg = SimpleNamespace(stop_policy={}, source_path=str(config))
    exec_state = {"cursor": cursor}
    return SimpleNamespace(
        project=project,
        manifest=manifest,
        manifest_hash=manifest_hash,
        rendered=rendered,
        rendered_hash=rendered_hash,
        persona=persona,
        step=step,
        events=events,
        response_record=response_record,
        args=args,
        cfg=cfg,
        exec_state=exec_state,
        cursor=cursor,
    )


def test_agent_native_host_step_binds_context_request_response_and_advance(
    host_step_fixture
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert prepared["kind"] == "needs_host"
    request = prepared["request"]
    assert request["identity"]["node"] == "L2"
    assert request["identity"]["persona"] == "Oppenheimer"
    assert request["identity"]["cursor"] == fixture.cursor
    assert request["inputs"]["context_manifest_path"] == str(fixture.manifest)
    assert request["inputs"]["context_manifest_sha256"] == fixture.manifest_hash
    assert request["inputs"]["rendered_context_path"] == str(fixture.rendered)
    assert request["inputs"]["rendered_context_sha256"] == fixture.rendered_hash
    assert request["inputs"]["persona_template_sha256"] == fixture.persona.template_sha256
    assert json.loads(fixture.manifest.read_text(encoding="utf-8"))["schema_version"] == "ContextManifest/v2"

    response = fixture.project / "host-response.json"
    raw_response = b'{"candidate_id":"C1","answer":"host output"}\n'
    response.write_bytes(raw_response)
    submitted = submit(
        fixture.project, "C1", request["request_id"], response,
        session_identity={"session_id": "codex-session-1", "source": "declared"},
    )

    assert submitted["kind"] == "committed"
    assert fixture.response_record["raw_response_sha256"] == hashlib.sha256(raw_response).hexdigest()
    terminal = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert terminal["kind"] == "terminal"
    assert fixture.events == [
        "next-step", "assemble-context", "host-request",
        "next-step", "raw-response", "RunReceipt/v3-host", "emit-delta",
        "advance", "next-step",
    ]


def test_agent_native_host_response_for_wrong_node_is_rejected(host_step_fixture):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    fixture.step["node"] = "L3"
    fixture.step["persona"] = "Darwin"
    response = fixture.project / "wrong-node-response.json"
    response.write_bytes(b'{"node":"L3","answer":"wrong node"}\n')

    with pytest.raises((ValueError, RuntimeError), match="(?i)(node|request|context|identity)"):
        submit(
            fixture.project, "C1", prepared["request"]["request_id"], response,
            session_identity={"session_id": "codex-session-1", "source": "declared"},
        )

    assert "raw-response" not in fixture.events
    assert "advance" not in fixture.events


def test_agent_native_resume_advances_committed_delta_without_new_host_request(
    host_step_fixture, monkeypatch
):
    prepare, _submit = _host_step_api()
    fixture = host_step_fixture
    monkeypatch.setattr(
        run_loop, "load_delta",
        lambda *_args: {"schema_version": "2.1", "triage": []},
    )

    result = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["kind"] == "deterministic"
    assert fixture.events.count("host-request") == 0
    assert fixture.events.count("advance") == 1


def test_concurrent_agent_native_submissions_have_one_commit_and_advance(
    host_step_fixture
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    response = fixture.project / "host-response.json"
    response.write_bytes(b'{"candidate_id":"C1","answer":"same bytes"}\n')

    def submit_once():
        return submit(
            fixture.project, "C1", prepared["request"]["request_id"], response,
            session_identity={"session_id": "codex-session-1", "source": "declared"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: submit_once(), range(2)))

    assert all(result["kind"] == "committed" for result in results)
    assert fixture.events.count("emit-delta") == 1
    assert fixture.events.count("advance") == 1


def test_recovery_after_advance_still_rejects_changed_response_bytes(
    host_step_fixture, monkeypatch
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    original_response = fixture.project / "original-response.json"
    original_response.write_bytes(b'{"candidate_id":"C1","answer":"original"}\n')
    real_write_marker = run_loop._write_host_step_marker

    def interrupt_after_advance(path, value):
        if value.get("phase") == "committed":
            raise RuntimeError("simulated interruption after advance")
        return real_write_marker(path, value)

    monkeypatch.setattr(run_loop, "_write_host_step_marker", interrupt_after_advance)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        submit(
            fixture.project, "C1", prepared["request_id"], original_response,
            session_identity={"session_id": "codex-session-1", "source": "declared"},
        )

    # A restarted process no longer has the injected interruption.
    monkeypatch.setattr(run_loop, "_write_host_step_marker", real_write_marker)
    changed_response = fixture.project / "changed-response.json"
    changed_response.write_bytes(b'{"candidate_id":"C1","answer":"changed"}\n')
    with pytest.raises((ValueError, RuntimeError), match="(?i)(response|content|bytes|conflict)"):
        submit(
            fixture.project, "C1", prepared["request_id"], changed_response,
            session_identity={"session_id": "codex-session-1", "source": "declared"},
        )


def test_same_response_recovers_after_advance_before_commit_marker(
    host_step_fixture, monkeypatch
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    response = fixture.project / "interrupted-after-advance.json"
    response.write_bytes(b'{"candidate_id":"C1","answer":"same bytes"}\n')
    old_action = {
        "kind": "cognitive", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
    }
    next_action = {
        "kind": "cognitive",
        "step": {**fixture.step, "node": "L3", "persona": "Darwin"},
        "profile_id": PROFILE_V21_CATALOG_1,
        "cursor": {**fixture.cursor, "revision": fixture.cursor.get("revision", 0) + 1},
    }
    actions = iter([old_action, next_action])
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: next(actions))
    real_write_marker = run_loop._write_host_step_marker

    def interrupt_before_committed_marker(path, value):
        if value.get("phase") == "committed":
            raise RuntimeError("simulated interruption after advance")
        return real_write_marker(path, value)

    monkeypatch.setattr(run_loop, "_write_host_step_marker", interrupt_before_committed_marker)
    with pytest.raises(RuntimeError, match="simulated interruption after advance"):
        submit(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"session_id": "codex-session-1", "source": "declared"},
        )
    assert fixture.events.count("emit-delta") == 1
    assert fixture.events.count("advance") == 1

    monkeypatch.setattr(run_loop, "_write_host_step_marker", real_write_marker)
    recovered = submit(
        fixture.project, "C1", prepared["request_id"], response,
        session_identity={"session_id": "codex-session-1", "source": "declared"},
    )

    assert recovered["kind"] == "committed"
    assert recovered["duplicate"] is True
    assert fixture.events.count("emit-delta") == 1
    assert fixture.events.count("advance") == 1


def test_host_resume_after_response_recorded_reuses_exact_response_without_new_cognition(
    host_step_fixture, monkeypatch
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    response = fixture.project / "interrupted-response.json"
    raw = b'{"candidate_id":"C1","answer":"recorded before interruption"}\n'
    response.write_bytes(raw)
    engine = run_loop.ENGINE
    real_submit_response = engine.submit_host_response
    calls = []

    def record_then_interrupt(*args, **kwargs):
        receipt = real_submit_response(*args, **kwargs)
        calls.append(receipt)
        if len(calls) == 1:
            raise RuntimeError("simulated interruption after RESPONSE_RECORDED")
        return receipt

    monkeypatch.setattr(engine, "submit_host_response", record_then_interrupt)
    with pytest.raises(RuntimeError, match="RESPONSE_RECORDED"):
        submit(fixture.project, "C1", prepared["request_id"], response)

    monkeypatch.setattr(engine, "submit_host_response", real_submit_response)
    resumed = submit(fixture.project, "C1", prepared["request_id"], response)

    assert resumed["kind"] == "committed"
    assert fixture.events.count("host-request") == 1
    assert fixture.events.count("emit-delta") == 1
    assert fixture.events.count("advance") == 1


@pytest.mark.parametrize("tamper_response", [False, True])
def test_host_protocol_resumes_cognitive_response_recorded_after_process_reset(
    host_step_fixture, monkeypatch, tamper_response
):
    fixture = host_step_fixture
    prepared = run_loop.prepare_host_step(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert prepared["kind"] == "needs_host"
    response = fixture.project / "protocol-response-recorded.json"
    raw = b'{"candidate_id":"C1","answer":"recover this exact response"}\n'
    response.write_bytes(raw)

    engine = run_loop.ENGINE
    real_submit_response = engine.submit_host_response
    recorded_receipts = []

    def persist_receipt_then_interrupt(*args, **kwargs):
        receipt = real_submit_response(*args, **kwargs)
        recorded_receipts.append(receipt)
        raise RuntimeError("simulated process interruption after RESPONSE_RECORDED")

    monkeypatch.setattr(engine, "submit_host_response", persist_receipt_then_interrupt)
    with pytest.raises(RuntimeError, match="RESPONSE_RECORDED"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response
        )
    monkeypatch.setattr(engine, "submit_host_response", real_submit_response)
    real_next_step = run_loop.next_step

    def profile_terminal_step(*args):
        step = real_next_step(*args)
        if step.get("terminal"):
            return {**step, "profile_id": PROFILE_V21_CATALOG_1}
        return step

    monkeypatch.setattr(run_loop, "next_step", profile_terminal_step)

    receipt = recorded_receipts[0]
    persisted_response = Path(receipt["raw_response_path"])
    assert persisted_response.read_bytes() == raw
    if tamper_response:
        persisted_response.write_bytes(b'{"candidate_id":"C1","answer":"tampered"}\n')
    fresh_exec_state = {"cursor": fixture.cursor}
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fresh_exec_state
    )

    if tamper_response:
        assert resumed["status"] == "blocked", (
            "changed persisted response bytes must fail closed before host re-entry"
        )
    else:
        assert resumed["status"] != "needs_host", (
            "RESPONSE_RECORDED must resume from persisted response bytes, not ask the host again"
        )
    request_files = list(
        (fixture.project / "08_Audit" / "host_handoff" / "requests").glob("*.json")
    )
    assert len(request_files) == 1
    assert persisted_response.read_bytes() == (
        b'{"candidate_id":"C1","answer":"tampered"}\n' if tamper_response else raw
    )
    assert fixture.events.count("emit-delta") == (0 if tamper_response else 1)
    assert fixture.events.count("advance") == (0 if tamper_response else 1)


def test_host_protocol_blocks_raw_response_without_receipt(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    prepared = run_loop.prepare_host_step(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    response = fixture.project / "response-without-receipt.json"
    response.write_bytes(b'{"candidate_id":"C1","answer":"incomplete receipt"}\n')
    engine = run_loop.ENGINE
    real_submit_response = engine.submit_host_response
    receipts = []

    def persist_receipt_then_interrupt(*args, **kwargs):
        receipt = real_submit_response(*args, **kwargs)
        receipts.append(receipt)
        raise RuntimeError("simulated interruption after response receipt")

    monkeypatch.setattr(engine, "submit_host_response", persist_receipt_then_interrupt)
    with pytest.raises(RuntimeError, match="response receipt"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response
        )
    monkeypatch.setattr(engine, "submit_host_response", real_submit_response)

    receipt_path = Path(receipts[0]["raw_response_path"]).with_suffix(".json")
    receipt_path.unlink()
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1",
        {"cursor": fixture.cursor},
    )

    assert resumed["status"] == "blocked", (
        "raw response without durable receipt must fail closed before host re-entry"
    )


def test_host_resume_after_delta_commit_marker_before_advance_advances_without_reemitting(
    host_step_fixture, monkeypatch
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    response = fixture.project / "pre-advance-response.json"
    response.write_bytes(b'{"candidate_id":"C1","answer":"delta committed"}\n')
    real_advance = run_loop.advance
    calls = []

    def interrupt_before_advance(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated interruption before advance")
        return real_advance(*args, **kwargs)

    monkeypatch.setattr(run_loop, "advance", interrupt_before_advance)
    with pytest.raises(RuntimeError, match="before advance"):
        submit(fixture.project, "C1", prepared["request_id"], response)

    monkeypatch.setattr(run_loop, "advance", real_advance)
    resumed = submit(fixture.project, "C1", prepared["request_id"], response)

    assert resumed["kind"] == "committed"
    assert fixture.events.count("host-request") == 1
    assert fixture.events.count("emit-delta") == 1
    assert fixture.events.count("advance") == 1


def test_agent_native_cannot_self_assert_verified_session_identity(host_step_fixture):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    response = fixture.project / "host-response.json"
    response.write_bytes(b'{"candidate_id":"C1","answer":"host output"}\n')

    with pytest.raises(ValueError, match="(?i)(verified|verification|trusted)"):
        submit(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"session_id": "claimed-session", "source": "verified"},
        )


@pytest.mark.parametrize(
    ("action_kind", "node"),
    [
        ("pre_research", "L4"),
        ("pre_research", "L8.5"),
        ("pre_research", "L7"),
        ("l7", "L7"),
        ("review", "REVIEW"),
    ],
)
def test_agent_native_reached_cognition_stages_require_host_requests_without_provider(
    host_step_fixture, monkeypatch, action_kind, node
):
    fixture = host_step_fixture
    fixture.step.update(node=node, persona={"L4": "Curie", "L8.5": "Curie",
                                            "L7": "Turing", "REVIEW": "Reviewer"}[node])
    if node == "REVIEW":
        (fixture.project / "FINAL_REPORT.md").write_text(
            "reviewable report\n", encoding="utf-8"
        )
    if node == "L7":
        persona_template = resolve_persona_template(
            get_profile(PROFILE_V21_CATALOG_1), "Turing"
        )
        manifest_data = json.loads(fixture.manifest.read_text(encoding="utf-8"))
        manifest_data.update({
            "node": "L7", "persona": "Turing",
            "persona_catalog_sha256": persona_template.catalog_sha256,
            "persona_catalog_entry_sha256": persona_template.entry_sha256,
            "persona_template_sha256": persona_template.template_sha256,
            "persona_body_sha256": persona_template.body_sha256,
        })
        fixture.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    action = {
        "kind": action_kind,
        "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1,
        "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(run_loop, "_recover_committed_advance", lambda *_args: None)
    monkeypatch.setattr(
        run_loop, "provider_for",
        lambda *_args, **_kwargs: pytest.fail("HOST_PROVIDER_FORBIDDEN: provider startup"),
    )
    monkeypatch.setattr(
        AgentProvider, "run_agent",
        lambda *_args, **_kwargs: pytest.fail("HOST_PROVIDER_FORBIDDEN: run_agent"),
    )
    monkeypatch.setattr(
        AgentProvider, "run_text",
        lambda *_args, **_kwargs: pytest.fail("HOST_PROVIDER_FORBIDDEN: run_text"),
        raising=False,
    )
    commands = []

    def deterministic_owner(*args):
        commands.append(args)
        owner = args[0]
        if owner == "audit-literature-evidence":
            return SimpleNamespace(returncode=1, stdout="", stderr="not yet present")
        if owner == "pre-research":
            return SimpleNamespace(
                returncode=0, stdout=f"authorized {node} task", stderr=""
            )
        if owner == "prepare-turing-workspace" and node == "L7":
            workspace = fixture.project / "08_Workspaces" / "C1" / "turing"
            workspace.mkdir(parents=True)
            (workspace / "WORKSPACE_MANIFEST.json").write_text(
                json.dumps({"candidate_id": "C1", "node": "L7", "missing": []}),
                encoding="utf-8",
            )
            return SimpleNamespace(
                returncode=0,
                stdout=f"Turing workspace ready: {workspace}",
                stderr="",
            )
        pytest.fail(f"HOST_COGNITION_FORBIDDEN: delegated command {owner}")

    monkeypatch.setattr(run_loop, "_ctl", deterministic_owner)
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "PENDING")

    prepared = run_loop.prepare_host_step(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert prepared["kind"] == "needs_host", (
        f"HOST_STAGE_MISSING: {node} {action_kind} was not handed to the host"
    )
    assert prepared.get("request")
    owners = [command[0] for command in commands]
    assert set(owners) <= {
        "audit-literature-evidence", "pre-research", "prepare-turing-workspace"
    }
    assert "deep-research-run" not in owners
    assert owners == {
        "pre_research-L4": ["audit-literature-evidence", "pre-research"],
        "pre_research-L8.5": ["audit-literature-evidence", "pre-research"],
        "pre_research-L7": ["pre-research"],
        "l7-L7": ["prepare-turing-workspace"],
        "review-REVIEW": [],
    }[f"{action_kind}-{node}"]


def test_agent_native_capabilities_enumerate_every_reachable_v21_cognition_stage():
    capabilities = getattr(run_loop, "agent_native_capabilities", None)
    assert callable(capabilities), "CAPABILITY_GATE_MISSING: agent_native_capabilities"

    result = capabilities(PROFILE_V21_CATALOG_1)

    required = {
        "L4_literature",
        "L8.5_literature",
        "pre_research_text",
        "L7_text_preparation",
        "L7_delta",
        "REVIEW",
    }
    assert isinstance(result, dict)
    assert required <= set(result), "CAPABILITY_GATE_INCOMPLETE: reachable stages omitted"
    assert all(type(value) is bool for value in result.values())


def test_agent_native_l85_capability_uses_shared_literature_receipt_owners():
    assert callable(run_loop._prepare_host_literature)
    assert callable(run_loop._submit_host_literature)
    assert callable(run_loop.deep_research._host_literature_payload)
    assert callable(run_loop.deep_research.persist_run)
    assert callable(run_loop.deep_research.audit_evidence_pack)

    capabilities = run_loop.agent_native_capabilities(PROFILE_V21_CATALOG_1)

    assert capabilities["L8.5_literature"] is True, (
        "L8.5 capability must reflect the shared literature handoff and receipt owners"
    )


def test_agent_native_capability_requires_native_l1_binding_owners(monkeypatch):
    monkeypatch.setattr(run_loop, "_native_l1_binding_ready", None)
    monkeypatch.setattr(run_loop, "_ensure_native_l1_recall", None)

    capabilities = run_loop.agent_native_capabilities(PROFILE_V21_CATALOG_1)

    assert "L1_native_binding" in capabilities, (
        "CAPABILITY_GATE_INCOMPLETE: native L1 binding/recall owner omitted"
    )
    assert capabilities["L1_native_binding"] is False, (
        "native L1 capability must fail when either deterministic owner is missing"
    )


def test_native_l1_binding_and_recall_run_before_l1_host_request(
    host_step_fixture, monkeypatch
):
    _host_step_api()
    fixture = host_step_fixture
    manifest = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    manifest["node"] = "L1"
    fixture.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    fixture.step.update(node="L1")
    run_loop._native_l1_binding_root(fixture.project, "C1").mkdir(parents=True)
    monkeypatch.setattr(run_loop, "next_step", lambda *_args: fixture.step)
    events = []
    monkeypatch.setattr(
        run_loop, "_native_l1_binding_ready",
        lambda *_args: events.append("native-l1-binding") or True,
    )
    monkeypatch.setattr(
        run_loop, "_ensure_native_l1_recall",
        lambda *_args: events.append("native-l1-recall") or True,
    )
    real_assemble = run_loop.assemble_context

    def assemble(*args, **kwargs):
        events.append("assemble-context")
        return real_assemble(*args, **kwargs)

    monkeypatch.setattr(run_loop, "assemble_context", assemble)
    engine = run_loop.ENGINE
    real_prepare_request = engine.prepare_host_request

    def prepare_request(*args, **kwargs):
        events.append("host-request")
        return real_prepare_request(*args, **kwargs)

    monkeypatch.setattr(engine, "prepare_host_request", prepare_request)
    fixture.events.clear()
    prepared = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert prepared["status"] == "needs_host"
    assert events == [
        "native-l1-binding", "native-l1-recall", "assemble-context", "host-request"
    ], (
        "native L1 deterministic binding and recall must complete before host cognition"
    )


def test_agent_native_capability_gate_blocks_before_provider_or_first_round_mutation(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "C1.md").write_text("candidate", encoding="utf-8")
    config = project / "runner.yaml"
    config.write_text("provider: fixture\n", encoding="utf-8")
    binding = project / "00_Preflight" / "hypothesis_store_binding.json"
    binding.parent.mkdir(parents=True)
    binding.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run_loop.rl, "binding_path", lambda _project: binding)
    monkeypatch.setattr(
        run_loop.rl, "_ledger_for",
        lambda *_args, **_kwargs: SimpleNamespace(
            project_profile=lambda _project: PROFILE_V21_CATALOG_1
        ),
    )
    monkeypatch.setattr(run_loop.l0_preflight, "validate_project_ready",
                        lambda *_args, **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(run_loop, "_formal_runtime_preflight", lambda: True)
    monkeypatch.setattr(run_loop, "_ctl", lambda *_args: SimpleNamespace(
        returncode=0, stdout="", stderr=""))
    cfg = SimpleNamespace(
        mode=None, max_rounds=1, review={"enabled": True}, stop_policy={},
        source_path=str(config),
    )
    monkeypatch.setattr(run_loop.orch.ProviderConfig, "load", lambda *_args: cfg)
    monkeypatch.setattr(run_loop, "restore_previous_round",
                        lambda *_args: {"binding_status": "NOT_APPLICABLE"})
    from research_loop import pre_e2e_closure
    monkeypatch.setattr(pre_e2e_closure, "audit_static_closure",
                        lambda *_args: {"e2e_start_allowed": True})
    capability_calls = []
    required = {
        "L4_literature": True,
        "L8.5_literature": False,
        "pre_research_text": True,
        "L7_text_preparation": True,
        "L7_delta": True,
        "REVIEW": True,
    }
    monkeypatch.setattr(
        run_loop, "agent_native_capabilities",
        lambda profile: capability_calls.append(profile) or required,
        raising=False,
    )
    provider_calls = []
    monkeypatch.setattr(
        run_loop, "preflight_providers",
        lambda *_args: provider_calls.append("provider") or True,
    )
    round_calls = []
    monkeypatch.setattr(
        run_loop, "run_round",
        lambda *_args, **_kwargs: round_calls.append("round") or "agent_native_handoff_required",
    )
    args = SimpleNamespace(
        project_dir=str(project), cand_id="C1", knowledge_store=None,
        dry_run=False, config=str(config), provider=None, max_rounds=1,
        no_review=False, resume=False,
    )

    result = run_loop.cmd_run(args, mode="agent_native")

    assert capability_calls == [PROFILE_V21_CATALOG_1], (
        "CAPABILITY_GATE_MISSING: entry did not inspect all reached cognitive stages"
    )
    assert result != 0
    assert provider_calls == []
    assert round_calls == []


def test_agent_native_review_requires_host_and_rejects_malformed_schema_before_emit(
    host_step_fixture, monkeypatch
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    (fixture.project / "FINAL_REPORT.md").write_text("reviewable report\n", encoding="utf-8")
    fixture.step.update(node="REVIEW", persona="Reviewer", tools_policy="no-fs")
    action = {
        "kind": "review", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["REVIEW"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(run_loop, "_recover_committed_advance", lambda *_args: None)
    monkeypatch.setattr(run_loop, "provider_for", lambda *_args, **_kwargs: pytest.fail(
        "HOST_PROVIDER_FORBIDDEN: REVIEW started a provider"
    ))
    monkeypatch.setattr(AgentProvider, "run_agent", lambda *_args, **_kwargs: pytest.fail(
        "HOST_PROVIDER_FORBIDDEN: REVIEW called run_agent"
    ))

    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert prepared["kind"] == "needs_host", "REVIEW_HOST_MISSING"
    schema = prepared["request"]["output_contract"]["schema"]
    assert set(schema["required"]) == set(run_loop.REVIEW_SCHEMA)
    assert schema["properties"]["review_verdict"]["enum"] == [
        "accept", "weak_accept", "major_revision", "reject"
    ]

    response = fixture.project / "malformed-review.json"
    response.write_text('{"unexpected":"no review verdict"}\n', encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError), match="(?i)(review|schema|contract)"):
        submit(fixture.project, "C1", prepared["request_id"], response)


def test_agent_native_review_host_submit_returns_validated_review_result(
    host_step_fixture, monkeypatch
):
    prepare, submit = _host_step_api()
    fixture = host_step_fixture
    (fixture.project / "FINAL_REPORT.md").write_text("reviewable report\n", encoding="utf-8")
    fixture.step.update(node="REVIEW", persona="Reviewer", tools_policy="no-fs")
    action = {
        "kind": "review", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["REVIEW"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(run_loop, "provider_for", lambda *_args, **_kwargs: pytest.fail(
        "HOST_PROVIDER_FORBIDDEN: REVIEW started a provider"
    ))
    prepared = prepare(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert prepared["kind"] == "needs_host"
    response = fixture.project / "valid-review.json"
    response.write_text(json.dumps({
        "review_verdict": "major_revision", "evidence_score": 2,
        "method_validity_score": 3, "novelty_score": 4,
        "falsification_risk_score": 5, "marginal_gain_score": 1,
        "required_revisions": ["clarify evidence"],
        "executable_next_actions": ["recheck source"], "reason": "needs work",
    }), encoding="utf-8")

    committed = submit(fixture.project, "C1", prepared["request_id"], response)

    assert committed["kind"] == "committed"
    assert committed["review"]["review_verdict"] == "major_revision"
    assert committed["response_receipt"]["raw_response_sha256"] == hashlib.sha256(
        response.read_bytes()
    ).hexdigest()


@pytest.mark.parametrize(
    ("prepared", "expected", "reason"),
    [
        ({"kind": "terminal", "step": {"status": "KEEP"}}, "terminal", None),
        ({"kind": "blocked", "reason": "approval required"}, "blocked", "approval required"),
        ({"kind": "blocked", "reason": "real RLR blocker"}, "blocked", "real RLR blocker"),
        ({"kind": "blocked", "reason": "human decision required"}, "blocked", "human decision required"),
        ({"kind": "deterministic", "advanced": True}, "continued", None),
        ({
            "kind": "needs_host",
            "request": {"request_id": "a" * 64, "request_path": "request.json"},
        }, "needs_host", None),
    ],
)
def test_host_next_returns_one_typed_action_without_provider(
    host_step_fixture, monkeypatch, prepared, expected, reason
):
    fixture = host_step_fixture
    if expected == "needs_host":
        request = prepared["request"]
        request_path = fixture.project / "request.json"
        request_bytes = json.dumps(request, sort_keys=True).encode("utf-8")
        request_path.write_bytes(request_bytes)
        request["request_path"] = str(request_path)
        request["request_sha256"] = hashlib.sha256(request_bytes).hexdigest()
    host_next = getattr(run_loop, "host_protocol_next", None)
    assert callable(host_next), "HOST_PROTOCOL_MISSING: host-next controller operation"
    seen = []
    monkeypatch.setattr(
        run_loop, "prepare_host_step",
        lambda *_args, **_kwargs: seen.append("prepare") or prepared,
    )
    monkeypatch.setattr(run_loop, "provider_for", lambda *_args, **_kwargs: pytest.fail(
        "HOST_PROVIDER_FORBIDDEN: host-next invoked a provider"
    ))
    monkeypatch.setattr(AgentProvider, "run_agent", lambda *_args, **_kwargs: pytest.fail(
        "HOST_PROVIDER_FORBIDDEN: host-next invoked run_agent"
    ))

    result = host_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["status"] == expected
    if reason:
        assert result["reason"] == reason
    assert seen == ["prepare"]
    if expected == "needs_host":
        assert result["request_id"] == "a" * 64
        assert result["request_path"] == str(request_path)
        assert result["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()


def test_host_next_blocks_missing_or_mismatched_request_bytes(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    request_path = fixture.project / "request.json"
    request_path.write_bytes(b'{"immutable":true}')
    prepared = {"kind": "needs_host", "request": {
        "request_id": "e" * 64, "request_path": str(request_path),
        "request_sha256": "0" * 64,
    }}
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: {
        "kind": "cognitive", "step": fixture.step,
    })
    monkeypatch.setattr(run_loop, "prepare_host_step", lambda *_args: prepared)
    result = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert result["status"] == "blocked"
    assert "persisted hash" in result["reason"]


def test_host_next_resumes_after_submit_without_reissuing_committed_request(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    host_next = getattr(run_loop, "host_protocol_next", None)
    host_submit = getattr(run_loop, "host_protocol_submit", None)
    assert callable(host_next) and callable(host_submit), (
        "HOST_PROTOCOL_MISSING: host-next/host-submit operations"
    )
    request = {"request_id": "b" * 64, "request_path": "request.json"}
    request_path = fixture.project / "request.json"
    request_bytes = b'{"request_id":"' + request["request_id"].encode() + b'"}'
    request_path.write_bytes(request_bytes)
    request["request_path"] = str(request_path)
    request["request_sha256"] = hashlib.sha256(request_bytes).hexdigest()
    monkeypatch.setattr(
        run_loop.ENGINE, "load_host_request",
        lambda _project, request_id: {
            **request, "request_id": request_id,
            "identity": {"stage": "cognitive"},
        },
    )
    prepared_steps = iter([
        {"kind": "needs_host", "request": request},
        {"kind": "deterministic", "advanced": True},
        {"kind": "terminal", "step": {"status": "KEEP"}},
    ])
    prepare_count = []
    submit_count = []
    monkeypatch.setattr(
        run_loop, "prepare_host_step",
        lambda *_args, **_kwargs: prepare_count.append(1) or next(prepared_steps),
    )
    monkeypatch.setattr(
        run_loop, "submit_host_step",
        lambda *_args, **_kwargs: submit_count.append(1) or {
            "kind": "committed", "duplicate": False,
        },
    )
    monkeypatch.setattr(run_loop, "provider_for", lambda *_args, **_kwargs: pytest.fail(
        "HOST_PROVIDER_FORBIDDEN: host protocol invoked a provider"
    ))

    first = host_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert first["status"] == "needs_host"
    submitted = host_submit(fixture.project, "C1", request["request_id"], "response.json")
    second = host_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    terminal = host_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert submitted["status"] == "committed"
    assert second["status"] == "continued"
    assert terminal["status"] == "terminal"
    assert len(prepare_count) == 3
    assert len(submit_count) == 1


def test_host_next_reconstructs_completed_pre_research_after_fresh_process(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    identity = {"profile_id": PROFILE_V21_CATALOG_1,
                "round_id": "1", "cursor": fixture.cursor, "nodes": ["L2"]}
    step = {**fixture.step, "node": "L2", "persona": "Oppenheimer"}
    pre_action = {"kind": "pre_research", "step": step,
                  "profile_id": PROFILE_V21_CATALOG_1,
                  "cursor": fixture.cursor, "identity": identity}
    cognitive_action = {**pre_action, "kind": "cognitive"}
    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L2_research.md"
    request_path = fixture.project / "stable-request.json"
    request_bytes = b'{"request_id":"' + b"d" * 64 + b'"}'
    request_path.write_bytes(request_bytes)
    request = {"request_id": "d" * 64, "request_path": str(request_path),
               "request_sha256": hashlib.sha256(request_bytes).hexdigest()}
    owner_calls = []

    def current(_project, _cand, _cfg, _args, _round, exec_state):
        if exec_state.get("prepared_action_identity") == identity:
            return cognitive_action
        return pre_action

    def prepare(_project, _cand, _cfg, args, _round, exec_state):
        owner_action = current(None, None, None, args, None, exec_state)
        if owner_action["kind"] == "pre_research":
            owner_calls.append("pre_research")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text("persisted deterministic completion\n", encoding="utf-8")
            return {"kind": "deterministic", "action": owner_action}
        owner_calls.append("cognitive")
        return {"kind": "needs_host", "request": request,
                "request_id": request["request_id"],
                "request_path": request["request_path"]}

    monkeypatch.setattr(run_loop, "current_action", current)
    monkeypatch.setattr(run_loop, "prepare_host_step", prepare)
    monkeypatch.setattr(run_loop, "provider_for", lambda *_a, **_k: pytest.fail(
        "HOST_PROVIDER_FORBIDDEN: resumed host protocol invoked provider"
    ))
    first = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )
    second = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )

    assert first["status"] == second["status"] == "needs_host"
    assert first["request_id"] == second["request_id"] == request["request_id"]
    assert target.is_file()
    assert owner_calls == ["pre_research", "cognitive", "pre_research", "cognitive"]


def test_one_host_protocol_carries_multiple_nodes_l05_review_to_stop_policy(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    host_next = getattr(run_loop, "host_protocol_next", None)
    host_submit = getattr(run_loop, "host_protocol_submit", None)
    assert callable(host_next) and callable(host_submit), (
        "HOST_PROTOCOL_MISSING: continuous next/submit operations"
    )
    stages = iter([
        {"kind": "needs_host", "request": {
            "request_id": "1" * 64, "request_path": "ordinary.json",
            "identity": {"stage": "cognitive", "node": "L2"},
        }},
        {"kind": "needs_host", "request": {
            "request_id": "4" * 64, "request_path": "ordinary-l5.json",
            "identity": {"stage": "cognitive", "node": "L5"},
        }},
        {"kind": "needs_host", "request": {
            "request_id": "2" * 64, "request_path": "l05.json",
            "identity": {"stage": "planner", "node": "L0.5"},
        }},
        {"kind": "needs_host", "request": {
            "request_id": "3" * 64, "request_path": "review.json",
            "identity": {"stage": "review", "node": "REVIEW"},
        }},
        {"kind": "terminal", "step": {"status": "KEEP"}},
    ])
    stage_values = list(stages)
    stages = iter(stage_values)
    for prepared in stage_values:
        if prepared.get("kind") != "needs_host":
            continue
        request = prepared["request"]
        request_path = fixture.project / request["request_path"]
        request_bytes = json.dumps(request, sort_keys=True).encode("utf-8")
        request_path.write_bytes(request_bytes)
        request["request_path"] = str(request_path)
        request["request_sha256"] = hashlib.sha256(request_bytes).hexdigest()
    monkeypatch.setattr(
        run_loop, "prepare_host_step", lambda *_a, **_k: next(stages)
    )
    review = {
        "review_verdict": "major_revision", "evidence_score": 2,
        "method_validity_score": 3, "novelty_score": 4,
        "falsification_risk_score": 5, "marginal_gain_score": 1,
        "required_revisions": ["clarify evidence"],
        "executable_next_actions": ["recheck source"], "reason": "needs work",
    }
    submissions = []

    def submit_stage(_project, _cand, request_id, _response_path):
        submissions.append(request_id)
        return {
            "kind": "committed", "duplicate": False,
            "review": review if request_id == "3" * 64 else None,
        }

    monkeypatch.setattr(run_loop, "submit_host_step", submit_stage)
    request_stages = {
        "1" * 64: "cognitive",
        "4" * 64: "cognitive",
        "2" * 64: "cognitive",
        "3" * 64: "review",
    }
    monkeypatch.setattr(
        run_loop.ENGINE, "load_host_request",
        lambda _project, request_id: {
            "request_id": request_id,
            "identity": {"stage": request_stages[request_id]},
        },
    )
    shared_state = fixture.exec_state
    review_received = None
    for _ in range(5):
        action = host_next(
            fixture.project, "C1", fixture.cfg, fixture.args, "1", shared_state
        )
        if action["status"] == "needs_host":
            committed = host_submit(
                fixture.project, "C1", action["request_id"], "response.json"
            )
            review_received = committed.get("review") or review_received
        elif action["status"] == "terminal":
            break
        else:
            pytest.fail(f"protocol stopped before the next authorized handoff: {action}")

    decision = run_loop.StopPolicy(max_rounds=3).decide(
        status="KEEP", l10b=None, review=review_received, round_id=1,
        prev_summaries=[], l7_failures=0, parent_fm={},
    )
    assert submissions == ["1" * 64, "4" * 64, "2" * 64, "3" * 64]
    assert review_received["review_verdict"] == "major_revision"
    assert decision["stop"] is True


def test_host_protocol_l05_routes_through_existing_acquisition_prepare_owner(
    host_step_fixture, monkeypatch
):
    from research_loop.l05_curie import europepmc_runtime

    fixture = host_step_fixture
    fixture.step.update(node="L0.5", persona="Curie")
    action = {
        "kind": "l05", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["L0.5"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    owner_request = {
        "request_id": "c" * 64,
        "request_path": str(fixture.project / "planner-request.json"),
    }
    owner_request_bytes = b'{"request_id":"' + owner_request["request_id"].encode() + b'"}'
    Path(owner_request["request_path"]).write_bytes(owner_request_bytes)
    owner_request["request_sha256"] = hashlib.sha256(owner_request_bytes).hexdigest()
    owner_calls = []

    def existing_acquisition_owner(project, candidate, *, run_id=None):
        owner_calls.append((str(project), candidate, run_id))
        return {"kind": "needs_host", "request": owner_request,
                "request_id": owner_request["request_id"],
                "request_path": owner_request["request_path"]}

    monkeypatch.setattr(
        europepmc_runtime, "prepare_acquisition_host_step",
        existing_acquisition_owner,
    )
    host_next = getattr(run_loop, "host_protocol_next", None)
    assert callable(host_next), "HOST_PROTOCOL_MISSING: host-next must route L0.5"

    result = host_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert owner_calls == [(str(fixture.project), "C1", None)]
    assert result["status"] == "needs_host"
    assert result["request_id"] == owner_request["request_id"]
    assert result["request_path"] == owner_request["request_path"]


@pytest.mark.parametrize(
    ("prepared", "continued", "expected", "continue_calls"),
    [
        ({"kind": "blocked", "reason": "uncertain_external_result"}, None,
         "blocked", 0),
        ({"kind": "deterministic", "checkpoint": {"phase": "COMMITTED"}},
         {"status": "FROZEN", "terminal_status": "FROZEN"},
         "continued", 1),
        ({"kind": "deterministic", "checkpoint": {"phase": "COMMITTED"}},
         {"status": "NO_ADMISSIBLE_REPLAN", "terminal_status": "NO_ADMISSIBLE_REPLAN"},
         "continued", 1),
    ],
)
def test_host_protocol_l05_maps_persisted_owner_outcomes_without_retry(
    host_step_fixture, monkeypatch, prepared, continued, expected, continue_calls
):
    from research_loop.l05_curie import europepmc_runtime

    fixture = host_step_fixture
    fixture.step.update(node="L0.5", persona="Curie")
    action = {
        "kind": "l05", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["L0.5"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(
        europepmc_runtime, "prepare_acquisition_host_step",
        lambda *_args, **_kwargs: prepared,
    )
    continued_calls = []
    monkeypatch.setattr(
        europepmc_runtime, "continue_acquisition",
        lambda *_args, **_kwargs: continued_calls.append(1) or continued,
    )
    result = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["status"] == expected
    assert len(continued_calls) == continue_calls
    if expected == "blocked":
        assert result["reason"] == "uncertain_external_result"


def test_host_protocol_resumes_literature_response_recorded_before_owner_completion(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    fixture.step.update(node="L4", persona="Curie")
    action = {
        "kind": "pre_research", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["L4"]},
    }
    terminal_action = {
        "kind": "terminal", "step": {"terminal": True, "status": "DONE"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": []},
    }

    def current_action(_project, _cand, _cfg, _args, _round, exec_state):
        return (terminal_action if exec_state.get("prepared_action_identity")
                == action["identity"] else action)

    monkeypatch.setattr(run_loop, "current_action", current_action)
    monkeypatch.setattr(run_loop, "_recover_committed_advance", lambda *_args: None)
    monkeypatch.setattr(
        run_loop, "_ctl",
        lambda *argv: (
            SimpleNamespace(returncode=1, stdout="", stderr="")
            if argv[0] == "audit-literature-evidence"
            else SimpleNamespace(returncode=0, stdout="RLR-owned L4 literature prompt", stderr="")
        ),
    )
    prepared = run_loop.prepare_host_step(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert prepared["kind"] == "needs_host"
    assert prepared["request"]["kind"] == "literature"
    response = fixture.project / "l4-literature-response.json"
    raw = b'{"schema_version":"v1","studies":[] }\n'
    response.write_bytes(raw)

    owner_calls = []

    def interrupt_before_literature_owner(*_args, **_kwargs):
        owner_calls.append("interrupted")
        raise RuntimeError("simulated interruption after response receipt")

    monkeypatch.setattr(run_loop, "_submit_host_literature", interrupt_before_literature_owner)
    with pytest.raises(RuntimeError, match="after response receipt"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"source": "unavailable"},
        )
    receipt = run_loop.ENGINE.load_host_response_receipt(
        fixture.project, prepared["request_id"], expected_cursor=fixture.cursor
    )
    assert Path(receipt["raw_response_path"]).read_bytes() == raw

    def finish_literature_owner(*_args, **_kwargs):
        owner_calls.append("completed")
        return {"run_id": "host-literature-run-1"}

    monkeypatch.setattr(run_loop, "_submit_host_literature", finish_literature_owner)
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {"cursor": fixture.cursor}
    )

    assert resumed["status"] != "needs_host", (
        "a durable literature response must resume through the existing owner"
    )
    assert owner_calls == ["interrupted", "completed"]
    assert len(list((fixture.project / "08_Audit" / "host_handoff").glob("requests/*.json"))) == 1


def test_duplicate_committed_pre_research_text_submit_rejects_tampered_target(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    _action, prepared = _prepare_text_host_step(fixture, monkeypatch)
    response = fixture.project / "host-l7-text-duplicate.json"
    response.write_text(json.dumps({"text": "Committed authoritative notes.\n"}),
                        encoding="utf-8")
    submit = run_loop.submit_host_step
    committed = submit(
        fixture.project, "C1", prepared["request_id"], response,
        session_identity={"source": "unavailable"},
    )
    assert committed["kind"] == "committed"
    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    target.write_text("tampered committed target", encoding="utf-8")

    with pytest.raises(RuntimeError, match="(?i)(target|text|artifact)"):
        submit(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"source": "unavailable"},
        )


def test_host_next_blocks_or_repairs_tampered_committed_pre_research_text(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    action, prepared = _prepare_text_host_step(fixture, monkeypatch)
    response = fixture.project / "host-l7-text-host-next.json"
    authoritative_text = "Committed notes bound by receipt.\n"
    response.write_text(json.dumps({"text": authoritative_text}), encoding="utf-8")
    run_loop.submit_host_step(
        fixture.project, "C1", prepared["request_id"], response,
        session_identity={"source": "unavailable"},
    )
    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    target.write_text("tampered after commit", encoding="utf-8")
    terminal_action = {
        "kind": "terminal", "step": {"terminal": True, "status": "DONE"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": []},
    }

    def current_action(_project, _cand, _cfg, _args, _round, exec_state):
        return (terminal_action if exec_state.get("prepared_action_identity")
                == action["identity"] else action)

    monkeypatch.setattr(run_loop, "current_action", current_action)
    fixture.args.no_review = True
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {"cursor": fixture.cursor}
    )

    safe_recovery = (
        resumed["status"] == "blocked"
        or target.read_text(encoding="utf-8") == authoritative_text
    )
    assert safe_recovery, (
        "host-next consumed a committed pre-research target without validating its marker hash"
    )


def test_host_l05_insufficient_stop_persists_headless_stop_record_contract(
    host_step_fixture, monkeypatch
):
    from research_loop.l05_curie import europepmc_runtime

    fixture = host_step_fixture
    fixture.step.update(node="L0.5", persona="Curie")
    action = {
        "kind": "l05", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["L0.5"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    owner_calls = []

    def prepare_acquisition(*_args, **_kwargs):
        owner_calls.append("prepare")
        return {"kind": "deterministic", "checkpoint": {"phase": "COMMITTED"}}

    monkeypatch.setattr(
        europepmc_runtime, "prepare_acquisition_host_step", prepare_acquisition
    )
    run_id = "acq-run-persist-contract"
    relative_manifest = (
        Path("08_Audit") / "l05_acquisition" / "C1" / run_id
        / "acquisition_manifest.json"
    )
    manifest = {
        "schema_version": "L05EuropePmcAcquisitionManifest/v2",
        "candidate_id": "C1", "round_id": "1",
        "acquisition_run_id": run_id,
        "terminal_status": "INSUFFICIENT_STOP",
        "terminal_reason": "no admissible evidence after bounded discovery",
        "status": "INSUFFICIENT_STOP", "coverage": {}, "evidence_pack": None,
    }
    manifest_path = fixture.project / relative_manifest
    manifest_path.parent.mkdir(parents=True)
    raw_manifest = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_path.write_bytes(raw_manifest)
    manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    terminal = {
        "terminal_status": "L0_5_INSUFFICIENT_STOP",
        "completed": False,
        "full_dag_completed": False,
        "terminal_reason": "no admissible evidence after bounded discovery",
        "acquisition_run_id": run_id,
        "acquisition_manifest_path": relative_manifest.as_posix(),
        "acquisition_manifest_sha256": manifest_hash,
    }
    def continue_acquisition(*_args, **_kwargs):
        owner_calls.append("continue")
        return terminal

    monkeypatch.setattr(europepmc_runtime, "continue_acquisition", continue_acquisition)
    monkeypatch.setattr(
        run_loop, "validate_europepmc_acquisition_result",
        lambda project, candidate, result: (
            europepmc_runtime._result_from_manifest(
                manifest, relative_manifest.as_posix(), manifest_hash
            )
        ),
    )
    monkeypatch.setattr(run_loop, "provider_for", lambda *_a, **_k: pytest.fail(
        "L0.5 insufficient stop must not invoke a provider"
    ))

    result = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["status"] == "terminal"
    stop_path = fixture.project / "08_Run_Receipts" / "C1" / "round_01" / "stop_decision.json"
    assert stop_path.is_file(), "L0.5 stop record must be persisted before returning terminal"
    record = json.loads(stop_path.read_text(encoding="utf-8"))
    expected_not_attempted = {
        node: "NOT_ATTEMPTED" for node in (
            "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8",
            "L8.5", "L9a", "L9b", "L10a", "L10b", "L10c", "REVIEW",
        )
    }
    assert record == {
        **terminal,
        "node": "L0.5",
        "downstream": "NOT_ATTEMPTED",
        "L1": "NOT_ATTEMPTED",
        "REVIEW": "NOT_ATTEMPTED",
        "L10b": "NOT_ATTEMPTED",
        "not_attempted_nodes": expected_not_attempted,
    }
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert resumed["status"] == "terminal"
    assert owner_calls == ["prepare", "continue"]


def test_host_protocol_resumes_persisted_l05_insufficient_stop_without_reacquisition(
    host_step_fixture, monkeypatch
):
    from research_loop.l05_curie import europepmc_runtime

    fixture = host_step_fixture
    run_id = "acq-run-resume"
    relative_manifest = (
        Path("08_Audit") / "l05_acquisition" / "C1" / run_id
        / "acquisition_manifest.json"
    )
    manifest = {
        "schema_version": "L05EuropePmcAcquisitionManifest/v2",
        "candidate_id": "C1",
        "round_id": "1",
        "acquisition_run_id": run_id,
        "terminal_status": "INSUFFICIENT_STOP",
        "terminal_reason": "bounded discovery found insufficient evidence",
        "status": "INSUFFICIENT_STOP",
        "coverage": {},
        "evidence_pack": None,
    }
    manifest_path = fixture.project / relative_manifest
    manifest_path.parent.mkdir(parents=True)
    manifest_raw = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_path.write_bytes(manifest_raw)
    manifest_hash = hashlib.sha256(manifest_raw).hexdigest()
    stop_record = run_loop._l05_insufficient_stop_record({
        "terminal_status": "L0_5_INSUFFICIENT_STOP",
        "completed": False,
        "full_dag_completed": False,
        "terminal_reason": "bounded discovery found insufficient evidence",
        "acquisition_run_id": run_id,
        "acquisition_manifest_path": relative_manifest.as_posix(),
        "acquisition_manifest_sha256": manifest_hash,
    })
    stop_path = fixture.project / "08_Run_Receipts" / "C1" / "round_01" / "stop_decision.json"
    stop_path.parent.mkdir(parents=True)
    stop_path.write_text(json.dumps(stop_record, indent=2, ensure_ascii=False), encoding="utf-8")
    validated_inputs = []

    def validate_stop_manifest(project, candidate, result):
        validated_inputs.append((Path(project), candidate, dict(result)))
        assert Path(project) == fixture.project
        assert candidate == "C1"
        assert result["status"] == "INSUFFICIENT_STOP"
        assert result["run_id"] == run_id
        assert result["acquisition_manifest_path"] == relative_manifest.as_posix()
        assert result["acquisition_manifest_sha256"] == manifest_hash
        return result

    monkeypatch.setattr(run_loop, "validate_europepmc_acquisition_result", validate_stop_manifest)
    monkeypatch.setattr(
        run_loop, "current_action",
        lambda *_args: pytest.fail("persisted L0.5 terminal must resume before next-step"),
    )
    monkeypatch.setattr(
        europepmc_runtime, "prepare_acquisition_host_step",
        lambda *_args, **_kwargs: pytest.fail("persisted L0.5 stop must not reacquire"),
    )
    monkeypatch.setattr(
        europepmc_runtime, "continue_acquisition",
        lambda *_args, **_kwargs: pytest.fail("persisted L0.5 stop must not continue twice"),
    )

    result = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["status"] == "terminal"
    assert result["result"] == stop_record
    assert len(validated_inputs) == 1


@pytest.mark.parametrize("tampered_field", ["node", "downstream", "not_attempted_nodes"])
def test_host_protocol_rejects_tampered_l05_stop_record_fields(
    host_step_fixture, monkeypatch, tampered_field
):
    from research_loop.l05_curie import europepmc_runtime

    fixture = host_step_fixture
    run_id = "acq-run-integrity"
    relative_manifest = (
        Path("08_Audit") / "l05_acquisition" / "C1" / run_id
        / "acquisition_manifest.json"
    )
    manifest = {
        "schema_version": "L05EuropePmcAcquisitionManifest/v2",
        "candidate_id": "C1", "round_id": "1",
        "acquisition_run_id": run_id,
        "terminal_status": "INSUFFICIENT_STOP",
        "terminal_reason": "bounded discovery found insufficient evidence",
        "status": "INSUFFICIENT_STOP", "coverage": {}, "evidence_pack": None,
    }
    manifest_path = fixture.project / relative_manifest
    manifest_path.parent.mkdir(parents=True)
    manifest_raw = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_path.write_bytes(manifest_raw)
    manifest_hash = hashlib.sha256(manifest_raw).hexdigest()
    not_attempted = {
        node: "NOT_ATTEMPTED" for node in (
            "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8",
            "L8.5", "L9a", "L9b", "L10a", "L10b", "L10c", "REVIEW",
        )
    }
    stop_record = {
        "terminal_status": "L0_5_INSUFFICIENT_STOP",
        "completed": False, "full_dag_completed": False,
        "terminal_reason": manifest["terminal_reason"],
        "acquisition_run_id": run_id,
        "acquisition_manifest_path": relative_manifest.as_posix(),
        "acquisition_manifest_sha256": manifest_hash,
        "node": "L0.5", "downstream": "NOT_ATTEMPTED",
        "L1": "NOT_ATTEMPTED", "REVIEW": "NOT_ATTEMPTED",
        "L10b": "NOT_ATTEMPTED", "not_attempted_nodes": not_attempted,
    }
    if tampered_field == "node":
        stop_record["node"] = "L4"
    elif tampered_field == "downstream":
        stop_record["downstream"] = "EXECUTED"
    else:
        stop_record["not_attempted_nodes"]["L1"] = "EXECUTED"
    stop_path = fixture.project / "08_Run_Receipts" / "C1" / "round_01" / "stop_decision.json"
    stop_path.parent.mkdir(parents=True)
    stop_path.write_text(json.dumps(stop_record, indent=2), encoding="utf-8")

    def validate_manifest(project, candidate, result):
        assert Path(project) == fixture.project
        assert candidate == "C1"
        assert result == europepmc_runtime._result_from_manifest(
            manifest, relative_manifest.as_posix(), manifest_hash
        )
        return result

    monkeypatch.setattr(run_loop, "validate_europepmc_acquisition_result", validate_manifest)
    monkeypatch.setattr(
        run_loop, "current_action",
        lambda *_args: pytest.fail("tampered stop record must block before next-step"),
    )
    monkeypatch.setattr(
        europepmc_runtime, "prepare_acquisition_host_step",
        lambda *_args, **_kwargs: pytest.fail("terminal recovery must not reacquire"),
    )
    monkeypatch.setattr(
        europepmc_runtime, "continue_acquisition",
        lambda *_args, **_kwargs: pytest.fail("terminal recovery must not continue"),
    )

    result = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["status"] == "blocked", (
        f"tampered authoritative stop field {tampered_field} was accepted"
    )


def test_l05_stop_record_atomic_replace_failure_recovers_without_duplicate_http(
    host_step_fixture, monkeypatch
):
    from research_loop.l05_curie import europepmc_runtime

    fixture = host_step_fixture
    fixture.step.update(node="L0.5", persona="Curie")
    action = {
        "kind": "l05", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["L0.5"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)

    run_id = "acq-stop-atomic"
    relative_manifest = (
        Path("08_Audit") / "l05_acquisition" / "C1" / run_id
        / "acquisition_manifest.json"
    )
    manifest = {
        "schema_version": "L05EuropePmcAcquisitionManifest/v2",
        "candidate_id": "C1", "round_id": "1",
        "acquisition_run_id": run_id,
        "terminal_status": "INSUFFICIENT_STOP",
        "terminal_reason": "bounded discovery found insufficient evidence",
        "status": "INSUFFICIENT_STOP", "coverage": {}, "evidence_pack": None,
    }
    manifest_path = fixture.project / relative_manifest
    manifest_path.parent.mkdir(parents=True)
    raw_manifest = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_path.write_bytes(raw_manifest)
    manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    terminal = {
        "terminal_status": "L0_5_INSUFFICIENT_STOP",
        "completed": False, "full_dag_completed": False,
        "terminal_reason": manifest["terminal_reason"],
        "acquisition_run_id": run_id,
        "acquisition_manifest_path": relative_manifest.as_posix(),
        "acquisition_manifest_sha256": manifest_hash,
    }
    owner_calls = []
    http_calls = []
    acquisition_cached = {"value": False}

    def prepare_acquisition(*_args, **_kwargs):
        owner_calls.append("prepare")
        return {"kind": "deterministic", "checkpoint": {"phase": "COMMITTED"}}

    def continue_acquisition(*_args, **_kwargs):
        owner_calls.append("continue")
        assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == manifest_hash
        if not acquisition_cached["value"]:
            http_calls.append("http_get")
            acquisition_cached["value"] = True
        return terminal

    monkeypatch.setattr(
        europepmc_runtime, "prepare_acquisition_host_step", prepare_acquisition
    )
    monkeypatch.setattr(
        europepmc_runtime, "continue_acquisition", continue_acquisition
    )
    monkeypatch.setattr(run_loop, "provider_for", lambda *_a, **_k: pytest.fail(
        "L0.5 terminal persistence recovery must not invoke a provider"
    ))
    stop_path = fixture.project / "08_Run_Receipts" / "C1" / "round_01" / "stop_decision.json"
    real_replace = run_loop.os.replace
    fail_replace = {"enabled": True}

    def fail_stop_replace(source, destination):
        if fail_replace["enabled"] and Path(destination) == stop_path:
            fail_replace["enabled"] = False
            raise OSError("injected stop record atomic replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(run_loop.os, "replace", fail_stop_replace)
    interrupted = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert interrupted["status"] == "blocked", (
        "failed atomic stop-record replace must not report a terminal result"
    )
    assert not stop_path.exists(), "failed atomic replace left visible terminal state"

    monkeypatch.setattr(run_loop.os, "replace", real_replace)
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert resumed["status"] == "terminal"
    assert stop_path.is_file()
    assert http_calls == ["http_get"], "recovery repeated the external acquisition request"
    assert owner_calls == ["prepare", "continue", "prepare", "continue"]


@pytest.mark.parametrize("artifact_state", ["missing", "wrong_hash", "wrong_status"])
def test_host_protocol_rejects_stale_persisted_l05_terminal_manifest_before_work(
    host_step_fixture, monkeypatch, artifact_state
):
    from research_loop.l05_curie import europepmc_runtime

    fixture = host_step_fixture
    run_id = "acq-run-1"
    relative_manifest = (
        Path("08_Audit") / "l05_acquisition" / "C1" / run_id
        / "acquisition_manifest.json"
    )
    manifest_path = fixture.project / relative_manifest
    if artifact_state != "missing":
        manifest_path.parent.mkdir(parents=True)
        manifest = {
            "schema_version": "L05AcquisitionManifest/v2",
            "candidate_id": "C1",
            "round_id": "1",
            "acquisition_run_id": run_id,
            "terminal_status": (
                "FROZEN" if artifact_state == "wrong_status"
                else "INSUFFICIENT_STOP"
            ),
            "terminal_reason": "bounded discovery found insufficient evidence",
            "coverage": {},
        }
        raw_manifest = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_path.write_bytes(raw_manifest)
        manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    else:
        manifest_hash = "a" * 64

    stop_record = {
        "terminal_status": "L0_5_INSUFFICIENT_STOP",
        "completed": False,
        "full_dag_completed": False,
        "terminal_reason": "bounded discovery found insufficient evidence",
        "acquisition_run_id": run_id,
        "acquisition_manifest_path": relative_manifest.as_posix(),
        "acquisition_manifest_sha256": (
            "0" * 64 if artifact_state == "wrong_hash" else manifest_hash
        ),
        "node": "L0.5",
        "downstream": "NOT_ATTEMPTED",
    }
    stop_path = fixture.project / "08_Run_Receipts" / "C1" / "round_01" / "stop_decision.json"
    stop_path.parent.mkdir(parents=True)
    stop_path.write_text(json.dumps(stop_record), encoding="utf-8")

    monkeypatch.setattr(
        run_loop, "current_action",
        lambda *_args: pytest.fail("terminal manifest must validate before next-step"),
    )
    monkeypatch.setattr(
        run_loop, "provider_for",
        lambda *_args, **_kwargs: pytest.fail("terminal recovery must not invoke provider"),
    )
    monkeypatch.setattr(
        europepmc_runtime, "prepare_acquisition_host_step",
        lambda *_args, **_kwargs: pytest.fail("terminal recovery must not reacquire"),
    )
    monkeypatch.setattr(
        europepmc_runtime, "continue_acquisition",
        lambda *_args, **_kwargs: pytest.fail("terminal recovery must not continue acquisition"),
    )
    if artifact_state == "wrong_status":
        def validated_frozen_manifest(_project, _candidate, result):
            assert result["status"] == "FROZEN"
            return result

        monkeypatch.setattr(
            run_loop, "validate_europepmc_acquisition_result",
            validated_frozen_manifest,
        )

    result = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["status"] == "blocked"
    assert "manifest" in result["reason"].lower() or "acquisition" in result["reason"].lower()


def test_host_protocol_approval_gate_stops_before_l7_workspace_or_request(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    fixture.step.update(node="L7", persona="Turing")
    action = {
        "kind": "l7", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["L7"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "METHOD_APPROVED")
    events = []

    def approval_owner(*args):
        events.append(args[0])
        if args[0] == "execution-gate":
            return SimpleNamespace(
                returncode=1, stdout="HUMAN_APPROVAL_REQUIRED", stderr=""
            )
        pytest.fail(f"dependent host action ran before approval: {args[0]}")

    monkeypatch.setattr(run_loop, "_ctl", approval_owner)
    host_next = getattr(run_loop, "host_protocol_next", None)
    assert callable(host_next), "HOST_PROTOCOL_MISSING: host-next approval gate"

    result = host_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert result["status"] == "blocked"
    assert "HUMAN_APPROVAL_REQUIRED" in result["reason"]
    assert events == ["execution-gate"]


def test_host_protocol_runs_round_end_review_and_persists_stop_policy(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    fixture.cfg.review = {"enabled": True}
    report = fixture.project / "FINAL_REPORT.md"
    report.write_text("Completed report for host review.\n", encoding="utf-8")
    round_dir = fixture.project / "08_Run_Receipts" / "C1" / "round_01"
    round_dir.mkdir(parents=True)
    terminal_action = {
        "kind": "terminal", "step": {"terminal": True, "status": "KEEP"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
    }
    review_action = {
        "kind": "review", "step": {"node": "REVIEW", "persona": "Reviewer"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
    }
    monkeypatch.setattr(
        run_loop, "current_action",
        lambda *_args: review_action if _args[-1].get("host_review_pending")
        else terminal_action,
    )
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "KEEP")
    monkeypatch.setattr(run_loop, "load_delta", lambda *_args: None)

    action = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )

    assert action["status"] == "needs_host", (
        "HOST_REVIEW_MISSING: completed DAG must request the existing REVIEW gate "
        "before reporting terminal"
    )
    request = run_loop.ENGINE.load_host_request(fixture.project, action["request_id"])
    assert request["kind"] == "review"
    response = fixture.project / "host-review.json"
    response.write_text(json.dumps({
        "review_verdict": "accept", "evidence_score": 4,
        "method_validity_score": 4, "novelty_score": 4,
        "falsification_risk_score": 1, "marginal_gain_score": 0,
        "required_revisions": [], "executable_next_actions": [],
        "reason": "evidence supports the conclusion",
    }), encoding="utf-8")
    committed = run_loop.host_protocol_submit(
        fixture.project, "C1", action["request_id"], response
    )
    assert committed["status"] == "committed"
    terminal = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )
    assert terminal["status"] == "terminal"
    decision_path = round_dir / "stop_decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["stop"] is True
    assert decision["reason"] == "KEEP and review=accept"
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )
    assert resumed["status"] == "terminal"
    assert resumed.get("stop_decision") == decision


def test_host_protocol_resumes_review_response_recorded_after_process_reset(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    fixture.cfg.review = {"enabled": True}
    (fixture.project / "FINAL_REPORT.md").write_text(
        "Completed report for host review.\n", encoding="utf-8"
    )
    round_dir = fixture.project / "08_Run_Receipts" / "C1" / "round_01"
    round_dir.mkdir(parents=True)
    terminal_action = {
        "kind": "terminal", "step": {"terminal": True, "status": "KEEP"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
    }
    review_action = {
        "kind": "review", "step": {"node": "REVIEW", "persona": "Reviewer"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
    }
    monkeypatch.setattr(
        run_loop, "current_action",
        lambda *_args: review_action if _args[-1].get("host_review_pending")
        else terminal_action,
    )
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "KEEP")
    monkeypatch.setattr(run_loop, "load_delta", lambda *_args: None)

    prepared = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )
    assert prepared["status"] == "needs_host"
    response = fixture.project / "host-review-interrupted.json"
    response.write_text(json.dumps({
        "review_verdict": "accept", "evidence_score": 4,
        "method_validity_score": 4, "novelty_score": 4,
        "falsification_risk_score": 1, "marginal_gain_score": 0,
        "required_revisions": [], "executable_next_actions": [],
        "reason": "evidence supports the conclusion",
    }), encoding="utf-8")

    engine = run_loop.ENGINE
    real_submit_response = engine.submit_host_response

    def persist_receipt_then_interrupt(*args, **kwargs):
        real_submit_response(*args, **kwargs)
        raise RuntimeError("simulated REVIEW interruption after RESPONSE_RECORDED")

    monkeypatch.setattr(engine, "submit_host_response", persist_receipt_then_interrupt)
    with pytest.raises(RuntimeError, match="RESPONSE_RECORDED"):
        run_loop.host_protocol_submit(
            fixture.project, "C1", prepared["request_id"], response
        )
    monkeypatch.setattr(engine, "submit_host_response", real_submit_response)

    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )

    assert resumed["status"] == "terminal", (
        "persisted REVIEW response must pass the existing validator and StopPolicy on resume"
    )
    decision = json.loads((round_dir / "stop_decision.json").read_text(encoding="utf-8"))
    assert decision["reason"] == "KEEP and review=accept"
    request_files = list(
        (fixture.project / "08_Audit" / "host_handoff" / "requests").glob("*.json")
    )
    assert len(request_files) == 1


def test_host_protocol_round_finalization_reuses_existing_child_after_resume(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    fixture.cfg.review = {"enabled": True}
    fixture.cfg.max_rounds = 3
    (fixture.project / "FINAL_REPORT.md").write_text(
        "Completed report for host review.\n", encoding="utf-8"
    )
    (fixture.project / "08_Run_Receipts" / "C1" / "round_01").mkdir(parents=True)
    terminal_action = {
        "kind": "terminal", "step": {"terminal": True, "status": "REVISE"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
    }
    review_action = {
        "kind": "review", "step": {"node": "REVIEW", "persona": "Reviewer"},
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
    }
    monkeypatch.setattr(
        run_loop, "current_action",
        lambda *_args: review_action if _args[-1].get("host_review_pending")
        else terminal_action,
    )
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "REVISE")
    monkeypatch.setattr(run_loop, "load_delta", lambda *_args: {
        "decision": "REVISE", "next_steps": ["run the control analysis"],
    })
    child_calls = []
    monkeypatch.setattr(
        run_loop, "create_child",
        lambda *_args: child_calls.append(1) or "C2",
    )
    monkeypatch.setattr(run_loop, "evidence_sig", lambda *_args: "f" * 64)

    first = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )
    assert first["status"] == "needs_host", (
        "HOST_REVIEW_MISSING: round continuation requires the existing REVIEW gate"
    )
    review_response = fixture.project / "host-review-revise.json"
    review_response.write_text(json.dumps({
        "review_verdict": "major_revision", "evidence_score": 2,
        "method_validity_score": 3, "novelty_score": 3,
        "falsification_risk_score": 4, "marginal_gain_score": 4,
        "required_revisions": ["run the control analysis"],
        "executable_next_actions": ["run the control analysis"],
        "reason": "one control remains",
    }), encoding="utf-8")
    run_loop.host_protocol_submit(
        fixture.project, "C1", first["request_id"], review_response
    )
    continued = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", {}
    )
    assert continued["status"] == resumed["status"] == "continued"
    assert continued["next_candidate_id"] == resumed["next_candidate_id"] == "C2"
    assert child_calls == [1]


def test_round_summary_history_follows_explicit_continuation_lineage(tmp_path):
    candidates = tmp_path / "01_Candidates"
    candidates.mkdir()
    (candidates / "C1.md").write_text(
        "---\ncandidate_id: C1\nround_id: 1\n---\n", encoding="utf-8"
    )
    (candidates / "C2.md").write_text(
        "---\ncandidate_id: C2\nround_id: 2\nprevious_candidate_id: C1\n---\n",
        encoding="utf-8",
    )
    prior_summary = {
        "round": 1, "candidate": "C1", "status": "REVISE",
        "evidence_sig": "a" * 64, "review_verdict": "major_revision",
    }
    path = tmp_path / "08_Run_Receipts" / "C1" / "round_01" / "stop_decision.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"stop": False, "round_summary": prior_summary}),
                    encoding="utf-8")

    assert run_loop._round_summary_history(tmp_path, "C2", 2) == [prior_summary]


def test_round_summary_history_uses_each_ancestor_declared_round(tmp_path):
    candidates = tmp_path / "01_Candidates"
    candidates.mkdir()
    for candidate, round_id, previous in (
        ("C1", 1, ""), ("C2", 2, "C1"), ("C3", 3, "C2"),
    ):
        (candidates / f"{candidate}.md").write_text(
            f"---\ncandidate_id: {candidate}\nround_id: {round_id}\n"
            f"previous_candidate_id: {previous}\n---\n", encoding="utf-8"
        )
    summaries = [
        {"round": 1, "candidate": "C1", "evidence_sig": "1" * 64},
        {"round": 2, "candidate": "C2", "evidence_sig": "2" * 64},
    ]
    for summary in summaries:
        path = (tmp_path / "08_Run_Receipts" / summary["candidate"]
                / f"round_{summary['round']:02d}" / "stop_decision.json")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"stop": False, "round_summary": summary}),
                        encoding="utf-8")

    assert run_loop._round_summary_history(tmp_path, "C3", 3) == summaries


def test_agent_native_l9a_and_l9b_are_separate_serial_authorizations(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    steps = iter([
        {"node": "L9a", "persona": "Feynman", "profile_id": PROFILE_V21_CATALOG_1,
         "schema_version": "2.1", "advance_command": "review-hypotheses"},
        {"node": "L9b", "persona": "Darwin", "profile_id": PROFILE_V21_CATALOG_1,
         "schema_version": "2.1", "advance_command": "review-hypotheses"},
    ])
    snapshots = []

    class Ledger:
        def snapshot_candidate(self, project, candidate, round_id):
            snapshots.append((str(project), candidate, round_id))
            return {"candidate_id": candidate, "round_id": round_id,
                    "revision": len(snapshots)}

    monkeypatch.setattr(run_loop, "next_step", lambda *_args: next(steps))
    monkeypatch.setattr(run_loop, "_bound_profile_id",
                        lambda *_args: PROFILE_V21_CATALOG_1)
    monkeypatch.setattr(run_loop.rl, "_ledger_for",
                        lambda *_args, **_kwargs: Ledger())
    args = SimpleNamespace(mode="agent_native", knowledge_store=None)

    first = run_loop.current_action(
        fixture.project, "C1", fixture.cfg, args, "1", {}
    )
    second = run_loop.current_action(
        fixture.project, "C1", fixture.cfg, args, "1", {}
    )

    assert first["step"]["node"] == "L9a"
    assert second["step"]["node"] == "L9b"
    assert first["identity"]["nodes"] == ["L9a"]
    assert second["identity"]["nodes"] == ["L9b"]
    assert first["cursor"] != second["cursor"]
    assert len(snapshots) == 2


def test_agent_native_l7_host_preparation_keeps_execution_gate_and_workspace_order(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    fixture.step.update(node="L7", persona="Turing")
    persona = resolve_persona_template(
        get_profile(PROFILE_V21_CATALOG_1), "Turing"
    )
    manifest_data = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    manifest_data.update({
        "node": "L7", "persona": "Turing",
        "persona_catalog_sha256": persona.catalog_sha256,
        "persona_catalog_entry_sha256": persona.entry_sha256,
        "persona_template_sha256": persona.template_sha256,
        "persona_body_sha256": persona.body_sha256,
    })
    fixture.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    action = {
        "kind": "l7", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(run_loop, "_recover_committed_advance", lambda *_args: None)
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "METHOD_APPROVED")
    events = []

    def controlled_command(*argv):
        events.append(argv[0])
        if argv[0] == "execution-gate":
            return SimpleNamespace(returncode=0, stdout="AUTHORIZED", stderr="")
        if argv[0] == "prepare-turing-workspace":
            workspace = fixture.project / "08_Workspaces" / "C1" / "turing"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "WORKSPACE_MANIFEST.json").write_text(json.dumps({
                "candidate_id": "C1", "node": "L7", "missing": [],
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0,
                stdout=f"Turing workspace ready: {workspace}", stderr="",
            )
        pytest.fail(f"unexpected controller command {argv[0]}")

    monkeypatch.setattr(run_loop, "_ctl", controlled_command)
    monkeypatch.setattr(
        run_loop, "provider_for",
        lambda *_args, **_kwargs: pytest.fail("HOST_PROVIDER_FORBIDDEN: L7 host preparation"),
    )

    prepared = run_loop.prepare_host_step(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert events == ["execution-gate", "prepare-turing-workspace"]
    assert prepared["kind"] == "needs_host"
    assert prepared.get("request")


def test_repeated_host_next_reuses_pending_l7_workspace_and_request(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    fixture.step.update(node="L7", persona="Turing", tools_policy="workspace-fs")
    persona = resolve_persona_template(
        get_profile(PROFILE_V21_CATALOG_1), "Turing"
    )
    manifest_data = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    manifest_data.update({
        "node": "L7", "persona": "Turing", "tools_policy": "workspace-fs",
        "persona_catalog_sha256": persona.catalog_sha256,
        "persona_catalog_entry_sha256": persona.entry_sha256,
        "persona_template_sha256": persona.template_sha256,
        "persona_body_sha256": persona.body_sha256,
    })
    fixture.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    action = {
        "kind": "l7", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(run_loop, "_recover_committed_advance", lambda *_args: None)
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "METHOD_APPROVED")
    workspace = fixture.project / "08_Workspaces" / "C1" / "turing"
    script_rel = Path("scripts") / "approved.py"
    script_bytes = b"print('approved')\n"
    prepare_calls = []

    def controlled_command(*argv):
        if argv[0] == "execution-gate":
            return SimpleNamespace(returncode=0, stdout="AUTHORIZED", stderr="")
        if argv[0] == "prepare-turing-workspace":
            prepare_calls.append(tuple(argv))
            if "--clean" in argv and prepare_calls[:-1]:
                shutil.rmtree(workspace, ignore_errors=True)
            (workspace / "scripts").mkdir(parents=True, exist_ok=True)
            script = workspace / script_rel
            if not script.exists():
                script.write_bytes(script_bytes)
            (workspace / "WORKSPACE_MANIFEST.json").write_text(json.dumps({
                "candidate_id": "C1", "node": "L7", "missing": [],
                "staged_files": [{
                    "path": str(script_rel).replace("\\", "/"),
                    "sha256": hashlib.sha256(script_bytes).hexdigest(),
                    "role": "approved_execution_script",
                }],
                "output_manifest": {"directory": "results", "allowed": ["result.json"]},
            }), encoding="utf-8")
            return SimpleNamespace(
                returncode=0, stdout=f"Turing workspace ready: {workspace}", stderr=""
            )
        pytest.fail(f"unexpected controller command {argv[0]}")

    monkeypatch.setattr(run_loop, "_ctl", controlled_command)
    first = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert first["status"] == "needs_host"
    request_id = first["request_id"]
    request_path = Path(first["request_path"])
    bound_workspace = workspace / script_rel
    assert bound_workspace.is_file()
    sentinel = workspace / "pending-host-sentinel.txt"
    sentinel.write_text("request-bound workspace must survive resume\n", encoding="utf-8")

    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )

    assert resumed["status"] == "needs_host"
    assert resumed["request_id"] == request_id
    assert Path(resumed["request_path"]) == request_path
    assert len(prepare_calls) == 1
    assert sentinel.read_text(encoding="utf-8") == (
        "request-bound workspace must survive resume\n"
    )


def test_agent_native_l7_host_submit_binds_workspace_and_emits_before_executed(
    host_step_fixture, monkeypatch
):
    """L7 host cognition must retain Turing's exact workspace/delta boundary."""
    _prepare, submit = _host_step_api()
    fixture = host_step_fixture
    fixture.step.update(
        node="L7", persona="Turing", advance_command="decision",
        advance_status="EXECUTED", advance_reason="Turing execution complete",
        tools_policy="workspace-fs",
    )
    persona = resolve_persona_template(
        get_profile(PROFILE_V21_CATALOG_1), "Turing"
    )
    manifest_data = json.loads(fixture.manifest.read_text(encoding="utf-8"))
    manifest_data.update({
        "node": "L7", "persona": "Turing",
        "persona_catalog_sha256": persona.catalog_sha256,
        "persona_catalog_entry_sha256": persona.entry_sha256,
        "persona_template_sha256": persona.template_sha256,
        "persona_body_sha256": persona.body_sha256,
        "tools_policy": "workspace-fs",
    })
    fixture.manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    workspace = fixture.project / "08_Workspaces" / "C1" / "turing"
    (workspace / "scripts").mkdir(parents=True)
    (workspace / "results").mkdir()
    script = workspace / "scripts" / "approved.py"
    script.write_text("print('approved')\n", encoding="utf-8")
    workspace_manifest = workspace / "WORKSPACE_MANIFEST.json"
    workspace_manifest.write_text(json.dumps({
        "candidate_id": "C1", "node": "L7",
        "staged_files": [{
            "path": "scripts/approved.py",
            "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "role": "approved_execution_script",
        }],
        "output_manifest": {"directory": "results", "allowed": ["result.json"]},
    }, sort_keys=True), encoding="utf-8")
    workspace_sha = hashlib.sha256(workspace_manifest.read_bytes()).hexdigest()

    actions = [
        {
            "kind": "l7", "step": fixture.step,
            "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
            "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                         "cursor": fixture.cursor},
        },
        {
            "kind": "cognitive", "step": fixture.step,
            "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
            "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                         "cursor": fixture.cursor},
        },
    ]
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: actions.pop(0))
    monkeypatch.setattr(run_loop, "_recover_committed_advance", lambda *_args: None)
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "METHOD_APPROVED")
    monkeypatch.setattr(run_loop, "_provider_output_schema",
                        lambda *_args: {"type": "object"})
    events = []

    def controlled_command(*argv):
        command = argv[0]
        events.append(command)
        if command == "execution-gate":
            return SimpleNamespace(returncode=0, stdout="AUTHORIZED", stderr="")
        if command == "prepare-turing-workspace":
            return SimpleNamespace(
                returncode=0,
                stdout=f"Turing workspace ready: {workspace}\n",
                stderr="",
            )
        if command == "decision":
            assert argv[argv.index("--status") + 1] == "EXECUTED"
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        pytest.fail(f"unexpected controller command {command}")

    monkeypatch.setattr(run_loop, "_ctl", controlled_command)
    monkeypatch.setattr(run_loop, "provider_for",
                        lambda *_a, **_k: pytest.fail("HOST_PROVIDER_FORBIDDEN: L7"))
    monkeypatch.setattr(AgentProvider, "run_agent",
                        lambda *_a, **_k: pytest.fail("HOST_PROVIDER_FORBIDDEN: L7"))

    prepared = run_loop.prepare_host_step(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert prepared["kind"] == "needs_host"
    request = prepared["request"]
    assert request["inputs"]["workspace_manifest_path"] == str(workspace_manifest.resolve())
    assert request["inputs"]["workspace_manifest_sha256"] == workspace_sha
    assert request["inputs"]["workspace_manifest"]["staged_files"][0]["path"] == (
        "scripts/approved.py"
    )
    assert request["inputs"]["workspace_manifest"]["output_manifest"] == {
        "directory": "results", "allowed": ["result.json"]
    }

    response = fixture.project / "host-l7-response.json"
    response.write_text(json.dumps({
        "schema_version": "2.1", "execution_summary": "approved script completed",
        "script_path": "scripts/approved.py", "output_path": "results/result.json",
    }), encoding="utf-8")
    real_emit = run_loop.ENGINE.emit_delta

    def recording_emit(*emit_args, provider_receipt=None, **emit_kwargs):
        host_receipt = RunReceipt.read(provider_receipt)
        assert host_receipt.schema_version == "RunReceipt/v3-host"
        events.append("RunReceipt/v3-host")
        events.append("emit-delta")
        return real_emit(*emit_args, provider_receipt=provider_receipt, **emit_kwargs)

    monkeypatch.setattr(run_loop.ENGINE, "emit_delta", recording_emit)
    committed = submit(
        fixture.project, "C1", request["request_id"], response,
        session_identity={"source": "declared", "session_id": "fixture-host"},
    )

    assert committed["kind"] == "committed"
    assert events.index("execution-gate") < events.index("prepare-turing-workspace")
    assert events.index("RunReceipt/v3-host") < events.index("emit-delta")
    assert events.index("emit-delta") < events.index("decision")


def _prepare_text_host_step(fixture, monkeypatch):
    fixture.step.update(node="L7", persona="Turing")
    action = {
        "kind": "pre_research", "step": fixture.step,
        "profile_id": PROFILE_V21_CATALOG_1, "cursor": fixture.cursor,
        "identity": {"profile_id": PROFILE_V21_CATALOG_1,
                     "cursor": fixture.cursor, "nodes": ["L7"]},
    }
    monkeypatch.setattr(run_loop, "current_action", lambda *_args: action)
    monkeypatch.setattr(run_loop, "_recover_committed_advance", lambda *_args: None)
    monkeypatch.setattr(
        run_loop, "_ctl",
        lambda *argv: SimpleNamespace(
            returncode=0, stdout="Existing RLR L3 research prompt", stderr=""
        ) if argv[0] == "pre-research" else pytest.fail(f"unexpected {argv}"),
    )
    prepared = run_loop.prepare_host_step(
        fixture.project, "C1", fixture.cfg, fixture.args, "1", fixture.exec_state
    )
    assert prepared["kind"] == "needs_host"
    assert prepared["request"]["kind"] == "pre_research_text"
    return action, prepared


def test_agent_native_pre_research_text_submits_through_persisted_host_receipt(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    _action, prepared = _prepare_text_host_step(fixture, monkeypatch)
    response = fixture.project / "host-l7-text.json"
    response.write_text(json.dumps({"text": "Host-authored L7 pre-research notes.\n"}),
                        encoding="utf-8")

    committed = run_loop.submit_host_step(
        fixture.project, "C1", prepared["request_id"], response,
        session_identity={"source": "unavailable"},
    )

    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    assert committed["kind"] == "committed"
    assert target.read_text(encoding="utf-8") == "Host-authored L7 pre-research notes.\n"
    assert committed["text_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert fixture.events.count("raw-response") == 1


def test_host_protocol_resumes_pre_research_text_response_recorded_after_reset(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    _action, prepared = _prepare_text_host_step(fixture, monkeypatch)
    response = fixture.project / "host-l7-text-interrupted.json"
    response.write_text(json.dumps({"text": "Persisted host L7 notes.\n"}), encoding="utf-8")

    engine = run_loop.ENGINE
    real_submit_response = engine.submit_host_response

    def persist_receipt_then_interrupt(*args, **kwargs):
        real_submit_response(*args, **kwargs)
        raise RuntimeError("simulated pre-research interruption after RESPONSE_RECORDED")

    monkeypatch.setattr(engine, "submit_host_response", persist_receipt_then_interrupt)
    with pytest.raises(RuntimeError, match="RESPONSE_RECORDED"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"source": "unavailable"},
        )
    monkeypatch.setattr(engine, "submit_host_response", real_submit_response)

    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1",
        {"cursor": fixture.cursor},
    )

    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    assert resumed["status"] != "needs_host", (
        "persisted pre-research response must resume without asking host again"
    )
    assert target.read_text(encoding="utf-8") == "Persisted host L7 notes.\n"
    assert fixture.events.count("host-request") == 1


def test_host_protocol_rebuilds_changed_pre_research_target_from_recorded_response(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    _action, prepared = _prepare_text_host_step(fixture, monkeypatch)
    response = fixture.project / "host-l7-text-truncated.json"
    response.write_text(json.dumps({"text": "Authoritative host notes.\n"}), encoding="utf-8")

    engine = run_loop.ENGINE
    real_submit_response = engine.submit_host_response

    def persist_receipt_then_interrupt(*args, **kwargs):
        real_submit_response(*args, **kwargs)
        raise RuntimeError("simulated interruption after response receipt")

    monkeypatch.setattr(engine, "submit_host_response", persist_receipt_then_interrupt)
    with pytest.raises(RuntimeError, match="response receipt"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"source": "unavailable"},
        )
    monkeypatch.setattr(engine, "submit_host_response", real_submit_response)

    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("truncated/forged notes", encoding="utf-8")
    resumed = run_loop.host_protocol_next(
        fixture.project, "C1", fixture.cfg, fixture.args, "1",
        {"cursor": fixture.cursor},
    )

    assert target.read_text(encoding="utf-8") == "Authoritative host notes.\n", (
        "recovery must rebuild the text artifact from exact response receipt bytes"
    )
    assert resumed["status"] != "needs_host"


def test_pre_research_text_atomic_replace_failure_leaves_no_partial_completion(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    _action, prepared = _prepare_text_host_step(fixture, monkeypatch)
    response = fixture.project / "host-l7-text-atomic.json"
    response.write_text(json.dumps({"text": "Complete authoritative notes.\n"}),
                        encoding="utf-8")

    engine = run_loop.ENGINE
    real_submit_response = engine.submit_host_response

    def persist_receipt_then_interrupt(*args, **kwargs):
        real_submit_response(*args, **kwargs)
        raise RuntimeError("simulated interruption after response receipt")

    monkeypatch.setattr(engine, "submit_host_response", persist_receipt_then_interrupt)
    with pytest.raises(RuntimeError, match="response receipt"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"source": "unavailable"},
        )
    monkeypatch.setattr(engine, "submit_host_response", real_submit_response)

    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    assert not target.exists()
    real_replace = run_loop.os.replace

    def fail_target_replace(source, destination):
        if Path(destination) == target:
            raise OSError("simulated failure before atomic target replace")
        return real_replace(source, destination)

    monkeypatch.setattr(run_loop.os, "replace", fail_target_replace)
    with pytest.raises(OSError, match="atomic target replace"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"source": "unavailable"},
        )

    assert not target.exists(), "failed atomic text persistence must not look complete"


def test_agent_native_pre_research_text_rejects_malformed_host_response(
    host_step_fixture, monkeypatch
):
    fixture = host_step_fixture
    _action, prepared = _prepare_text_host_step(fixture, monkeypatch)
    response = fixture.project / "host-l7-invalid.json"
    response.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="(?i)(JSON|response)"):
        run_loop.submit_host_step(
            fixture.project, "C1", prepared["request_id"], response,
            session_identity={"source": "unavailable"},
        )

    target = fixture.project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    assert not target.exists()
