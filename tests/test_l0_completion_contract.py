import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_loop
from research_loop import l0_contract, l0_state
from research_loop.commands import continuation, lifecycle, reporting
from research_loop.compatibility import PROFILE_V20, get_profile
from research_loop.l0_preflight import ProbeResult, write_preflight_receipt
from research_loop.l0_state import L0StateError, build_round_manifest


class _Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _candidate(project: Path, cand: str = "C1", *, round_id="1", extra="") -> Path:
    path = project / "01_Candidates" / f"{cand}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"candidate_id: {cand}\n"
        f"round_id: {round_id}\n"
        "current_status: NEW\n"
        f"{extra}"
        "---\n",
        encoding="utf-8",
    )
    return path


def _project_with_source(tmp_path: Path, cand="C1") -> Path:
    project = tmp_path / "P"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: P\n---\n", encoding="utf-8"
    )
    _candidate(project, cand)
    source = project / "raw.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    contract = l0_contract.build_initial_contract(
        cand,
        "1",
        "Q?",
        l0_contract.build_source_input(
            input_type="files", files=["raw.csv"], description="raw", fmt="csv"
        ),
        "H",
    )
    l0_contract.write_contract(project, cand, contract)
    return project


def test_preflight_receipt_distinguishes_blocking_from_readiness_only(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    results = [
        ProbeResult(
            "research.academic_research", "PASS", "OK", "ready",
            "L1/L4/L8.5 research reasoning", enforcement="blocking",
        ),
        ProbeResult(
            "research.pubmed_mcp", "FAIL", "L0_RESEARCH_PUBMED_MCP_START_FAILED",
            "not wired yet", "future literature transport",
            enforcement="readiness_only",
        ),
        ProbeResult(
            "research.zotero", "FAIL", "L0_RESEARCH_ZOTERO_UNREACHABLE",
            "not wired yet", "future selected-literature management",
            enforcement="readiness_only",
        ),
    ]

    receipt = write_preflight_receipt(project, results)
    payload = json.loads(receipt.read_text(encoding="utf-8"))

    assert payload["overall_status"] == "PASS_WITH_WARNINGS"
    assert payload["results"][1]["enforcement"] == "readiness_only"
    assert payload["results"][2]["enforcement"] == "readiness_only"


def test_blocking_preflight_failure_still_fails_overall_receipt(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    results = [
        ProbeResult(
            "state.obsidian", "FAIL", "L0_STATE_OBSIDIAN_INVALID_VAULT",
            "vault missing", "L10c projection", enforcement="blocking",
        )
    ]

    receipt = write_preflight_receipt(project, results)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "FAIL"


def test_check_deps_uses_single_probe_authority_without_second_ars_check(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "P"
    project.mkdir()
    advisory = {
        "kind": "probe",
        "name": "research.pubmed_mcp",
        "label": "research.pubmed_mcp",
        "needed_for": "future literature transport",
        "present": False,
        "error_code": "L0_RESEARCH_PUBMED_MCP_START_FAILED",
        "detail": "not ready",
        "enforcement": "readiness_only",
    }
    monkeypatch.setattr(
        lifecycle,
        "_check_dependencies",
        lambda _project: ([], [], [advisory]),
    )
    monkeypatch.setattr(
        lifecycle.deep_research,
        "load_runtime_spec",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("lifecycle must not run a second ARS readiness check")
        ),
    )

    rc = lifecycle.cmd_check_deps(SimpleNamespace(project_dir=str(project)))

    captured = capsys.readouterr()
    assert rc == 0
    assert "WARN" in captured.err
    assert "research.pubmed_mcp" in captured.err


def test_round_manifest_promotes_l7_result_and_registers_delta_once(tmp_path, monkeypatch):
    project = _project_with_source(tmp_path)
    cand = "C1"
    output = project / "04_Analysis_Outputs" / "result.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("value\n42\n", encoding="utf-8")
    exec_dir = output.parent / "_exec_manifest"
    exec_dir.mkdir()
    exec_manifest = exec_dir / f"{cand}_L7.json"
    exec_manifest.write_text(
        json.dumps({
            "candidate_id": cand,
            "scripts": [{"name": "analysis", "output_files": [str(output)]}],
        }),
        encoding="utf-8",
    )
    delta_path = project / "02_Agent_Notes" / "Turing" / f"{cand}_L7_turing_delta.v2.json"
    delta_path.parent.mkdir(parents=True, exist_ok=True)
    delta_path.write_text(
        json.dumps({
            "results": [{
                "result_key": "R1",
                "summary": "final result",
                "artifact_refs": [{"path": str(output)}],
            }],
            "scripts_run": [],
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        l0_state,
        "_delta_for_candidate",
        lambda _project, key, _cand: delta_path if key == "L7_turing" else None,
        raising=False,
    )
    monkeypatch.setattr(
        l0_state,
        "_profile_delta_keys",
        lambda _project: ["L7_turing"],
        raising=False,
    )

    manifest = build_round_manifest(project, cand)
    result_entries = [a for a in manifest["artifacts"] if a["path"].endswith("result.csv")]
    delta_entries = [a for a in manifest["artifacts"] if a["path"].endswith("L7_turing_delta.v2.json")]

    assert len(result_entries) == 1
    assert result_entries[0]["class"] == "result"
    assert result_entries[0]["producer_node"] == "L7"
    assert result_entries[0]["producer_receipt"].endswith(
        f"04_Analysis_Outputs/_exec_manifest/{cand}_L7.json"
    )
    assert len(delta_entries) == 1
    assert delta_entries[0]["class"] == "audit"


def test_emit_loop_memory_never_creates_missing_round_manifest(tmp_path, monkeypatch):
    project = tmp_path / "P"
    project.mkdir()
    _candidate(project, "C1")
    monkeypatch.setattr(
        continuation,
        "_build_loop_memory",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("semantic loop memory must not be built before manifest verification")
        ),
    )

    rc = continuation.cmd_emit_loop_memory(
        SimpleNamespace(project_dir=str(project), cand_id="C1", knowledge_store=None)
    )

    assert rc == 2
    assert not (project / "08_Audit" / "round_manifests" / "C1_round_1.json").exists()
    assert not (project / "08_Audit" / "loop_memory" / "C1_next_loop_memory.json").exists()


def test_aggregate_report_sync_failure_prevents_manifest_freeze(tmp_path, monkeypatch):
    project = tmp_path / "P"
    project.mkdir()
    _candidate(project, "C1")
    monkeypatch.setattr(reporting, "_profile_for_project", lambda _p: get_profile(PROFILE_V20))
    monkeypatch.setattr(reporting, "_delta_for_candidate", lambda *_a, **_k: None)
    calls = []
    monkeypatch.setattr(
        reporting,
        "cmd_obsidian_sync",
        lambda _args: calls.append("sync") or 2,
    )
    monkeypatch.setattr(
        reporting,
        "write_round_manifest",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("manifest must not freeze after failed Obsidian sync")
        ),
    )

    rc = reporting.cmd_aggregate_report(
        SimpleNamespace(project_dir=str(project), cand_id="C1", force=False)
    )

    assert rc == 2
    assert calls == ["sync"]


def test_aggregate_report_syncs_before_manifest_freeze(tmp_path, monkeypatch):
    project = tmp_path / "P"
    project.mkdir()
    _candidate(project, "C1")
    monkeypatch.setattr(reporting, "_profile_for_project", lambda _p: get_profile(PROFILE_V20))
    monkeypatch.setattr(reporting, "_delta_for_candidate", lambda *_a, **_k: None)
    calls = []
    monkeypatch.setattr(
        reporting,
        "cmd_obsidian_sync",
        lambda _args: calls.append("sync") or 0,
    )
    fake_manifest = project / "08_Audit" / "round_manifests" / "C1_round_1.json"

    def freeze(*_a, **_k):
        calls.append("manifest")
        return fake_manifest, "abc123"

    monkeypatch.setattr(reporting, "write_round_manifest", freeze)

    rc = reporting.cmd_aggregate_report(
        SimpleNamespace(project_dir=str(project), cand_id="C1", force=False)
    )

    assert rc == 0
    assert calls == ["sync", "manifest"]


def test_run_round_propagates_l10c_finalization_failure_without_second_sync(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        run_loop,
        "next_step",
        lambda *_a, **_k: {"node": "L10c", "persona": "Linnaeus"},
    )
    monkeypatch.setattr(run_loop, "ensure_pre_research", lambda *_a, **_k: True)
    calls = []
    monkeypatch.setattr(
        run_loop,
        "_ctl",
        lambda *args: calls.append(args) or _Result(2, "", "obsidian failed"),
    )
    monkeypatch.setattr(
        run_loop.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("run_loop must not own a second Obsidian sync path")
        ),
    )
    cfg = SimpleNamespace(stop_policy={"max_l7_failures": 2, "max_node_failures": 2})
    args = SimpleNamespace(stop_after_node=None)

    outcome = run_loop.run_round(
        str(tmp_path), "C1", cfg, args, 1, 1,
        {"l7_failures": 0, "node_failures": {}},
    )

    assert outcome == "node_failed:L10c"
    assert calls == [("aggregate-report", str(tmp_path), "C1")]


def test_cmd_run_restore_failure_happens_before_provider_preflight(tmp_path, monkeypatch):
    project = tmp_path / "P"
    project.mkdir()
    _candidate(
        project,
        "C1",
        round_id="2",
        extra="from_memory: true\nround_type: continuation\n",
    )
    config = project / "runner.yaml"
    config.write_text("x", encoding="utf-8")
    monkeypatch.setattr(run_loop, "_ctl", lambda *_a, **_k: _Result(0, "", ""))
    monkeypatch.setattr(
        run_loop.orch.ProviderConfig,
        "load",
        lambda _path: SimpleNamespace(
            max_rounds=1, review={"enabled": False}, stop_policy={},
            mode="main_agent", default={},
        ),
    )
    monkeypatch.setattr(
        run_loop,
        "restore_previous_round",
        lambda *_a, **_k: (_ for _ in ()).throw(
            L0StateError("L0_RESTORE_MANIFEST_MISSING", "missing prior manifest")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        run_loop,
        "preflight_providers",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("provider readiness must not run after restore failure")
        ),
    )
    args = SimpleNamespace(
        project_dir=str(project), cand_id="C1", knowledge_store=None,
        config=str(config), max_rounds=None, dry_run=False, no_review=True,
        provider=None, resume=True, stop_after_node=None,
    )

    rc = run_loop.cmd_run(args)

    assert rc == 3
