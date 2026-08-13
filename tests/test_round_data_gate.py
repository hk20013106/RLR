"""Gate-order tests for current-round data authorization."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_loop import l0_contract
from research_loop.gates import _audit_l0_contract
from research_loop.hypothesis_ledger import binding_path
from research_loop.l0_data import current_round_data_binding_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "P"
    (project / "00_Preflight").mkdir(parents=True)
    (project / "01_Candidates").mkdir(parents=True)
    binding_path(project).write_text(
        json.dumps({"project_id": "P1", "profile_id": "v2.1-native"}),
        encoding="utf-8",
    )
    return project


def _candidate(project: Path, cand_id: str, data: Path) -> Path:
    source = l0_contract.build_source_input(
        input_type="files", files=[str(data)], location=str(data.parent),
        description="round data", fmt="csv")
    source["file_manifest"] = [{
        "role": "raw", "path": str(data), "bytes": data.stat().st_size,
        "sha256": _sha(data),
    }]
    contract = l0_contract.build_initial_contract(cand_id, "1", "Q?", source, "H")
    contract["schema_version"] = "1.1"
    raw = l0_contract.serialize_contract(contract)
    contract_path = project / "01_Candidates" / f"{cand_id}.l0_input.yaml"
    contract_path.write_bytes(raw)
    candidate = project / "01_Candidates" / f"{cand_id}.md"
    candidate.write_text(
        "---\n"
        f"candidate_id: {cand_id}\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"input_contract_path: 01_Candidates/{cand_id}.l0_input.yaml\n"
        f"input_contract_hash: {hashlib.sha256(raw).hexdigest()}\n"
        "---\n",
        encoding="utf-8",
    )
    return candidate


def test_l0_contract_gate_writes_verified_data_binding(tmp_path):
    project = _project(tmp_path)
    data = project / "raw.csv"
    data.write_bytes(b"x\n1\n")
    _candidate(project, "C1", data)

    ok, reason = _audit_l0_contract(project, "C1")

    assert ok is True, reason
    assert current_round_data_binding_path(project, "C1").is_file()


def test_l0_gate_rejects_current_data_changed_after_declaration(tmp_path):
    project = _project(tmp_path)
    data = project / "raw.csv"
    data.write_bytes(b"old\n")
    _candidate(project, "C1", data)
    data.write_bytes(b"changed\n")

    ok, reason = _audit_l0_contract(project, "C1")

    assert ok is False
    assert "L0_DATA_CURRENT_HASH_MISMATCH" in reason
    assert not current_round_data_binding_path(project, "C1").exists()
