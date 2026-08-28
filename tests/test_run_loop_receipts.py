import hashlib
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

import run_loop
from research_loop.api import EngineAPI
from research_loop.commands import ledger as ledger_commands
from research_loop import research_seed
from research_loop import l4_evidence_bundle as l4_bundle
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


def test_l4_handle_binding_creates_bound_artifact_and_explicit_provenance_edge(
    tmp_path, monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    raw = tmp_path / "L4_Fisher_delta.json"
    raw_data = {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": "RUN1",
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
    manifest = tmp_path / "context_manifest.json"
    manifest.write_text(json.dumps({
        "pre_research": {"evidence_artifacts": {"run_id": "RUN1"}},
    }), encoding="utf-8")
    evidence = {
        "run_id": "RUN1",
        "evidence_bundle_schema": l4_bundle.EVIDENCE_BUNDLE_SCHEMA,
        "evidence_cards": [{
            "status": "accepted", "evidence_card_id": "CARD-CANONICAL",
            "anchor_id": "ANCHOR-CANONICAL", "method_id": "M1",
        }],
        "evidence_gaps": [],
    }
    monkeypatch.setattr(ledger_commands.deep_research, "_artifact",
                        lambda *args, **kwargs: evidence)
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
    assert provenance["raw_provider_delta_sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()


def test_emit_boundary_resolves_l4_handles_without_runner_owned_bound_copy(
    tmp_path, monkeypatch,
):
    raw_data = {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": "RUN1",
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
    manifest = tmp_path / "context_manifest.json"
    manifest.write_text(json.dumps({
        "pre_research": {"evidence_artifacts": {"run_id": "RUN1"}},
    }), encoding="utf-8")
    evidence = {
        "run_id": "RUN1",
        "evidence_bundle_schema": l4_bundle.EVIDENCE_BUNDLE_SCHEMA,
        "evidence_cards": [{
            "status": "accepted", "evidence_card_id": "CARD-CANONICAL",
            "anchor_id": "ANCHOR-CANONICAL", "method_id": "M1",
        }],
        "evidence_gaps": [],
    }
    monkeypatch.setattr(ledger_commands.deep_research, "_artifact",
                        lambda *args, **kwargs: evidence)
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
        assert argv == ("l05-acquire-europepmc", str(project), candidate)
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
        SimpleNamespace(), SimpleNamespace(), tmp_path / "run", 1,
    )

    assert ok is True
    assert [item[0] for item in calls] == ["bind", "activate"]
    assert calls[0][1][0:2] == (str(project), seed)
    assert calls[0][1][2:] == (evidence_pack, run_id)


def test_l05_command_uses_configured_reproducible_queries(tmp_path):
    cfg = SimpleNamespace(data={
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
    ]


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
