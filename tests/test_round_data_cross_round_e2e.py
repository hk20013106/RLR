"""Vertical Round N -> N+1 data continuity through the real L0/L7 boundaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import l0_contract
from research_loop.commands import execution
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.gates import _audit_l0_contract
from research_loop.hypothesis_ledger import binding_path
from research_loop.l0_data import current_round_data_binding_path
from research_loop.l0_state import write_round_manifest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "P"
    (project / "00_Preflight").mkdir(parents=True)
    (project / "01_Candidates").mkdir(parents=True)
    binding_path(project).write_text(
        json.dumps({"project_id": "P1", "profile_id": DEFAULT_NATIVE_PROFILE}),
        encoding="utf-8",
    )
    for name in ("skill_use_plan.md", "output_manifest.md", "forbidden_shortcuts.md"):
        (project / "00_Preflight" / name).write_text(name, encoding="utf-8")
    return project


def _write_parent_round(project: Path) -> tuple[str, Path, Path, Path, str]:
    parent = "CROUND1"
    source = project / "round1_raw.csv"
    source.write_text("sample,value\nA,1\n", encoding="utf-8")
    source_input = l0_contract.build_source_input(
        input_type="files", files=[str(source)], location=str(project),
        description="round 1 raw data", fmt="csv")
    source_input["file_manifest"] = [{
        "role": "round1_raw", "path": str(source),
        "bytes": source.stat().st_size, "sha256": _sha(source),
    }]
    contract = l0_contract.build_initial_contract(
        parent, "1", "Round 1 question?", source_input, "Round 1 hypothesis")
    raw = l0_contract.serialize_contract(contract)
    contract_path = project / "01_Candidates" / f"{parent}.l0_input.yaml"
    contract_path.write_bytes(raw)
    (project / "01_Candidates" / f"{parent}.md").write_text(
        "---\n"
        f"candidate_id: {parent}\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"input_contract_path: 01_Candidates/{parent}.l0_input.yaml\n"
        f"input_contract_hash: {hashlib.sha256(raw).hexdigest()}\n"
        "---\n",
        encoding="utf-8",
    )

    prior_result = project / "04_Analysis_Outputs" / "prior_result.csv"
    prior_result.parent.mkdir(parents=True)
    prior_result.write_text("sample,result\nA,42\n", encoding="utf-8")
    exec_manifest = prior_result.parent / "_exec_manifest" / f"{parent}_L7.json"
    exec_manifest.parent.mkdir()
    exec_manifest.write_text(json.dumps({
        "candidate_id": parent,
        "scripts": [{"name": "analysis", "output_files": [str(prior_result)]}],
    }), encoding="utf-8")

    manifest_path, manifest_sha = write_round_manifest(project, parent)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prior_entry = next(
        item for item in manifest["artifacts"]
        if item["path"] == prior_result.relative_to(project).as_posix()
    )
    assert prior_entry["class"] == "intermediate"
    return parent, source, prior_result, manifest_path, manifest_sha


def _write_child_round(
    project: Path,
    parent: str,
    prior_result: Path,
    manifest_path: Path,
    manifest_sha: str,
    *,
    include_inherited: bool,
    include_new: bool,
) -> tuple[str, Path | None]:
    child = "CROUND2"
    memory = project / "08_Audit" / "loop_memory" / f"{parent}_next_loop_memory.json"
    memory.parent.mkdir(parents=True)
    memory.write_text(json.dumps({
        "schema_version": "2.0",
        "source_candidate_id": parent,
        "parent_round_id": "1",
        "round_id": "2",
        "next_round_hypothesis": "Round 2 hypothesis",
        "required_new_search_directions": ["new direction"],
        "round_manifest_path": manifest_path.relative_to(project).as_posix(),
        "round_manifest_sha256": manifest_sha,
    }), encoding="utf-8")
    memory_hash = _sha(memory)

    new_data = None
    source_input = None
    if include_new:
        new_data = project / "round2_new.csv"
        new_data.write_text("sample,new_value\nA,7\n", encoding="utf-8")
        source_input = l0_contract.build_source_input(
            input_type="files", files=[str(new_data)], location=str(project),
            description="round 2 new data", fmt="csv")
        source_input["file_manifest"] = [{
            "role": "new_data", "path": str(new_data),
            "bytes": new_data.stat().st_size, "sha256": _sha(new_data),
        }]

    contract = l0_contract.build_continuation_contract(
        child, "2", "1", parent, "Round 2 question?", source_input,
        {
            "candidate_id": parent,
            "hypothesis": "Round 1 hypothesis",
            "final_decision": "REVISE",
            "conclusion": "Reuse verified evidence in the next round",
            "memory_hash": memory_hash,
        },
        "Round 2 hypothesis",
    )
    # Low-level builders retain historical 1.0 compatibility. Native N+1
    # declarations opt into the current schema at the intake boundary.
    contract["schema_version"] = "1.1"
    contract["inherited_inputs"] = []
    if include_inherited:
        contract["inherited_inputs"] = [{
            "path": prior_result.relative_to(project).as_posix(),
            "sha256": _sha(prior_result),
            "role": "prior_result",
            "reuse_reason": "reanalyze the verified prior result",
        }]
    raw = l0_contract.serialize_contract(contract)
    (project / "01_Candidates" / f"{child}.l0_input.yaml").write_bytes(raw)
    (project / "01_Candidates" / f"{child}.md").write_text(
        "---\n"
        f"candidate_id: {child}\n"
        "round_type: continuation\n"
        "round_id: 2\n"
        "parent_round_id: 1\n"
        f"previous_candidate_id: {parent}\n"
        "from_memory: true\n"
        f"memory_file: {memory.as_posix()}\n"
        f"memory_hash: {memory_hash}\n"
        "current_status: NEEDS_EXECUTION\n"
        "current_owner: Turing\n"
        f"input_contract_path: 01_Candidates/{child}.l0_input.yaml\n"
        f"input_contract_hash: {hashlib.sha256(raw).hexdigest()}\n"
        "---\n",
        encoding="utf-8",
    )
    return child, new_data


def _prepare_workspace(project: Path, child: str, monkeypatch) -> tuple[int, Path | None]:
    l0_delta = project / "l0.json"
    l6_delta = project / "l6.json"
    l0_delta.write_text("{}", encoding="utf-8")
    l6_delta.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        execution, "_delta_for_candidate",
        lambda _project, key, _cand: l0_delta if key == "L0_linnaeus" else l6_delta,
    )
    monkeypatch.setattr(execution, "_approved_execution_scripts", lambda *_: ([], []))

    rc = execution.cmd_prepare_turing_workspace(SimpleNamespace(
        project_dir=str(project), cand_id=child, clean=False, file=[]))
    workspaces = list(project.glob(f"_turing_workspace_{child}_*"))
    return rc, workspaces[0] if workspaces else None


@pytest.mark.parametrize(
    ("mode", "include_inherited", "include_new"),
    [
        ("inherited-only", True, False),
        ("new-only", False, True),
        ("combined", True, True),
    ],
)
def test_round_n_manifest_to_n_plus_1_turing_workspace(
    tmp_path, monkeypatch, mode, include_inherited, include_new,
):
    project = _project(tmp_path)
    parent, unselected_parent_source, prior_result, manifest_path, manifest_sha = (
        _write_parent_round(project)
    )
    child, new_data = _write_child_round(
        project, parent, prior_result, manifest_path, manifest_sha,
        include_inherited=include_inherited, include_new=include_new)

    ok, reason = _audit_l0_contract(project, child)
    assert ok, f"{mode}: {reason}"

    binding_path_value = current_round_data_binding_path(project, child)
    binding = json.loads(binding_path_value.read_text(encoding="utf-8"))
    expected = set()
    if include_inherited:
        expected.add(("inherited", "prior_result"))
    if include_new:
        expected.add(("current_round", "new_data"))
    assert {(item["origin"], item["role"]) for item in binding["authorized_inputs"]} == expected

    authorized_paths = {item["path"] for item in binding["authorized_inputs"]}
    prior_rel = prior_result.relative_to(project).as_posix()
    parent_source_rel = unselected_parent_source.relative_to(project).as_posix()
    assert (prior_rel in authorized_paths) is include_inherited
    if new_data is not None:
        assert new_data.relative_to(project).as_posix() in authorized_paths
    assert parent_source_rel not in authorized_paths

    rc, workspace = _prepare_workspace(project, child, monkeypatch)
    assert rc == 0, mode
    assert workspace is not None

    ws_manifest = json.loads(
        (workspace / "WORKSPACE_MANIFEST.json").read_text(encoding="utf-8"))
    staged_originals = {
        Path(item["original_path"]).resolve() for item in ws_manifest["staged_files"]
    }
    assert (prior_result.resolve() in staged_originals) is include_inherited
    if new_data is not None:
        assert new_data.resolve() in staged_originals
    assert unselected_parent_source.resolve() not in staged_originals
    assert not (workspace / "inputs" / "input_manifest.md").exists()


def test_selected_prior_artifact_tamper_fails_at_n_plus_1_l0(tmp_path):
    project = _project(tmp_path)
    parent, _parent_source, prior_result, manifest_path, manifest_sha = _write_parent_round(project)
    child, _new_data = _write_child_round(
        project, parent, prior_result, manifest_path, manifest_sha,
        include_inherited=True, include_new=False)
    prior_result.write_text("tampered\n", encoding="utf-8")

    ok, reason = _audit_l0_contract(project, child)

    assert ok is False
    assert "L0_RESTORE_ARTIFACT_HASH_MISMATCH" in reason
    assert not current_round_data_binding_path(project, child).exists()


def test_current_n_plus_1_file_tamper_fails_before_l7_workspace(tmp_path, monkeypatch):
    project = _project(tmp_path)
    parent, _parent_source, prior_result, manifest_path, manifest_sha = _write_parent_round(project)
    child, new_data = _write_child_round(
        project, parent, prior_result, manifest_path, manifest_sha,
        include_inherited=False, include_new=True)
    ok, reason = _audit_l0_contract(project, child)
    assert ok, reason
    assert new_data is not None
    new_data.write_text("tampered\n", encoding="utf-8")

    rc, workspace = _prepare_workspace(project, child, monkeypatch)

    assert rc == 1
    assert workspace is None
