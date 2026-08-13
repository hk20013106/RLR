"""Contract tests for legal non-file L0 sources in CurrentRoundDataBinding."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_loop import l0_contract
from research_loop.hypothesis_ledger import binding_path
from research_loop.l0_data import build_current_round_data_binding


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "P"
    (project / "00_Preflight").mkdir(parents=True)
    (project / "01_Candidates").mkdir(parents=True)
    binding_path(project).write_text(
        json.dumps({"project_id": "P1", "profile_id": "v2.1-native"}),
        encoding="utf-8",
    )
    return project


def _write_candidate(project: Path, cand_id: str, source: dict) -> None:
    contract = l0_contract.build_initial_contract(cand_id, "1", "Q?", source, "H")
    contract["schema_version"] = "1.1"
    raw = l0_contract.serialize_contract(contract)
    (project / "01_Candidates" / f"{cand_id}.l0_input.yaml").write_bytes(raw)
    (project / "01_Candidates" / f"{cand_id}.md").write_text(
        "---\n"
        f"candidate_id: {cand_id}\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"input_contract_path: 01_Candidates/{cand_id}.l0_input.yaml\n"
        f"input_contract_hash: {hashlib.sha256(raw).hexdigest()}\n"
        "---\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("kind", ["inline", "other"])
def test_non_file_contract_types_are_represented_not_rejected(tmp_path, kind):
    project = _project(tmp_path)
    source = l0_contract.build_source_input(
        input_type=kind,
        description="non-file scientific input",
        fmt="text",
    )
    _write_candidate(project, "C1", source)

    binding = build_current_round_data_binding(project, "C1", None)

    assert binding["authorized_inputs"] == []
    assert binding["non_file_inputs"] == [{
        "origin": "current_round",
        "kind": kind,
        "location": "",
        "role": kind,
        "description": "non-file scientific input",
        "verification_status": "",
        "reason": "",
    }]


def test_remote_dataset_keeps_existing_non_file_semantics(tmp_path):
    project = _project(tmp_path)
    source = l0_contract.build_source_input(
        input_type="dataset",
        location="GEO:GSE12345",
        description="remote dataset",
        fmt="h5",
        verification_status="unverifiable",
        reason="not materialized locally",
    )
    _write_candidate(project, "C1", source)

    binding = build_current_round_data_binding(project, "C1", None)

    assert binding["authorized_inputs"] == []
    assert binding["non_file_inputs"][0]["kind"] == "dataset"
    assert binding["non_file_inputs"][0]["location"] == "GEO:GSE12345"
