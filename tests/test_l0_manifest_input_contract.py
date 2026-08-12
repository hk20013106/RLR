import json
from pathlib import Path

import pytest

from research_loop import l0_contract
from research_loop.l0_state import (
    L0StateError,
    build_round_manifest,
    verify_round_manifest,
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "P"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: P\n---\n", encoding="utf-8"
    )
    candidates = project / "01_Candidates"
    candidates.mkdir()
    (candidates / "C1.md").write_text(
        "---\ncandidate_id: C1\nround_id: '1'\ncurrent_status: NEW\n---\n",
        encoding="utf-8",
    )
    source = project / "raw.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    contract = l0_contract.build_initial_contract(
        "C1", "1", "Q?",
        l0_contract.build_source_input(
            input_type="files", files=["raw.csv"], description="raw", fmt="csv"
        ),
        "H",
    )
    l0_contract.write_contract(project, "C1", contract)
    return project


def test_round_manifest_registers_input_contract_and_detects_its_tampering(tmp_path):
    project = _project(tmp_path)
    manifest = build_round_manifest(project, "C1")

    input_records = [
        item for item in manifest["artifacts"]
        if item["path"] == "01_Candidates/C1.l0_input.yaml"
    ]
    assert len(input_records) == 1
    assert input_records[0]["class"] == "audit"
    assert input_records[0]["producer_node"] == "L0"

    contract_path = project / "01_Candidates" / "C1.l0_input.yaml"
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "# tampered\n",
        encoding="utf-8",
    )

    with pytest.raises(L0StateError) as exc:
        verify_round_manifest(
            project, manifest, expected_candidate="C1", expected_round="1"
        )
    assert exc.value.code == "L0_RESTORE_ARTIFACT_HASH_MISMATCH"
