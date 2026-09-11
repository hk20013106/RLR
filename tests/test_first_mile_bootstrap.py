"""TDD coverage for the v0.9.7 first-mile bootstrap contract."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pitfall_ledger as pl
import yaml

from research_loop import cli, gates, l0_preflight
from research_loop.commands import lifecycle
from research_loop.l0_data import current_round_data_binding_path


def _new_project(tmp_path, monkeypatch):
    store = tmp_path / "hypotheses.sqlite"
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    project = tmp_path / "project"
    assert cli.main([
        "new-project", str(project), "first-mile test",
        "--knowledge-store", str(store), "--profile", "v2.1-catalog-1",
    ]) == 0
    return project


def _passing_probe_results(project, **_kwargs):
    return [
        l0_preflight.ProbeResult(
            "core.python_packages", "PASS", "OK", "packages ready", "RLR runtime"
        ),
        l0_preflight.ProbeResult(
            "core.filesystem", "PASS", "OK", "project writable", "project artifacts"
        ),
        l0_preflight.ProbeResult(
            "research.academic_research", "PASS", "OK", "ARS ready", "L1/L4/L8.5"
        ),
        l0_preflight.ProbeResult(
            "research.pubmed_mcp", "FAIL", "ADVISORY", "not wired", "future transport",
            enforcement=l0_preflight.ENFORCEMENT_READINESS_ONLY,
        ),
        l0_preflight.ProbeResult(
            "research.zotero", "FAIL", "ADVISORY", "not wired", "future PDF manager",
            enforcement=l0_preflight.ENFORCEMENT_READINESS_ONLY,
        ),
        l0_preflight.ProbeResult(
            "state.hypothesis_ledger", "PASS", "OK", "binding valid", "ledger"
        ),
        l0_preflight.ProbeResult(
            "state.evidence_store", "PASS", "OK", "stores writable", "evidence"
        ),
        l0_preflight.ProbeResult(
            "state.obsidian", "PASS", "OK", "vault writable", "projection"
        ),
    ]


def _preflight(project, monkeypatch, *, backend="codex", probes=True):
    if probes:
        monkeypatch.setattr(
            l0_preflight, "run_preflight_probes", _passing_probe_results
        )
    return cli.main(["preflight", str(project), "--backend", backend])


def _new_candidate(project):
    return cli.main([
        "new-candidate", str(project),
        "--title", "candidate",
        "--question", "Which bootstrap contract is authoritative?",
        "--claim", "The project-ready receipt binds the first-mile runtime.",
        "--input", "inline source",
    ])


def _candidate_id(project):
    return next((project / "01_Candidates").glob("C*.md")).stem


def _normalize_args(project, request, data):
    return [
        "normalize-l0-input", "--project", str(project), "--input", str(request),
        "--data", str(data),
    ]


def test_fresh_project_without_backend_has_no_project_ready(monkeypatch, tmp_path):
    project = _new_project(tmp_path, monkeypatch)
    rc = cli.main(["preflight", str(project)])

    assert rc != 0
    assert not (project / "00_Preflight" / "deep_research_runtime.json").exists()
    assert not (project / "00_Preflight" / "preflight_receipt.json").exists()


def test_explicit_codex_bootstrap_materializes_project_ready(monkeypatch, tmp_path):
    project = _new_project(tmp_path, monkeypatch)
    rc = _preflight(project, monkeypatch)

    assert rc == 0
    runtime = project / "00_Preflight" / "deep_research_runtime.json"
    receipt = project / "00_Preflight" / "preflight_receipt.json"
    assert runtime.is_file()
    assert receipt.is_file()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "L0PreflightReceipt/v2"
    assert payload["readiness"]["status"] == "PASS"
    assert payload["readiness"]["code"] == "PROJECT_READY"
    assert payload["backend"]["name"] == "codex"
    assert payload["backend"]["declaration_source"] == "--backend"
    assert payload["runtime_config"]["sha256"] == hashlib.sha256(
        runtime.read_bytes()
    ).hexdigest()
    assert l0_preflight.validate_project_ready(project)["status"] == "PASS"


def test_candidate_before_readiness_is_rejected_without_artifacts(monkeypatch, tmp_path, capsys):
    project = _new_project(tmp_path, monkeypatch)

    rc = _new_candidate(project)

    captured = capsys.readouterr()
    assert rc != 0
    assert "PROJECT_NOT_READY" in captured.err
    assert not list((project / "01_Candidates").glob("C*.md"))
    assert not list((project / "01_Candidates").glob("*.l0_input.yaml"))


def test_normalize_before_readiness_is_rejected_without_candidate(monkeypatch, tmp_path, capsys):
    project = _new_project(tmp_path, monkeypatch)
    request = tmp_path / "request.md"
    request.write_text(
        "Scientific question: Which bootstrap contract is authoritative?\n"
        "Current hypothesis: The receipt binds the runtime.\n",
        encoding="utf-8",
    )
    data = tmp_path / "data.tsv"
    data.write_text("sample\tvalue\nA\t1\n", encoding="utf-8")

    rc = cli.main(_normalize_args(project, request, data))

    captured = capsys.readouterr()
    assert rc != 0
    assert "PROJECT_NOT_READY" in captured.err
    assert not list((project / "01_Candidates").glob("C*.md"))
    assert not list((project / "01_Candidates").glob("*.l0_input.yaml"))


def test_candidate_pins_exact_project_ready_receipt_bytes(monkeypatch, tmp_path):
    project = _new_project(tmp_path, monkeypatch)
    assert _preflight(project, monkeypatch) == 0
    receipt = project / "00_Preflight" / "preflight_receipt.json"
    expected = hashlib.sha256(receipt.read_bytes()).hexdigest()

    assert _new_candidate(project) == 0
    candidate = project / "01_Candidates" / f"{_candidate_id(project)}.md"
    frontmatter = yaml.safe_load(candidate.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["project_ready_receipt_sha256"] == expected
    assert frontmatter["project_ready_receipt_path"] == "00_Preflight/preflight_receipt.json"


def test_receipt_tampering_blocks_l0_before_current_round_binding(monkeypatch, tmp_path):
    project = _new_project(tmp_path, monkeypatch)
    assert _preflight(project, monkeypatch) == 0
    assert _new_candidate(project) == 0
    candidate_id = _candidate_id(project)
    receipt = project / "00_Preflight" / "preflight_receipt.json"
    receipt.write_bytes(receipt.read_bytes() + b"tampered\n")

    ok, reason = gates._audit_l0_contract(project, candidate_id)

    assert not ok
    assert "PROJECT_NOT_READY" in reason
    assert not current_round_data_binding_path(project, candidate_id).exists()


def test_runtime_config_tampering_blocks_l0_admission(monkeypatch, tmp_path):
    project = _new_project(tmp_path, monkeypatch)
    assert _preflight(project, monkeypatch) == 0
    assert _new_candidate(project) == 0
    candidate_id = _candidate_id(project)
    runtime = project / "00_Preflight" / "deep_research_runtime.json"
    runtime.write_bytes(runtime.read_bytes() + b"tampered\n")

    ok, reason = gates._audit_l0_contract(project, candidate_id)

    assert not ok
    assert "runtime config" in reason.lower()
    assert not current_round_data_binding_path(project, candidate_id).exists()


def test_backend_rebind_is_rejected_after_codex_project_ready(monkeypatch, tmp_path, capsys):
    project = _new_project(tmp_path, monkeypatch)
    assert _preflight(project, monkeypatch) == 0
    receipt = project / "00_Preflight" / "preflight_receipt.json"
    before = receipt.read_bytes()

    rc = _preflight(project, monkeypatch, backend="claude")

    captured = capsys.readouterr()
    assert rc != 0
    assert "backend" in captured.err.lower()
    assert receipt.read_bytes() == before


def test_preflight_writes_receipt_only_after_hard_stop_evaluation(
    monkeypatch, tmp_path
):
    project = _new_project(tmp_path, monkeypatch)
    monkeypatch.setattr(l0_preflight, "run_preflight_probes", _passing_probe_results)
    events = []
    real_writer = l0_preflight.write_preflight_receipt

    def record_writer(*args, **kwargs):
        events.append("receipt")
        return real_writer(*args, **kwargs)

    monkeypatch.setattr(l0_preflight, "write_preflight_receipt", record_writer)
    monkeypatch.setattr(
        lifecycle.pl,
        "hard_stop_check",
        lambda *_args, **_kwargs: (events.append("hard_stop") or (False, [{"id": "P1"}])),
    )

    rc = _preflight(project, monkeypatch)

    assert rc != 0
    assert events.index("hard_stop") < events.index("receipt")
    payload = json.loads(
        (project / "00_Preflight" / "preflight_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["readiness"]["status"] == "FAIL"
    assert payload["readiness"]["code"] != "PROJECT_READY"


def test_normalize_run_l0_points_to_existing_canonical_runner(monkeypatch, tmp_path):
    project = _new_project(tmp_path, monkeypatch)
    request = tmp_path / "request.md"
    request.write_text(
        "Scientific question: Q?\nCurrent hypothesis: H.\n", encoding="utf-8"
    )
    data = tmp_path / "data.tsv"
    data.write_text("x\n", encoding="utf-8")
    captured = {}

    def fake_run(command):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    # This test intentionally exercises the existing command builder only after
    # readiness is satisfied; it must name the real production runner file.
    assert _preflight(project, monkeypatch) == 0
    rc = cli.main(_normalize_args(project, request, data) + ["--run-l0"])

    assert rc == 0
    runner = Path(captured["command"][5])
    assert runner.is_file()
    assert runner.resolve() == (Path(__file__).resolve().parents[1] / "src" / "run_loop.py").resolve()
