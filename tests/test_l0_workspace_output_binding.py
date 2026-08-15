import hashlib
import json
from pathlib import Path

import pytest

from research_loop import l0_contract
from research_loop.l0_state import L0StateError, build_round_manifest


def _workspace_project(tmp_path: Path, *, declared_hash: str | None = None):
    project = tmp_path / "P"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: P\n---\n", encoding="utf-8"
    )
    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(
        "---\n"
        "candidate_id: C1\n"
        "round_id: 1\n"
        "current_status: NEW\n"
        "---\n",
        encoding="utf-8",
    )
    (project / "raw.csv").write_text("x\n1\n", encoding="utf-8")
    contract = l0_contract.build_initial_contract(
        "C1",
        "1",
        "Q?",
        l0_contract.build_source_input(
            input_type="files", files=["raw.csv"], description="raw", fmt="csv"
        ),
        "H",
    )
    l0_contract.write_contract(project, "C1", contract)

    workspace = project / "_turing_workspace_C1_20260816000000000000"
    result = workspace / "results" / "orthology_coverage_qc.json"
    result.parent.mkdir(parents=True)
    result.write_text('{"status":"OK","node":"L7"}\n', encoding="utf-8")
    result_hash = hashlib.sha256(result.read_bytes()).hexdigest()

    exec_manifest = project / "04_Analysis_Outputs" / "_exec_manifest" / "C1_L7.json"
    exec_manifest.parent.mkdir(parents=True)
    exec_manifest.write_text(
        json.dumps({
            "candidate_id": "C1",
            "scripts": [{
                "name": "analysis",
                "output_files": ["results/orthology_coverage_qc.json"],
            }],
        }),
        encoding="utf-8",
    )
    delta = project / "02_Agent_Notes" / "Turing" / "C1_L7_turing_delta.v2.json"
    delta.parent.mkdir(parents=True)
    delta.write_text(
        json.dumps({
            "candidate_id": "C1",
            "schema_version": "2.1",
            "workspace": workspace.name,
            "results": [{
                "result_key": "orthology_coverage_diagnostic",
                "artifact_refs": [{
                    "path": f"{workspace.name}/results/orthology_coverage_qc.json",
                    "sha256": declared_hash or result_hash,
                }],
            }],
        }),
        encoding="utf-8",
    )
    return project, workspace, result, result_hash


def test_round_manifest_binds_workspace_relative_l7_result(tmp_path):
    project, workspace, result, result_hash = _workspace_project(tmp_path)

    manifest = build_round_manifest(project, "C1")

    entries = [
        item for item in manifest["artifacts"]
        if item["path"].endswith("orthology_coverage_qc.json")
    ]
    assert len(entries) == 1
    assert entries[0]["path"] == f"{workspace.name}/results/orthology_coverage_qc.json"
    assert entries[0]["class"] == "result"
    assert entries[0]["sha256"] == result_hash
    assert result.exists()


def test_round_manifest_rejects_workspace_result_hash_mismatch(tmp_path):
    project, _workspace, _result, _result_hash = _workspace_project(
        tmp_path, declared_hash="0" * 64
    )

    with pytest.raises(L0StateError) as exc:
        build_round_manifest(project, "C1")

    assert exc.value.code == "L0_ROUND_MANIFEST_ARTIFACT_HASH_MISMATCH"
