import hashlib
import json
from pathlib import Path

import pytest

from research_loop import l0_contract
from research_loop.l0_state import (
    L0StateError,
    build_round_manifest,
    restore_previous_round,
    write_round_manifest,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(project: Path, cand: str, *, round_id: str = "1", extra: str = "") -> Path:
    path = project / "01_Candidates" / f"{cand}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"candidate_id: {cand}\n"
        f"round_id: {round_id}\n"
        f"round_type: {'continuation' if extra else 'initial'}\n"
        f"{extra}"
        "---\n",
        encoding="utf-8",
    )
    return path


def _initial_project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "00_Project_Index.md").write_text(
        "---\nproject_name: test-project\n---\n", encoding="utf-8"
    )
    cand = "CROUND1"
    _candidate(project, cand)
    source = project / "data.csv"
    source.write_text("sample,value\na,1\n", encoding="utf-8")
    contract = l0_contract.build_initial_contract(
        cand,
        "1",
        "Does X change Y?",
        l0_contract.build_source_input(
            input_type="files",
            files=["data.csv"],
            description="raw measurements",
            fmt="csv",
        ),
        "X changes Y",
    )
    l0_contract.write_contract(project, cand, contract)
    return project, cand, source


def test_round_manifest_captures_source_and_l7_output_hashes(tmp_path):
    project, cand, source = _initial_project(tmp_path)
    output = project / "04_Analysis_Outputs" / "normalized.csv"
    output.parent.mkdir(parents=True)
    output.write_text("sample,value\na,0.5\n", encoding="utf-8")
    exec_dir = output.parent / "_exec_manifest"
    exec_dir.mkdir()
    (exec_dir / f"{cand}_L7.json").write_text(
        json.dumps({
            "candidate_id": cand,
            "scripts": [{"name": "normalize", "output_files": [str(output)]}],
        }),
        encoding="utf-8",
    )

    manifest = build_round_manifest(project, cand)

    assert manifest["schema_version"] == "RLRRoundEvidenceManifest/v1"
    assert manifest["candidate_id"] == cand
    assert manifest["round_id"] == "1"
    source_entry = next(a for a in manifest["artifacts"] if a["class"] == "source")
    output_entry = next(a for a in manifest["artifacts"] if a["path"].endswith("normalized.csv"))
    assert source_entry["sha256"] == _sha(source)
    assert output_entry["sha256"] == _sha(output)
    assert output_entry["class"] == "intermediate"
    assert output_entry["producer_node"] == "L7"


def test_write_round_manifest_is_idempotent_and_rejects_collision(tmp_path):
    project, cand, _ = _initial_project(tmp_path)
    path, digest = write_round_manifest(project, cand)
    assert path.exists()
    assert digest == _sha(path)
    same_path, same_digest = write_round_manifest(project, cand)
    assert (same_path, same_digest) == (path, digest)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["round_id"] = "999"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(L0StateError) as exc:
        write_round_manifest(project, cand)
    assert exc.value.code == "L0_ROUND_MANIFEST_COLLISION"


def test_initial_round_restore_is_noop(tmp_path):
    project, cand, _ = _initial_project(tmp_path)
    binding = restore_previous_round(project, cand)
    assert binding["schema_version"] == "L0EvidenceBinding/v1"
    assert binding["binding_status"] == "NOT_APPLICABLE"
    assert binding["verified_artifacts"] == []


def _continuation_candidate(project: Path, manifest_path: Path, manifest_sha: str):
    parent = "CROUND1"
    child = "CROUND2"
    memory_dir = project / "08_Audit" / "loop_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_path = memory_dir / f"{parent}_next_loop_memory.json"
    memory_path.write_text(
        json.dumps({
            "schema_version": "2.0",
            "source_candidate_id": parent,
            "parent_round_id": "1",
            "round_id": "2",
            "next_round_hypothesis": "follow-up",
            "required_new_search_directions": [],
            "round_manifest_path": manifest_path.relative_to(project).as_posix(),
            "round_manifest_sha256": manifest_sha,
        }),
        encoding="utf-8",
    )
    _candidate(
        project,
        child,
        round_id="2",
        extra=(
            f"previous_candidate_id: {parent}\n"
            f"from_memory: true\n"
            f"memory_file: {memory_path.as_posix()}\n"
            f"memory_hash: {_sha(memory_path)}\n"
        ),
    )
    return child


def test_continuation_restore_fails_closed_on_hash_mismatch(tmp_path):
    project, parent, source = _initial_project(tmp_path)
    manifest_path, manifest_sha = write_round_manifest(project, parent)
    child = _continuation_candidate(project, manifest_path, manifest_sha)
    source.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(L0StateError) as exc:
        restore_previous_round(project, child)
    assert exc.value.code == "L0_RESTORE_ARTIFACT_HASH_MISMATCH"


def test_valid_continuation_restore_writes_binding(tmp_path):
    project, parent, _ = _initial_project(tmp_path)
    manifest_path, manifest_sha = write_round_manifest(project, parent)
    child = _continuation_candidate(project, manifest_path, manifest_sha)

    binding = restore_previous_round(project, child)

    assert binding["binding_status"] == "PASS"
    assert binding["previous_candidate_id"] == parent
    assert binding["previous_round_id"] == "1"
    assert binding["manifest_sha256"] == manifest_sha
    assert binding["verified_artifacts"]
    binding_path = project / "08_Audit" / "l0_restore" / f"{child}_evidence_binding.json"
    assert json.loads(binding_path.read_text(encoding="utf-8")) == binding
