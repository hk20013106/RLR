"""Execution tests proving CurrentRoundDataBinding is the sole scientific-data authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from research_loop import l0_contract
from research_loop.commands import execution
from research_loop.gates import _audit_l0_contract
from research_loop.hypothesis_ledger import binding_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project(tmp_path: Path, cand_id="C1", status="NEEDS_EXECUTION") -> tuple[Path, Path]:
    project = tmp_path / "P"
    (project / "00_Preflight").mkdir(parents=True)
    (project / "01_Candidates").mkdir(parents=True)
    binding_path(project).write_text(
        json.dumps({"project_id": "P1", "profile_id": "v2.1-native"}),
        encoding="utf-8",
    )
    data = project / "raw.csv"
    data.write_bytes(b"x\n1\n")
    source = l0_contract.build_source_input(
        input_type="files", files=[str(data)], location=str(project),
        description="authorized round data", fmt="csv")
    source["file_manifest"] = [{
        "role": "raw", "path": str(data), "bytes": data.stat().st_size,
        "sha256": _sha(data),
    }]
    contract = l0_contract.build_initial_contract(cand_id, "1", "Q?", source, "H")
    contract["schema_version"] = "1.1"
    raw = l0_contract.serialize_contract(contract)
    (project / "01_Candidates" / f"{cand_id}.l0_input.yaml").write_bytes(raw)
    (project / "01_Candidates" / f"{cand_id}.md").write_text(
        "---\n"
        f"candidate_id: {cand_id}\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"current_status: {status}\n"
        f"input_contract_path: 01_Candidates/{cand_id}.l0_input.yaml\n"
        f"input_contract_hash: {hashlib.sha256(raw).hexdigest()}\n"
        "input_alias: legacy\n"
        "---\n",
        encoding="utf-8",
    )
    ok, reason = _audit_l0_contract(project, cand_id)
    assert ok, reason
    return project, data


def test_workspace_stages_binding_data_not_extra_legacy_manifest(tmp_path, monkeypatch):
    project, authorized = _project(tmp_path)
    extra = project / "extra.csv"
    extra.write_bytes(b"secret\n")
    (project / "00_Preflight" / "input_manifest.md").write_text(
        "| Alias | Root | Key files |\n|---|---|---|\n"
        f"| legacy | {project} | raw.csv; extra.csv |\n",
        encoding="utf-8",
    )

    l0_delta = project / "l0.json"
    l6_delta = project / "l6.json"
    l0_delta.write_text("{}", encoding="utf-8")
    l6_delta.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(execution, "PREFLIGHT_FILES", [])
    monkeypatch.setattr(
        execution, "_delta_for_candidate",
        lambda _project, key, _cand: l0_delta if key == "L0_linnaeus" else l6_delta,
    )
    monkeypatch.setattr(execution, "_approved_execution_scripts", lambda *_: ([], []))

    rc = execution.cmd_prepare_turing_workspace(SimpleNamespace(
        project_dir=str(project), cand_id="C1", clean=False, file=[]))

    assert rc == 0
    ws = next(project.glob("_turing_workspace_C1_*"))
    manifest = json.loads((ws / "WORKSPACE_MANIFEST.json").read_text(encoding="utf-8"))
    originals = {Path(item["original_path"]).resolve() for item in manifest["staged_files"]}
    assert authorized.resolve() in originals
    assert extra.resolve() not in originals


def test_execution_gate_does_not_require_legacy_input_manifest(tmp_path, monkeypatch):
    project, _authorized = _project(tmp_path, status="METHOD_APPROVED")
    (project / "00_Preflight" / "skill_use_plan.md").write_text("# skills\n", encoding="utf-8")
    legacy = project / "00_Preflight" / "input_manifest.md"
    assert not legacy.exists()
    monkeypatch.setattr(execution, "_approved_execution_scripts", lambda *_: ([], []))
    monkeypatch.setattr(execution, "_append_decision", lambda *args, **kwargs: None)
    monkeypatch.setattr(execution, "_set_status", lambda *args, **kwargs: None)

    rc = execution.cmd_execution_gate(SimpleNamespace(project_dir=str(project), cand_id="C1"))

    assert rc == 0


def test_execution_gate_rejects_unresolvable_approved_script(
    tmp_path, monkeypatch, capsys
):
    project, _authorized = _project(tmp_path, status="METHOD_APPROVED")
    (project / "00_Preflight" / "skill_use_plan.md").write_text("# skills\n", encoding="utf-8")
    status_changes = []
    monkeypatch.setattr(
        execution,
        "_approved_execution_scripts",
        lambda *_: ([], ["missing execution script: orthology_and_annotation_coverage_audit"]),
    )
    monkeypatch.setattr(execution, "_append_decision", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        execution, "_set_status",
        lambda _project, _cand, status, _owner: status_changes.append(status),
    )

    rc = execution.cmd_execution_gate(SimpleNamespace(project_dir=str(project), cand_id="C1"))

    assert rc == 1
    assert status_changes == []
    assert "missing execution script: orthology_and_annotation_coverage_audit" in capsys.readouterr().out


def test_workspace_revalidates_bound_bytes_before_copy(tmp_path, monkeypatch):
    project, authorized = _project(tmp_path)
    authorized.write_bytes(b"tampered\n")
    monkeypatch.setattr(execution, "PREFLIGHT_FILES", [])
    monkeypatch.setattr(execution, "_delta_for_candidate", lambda *_: None)
    monkeypatch.setattr(execution, "_approved_execution_scripts", lambda *_: ([], []))

    rc = execution.cmd_prepare_turing_workspace(SimpleNamespace(
        project_dir=str(project), cand_id="C1", clean=False, file=[]))

    assert rc == 1
    # A failed binding check must happen before an execution workspace is created.
    assert not list(project.glob("_turing_workspace_C1_*"))
