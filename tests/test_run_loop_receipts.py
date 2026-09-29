import copy
import hashlib
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

import run_loop
from research_loop.api import EngineAPI
from research_loop.commands import ledger as ledger_commands
from research_loop import deep_research as dr
from research_loop import research_seed
from research_loop import l4_evidence_bundle as l4_bundle
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.providers.base import RunReceipt
from research_loop.providers.command import CommandProvider


GOAL2_L0_FIXTURE = Path(__file__).parent / "fixtures" / "goal2_l0_blocked"


def test_engine_api_binds_receipt_to_goal2_persisted_context_bytes(tmp_path):
    """Replay Goal 2's context boundary without invoking a real provider.

    The controller writes the rendered context artifact and reports it through
    stderr, while its legacy stdout presentation adds a line terminator.  The
    receipt must consume the persisted bytes identified by the manifest.
    """
    fixture_context = (GOAL2_L0_FIXTURE / "rendered_context.txt").read_bytes()
    assert hashlib.sha256(fixture_context).hexdigest() == (
        "a42bf53714531498af7bd71955b39d5e8e941bb542ab77286926722786a6d725"
    )
    rendered = tmp_path / "rendered_context.txt"
    rendered.write_bytes(fixture_context)
    manifest = tmp_path / "context_manifest.json"
    prompt = tmp_path / "provider_prompt.txt"
    prompt.write_bytes(b"Goal 2 captured provider prompt replay\n")

    def fake_engine(argv):
        assert argv == ["assemble-context", "P", "C1", "--node", "L0"]
        manifest.write_text(json.dumps({
            "project_id": "PROJECT:1",
            "rendered_context_path": str(rendered),
            "rendered_context_sha256": hashlib.sha256(
                rendered.read_bytes()
            ).hexdigest(),
        }), encoding="utf-8")
        # Mirror the controller's stdout presentation, including its extra
        # print terminator, without making stdout a second artifact owner.
        print(fixture_context.decode("utf-8").replace("\r\n", "\n"))
        print(f"context manifest: {manifest}", file=sys.stderr)
        return 0

    context, manifest_path = EngineAPI(engine_main=fake_engine).assemble_context(
        "P", "C1", "L0"
    )
    provider = SimpleNamespace(
        name="command",
        type="command",
        last_prompt_file=str(prompt),
        last_delta_file=str(GOAL2_L0_FIXTURE / "provider_delta.json"),
        last_fresh_session=True,
    )

    receipt_path = run_loop.write_receipt(
        tmp_path / "run",
        "L0",
        "Linnaeus",
        provider,
        context,
        {"tools_policy": "no-fs", "everos_read_scopes": [],
         "profile_id": "v2.1-catalog-1"},
        "C1",
        "1",
        manifest=manifest_path,
        provider_delta_file=provider.last_delta_file,
    )

    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    assert context.encode("utf-8") == fixture_context
    assert receipt["context_hash"] == (
        "a42bf53714531498af7bd71955b39d5e8e941bb542ab77286926722786a6d725"
    )


def _host_receipt_fixture(tmp_path):
    """Create byte-backed v3-host artifacts for the versioned receipt contract."""
    context = tmp_path / "rendered-context.txt"
    context.write_bytes(b"host context\n")
    context_hash = hashlib.sha256(context.read_bytes()).hexdigest()
    manifest = tmp_path / "context-manifest.json"
    manifest_bytes = json.dumps({
        "schema_version": "ContextManifest/v2",
        "project_id": "PROJECT:host-test",
        "candidate_id": "C1",
        "round_id": "1",
        "node": "L2",
        "persona": "Linnaeus",
        "profile_id": "v2.1-catalog-1",
        "persona_catalog_sha256": "1" * 64,
        "persona_catalog_entry_sha256": "2" * 64,
        "persona_template_sha256": "3" * 64,
        "persona_body_sha256": "4" * 64,
        "rendered_context_path": str(context),
        "rendered_context_sha256": context_hash,
        "tools_policy": "no-fs",
    }, sort_keys=True).encode("utf-8")
    manifest.write_bytes(manifest_bytes)
    config_path = tmp_path / "runner.yaml"
    config_path.write_bytes(b"provider: host_session\n")

    request = tmp_path / "host-request.json"
    request_body = {
        "schema_version": "HostRequest/v1",
        "kind": "cognitive",
        "identity": {
            "project_id": "PROJECT:host-test",
            "candidate_id": "C1",
            "round_id": "1",
            "node": "L2",
            "persona": "Linnaeus",
            "profile_id": "v2.1-catalog-1",
            "stage": "cognitive",
            "attempt": 1,
            "cursor": {
                "project_id": "PROJECT:host-test",
                "candidate_id": "C1",
                "round_id": "1",
                "as_of_commit_seq": 0,
            },
        },
        "inputs": {
            "context_manifest_path": str(manifest),
            "context_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "rendered_context_path": str(context),
            "rendered_context_sha256": context_hash,
            "context_hash": context_hash,
            "persona_catalog_sha256": "1" * 64,
            "persona_catalog_entry_sha256": "2" * 64,
            "persona_template_sha256": "3" * 64,
            "persona_body_sha256": "4" * 64,
            "runner_config_path": str(config_path),
            "runner_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        },
        "tools_policy": "no-fs",
        "output_contract": {"schema_version": "2.1", "type": "object"},
    }
    request_id = hashlib.sha256(json.dumps(
        request_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    request_bytes = (json.dumps(
        {**request_body, "request_id": request_id},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ) + "\n").encode("utf-8")
    request.write_bytes(request_bytes)
    raw_response = tmp_path / "host-response.json"
    raw_response_bytes = b'{"answer":"host supplied"}\r\n'
    raw_response.write_bytes(raw_response_bytes)
    canonical_delta = tmp_path / "canonical-delta.json"
    canonical_bytes = b'{"candidate_id":"C1","schema_version":"2.1"}\n'
    canonical_delta.write_bytes(canonical_bytes)

    receipt = {
        "schema_version": "RunReceipt/v3-host",
        "node": "L2",
        "persona": "Linnaeus",
        "provider": "host_session",
        "timestamp": "2026-09-28T00:00:00Z",
        "context_hash": context_hash,
        "project_id": "PROJECT:host-test",
        "candidate_id": "C1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
        "context_manifest_path": str(manifest),
        "context_manifest_hash": hashlib.sha256(manifest_bytes).hexdigest(),
        "rendered_context_path": str(context),
        "rendered_context_hash": context_hash,
        "provider_delta_path": str(canonical_delta),
        "provider_delta_hash": hashlib.sha256(canonical_bytes).hexdigest(),
        "host_request_path": str(request),
        "host_request_hash": hashlib.sha256(request_bytes).hexdigest(),
        "raw_response_path": str(raw_response),
        "raw_response_hash": hashlib.sha256(raw_response_bytes).hexdigest(),
        "canonical_delta_path": str(canonical_delta),
        "canonical_delta_hash": hashlib.sha256(canonical_bytes).hexdigest(),
        "host_session_id": "session-1",
        "host_session_id_source": "verified",
        "allowed_tools": ["no-fs"],
        "everos_scope": [],
        "git_head": "a" * 40,
        "git_dirty": False,
        "working_tree_diff_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "code_state_id": "d" * 64,
        "exit_code": None,
        "timed_out": None,
        "terminal_state": None,
        "execution_status": None,
    }
    receipt_path = tmp_path / "host-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt_path, receipt, request, raw_response, canonical_delta


def test_host_v3_receipt_accepts_only_exact_artifact_and_context_bindings(tmp_path):
    receipt_path, receipt, request, raw_response, canonical_delta = (
        _host_receipt_fixture(tmp_path)
    )
    try:
        accepted = RunReceipt.read(receipt_path)
    except ValueError as exc:
        pytest.fail(f"valid RunReceipt/v3-host rejected: {exc}")
    assert accepted.schema_version == "RunReceipt/v3-host"

    for field in (
        "host_request_hash",
        "raw_response_hash",
        "canonical_delta_hash",
    ):
        changed = copy.deepcopy(receipt)
        changed[field] = "0" * 64
        receipt_path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError):
            RunReceipt.read(receipt_path)

    changed = copy.deepcopy(receipt)
    changed["context_hash"] = "0" * 64
    receipt_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError):
        RunReceipt.read(receipt_path)

    context_path = Path(receipt["rendered_context_path"])
    for artifact_path in (request, context_path, raw_response, canonical_delta):
        artifact_bytes = artifact_path.read_bytes()
        artifact_path.write_bytes(artifact_bytes + b"tampered")
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with pytest.raises(ValueError):
            RunReceipt.read(receipt_path)
        artifact_path.write_bytes(artifact_bytes)

    changed_request = json.loads(request.read_text(encoding="utf-8"))
    changed_request["request_id"] = "0" * 64
    changed_request_bytes = (json.dumps(
        changed_request, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ) + "\n").encode("utf-8")
    request.write_bytes(changed_request_bytes)
    changed_receipt = copy.deepcopy(receipt)
    changed_receipt["host_request_hash"] = hashlib.sha256(
        changed_request_bytes
    ).hexdigest()
    receipt_path.write_text(json.dumps(changed_receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="(?i)request ID"):
        RunReceipt.read(receipt_path)

    for field, changed_value in (
        ("context_manifest_path", str(Path(receipt["context_manifest_path"]).with_name("other-manifest.json"))),
        ("context_manifest_sha256", "e" * 64),
        ("rendered_context_path", str(Path(receipt["rendered_context_path"]).with_name("other-context.txt"))),
        ("rendered_context_sha256", "f" * 64),
    ):
        changed_request = json.loads(request.read_text(encoding="utf-8"))
        changed_request["inputs"][field] = changed_value
        request_body = {
            name: changed_request[name]
            for name in (
                "schema_version", "kind", "identity", "inputs", "tools_policy",
                "output_contract",
            )
        }
        changed_request["request_id"] = hashlib.sha256(json.dumps(
            request_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        changed_request_bytes = (json.dumps(
            changed_request, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ) + "\n").encode("utf-8")
        request.write_bytes(changed_request_bytes)
        changed_receipt = copy.deepcopy(receipt)
        changed_receipt["host_request_hash"] = hashlib.sha256(
            changed_request_bytes
        ).hexdigest()
        receipt_path.write_text(json.dumps(changed_receipt), encoding="utf-8")
        with pytest.raises(ValueError, match="(?i)(request|context|path|hash)"):
            RunReceipt.read(receipt_path)


def test_host_submit_validation_rejects_rehashed_request_with_changed_persona_template(
    tmp_path,
):
    receipt_path, receipt, request_path, *_ = _host_receipt_fixture(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["inputs"]["persona_template_sha256"] = "f" * 64
    request_body = {key: value for key, value in request.items() if key != "request_id"}
    request_id = hashlib.sha256(json.dumps(
        request_body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    request["request_id"] = request_id
    request_bytes = (json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ) + "\n").encode("utf-8")
    request_path.write_bytes(request_bytes)
    changed_receipt = copy.deepcopy(receipt)
    changed_receipt["host_request_hash"] = hashlib.sha256(request_bytes).hexdigest()
    receipt_path.write_text(json.dumps(changed_receipt), encoding="utf-8")

    request.update({
        "request_path": str(request_path),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
    })
    action = {
        "profile_id": request["identity"]["profile_id"],
        "cursor": request["identity"]["cursor"],
        "step": {
            "node": request["identity"]["node"],
            "persona": request["identity"]["persona"],
            "tools_policy": request["tools_policy"],
        },
    }
    with pytest.raises(RuntimeError, match="(?i)(persona|template)"):
        run_loop._validate_host_step_request(
            tmp_path, "C1", "1", action, request
        )


def test_unavailable_host_session_source_does_not_require_an_invented_id(tmp_path):
    receipt_path, receipt, *_ = _host_receipt_fixture(tmp_path)
    receipt["host_session_id"] = None
    receipt["host_session_id_source"] = "unavailable"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    try:
        accepted = RunReceipt.read(receipt_path)
    except ValueError as exc:
        pytest.fail(f"unavailable host session ID should be representable: {exc}")
    assert accepted.host_session_id is None
    assert accepted.host_session_id_source == "unavailable"


@pytest.mark.parametrize("source", ["verified", "declared"])
def test_verified_or_declared_host_session_source_requires_an_id(tmp_path, source):
    receipt_path, receipt, *_ = _host_receipt_fixture(tmp_path)
    receipt["host_session_id"] = None
    receipt["host_session_id_source"] = source
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="(?i)host_session_id"):
        RunReceipt.read(receipt_path)


def test_emit_delta_rejects_host_request_missing_context_artifact_references(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    context = project / "rendered-context.txt"
    context.write_bytes(b"frozen context\n")
    context_hash = hashlib.sha256(context.read_bytes()).hexdigest()
    manifest = project / "context-manifest.json"
    auth = {
        "authorization_id": "AUTH:fixture",
        "as_of_commit_seq": 0,
        "projection_hash": "a" * 64,
        "artifact_hash": "b" * 64,
        "event_ids": [],
    }
    manifest_data = {
        "schema_version": "ContextManifest/v2",
        "project_id": "PROJECT:host-test",
        "candidate_id": "C1",
        "round_id": "1",
        "node": "L2",
        "persona": "Linnaeus",
        "profile_id": "v2.1-catalog-1",
        "persona_catalog_sha256": "c" * 64,
        "persona_catalog_entry_sha256": "d" * 64,
        "persona_template_sha256": "e" * 64,
        "persona_body_sha256": "f" * 64,
        "rendered_context_path": str(context),
        "rendered_context_sha256": context_hash,
        "tools_policy": "no-fs",
        "hypothesis_authorization": auth,
        "injected_deltas": [],
    }
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    cursor = {
        "project_id": "PROJECT:host-test",
        "candidate_id": "C1",
        "round_id": "1",
        "as_of_commit_seq": 0,
        "authorized_events": [],
        "projection_hash": "a" * 64,
    }
    identity = {
        "project_id": "PROJECT:host-test",
        "candidate_id": "C1",
        "round_id": "1",
        "node": "L2",
        "persona": "Linnaeus",
        "profile_id": "v2.1-catalog-1",
        "cursor": cursor,
    }
    request = project / "08_Audit" / "host_handoff" / "requests" / "request.json"
    request.parent.mkdir(parents=True)
    request_data = {
        "schema_version": "HostRequest/v1",
        "kind": "cognitive",
        "identity": identity,
        "inputs": {
            "context_hash": context_hash,
        },
        "tools_policy": "no-fs",
        "output_contract": {"type": "object"},
        "request_id": "request-id",
    }
    request.write_text(json.dumps(request_data), encoding="utf-8")
    request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
    raw_response = project / "08_Audit" / "host_handoff" / "responses" / "request.raw"
    raw_response.parent.mkdir(parents=True)
    raw_response.write_bytes(b'{"answer":1}\n')
    raw_hash = hashlib.sha256(raw_response.read_bytes()).hexdigest()
    response_receipt = raw_response.with_suffix(".json")
    response_receipt.write_text(json.dumps({
        "request_id": "request-id",
        "request_path": str(request),
        "request_sha256": request_hash,
        "raw_response_path": str(raw_response),
        "raw_response_sha256": raw_hash,
        "cursor": cursor,
    }), encoding="utf-8")
    delta = project / "delta.json"
    delta.write_bytes(b'{"candidate_id":"C1","schema_version":"2.1"}\n')
    delta_hash = hashlib.sha256(delta.read_bytes()).hexdigest()
    receipt_path = project / "host-receipt.json"
    expected = {
        "project_id": "PROJECT:host-test",
        "candidate_id": "C1",
        "round_id": "1",
        "node": "L2",
        "persona": "Linnaeus",
        "profile_id": "v2.1-catalog-1",
    }
    provider = SimpleNamespace(
        **expected,
        schema_version="RunReceipt/v3-host",
        context_manifest_hash=manifest_hash,
        rendered_context_hash=context_hash,
        context_hash=context_hash,
        provider_delta_path=str(delta),
        provider_delta_hash=delta_hash,
        raw_provider_delta_path=None,
        raw_provider_delta_hash=None,
        prompt_file=None,
        prompt_hash=None,
        host_request_path=str(request),
        host_request_hash=request_hash,
        raw_response_path=str(raw_response),
        raw_response_hash=raw_hash,
        canonical_delta_path=str(delta),
        canonical_delta_hash=delta_hash,
        transformation_receipt_path=None,
        transformation_receipt_hash=None,
        host_session_id="session-1",
        host_session_id_source="verified",
        allowed_tools=["no-fs"],
        git_head="1" * 40,
        git_dirty=False,
        working_tree_diff_sha256="2" * 64,
        config_sha256="3" * 64,
        code_state_id="4" * 64,
    )
    monkeypatch.setattr(
        ledger_commands.RunReceipt,
        "read",
        classmethod(lambda _cls, _path: provider),
    )
    monkeypatch.setattr(
        ledger_commands,
        "resolve_persona_template",
        lambda *_args: SimpleNamespace(
            catalog_sha256="c" * 64,
            entry_sha256="d" * 64,
            template_sha256="e" * 64,
            body_sha256="f" * 64,
        ),
    )

    class Ledger:
        def load_authorized_context(self, _project, _authorization_id):
            return {
                **auth,
                "candidate_id": "C1",
                "round_id": "1",
                "node": "L2",
            }

        def snapshot_candidate(self, _project, candidate_id, round_id):
            assert candidate_id == "C1"
            assert round_id == "1"
            return cursor

    args = SimpleNamespace(
        context_manifest=str(manifest),
        receipt=None,
        provider_receipt=str(receipt_path),
        cand_id="C1",
        node="L2",
        persona="Linnaeus",
        project_dir=str(project),
    )
    profile = SimpleNamespace(
        delta_schema_version="2.1",
        profile_id="v2.1-catalog-1",
        l9_parallel=False,
    )

    with pytest.raises(ledger_commands.LedgerError, match="context artifact"):
        ledger_commands._validate_native_receipts(
            args,
            profile,
            source_file=delta,
            project_id="PROJECT:host-test",
            round_id="1",
            ledger=Ledger(),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param({"exit_code": 0}, id="fabricated-exit-code"),
        pytest.param({"timed_out": False}, id="fabricated-timeout"),
        pytest.param({"command": "claude --print"}, id="fabricated-subprocess-command"),
        pytest.param({"http_status": 200}, id="fabricated-http-status"),
        pytest.param({"persona": "DifferentPersona"}, id="changed-persona"),
        pytest.param({"allowed_tools": ["filesystem-write"]}, id="changed-tool-policy"),
    ],
)
def test_host_v3_receipt_rejects_fabricated_execution_or_changed_identity(tmp_path, mutation):
    receipt_path, receipt, *_ = _host_receipt_fixture(tmp_path)
    changed = copy.deepcopy(receipt)
    changed.update(mutation)
    receipt_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError):
        RunReceipt.read(receipt_path)


@pytest.mark.parametrize("schema_version", ["RunReceipt/v1", "RunReceipt/v2"])
def test_existing_v1_and_v2_receipts_remain_readable(tmp_path, schema_version):
    receipt = {
        "schema_version": schema_version,
        "node": "L2",
        "persona": "Linnaeus",
        "provider": "command",
        "timestamp": "2026-09-28T00:00:00Z",
        "context_hash": "a" * 64,
        "project_id": "PROJECT:host-test",
        "candidate_id": "C1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
        "context_manifest_path": str(tmp_path / "manifest.json"),
        "context_manifest_hash": "b" * 64,
        "rendered_context_path": str(tmp_path / "context.txt"),
        "rendered_context_hash": "a" * 64,
        "prompt_file": str(tmp_path / "prompt.txt"),
        "prompt_hash": "c" * 64,
        "provider_delta_path": str(tmp_path / "delta.json"),
        "provider_delta_hash": "d" * 64,
    }
    if schema_version == "RunReceipt/v2":
        receipt.update({
            "git_head": "e" * 40,
            "git_dirty": False,
            "working_tree_diff_sha256": "f" * 64,
            "config_sha256": "1" * 64,
            "code_state_id": "2" * 64,
            "raw_provider_delta_path": str(tmp_path / "delta.json"),
            "raw_provider_delta_hash": "d" * 64,
        })
    path = tmp_path / f"{schema_version.replace('/', '-')}.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert RunReceipt.read(path).schema_version == schema_version


def test_write_receipt_rejects_context_text_that_does_not_match_manifest_bytes(tmp_path):
    rendered = tmp_path / "rendered_context.txt"
    rendered.write_text("context\n", encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("prompt", encoding="utf-8")
    delta = tmp_path / "delta.json"
    delta.write_text('{"schema_version":"2.1"}', encoding="utf-8")
    manifest = tmp_path / "context_manifest.json"
    manifest.write_text(json.dumps({
        "project_id": "PROJECT:1",
        "rendered_context_path": str(rendered),
        "rendered_context_sha256": hashlib.sha256(rendered.read_bytes()).hexdigest(),
    }), encoding="utf-8")

    provider = CommandProvider({"command": "unused"})
    provider.last_prompt_file = str(prompt)
    provider.last_delta_file = str(delta)

    with pytest.raises(ValueError, match="context bytes do not match"):
        run_loop.write_receipt(
            tmp_path / "run",
            "L0",
            "Linnaeus",
            provider,
            rendered.read_text(encoding="utf-8") + "\n",
            {"tools_policy": "no-fs", "everos_read_scopes": [],
             "profile_id": "v2.1-catalog-1"},
            "C1",
            "1",
            manifest=str(manifest),
            provider_delta_file=delta,
        )


def test_provider_raw_delta_is_reused_as_the_canonical_emission(tmp_path):
    raw = tmp_path / "L4_Fisher_delta.json"
    raw_bytes = b'{"candidate_id":"C1","schema_version":"2.1"}\r\n'
    raw.write_bytes(raw_bytes)
    provider = SimpleNamespace(last_delta_file=str(raw))

    emitted, transformation = run_loop.canonical_provider_emission(
        provider,
        tmp_path / "run",
        "L4",
        "Fisher",
        json.loads(raw_bytes),
    )

    assert emitted == raw
    assert emitted.read_bytes() == raw_bytes
    assert transformation is None


def test_code_state_changes_when_same_head_has_different_working_tree_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / "run.yaml"
    config.write_text("mode: headless\n", encoding="utf-8")
    source = repo / "module.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    import subprocess
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Test User"],
        ["git", "add", "module.py", "run.yaml"],
        ["git", "commit", "-qm", "baseline"],
    ):
        subprocess.run(command, cwd=repo, check=True)

    first = run_loop.capture_code_state(repo, config)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    second = run_loop.capture_code_state(repo, config)

    assert first["git_head"] == second["git_head"]
    assert first["working_tree_diff_sha256"] != second["working_tree_diff_sha256"]
    assert first["code_state_id"] != second["code_state_id"]
    assert second["config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()


def _synthetic_l4_run_entry(project, monkeypatch):
    """Freeze a real synthetic native L4 run in the production manifest shape.

    Native L4 contexts carry the exact evidence authority in the dedicated
    ``native_l4_evidence`` field while ``pre_research`` stays None.  The
    staged-bundle boundary is faked here because these are unit tests of the
    handle binder; the full real chain lives in
    tests/test_native_l4_evidence_authority.py.
    """
    payload = {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["synthetic L4 receipt fixture"],
        "papers": [{
            "url": "https://example.invalid/C1/L4",
            "title": "Synthetic receipt fixture",
            "source_database": "synthetic-test",
            "source_metadata_response": {"candidate_id": "C1", "node": "L4"},
            "open_access": False,
            "extracts": [
                {"section": section, "text": f"{section} evidence",
                 "locator": f"{section} 1"}
                for section in ("Results", "Discussion", "Conclusion", "Methods")
            ],
        }],
        "review_search": {
            "status": "none_found",
            "receipt": "synthetic zero-result review search",
        },
    }
    artifact = dr.persist_run(
        project, "C1", "L4", payload,
        dr.skill_receipt("codex", ["codex"], "synthetic", "test"),
        project_id="P1", round_id="1", profile_id=PROFILE_V21_CATALOG_1,
        research_persona="Curie",
    )
    evidence = {
        **artifact,
        "evidence_bundle_schema": l4_bundle.EVIDENCE_BUNDLE_SCHEMA,
        "evidence_cards": [{
            "status": "accepted", "evidence_card_id": "CARD-CANONICAL",
            "anchor_id": "ANCHOR-CANONICAL", "method_id": "M1",
        }],
        "evidence_gaps": [],
    }
    monkeypatch.setattr(ledger_commands.deep_research, "_artifact",
                        lambda *args, **kwargs: evidence)
    manifest_entry = dr.evidence_artifact_manifest(
        project, "C1", "L4", artifact["run_id"]
    )
    manifest = project / "context_manifest.json"
    manifest.write_text(json.dumps({
        "pre_research": None,
        "native_l4_evidence": manifest_entry,
    }), encoding="utf-8")
    return artifact["run_id"], manifest


def test_l4_handle_binding_creates_bound_artifact_and_explicit_provenance_edge(
    tmp_path, monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    raw = tmp_path / "L4_Fisher_delta.json"
    run_id, manifest = _synthetic_l4_run_entry(project, monkeypatch)
    raw_data = {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": run_id,
        "method_components": [],
        "method_candidates": [{
            "method_id": "M1",
            "component_id": "MC1",
            "evidence_card_handles": ["E1"],
            "evidence_gap_handles": [],
            "method_anchor_handles": ["A1"],
        }],
    }
    raw.write_text(json.dumps(raw_data, separators=(",", ":")), encoding="utf-8")
    args = SimpleNamespace(
        project_dir=str(project), node="L4", cand_id="C1",
        context_manifest=str(manifest), receipt=None,
    )

    bound, provenance = ledger_commands._bind_l4_delta_for_commit(
        args, raw_data, raw
    )

    assert raw.read_text(encoding="utf-8") == json.dumps(raw_data, separators=(",", ":"))
    candidate = bound["method_candidates"][0]
    assert candidate["evidence_card_ids"] == ["CARD-CANONICAL"]
    assert candidate["method_anchor_ids"] == ["ANCHOR-CANONICAL"]
    assert provenance["evidence_run_id"] == run_id
    assert provenance["raw_provider_delta_sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()


def test_emit_boundary_resolves_l4_handles_without_runner_owned_bound_copy(
    tmp_path, monkeypatch,
):
    run_id, manifest = _synthetic_l4_run_entry(tmp_path, monkeypatch)
    raw_data = {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": run_id,
        "method_components": [],
        "method_candidates": [{
            "method_id": "M1",
            "component_id": "MC1",
            "evidence_card_handles": ["E1"],
            "evidence_gap_handles": [],
            "method_anchor_handles": ["A1"],
        }],
    }
    raw = tmp_path / "L4_Fisher_provider.json"
    raw.write_text(json.dumps(raw_data), encoding="utf-8")
    args = SimpleNamespace(
        project_dir=str(tmp_path), node="L4", cand_id="C1",
        context_manifest=str(manifest), receipt=None,
    )

    resolved, binding = ledger_commands._bind_l4_delta_for_commit(
        args, raw_data, raw
    )

    candidate = resolved["method_candidates"][0]
    assert candidate["evidence_card_ids"] == ["CARD-CANONICAL"]
    assert candidate["method_anchor_ids"] == ["ANCHOR-CANONICAL"]
    assert binding["evidence_run_id"] == run_id
    assert binding["raw_provider_delta_path"] == str(raw)
    assert not raw.with_name("L4_Fisher_provider_bound.json").exists()


def test_loopx_same_external_fingerprint_retries_once_then_escalates():
    policy = run_loop.LoopXRetryPolicy(retry_threshold=2)

    first = policy.record("L4", "EXTERNAL", "provider_timeout")
    second = policy.record("L4", "EXTERNAL", "provider_timeout")

    assert first["failure_class"] == "EXTERNAL"
    assert first["node"] == "L4"
    assert first["attempt_count"] == 1
    assert first["recommended_action"] == "RETRY_SAME_NODE"
    assert second["failure_fingerprint"] == first["failure_fingerprint"]
    assert second["attempt_count"] == 2
    assert second["recommended_action"] == "ESCALATE_ARCHITECTURE_REVIEW"


def test_loopx_contract_failure_never_allows_prompt_only_retry():
    policy = run_loop.LoopXRetryPolicy(retry_threshold=2)

    event = policy.record("L4", "CONTRACT", "unknown_evidence_card_handle")

    assert event["attempt_count"] == 1
    assert event["recommended_action"] == "ESCALATE_ARCHITECTURE_REVIEW"


def test_run_round_contract_escalation_stops_before_second_provider_dispatch(
    monkeypatch, tmp_path,
):
    step = {
        "node": "L4", "persona": "Fisher", "advance_command": "decision",
        "profile_id": "v2.1-catalog-1", "schema_version": "2.1",
    }
    provider_calls = []

    monkeypatch.setattr(run_loop, "next_step", lambda *_: step)
    monkeypatch.setattr(run_loop, "status_of", lambda *_: "IDEA_SELECTED")
    monkeypatch.setattr(run_loop, "load_delta", lambda *_: None)
    monkeypatch.setattr(run_loop, "ensure_pre_research", lambda *args: True)

    def contract_failure(*args, **kwargs):
        provider_calls.append("called")
        run_loop.record_loopx_failure(
            kwargs["failure_state"], "L4", "CONTRACT", "unknown_evidence_card_handle"
        )
        return False

    monkeypatch.setattr(run_loop, "exec_cognitive", contract_failure)
    cfg = SimpleNamespace(stop_policy={
        "max_l7_failures": 2, "max_node_failures": 5,
        "loopx_retry_threshold": 2,
    })
    args = SimpleNamespace(stop_after_node=None)
    state = {"l7_failures": 0, "node_failures": {}}

    outcome = run_loop.run_round(str(tmp_path), "C1", cfg, args, 1, 1, state)

    assert outcome == "node_failed:L4"
    assert provider_calls == ["called"]
    assert state["last_loopx_failure"]["recommended_action"] == "ESCALATE_ARCHITECTURE_REVIEW"


def test_headless_round_dispatches_l05_through_existing_acquisition_owner(
    monkeypatch, tmp_path
):
    l05_step = {
        "node": "L0.5", "persona": "Curie", "profile_id": "v2.1-catalog-1",
        "schema_version": "2.1",
    }
    steps = iter([l05_step, {"terminal": True, "status": "IDEA_PROPOSED"}])
    dispatches = []
    monkeypatch.setattr(run_loop, "next_step", lambda *_args: next(steps))
    monkeypatch.setattr(
        run_loop, "exec_l05",
        lambda *args: dispatches.append(args[2]) or {"terminal_status": "FROZEN"},
    )

    outcome = run_loop.run_round(
        str(tmp_path), "C1", SimpleNamespace(stop_policy={}),
        SimpleNamespace(), 1, 1, {"l7_failures": 0, "node_failures": {}},
    )

    assert outcome == "terminal"
    assert dispatches == [l05_step]


def test_headless_round_dispatches_l7_through_existing_execution_owner(
    monkeypatch, tmp_path
):
    l7_step = {
        "node": "L7", "persona": "Turing", "profile_id": "v2.1-catalog-1",
        "schema_version": "2.1",
    }
    steps = iter([
        l7_step, l7_step, {"terminal": True, "status": "EXECUTED"},
    ])
    dispatches = []
    monkeypatch.setattr(run_loop, "next_step", lambda *_args: next(steps))
    monkeypatch.setattr(run_loop, "ensure_pre_research", lambda *_args: True)
    monkeypatch.setattr(
        run_loop, "exec_turing",
        lambda *args: dispatches.append(args[2]) or True,
    )

    outcome = run_loop.run_round(
        str(tmp_path), "C1",
        SimpleNamespace(stop_policy={"max_l7_failures": 2, "max_node_failures": 2}),
        SimpleNamespace(), 1, 1, {"l7_failures": 0, "node_failures": {}},
    )

    assert outcome == "terminal"
    assert dispatches == [l7_step]


def test_headless_round_finalizes_l10c_through_existing_report_command(
    monkeypatch, tmp_path
):
    l10c_step = {
        "node": "L10c", "persona": "Jobs", "profile_id": "v2.1-catalog-1",
        "schema_version": "2.1",
    }
    calls = []
    monkeypatch.setattr(run_loop, "next_step", lambda *_args: l10c_step)
    monkeypatch.setattr(run_loop, "ensure_pre_research", lambda *_args: True)
    monkeypatch.setattr(
        run_loop, "_ctl",
        lambda *args: calls.append(args) or SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
    )

    outcome = run_loop.run_round(
        str(tmp_path), "C1",
        SimpleNamespace(stop_policy={"max_l7_failures": 2, "max_node_failures": 2}),
        SimpleNamespace(), 1, 1, {"l7_failures": 0, "node_failures": {}},
    )

    assert outcome == "completed"
    assert calls == [("aggregate-report", str(tmp_path), "C1")]


def test_exec_cognitive_classifies_provider_exception_and_fails_closed(
    monkeypatch, tmp_path,
):
    provider = SimpleNamespace(
        name="command",
        run_agent=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("timeout")),
    )
    monkeypatch.setattr(run_loop, "assemble_context", lambda *args, **kwargs: ("ctx", None))
    monkeypatch.setattr(run_loop, "provider_for", lambda *args, **kwargs: provider)
    monkeypatch.setattr(run_loop, "auto_pitfall", lambda *args, **kwargs: None)
    state = {"loopx_policy": run_loop.LoopXRetryPolicy(retry_threshold=2)}
    cfg = SimpleNamespace(data={}, source_path=None)
    args = SimpleNamespace(evidence_run_ids={})
    step = {"node": "L4", "persona": "Fisher", "schema_version": "2.1"}

    ok = run_loop.exec_cognitive(
        str(tmp_path), "C1", step, cfg, args, tmp_path / "run", 1,
        failure_state=state,
    )

    assert ok is False
    assert state["last_loopx_failure"]["failure_class"] == "EXTERNAL"
    assert state["last_loopx_failure"]["recommended_action"] == "RETRY_SAME_NODE"


def test_exec_turing_fails_closed_when_final_controller_decision_rejects(
    monkeypatch, tmp_path,
):
    provider = SimpleNamespace(
        name="command", last_delta_file=None,
        run_agent=lambda *args, **kwargs: {"schema_version": "2.1"},
    )

    def fake_ctl(*argv):
        if argv[0] == "prepare-turing-workspace":
            return SimpleNamespace(
                returncode=0, stdout="Turing workspace ready: WORKSPACE\n", stderr=""
            )
        if argv[0] == "decision":
            return SimpleNamespace(returncode=1, stdout="", stderr="rejected")
        raise AssertionError(argv)

    monkeypatch.setattr(run_loop, "_ctl", fake_ctl)
    monkeypatch.setattr(run_loop, "status_of", lambda *args: "EXECUTION_READY")
    monkeypatch.setattr(run_loop, "assemble_context", lambda *args, **kwargs: ("ctx", None))
    monkeypatch.setattr(run_loop, "provider_for", lambda *args, **kwargs: provider)
    monkeypatch.setattr(run_loop, "emit_delta", lambda *args, **kwargs: True)
    monkeypatch.setattr(run_loop, "write_receipt", lambda *args, **kwargs: "receipt.json")
    monkeypatch.setattr(run_loop, "auto_pitfall", lambda *args, **kwargs: None)
    cfg = SimpleNamespace(data={}, source_path=None)
    args = SimpleNamespace(provider=None)
    state = {
        "l7_failures": 0,
        "loopx_policy": run_loop.LoopXRetryPolicy(retry_threshold=2),
    }

    ok = run_loop.exec_turing(
        str(tmp_path), "C1", {"node": "L7", "persona": "Turing", "schema_version": "2.1"},
        cfg, args, tmp_path / "run", 1, state,
    )

    assert ok is False
    assert state["last_loopx_failure"]["failure_class"] == "IMPLEMENTATION"


def test_exec_turing_classifies_provider_exception_for_loopx(monkeypatch, tmp_path):
    provider = SimpleNamespace(
        name="command",
        run_agent=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("timeout")),
    )
    monkeypatch.setattr(
        run_loop, "_ctl", lambda *argv: SimpleNamespace(
            returncode=0, stdout="Turing workspace ready: WORKSPACE\n", stderr=""
        ),
    )
    monkeypatch.setattr(run_loop, "status_of", lambda *args: "EXECUTION_READY")
    monkeypatch.setattr(run_loop, "assemble_context", lambda *args, **kwargs: ("ctx", None))
    monkeypatch.setattr(run_loop, "provider_for", lambda *args, **kwargs: provider)
    monkeypatch.setattr(run_loop, "auto_pitfall", lambda *args, **kwargs: None)
    cfg = SimpleNamespace(data={}, source_path=None)
    args = SimpleNamespace(provider=None)
    state = {
        "l7_failures": 0,
        "loopx_policy": run_loop.LoopXRetryPolicy(retry_threshold=2),
    }

    ok = run_loop.exec_turing(
        str(tmp_path), "C1", {"node": "L7", "persona": "Turing", "schema_version": "2.1"},
        cfg, args, tmp_path / "run", 1, state,
    )

    assert ok is False
    assert state["last_loopx_failure"]["failure_class"] == "EXTERNAL"


def test_native_provider_schema_uses_bound_profile_schema(tmp_path):
    binding = tmp_path / "00_Preflight" / "hypothesis_store_binding.json"
    binding.parent.mkdir(parents=True)
    binding.write_text("{}", encoding="utf-8")

    schema = run_loop._provider_output_schema(
        tmp_path,
        "L0",
        {"schema_version": "2.1", "profile_id": "v2.1-catalog-1"},
    )

    assert schema["properties"]["schema_version"]["const"] == "2.1"


def test_native_l4c_provider_schema_uses_local_handles_not_canonical_ids(tmp_path):
    binding = tmp_path / "00_Preflight" / "hypothesis_store_binding.json"
    binding.parent.mkdir(parents=True)
    binding.write_text("{}", encoding="utf-8")

    schema = run_loop._provider_output_schema(
        tmp_path,
        "L4",
        {"schema_version": "2.1", "profile_id": "v2.1-catalog-1"},
    )
    candidate = schema["properties"]["method_candidates"]["items"]
    properties = set(candidate["properties"])

    assert {
        "evidence_card_handles",
        "evidence_gap_handles",
        "method_anchor_handles",
    } <= properties
    assert not {
        "evidence_card_ids",
        "evidence_gap_ids",
        "method_anchor_ids",
    } & properties
    assert "method_anchor_handles" in candidate["required"]


def test_legacy_v21_l4c_provider_schema_is_profile_isolated(tmp_path):
    binding = tmp_path / "00_Preflight" / "hypothesis_store_binding.json"
    binding.parent.mkdir(parents=True)
    binding.write_text("{}", encoding="utf-8")

    schema = run_loop._provider_output_schema(
        tmp_path,
        "L4",
        {"schema_version": "2.1", "profile_id": "v2.1"},
    )
    properties = set(schema["properties"]["method_candidates"]["items"]["properties"])

    assert {
        "evidence_card_ids",
        "evidence_gap_ids",
        "method_anchor_ids",
    } <= properties
    assert not {
        "evidence_card_handles",
        "evidence_gap_handles",
        "method_anchor_handles",
    } & properties


def test_l05_runner_binds_and_activates_frozen_curie_result(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    candidate = "C1"
    run_id = "EPMC_TEST_RUN"
    evidence_pack = {
        "schema_version": "L05EvidencePackManifest/v1",
        "pack_id": "EP_C1_1_v1",
        "version": 1,
        "status": "FROZEN",
    }
    calls = []
    seed = {"candidate_id": candidate, "round_id": "1"}

    def fake_ctl(*argv):
        assert argv == (
            "l05-acquire-europepmc", str(project), candidate,
            "--semantic-assessor-command", "fixture {prompt_file} {output_file}",
            "--semantic-assessor-timeout", "300",
        )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "status": "FROZEN",
                "run_id": run_id,
                "evidence_pack": evidence_pack,
                "acquisition_manifest_path": "08_Audit/l05_acquisition/manifest.json",
            }),
            stderr="",
        )

    monkeypatch.setattr(run_loop, "_ctl", fake_ctl)
    monkeypatch.setattr(research_seed, "load_l1_research_seed", lambda *_: seed)
    monkeypatch.setattr(run_loop, "validate_europepmc_acquisition_result",
                        lambda _project, _candidate, result: result)
    monkeypatch.setattr(
        research_seed,
        "write_l1_native_evidence_binding",
        lambda *args: calls.append(("bind", args)) or {"evidence_run_id": run_id},
    )
    monkeypatch.setattr(
        research_seed,
        "activate_l1_native_evidence_binding",
        lambda *args: calls.append(("activate", args)) or {"acquisition_run_id": run_id},
    )
    monkeypatch.setattr(
        research_seed,
        "active_l1_native_evidence_run_id",
        lambda *_: run_id,
    )

    ok = run_loop.exec_l05(
        str(project), candidate, {"node": "L0.5", "persona": "Curie"},
        run_loop.orch.ProviderConfig({"provider": {"default": {
            "type": "command", "command": "fixture {prompt_file} {output_file}",
        }}}), SimpleNamespace(), tmp_path / "run", 1,
    )

    assert ok["terminal_status"] == "FROZEN"
    assert [item[0] for item in calls] == ["bind", "activate"]
    assert calls[0][1][0:2] == (str(project), seed)
    assert calls[0][1][2:] == (evidence_pack, run_id)


def test_l05_command_uses_configured_reproducible_queries(tmp_path):
    cfg = run_loop.orch.ProviderConfig({
        "provider": {"default": {
            "type": "command", "command": "fixture {prompt_file} {output_file}",
        }},
        "l05_acquisition": {
            "queries": [
                "bat cardiac transcriptome",
                "shrew cardiac transcriptome",
            ],
            "max_papers": 2,
            "page_size": 10,
            "timeout": 30,
        },
    })

    assert run_loop._l05_command("PROJECT", "C1", cfg) == [
        "l05-acquire-europepmc", "PROJECT", "C1",
        "--query", "bat cardiac transcriptome",
        "--query", "shrew cardiac transcriptome",
        "--max-papers", "2",
        "--page-size", "10",
        "--timeout", "30",
        "--semantic-assessor-command", "fixture {prompt_file} {output_file}",
        "--semantic-assessor-timeout", "300",
    ]


def test_l05_insufficient_outcome_stops_round_before_downstream(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    calls = []
    monkeypatch.setattr(run_loop, "_ctl", lambda *args: SimpleNamespace(
        returncode=0, stderr="", stdout=json.dumps({
            "status": "INSUFFICIENT_STOP",
            "terminal_reason": "no_admissible_replan",
            "run_id": "EMPTY",
            "acquisition_manifest_path": "08_Audit/l05_acquisition/C1/EMPTY/acquisition_manifest.json",
            "acquisition_manifest_sha256": "a" * 64,
            "evidence_pack": None,
        }),
    ))
    monkeypatch.setattr(run_loop, "validate_europepmc_acquisition_result",
                        lambda _project, _candidate, result: result)
    monkeypatch.setattr(run_loop.research_seed, "write_l1_native_evidence_binding",
                        lambda *args: calls.append("bind"))
    monkeypatch.setattr(run_loop, "next_step", lambda *_: {
        "node": "L0.5", "persona": "Curie", "terminal": False,
    })
    monkeypatch.setattr(run_loop, "_l05_command", lambda *_: ["l05-acquire-europepmc", str(project), "C1"])
    outcome = run_loop.run_round(
        str(project), "C1", SimpleNamespace(stop_policy={}), SimpleNamespace(),
        1, 1, {},
    )
    assert outcome["terminal_status"] == "L0_5_INSUFFICIENT_STOP"
    assert outcome["completed"] is False
    assert calls == []


def test_cmd_run_records_incomplete_l05_stop_without_stop_policy(tmp_path, monkeypatch):
    project = tmp_path / "project"
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "C1.md").write_text("candidate", encoding="utf-8")
    config = project / "runner.yaml"
    config.write_text("provider: fixture", encoding="utf-8")
    cfg = SimpleNamespace(mode=None, max_rounds=1, review={"enabled": True},
                          stop_policy={})
    monkeypatch.setattr(run_loop.l0_preflight, "validate_project_ready",
                        lambda *args, **kwargs: {"status": "PASS"})
    monkeypatch.setattr(run_loop, "_formal_runtime_preflight", lambda: True)
    monkeypatch.setattr(run_loop, "_ctl", lambda *args: SimpleNamespace(
        returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(run_loop.orch.ProviderConfig, "load", lambda *_: cfg)
    monkeypatch.setattr(run_loop, "restore_previous_round",
                        lambda *_: {"binding_status": "NOT_APPLICABLE"})
    from research_loop import pre_e2e_closure
    monkeypatch.setattr(pre_e2e_closure, "audit_static_closure",
                        lambda *_: {"e2e_start_allowed": True})
    monkeypatch.setattr(run_loop, "preflight_providers", lambda *_: True)
    monkeypatch.setattr(run_loop, "run_round", lambda *_, **__: {
        "terminal_status": "L0_5_INSUFFICIENT_STOP", "completed": False,
        "full_dag_completed": False, "terminal_reason": "no_admissible_replan",
        "acquisition_run_id": "EMPTY", "acquisition_manifest_path": "manifest.json",
        "acquisition_manifest_sha256": "a" * 64,
    })
    monkeypatch.setattr(run_loop, "run_review_gate",
                        lambda *_: pytest.fail("review ran after L0.5 stop"))
    monkeypatch.setattr(run_loop, "create_child",
                        lambda *_: pytest.fail("child created after L0.5 stop"))
    monkeypatch.setattr(run_loop.StopPolicy, "decide",
                        lambda *_args, **_kwargs: pytest.fail("StopPolicy ran after L0.5 stop"))
    args = SimpleNamespace(
        project_dir=str(project), cand_id="C1", knowledge_store=None,
        dry_run=False, config=str(config), provider=None, max_rounds=1,
        no_review=False, resume=False,
    )
    assert run_loop.cmd_run(args) == 0
    record = json.loads((project / "08_Run_Receipts" / "C1" / "round_01"
                         / "stop_decision.json").read_text(encoding="utf-8"))
    assert record["terminal_status"] == "L0_5_INSUFFICIENT_STOP"
    assert record["completed"] is False
    assert record["full_dag_completed"] is False
    assert record["L1"] == record["REVIEW"] == record["L10b"] == "NOT_ATTEMPTED"
    assert record["acquisition_manifest_sha256"] == "a" * 64


def test_l05_binding_failure_is_typed_error(tmp_path, monkeypatch):
    result = {
        "status": "FROZEN", "run_id": "BIND_FAIL", "evidence_pack": {"status": "FROZEN"},
    }
    monkeypatch.setattr(run_loop, "_ctl", lambda *_: SimpleNamespace(
        returncode=0, stdout=json.dumps(result), stderr=""))
    monkeypatch.setattr(run_loop, "_l05_command", lambda *_: ["l05-acquire-europepmc"])
    monkeypatch.setattr(run_loop, "validate_europepmc_acquisition_result",
                        lambda *_: result)
    monkeypatch.setattr(run_loop.research_seed, "load_l1_research_seed",
                        lambda *_: {"candidate_id": "C1", "round_id": "1"})
    monkeypatch.setattr(run_loop.research_seed, "write_l1_native_evidence_binding",
                        lambda *_: (_ for _ in ()).throw(
                            run_loop.research_seed.ResearchSeedError("injected bind failure")))
    monkeypatch.setattr(run_loop, "auto_pitfall", lambda *_args, **_kwargs: None)
    outcome = run_loop.exec_l05(
        str(tmp_path), "C1", {"node": "L0.5"}, SimpleNamespace(),
        SimpleNamespace(), tmp_path / "run", 1,
    )
    assert outcome["terminal_status"] == "ERROR"
    assert outcome["error_category"] == "BINDING_ERROR"


def test_native_l1_binding_suppresses_legacy_deep_research(tmp_path, monkeypatch):
    project = tmp_path / "project"
    native_root = project / "08_Audit" / "research_seed_bindings" / "native" / "C1"
    native_root.mkdir(parents=True)
    recall = project / "08_Audit" / "hypothesis_recall" / "C1_round_1.json"
    recall.parent.mkdir(parents=True)
    recall.write_text("{}", encoding="utf-8")
    seed = {"candidate_id": "C1", "round_id": "1"}
    called = []

    monkeypatch.setattr(research_seed, "load_l1_research_seed", lambda *_: seed)
    monkeypatch.setattr(
        research_seed,
        "active_l1_native_evidence_run_id",
        lambda *_: "EPMC_TEST_RUN",
    )
    monkeypatch.setattr(
        research_seed,
        "load_l1_native_evidence_binding",
        lambda *_: {"acquisition_run_id": "EPMC_TEST_RUN"},
    )
    monkeypatch.setattr(
        run_loop,
        "_ctl",
        lambda *argv: called.append(argv) or (_ for _ in ()).throw(
            AssertionError("legacy Deep Research must not run for native L1")
        ),
    )

    assert run_loop.ensure_pre_research(
        str(project), "C1", "L1", SimpleNamespace(data={}),
        SimpleNamespace(), tmp_path / "run",
    ) is True
    assert called == []


def test_l7_pre_research_uses_canonical_provider_text_capability(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    target = project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    calls = []

    class TextProvider:
        def run_text(self, prompt, run_dir, tag, timeout=None):
            calls.append((prompt, Path(run_dir), tag, timeout))
            return "# located code\n"

    monkeypatch.setattr(run_loop, "_bound_profile_id", lambda *_a: "v2.1-catalog-1")
    monkeypatch.setattr(
        run_loop,
        "_ctl",
        lambda *argv: SimpleNamespace(returncode=0, stdout="search prompt", stderr=""),
    )
    monkeypatch.setattr(run_loop, "provider_for", lambda *_a: TextProvider())

    assert run_loop.ensure_pre_research(
        str(project), "C1", "L7", SimpleNamespace(),
        SimpleNamespace(provider=None), tmp_path / "run",
    ) is True
    assert target.read_text(encoding="utf-8") == "# located code\n"
    assert calls == [("search prompt", tmp_path / "run", "prefetch_L7", None)]


def test_l7_pre_research_missing_text_provider_fails_closed(tmp_path, monkeypatch):
    project = tmp_path / "project"
    monkeypatch.setattr(run_loop, "_bound_profile_id", lambda *_a: "v2.1-catalog-1")
    monkeypatch.setattr(
        run_loop,
        "_ctl",
        lambda *argv: SimpleNamespace(returncode=0, stdout="search prompt", stderr=""),
    )
    monkeypatch.setattr(run_loop, "provider_for", lambda *_a: object())

    assert run_loop.ensure_pre_research(
        str(project), "C1", "L7", SimpleNamespace(),
        SimpleNamespace(provider=None), tmp_path / "run",
    ) is False
    assert not (
        project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    ).exists()


def test_existing_l7_pre_research_continues_without_provider_dispatch(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    target = project / "02_Agent_Notes" / "_pre_research" / "L7_research.md"
    target.parent.mkdir(parents=True)
    target.write_text("existing located code", encoding="utf-8")
    monkeypatch.setattr(run_loop, "_bound_profile_id", lambda *_a: "v2.1-catalog-1")
    monkeypatch.setattr(
        run_loop,
        "provider_for",
        lambda *_a: pytest.fail("existing pre-research must not dispatch provider"),
    )

    assert run_loop.ensure_pre_research(
        str(project), "C1", "L7", SimpleNamespace(),
        SimpleNamespace(provider=None), tmp_path / "run",
    ) is True


def test_malformed_review_response_is_a_blocker_not_a_skipped_review(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "FINAL_REPORT.md").write_text("Reviewable report\n", encoding="utf-8")
    monkeypatch.setattr(run_loop, "next_step", lambda *_args: {
        "profile_id": PROFILE_V21_CATALOG_1,
    })
    monkeypatch.setattr(run_loop, "load_delta", lambda *_args: None)
    monkeypatch.setattr(run_loop, "provider_for", lambda *_args: SimpleNamespace(
        run_agent=lambda *_a, **_kw: {"unexpected": "no review schema fields"}
    ))

    with pytest.raises((ValueError, RuntimeError), match="(?i)(review|schema|contract)"):
        run_loop.run_review_gate(
            str(project), "C1", SimpleNamespace(), SimpleNamespace(), tmp_path / "run"
        )


def test_optional_review_disabled_never_starts_review_provider(tmp_path, monkeypatch):
    project = tmp_path / "project"
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "C1.md").write_text("candidate\n", encoding="utf-8")
    config = project / "runner.yaml"
    config.write_text("provider: fixture\n", encoding="utf-8")
    cfg = SimpleNamespace(
        mode=None, max_rounds=1, review={"enabled": False}, stop_policy={},
        source_path=str(config),
    )
    monkeypatch.setattr(run_loop.l0_preflight, "validate_project_ready",
                        lambda *_args, **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(run_loop, "_formal_runtime_preflight", lambda: True)
    monkeypatch.setattr(run_loop, "_ctl", lambda *_args: SimpleNamespace(
        returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(run_loop.orch.ProviderConfig, "load", lambda *_args: cfg)
    monkeypatch.setattr(run_loop, "restore_previous_round",
                        lambda *_args: {"binding_status": "NOT_APPLICABLE"})
    from research_loop import pre_e2e_closure
    monkeypatch.setattr(pre_e2e_closure, "audit_static_closure",
                        lambda *_args: {"e2e_start_allowed": True})
    monkeypatch.setattr(run_loop, "preflight_providers", lambda *_args: True)
    monkeypatch.setattr(run_loop, "run_round", lambda *_args, **_kwargs: "completed")
    monkeypatch.setattr(run_loop, "status_of", lambda *_args: "KEEP")
    monkeypatch.setattr(run_loop, "load_delta", lambda *_args: None)
    monkeypatch.setattr(run_loop, "evidence_sig", lambda *_args: "fixture")
    monkeypatch.setattr(run_loop.StopPolicy, "decide", lambda *_args, **_kwargs: {
        "stop": True, "reason": "fixture terminal",
    })
    monkeypatch.setattr(
        run_loop, "run_review_gate",
        lambda *_args: pytest.fail("disabled optional REVIEW invoked provider path"),
    )
    args = SimpleNamespace(
        project_dir=str(project), cand_id="C1", knowledge_store=None,
        dry_run=False, config=str(config), provider=None, max_rounds=1,
        no_review=False, resume=False,
    )

    assert run_loop.cmd_run(args) == 0


@pytest.mark.parametrize("node", ["L4", "L8.5", "L7"])
def test_agent_native_pre_research_helper_fails_closed_without_host_cursor(
    node, tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "02_Agent_Notes" / "_pre_research" / f"{node}_research.md"
    monkeypatch.setattr(run_loop, "_bound_profile_id",
                        lambda *_args: PROFILE_V21_CATALOG_1)
    commands = []

    def controlled_command(*argv):
        commands.append(argv)
        if argv[0] == "audit-literature-evidence":
            return SimpleNamespace(returncode=1, stdout="", stderr="not yet present")
        if argv[0] == "pre-research":
            return SimpleNamespace(returncode=0, stdout="authorized search prompt", stderr="")
        pytest.fail(f"NESTED_COGNITION_FORBIDDEN: {argv[0]}")

    monkeypatch.setattr(run_loop, "_ctl", controlled_command)

    class Provider:
        def run_text(self, *_args, **_kwargs):
            pytest.fail("HOST_PROVIDER_FORBIDDEN: agent-native pre-research called run_text")

    monkeypatch.setattr(run_loop, "provider_for", lambda *_args: Provider())
    args = SimpleNamespace(mode="agent_native", provider=None, evidence_run_ids={})
    result = run_loop.ensure_pre_research(
        str(project), "C1", node, SimpleNamespace(), args, tmp_path / "run"
    )

    assert result is False, (
        f"AGENT_NATIVE_FALLBACK: ensure_pre_research must fail closed and direct "
        f"agent-native callers to prepare_host_step for {node}"
    )
    assert not target.exists()
    assert all(command[0] != "deep-research-run" for command in commands)




def test_runner_forwards_explicit_context_budget_to_engine(monkeypatch):
    seen = {}

    class FakeEngine:
        def assemble_context(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            return "context", "manifest"

    monkeypatch.setattr(run_loop, "ENGINE", FakeEngine())
    assert run_loop.assemble_context(
        "PROJECT", "C1", "L1", context_token_budget=24000
    ) == ("context", "manifest")
    assert seen["kwargs"]["context_token_budget"] == 24000


def test_runner_context_budget_reads_project_config():
    assert run_loop._context_token_budget(
        SimpleNamespace(data={"context_token_budget": 24000})
    ) == 24000


def test_native_l1_recall_is_created_before_context_assembly(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    seed = {
        "candidate_id": "C1",
        "round_id": "1",
        "scientific_question": "Which hypotheses are already known?",
        "hypothesis_seed": "A cardiac expression hypothesis.",
    }
    store = tmp_path / "hypotheses.sqlite"
    calls = []

    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    monkeypatch.setattr(research_seed, "load_l1_research_seed", lambda *_: seed)

    def fake_ctl(*argv):
        calls.append(argv)
        path = project / "08_Audit" / "hypothesis_recall" / "C1_round_1.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(run_loop, "_ctl", fake_ctl)

    assert run_loop._ensure_native_l1_recall(str(project), "C1") is True
    assert calls == [(
        "hypothesis-recall", str(project), "C1", "--round-id", "1",
        "--query", "Which hypotheses are already known? A cardiac expression hypothesis.",
        "--knowledge-store", str(store),
    )]


def test_v21_advance_uses_delta_derived_triage_contract(monkeypatch):
    calls = []

    monkeypatch.setattr(
        run_loop,
        "load_delta",
        lambda *_: {"schema_version": "2.1", "triage": []},
    )
    monkeypatch.setattr(
        run_loop,
        "_ctl",
        lambda *argv: calls.append(argv) or SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
    )

    run_loop.advance(
        "PROJECT", "C1", {"node": "L3", "advance_command": "triage-idea"}
    )

    assert calls == [("triage-idea", "PROJECT", "C1")]


def test_advance_raises_on_controller_failure(monkeypatch):
    monkeypatch.setattr(
        run_loop,
        "_ctl",
        lambda *argv: SimpleNamespace(
            returncode=1, stdout="", stderr="controller rejected"
        ),
    )

    with pytest.raises(RuntimeError, match="decision failed"):
        run_loop.advance(
            "PROJECT", "C1", {
                "node": "L4",
                "advance_command": "decision",
                "advance_status": "METHOD_PROPOSED",
            }
        )


def test_run_round_recovers_committed_v21_delta_before_provider(monkeypatch, tmp_path):
    step = {
        "node": "L3",
        "persona": "Oppenheimer",
        "advance_command": "triage-idea",
        "profile_id": "v2.1-catalog-1",
        "schema_version": "2.1",
    }
    steps = iter([step, {"terminal": True, "status": "IDEA_SELECTED"}])
    advanced = []

    monkeypatch.setattr(run_loop, "next_step", lambda *_: next(steps))
    monkeypatch.setattr(run_loop, "status_of", lambda *_: "IDEA_PROPOSED")
    monkeypatch.setattr(
        run_loop,
        "load_delta",
        lambda *_: {"schema_version": "2.1", "triage": []},
    )
    monkeypatch.setattr(run_loop, "advance", lambda *args: advanced.append(args))
    monkeypatch.setattr(
        run_loop,
        "ensure_pre_research",
        lambda *args, **kwargs: pytest.fail("recovery must skip pre-research"),
    )
    monkeypatch.setattr(
        run_loop,
        "exec_cognitive",
        lambda *args, **kwargs: pytest.fail("recovery must skip provider dispatch"),
    )

    cfg = SimpleNamespace(stop_policy={"max_l7_failures": 1, "max_node_failures": 1})
    args = SimpleNamespace(stop_after_node=None)
    exec_state = {"l7_failures": 0, "node_failures": {}}

    outcome = run_loop.run_round(
        str(tmp_path), "C1", cfg, args, 1, 1, exec_state
    )

    assert outcome == "terminal"
    assert len(advanced) == 1
