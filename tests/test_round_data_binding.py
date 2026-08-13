"""Contract tests for deterministic current-round scientific data authorization."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_loop import l0_contract
from research_loop.hypothesis_ledger import binding_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_project(tmp_path: Path) -> Path:
    project = tmp_path / "P"
    (project / "01_Candidates").mkdir(parents=True)
    (project / "08_Audit" / "l0_restore").mkdir(parents=True)
    (project / "00_Preflight").mkdir(parents=True)
    binding_path(project).write_text(
        json.dumps({"project_id": "P1", "profile_id": "v2.1-native"}),
        encoding="utf-8",
    )
    return project


def _write_candidate(project: Path, cand_id: str, round_id: str, *, continuation=False):
    rows = ["---", f"candidate_id: {cand_id}", f"round_id: {round_id}"]
    if continuation:
        seed = project / "08_Audit" / f"{cand_id}_seed.json"
        seed.write_text("{}", encoding="utf-8")
        rows += [
            "round_type: continuation",
            "from_memory: true",
            f"memory_file: {seed.as_posix()}",
            f"memory_hash: {'a' * 64}",
        ]
    rows += ["---", ""]
    (project / "01_Candidates" / f"{cand_id}.md").write_text("\n".join(rows), encoding="utf-8")


def _write_contract(project: Path, cand_id: str, contract: dict) -> Path:
    path = project / "01_Candidates" / f"{cand_id}.l0_input.yaml"
    path.write_bytes(l0_contract.serialize_contract(contract))
    return path


def _current_contract(project: Path, cand_id: str, data: Path) -> dict:
    source = l0_contract.build_source_input(
        input_type="files",
        files=[str(data)],
        location=str(data.parent),
        description="new round data",
        fmt=data.suffix.lstrip(".") or "file",
    )
    contract = l0_contract.build_initial_contract(cand_id, "1", "Q?", source, "H")
    contract["schema_version"] = "1.1"
    contract["source_input"]["file_manifest"] = [{
        "role": "new_data",
        "path": str(data),
        "bytes": data.stat().st_size,
        "sha256": _sha(data),
    }]
    return contract


def _continuation_contract(project: Path, cand_id: str, inherited: list[dict], current: Path | None = None) -> dict:
    source = None
    if current is not None:
        source = l0_contract.build_source_input(
            input_type="files", files=[str(current)], location=str(current.parent),
            description="new N+1 data", fmt=current.suffix.lstrip(".") or "file")
        source["file_manifest"] = [{
            "role": "new_data", "path": str(current),
            "bytes": current.stat().st_size, "sha256": _sha(current),
        }]
    contract = l0_contract.build_continuation_contract(
        cand_id, "2", "1", "C_N", "Q2?", source,
        {"hypothesis": "H0", "final_decision": "REVISE",
         "conclusion": "C0", "memory_hash": "a" * 64}, "H1")
    contract["schema_version"] = "1.1"
    contract["inherited_inputs"] = inherited
    return contract


def _evidence_binding(project: Path, artifact: Path, *, klass="result", cand="C_N", round_id="1") -> dict:
    try:
        stored = artifact.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        stored = artifact.resolve().as_posix()
    return {
        "schema_version": "L0EvidenceBinding/v1",
        "current_candidate_id": "C_N1",
        "previous_candidate_id": cand,
        "previous_round_id": round_id,
        "manifest_path": "08_Audit/round_manifests/C_N_round_1.json",
        "manifest_sha256": "b" * 64,
        "verified_artifacts": [{
            "artifact_id": "A1", "class": klass, "path": stored,
            "sha256": _sha(artifact), "producer_node": "L7",
            "producer_receipt": "", "created_in_round": round_id,
        }],
        "failures": [], "binding_status": "PASS",
    }


def test_initial_binding_authorizes_only_current_declared_files(tmp_path):
    from research_loop.l0_data import build_current_round_data_binding

    project = _seed_project(tmp_path)
    data = project / "raw.csv"
    data.write_bytes(b"x\n1\n")
    _write_candidate(project, "C1", "1")
    _write_contract(project, "C1", _current_contract(project, "C1", data))

    binding = build_current_round_data_binding(project, "C1", None)

    assert binding["schema_version"] == "CurrentRoundDataBinding/v1"
    assert len(binding["authorized_inputs"]) == 1
    item = binding["authorized_inputs"][0]
    assert item["origin"] == "current_round"
    assert item["role"] == "new_data"
    assert item["sha256"] == _sha(data)


def test_continuation_combines_selected_inherited_and_new_data(tmp_path):
    from research_loop.l0_data import build_current_round_data_binding

    project = _seed_project(tmp_path)
    inherited = project / "04_Analysis_Outputs" / "result.json"
    inherited.parent.mkdir(parents=True)
    inherited.write_bytes(b'{"value":42}\n')
    new = project / "new.csv"
    new.write_bytes(b"sample\nA\n")
    _write_candidate(project, "C_N1", "2", continuation=True)
    selector = {
        "path": inherited.relative_to(project).as_posix(),
        "sha256": _sha(inherited),
        "role": "prior_result",
        "reuse_reason": "reanalyze verified result",
    }
    _write_contract(project, "C_N1", _continuation_contract(project, "C_N1", [selector], new))

    binding = build_current_round_data_binding(
        project, "C_N1", _evidence_binding(project, inherited))

    assert {item["origin"] for item in binding["authorized_inputs"]} == {"current_round", "inherited"}
    inherited_item = next(item for item in binding["authorized_inputs"] if item["origin"] == "inherited")
    assert inherited_item["source_candidate_id"] == "C_N"
    assert inherited_item["source_round_id"] == "1"
    assert inherited_item["artifact_class"] == "result"


def test_inherited_only_is_valid_and_unselected_artifacts_are_not_authorized(tmp_path):
    from research_loop.l0_data import build_current_round_data_binding

    project = _seed_project(tmp_path)
    chosen = project / "chosen.json"
    chosen.write_bytes(b"1")
    extra = project / "extra.json"
    extra.write_bytes(b"2")
    _write_candidate(project, "C_N1", "2", continuation=True)
    selector = {"path": chosen.relative_to(project).as_posix(), "sha256": _sha(chosen),
                "role": "prior_result", "reuse_reason": "reuse exact result"}
    _write_contract(project, "C_N1", _continuation_contract(project, "C_N1", [selector]))
    evidence = _evidence_binding(project, chosen)
    evidence["verified_artifacts"].append({
        **evidence["verified_artifacts"][0],
        "artifact_id": "A2", "path": extra.relative_to(project).as_posix(),
        "sha256": _sha(extra),
    })

    binding = build_current_round_data_binding(project, "C_N1", evidence)

    assert [item["path"] for item in binding["authorized_inputs"]] == [selector["path"]]


@pytest.mark.parametrize("klass", ["literature", "audit", "receipt"])
def test_non_data_previous_artifacts_cannot_be_authorized(tmp_path, klass):
    from research_loop.l0_data import L0DataError, build_current_round_data_binding

    project = _seed_project(tmp_path)
    prior = project / "prior.json"
    prior.write_bytes(b"{}")
    _write_candidate(project, "C_N1", "2", continuation=True)
    selector = {"path": prior.relative_to(project).as_posix(), "sha256": _sha(prior),
                "role": "prior", "reuse_reason": "try to reuse"}
    _write_contract(project, "C_N1", _continuation_contract(project, "C_N1", [selector]))

    with pytest.raises(L0DataError) as exc:
        build_current_round_data_binding(project, "C_N1", _evidence_binding(project, prior, klass=klass))
    assert exc.value.code == "L0_DATA_INHERITED_CLASS_FORBIDDEN"


def test_inherited_selector_must_match_verified_path_and_hash(tmp_path):
    from research_loop.l0_data import L0DataError, build_current_round_data_binding

    project = _seed_project(tmp_path)
    prior = project / "prior.json"
    prior.write_bytes(b"{}")
    _write_candidate(project, "C_N1", "2", continuation=True)
    selector = {"path": prior.relative_to(project).as_posix(), "sha256": "f" * 64,
                "role": "prior", "reuse_reason": "reuse"}
    _write_contract(project, "C_N1", _continuation_contract(project, "C_N1", [selector]))

    with pytest.raises(L0DataError) as exc:
        build_current_round_data_binding(project, "C_N1", _evidence_binding(project, prior))
    assert exc.value.code == "L0_DATA_INHERITED_NOT_VERIFIED"


def test_current_file_change_is_rejected_before_binding(tmp_path):
    from research_loop.l0_data import L0DataError, build_current_round_data_binding

    project = _seed_project(tmp_path)
    data = project / "raw.csv"
    data.write_bytes(b"old\n")
    _write_candidate(project, "C1", "1")
    _write_contract(project, "C1", _current_contract(project, "C1", data))
    data.write_bytes(b"changed\n")

    with pytest.raises(L0DataError) as exc:
        build_current_round_data_binding(project, "C1", None)
    assert exc.value.code == "L0_DATA_CURRENT_HASH_MISMATCH"
