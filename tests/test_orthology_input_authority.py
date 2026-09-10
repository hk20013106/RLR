"""Batch 3 tests for binding completed orthology as L0 input authority."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from research_loop import l0_contract, l0_data, l0_intake, l0_plan_intake, l4_pipeline
from research_loop.authority import project_context_authorities
from research_loop.gates import _audit_l0_contract


FORMAL_SPECIES = ["Mmus", "Rn", "Sk", "Sm"]
SPECIES_TREE = "((Mmus,Rnor)Rodentia,(Skuh,Smur)Eulipotyphla)Boreoeutheria"
REAL_PREPLAN = Path(
    r"D:\R-HK\yigene\newdata_260727\FOUR_SPECIES_HHR_RESEARCH_LOOP_PREPLAN.md"
)
REAL_DATA_ROOT = REAL_PREPLAN.parent


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_authority_inputs(tmp_path: Path, *, rows=("G1", "G2")) -> tuple[Path, dict[str, Path]]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    gene_length = data_dir / "four_species_gene_ids_lengths.tsv"
    raw_counts = data_dir / "four_species_raw_counts.tsv"
    length_scaled = data_dir / "four_species_length_scaled_counts.tsv"

    gene_length.write_text(
        "Mmus_symbol\tMmus_gene_id\tRnor_gene_id\n"
        + "".join(f"{row}\t{row}_m\t{row}_r\n" for row in rows),
        encoding="utf-8",
    )
    raw_counts.write_text(
        "Mmus_symbol\tS1\tS2\n"
        + "".join(f"{row}\t1\t2\n" for row in rows),
        encoding="utf-8",
    )
    length_scaled.write_text(
        "Mmus_symbol\tS1\tS2\n"
        + "".join(f"{row}\t1.0\t2.0\n" for row in rows),
        encoding="utf-8",
    )
    return data_dir, {
        "gene_length": gene_length,
        "raw_counts": raw_counts,
        "length_scaled_expression": length_scaled,
    }


def _plan_text(data_dir: Path, files: dict[str, Path], *, rows: int = 2) -> str:
    manifest = [
        {
            "role": role,
            "path": path.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
        }
        for role, path in files.items()
    ]
    plan = {
        "intake_schema": "research-loop-plan/1.0",
        "round_type": "initial",
        "round_id": "1",
        "scientific_question": "Are the four formal species comparable?",
        "current_round": {"hypothesis": "The aligned feature space is usable."},
        "source_input": {"file_manifest": manifest},
        "research_plan": {
            "scientific_provenance": {
                "upstream_completed_inputs": {
                    "orthology": {
                        "status": "completed_upstream",
                        "method": "FastOMA v0.5.1 + OMAmer",
                        "policy": "strict_one_to_one_single_copy",
                        "orthogroup_count": rows,
                        "species_tree": SPECIES_TREE,
                        "formal_species": FORMAL_SPECIES,
                        "feature_space": {
                            "key": "Mmus_symbol",
                            "rows": rows,
                            "aligned_source_files": [
                                {"role": role, "path": path.as_posix()}
                                for role, path in files.items()
                            ],
                        },
                    }
                }
            },
            "goal": "Use the completed upstream orthology input.",
        },
    }
    return "---\n" + yaml.safe_dump(
        plan, allow_unicode=True, sort_keys=False
    ) + "---\n"


def _normalized_plan(tmp_path: Path, *, rows=("G1", "G2")):
    data_dir, files = _write_authority_inputs(tmp_path, rows=rows)
    request_path = tmp_path / "preplan.md"
    request_text = _plan_text(data_dir, files, rows=len(rows))
    request_path.write_text(request_text, encoding="utf-8")
    result = l0_intake.normalize_request(
        request_path, request_text, "C1", data=str(data_dir)
    )
    return result, request_path, request_text, data_dir, files


def _materialize_project(tmp_path: Path):
    result, request_path, request_text, data_dir, files = _normalized_plan(tmp_path)
    assert result["errors"] == []
    assert result["missing_fields"] == []
    project = tmp_path / "project"
    (project / "00_Project_Index.md").parent.mkdir(parents=True)
    (project / "00_Project_Index.md").write_text("# project\n", encoding="utf-8")
    (project / "01_Candidates").mkdir(parents=True)
    contract = result["contract"]
    artifact_path, _ = l0_contract.write_contract(project, "C1", contract)
    snapshot = project / contract["provenance"]["research_plan_snapshot_path"]
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(request_path.read_bytes())
    (project / "01_Candidates" / "C1.md").write_text(
        "---\n"
        "candidate_id: C1\n"
        "round_id: 1\n"
        "round_type: initial\n"
        "---\n",
        encoding="utf-8",
    )
    return project, contract, snapshot, data_dir, files, artifact_path, request_text


def test_structured_preplan_promotes_completed_upstream_authority_into_l0_contract(tmp_path):
    result, _request_path, _request_text, _data_dir, _files = _normalized_plan(tmp_path)

    assert result["errors"] == []
    authority = result["contract"]["upstream_completed_inputs"]["orthology"]
    assert authority["status"] == "completed_upstream"
    assert authority["method"] == "FastOMA v0.5.1 + OMAmer"
    assert authority["policy"] == "strict_one_to_one_single_copy"
    assert authority["orthogroup_count"] == 2
    assert authority["formal_species"] == FORMAL_SPECIES
    assert authority["feature_space"] == {
        "key": "Mmus_symbol",
        "rows": 2,
        "aligned_source_files": authority["feature_space"]["aligned_source_files"],
    }


def test_l0_contract_renderer_carries_upstream_authority_into_physical_context(tmp_path):
    result, _request_path, _request_text, _data_dir, _files = _normalized_plan(tmp_path)

    rendered = l0_contract.render_contract_block(result["contract"])

    assert "upstream_completed_inputs:" in rendered
    assert "status: completed_upstream" in rendered
    assert "method: FastOMA v0.5.1 + OMAmer" in rendered
    assert "orthogroup_count: 2" in rendered
    assert "key: Mmus_symbol" in rendered


def test_current_round_binding_contains_typed_orthology_and_hash_bound_sources(tmp_path):
    project, _contract, snapshot, _data_dir, files, _artifact_path, request_text = (
        _materialize_project(tmp_path)
    )

    binding = l0_data.build_current_round_data_binding(project, "C1")
    authority = binding["upstream_completed_inputs"]
    orthology = authority["orthology"]

    assert orthology["status"] == "completed_upstream"
    assert orthology["method"] == "FastOMA v0.5.1 + OMAmer"
    assert orthology["policy"] == "strict_one_to_one_single_copy"
    assert orthology["orthogroup_count"] == 2
    assert orthology["species_tree"] == SPECIES_TREE
    assert orthology["formal_species"] == FORMAL_SPECIES
    assert orthology["feature_space"]["key"] == "Mmus_symbol"
    assert orthology["feature_space"]["rows"] == 2
    assert orthology["feature_space"]["validation"] == {
        "observed_rows": {
            "gene_length": 2,
            "length_scaled_expression": 2,
            "raw_counts": 2,
        },
        "row_order_matches": True,
    }

    source_files = {
        item["role"]: item
        for item in orthology["feature_space"]["source_files"]
    }
    assert set(source_files) == set(files)
    for role, path in files.items():
        assert source_files[role]["path"]
        assert source_files[role]["bytes"] == path.stat().st_size
        assert source_files[role]["sha256"] == _sha(path)

    snapshot_bytes = snapshot.read_bytes()
    assert authority["source_preplan"] == {
        "path": snapshot.relative_to(project).as_posix(),
        "bytes": len(snapshot_bytes),
        "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
    }


def test_l4_context_projection_exposes_same_binding_to_method_contract_consumer(tmp_path):
    project, _contract, _snapshot, _data_dir, _files, _artifact_path, _text = (
        _materialize_project(tmp_path)
    )
    l0_data.write_current_round_data_binding(project, "C1")

    sections, manifest_rows = project_context_authorities(
        project,
        "C1",
        {"node": "L4", "requires_authorities": ["current_round_data_binding"]},
    )
    projection = json.loads(sections[1])

    assert projection["schema_version"] == "CurrentRoundDataBinding/v1"
    orthology = projection["upstream_completed_inputs"]["orthology"]
    assert orthology["status"] == "completed_upstream"
    assert orthology["orthogroup_count"] == 2
    assert orthology["policy"] == "strict_one_to_one_single_copy"
    assert orthology["feature_space"]["key"] == "Mmus_symbol"
    assert orthology["feature_space"]["rows"] == 2
    assert orthology["feature_space"]["validation"]["row_order_matches"] is True
    assert len(orthology["feature_space"]["source_files"]) == 3
    assert manifest_rows[0]["authority"] == "current_round_data_binding"


def test_l45_records_the_same_l0_binding_and_typed_upstream_authority(tmp_path):
    project, _contract, _snapshot, _data_dir, _files, _artifact_path, _text = (
        _materialize_project(tmp_path)
    )
    binding_path, binding_sha = l0_data.write_current_round_data_binding(project, "C1")

    authority = l4_pipeline._l45_input_authority(project, "C1")

    assert authority["schema_version"] == "CurrentRoundDataBinding/v1"
    assert authority["path"] == binding_path.relative_to(project).as_posix()
    assert authority["sha256"] == binding_sha
    assert authority["upstream_completed_inputs"]["orthology"]["status"] == (
        "completed_upstream"
    )
    assert authority["upstream_completed_inputs"]["orthology"]["feature_space"][
        "validation"
    ]["row_order_matches"] is True


@pytest.mark.skipif(not REAL_PREPLAN.is_file(), reason="authoritative real-data preplan is unavailable")
def test_real_authoritative_preplan_binding_smoke(tmp_path):
    request_text = REAL_PREPLAN.read_text(encoding="utf-8")
    result = l0_intake.normalize_request(
        REAL_PREPLAN, request_text, "REAL-C1", data=str(REAL_DATA_ROOT)
    )
    assert result["errors"] == []
    assert result["missing_fields"] == []

    project = tmp_path / "project"
    (project / "00_Project_Index.md").parent.mkdir(parents=True)
    (project / "00_Project_Index.md").write_text("# project\n", encoding="utf-8")
    (project / "01_Candidates").mkdir(parents=True)
    contract = result["contract"]
    l0_contract.write_contract(project, "REAL-C1", contract)
    snapshot = project / contract["provenance"]["research_plan_snapshot_path"]
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(REAL_PREPLAN.read_bytes())
    (project / "01_Candidates" / "REAL-C1.md").write_text(
        "---\n"
        "candidate_id: REAL-C1\n"
        "round_id: 1\n"
        "round_type: initial\n"
        "---\n",
        encoding="utf-8",
    )

    binding_path, binding_sha = l0_data.write_current_round_data_binding(
        project, "REAL-C1"
    )
    binding = l0_data.load_current_round_data_binding(project, "REAL-C1")
    orthology = binding["upstream_completed_inputs"]["orthology"]
    assert orthology["status"] == "completed_upstream"
    assert orthology["method"] == "FastOMA v0.5.1 + OMAmer"
    assert orthology["policy"] == "strict_one_to_one_single_copy"
    assert orthology["orthogroup_count"] == 14385
    assert orthology["formal_species"] == FORMAL_SPECIES
    assert orthology["feature_space"] == {
        "key": "Mmus_symbol",
        "rows": 14385,
        "source_files": orthology["feature_space"]["source_files"],
        "validation": {
            "observed_rows": {
                "gene_length": 14385,
                "length_scaled_expression": 14385,
                "raw_counts": 14385,
            },
            "row_order_matches": True,
        },
    }
    assert binding_path.is_file()
    assert l0_data.verify_current_round_data_binding(project, "REAL-C1") == binding
    l45_authority = l4_pipeline._l45_input_authority(project, "REAL-C1")
    assert l45_authority["path"] == binding_path.relative_to(project).as_posix()
    assert l45_authority["sha256"] == binding_sha
    assert l45_authority["upstream_completed_inputs"]["orthology"][
        "orthogroup_count"
    ] == 14385
    sections, _manifest_rows = project_context_authorities(
        project,
        "REAL-C1",
        {"node": "L4", "requires_authorities": ["current_round_data_binding"]},
    )
    projection = json.loads(sections[1])
    assert projection["upstream_completed_inputs"]["orthology"]["feature_space"][
        "validation"
    ]["row_order_matches"] is True


def test_completed_upstream_authority_does_not_start_a_new_inference_path(
    tmp_path, monkeypatch
):
    project, _contract, _snapshot, _data_dir, _files, _artifact_path, _text = (
        _materialize_project(tmp_path)
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Batch 3 must not invoke an orthology inference process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    ok, reason = _audit_l0_contract(project, "C1")

    assert ok, reason
    binding = l0_data.load_current_round_data_binding(project, "C1")
    assert binding["upstream_completed_inputs"]["orthology"]["status"] == (
        "completed_upstream"
    )


def test_missing_orthogroup_count_fails_closed_at_l0_contract(tmp_path):
    result, _request_path, _request_text, _data_dir, _files = _normalized_plan(tmp_path)
    contract = result["contract"]
    del contract["upstream_completed_inputs"]["orthology"]["orthogroup_count"]

    errors = l0_contract.validate_l0_input_contract(contract, {}, tmp_path, "C1")

    assert any("orthogroup_count" in error for error in errors), errors


def test_formal_species_mismatch_fails_closed_at_l0_contract(tmp_path):
    result, _request_path, _request_text, _data_dir, _files = _normalized_plan(tmp_path)
    contract = result["contract"]
    contract["upstream_completed_inputs"]["orthology"]["formal_species"] = [
        "Mmus",
        "Rn",
        "Sk",
    ]

    errors = l0_contract.validate_l0_input_contract(contract, {}, tmp_path, "C1")

    assert any("formal_species" in error for error in errors), errors


def test_source_hash_mismatch_still_fails_closed_before_upstream_binding(tmp_path):
    project, _contract, _snapshot, _data_dir, files, _artifact_path, _text = (
        _materialize_project(tmp_path)
    )
    files["raw_counts"].write_text(
        files["raw_counts"].read_text(encoding="utf-8") + "G3\t3\t4\n",
        encoding="utf-8",
    )

    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")

    assert exc.value.code == "L0_DATA_CURRENT_HASH_MISMATCH"


def test_feature_row_mismatch_fails_closed_even_if_manifest_is_updated(tmp_path):
    project, contract, snapshot, _data_dir, files, _artifact_path, _text = (
        _materialize_project(tmp_path)
    )
    raw = files["raw_counts"]
    manifest_entry = next(
        item for item in contract["source_input"]["file_manifest"]
        if Path(item["path"]).resolve() == raw.resolve()
    )
    raw.write_text("Mmus_symbol\tS1\tS2\nG1\t1\t2\n", encoding="utf-8")
    manifest_entry["bytes"] = raw.stat().st_size
    manifest_entry["sha256"] = _sha(raw)

    snapshot_text = snapshot.read_text(encoding="utf-8")
    parsed, parse_errors = l0_plan_intake.parse_plan_text_strict(snapshot_text)
    assert parse_errors == []
    snapshot_manifest_entry = next(
        item for item in parsed["source_input"]["file_manifest"]
        if Path(item["path"]).resolve() == raw.resolve()
    )
    snapshot_manifest_entry.update(
        bytes=manifest_entry["bytes"], sha256=manifest_entry["sha256"]
    )
    closing = snapshot_text.find("\n---", 4)
    assert closing >= 0
    snapshot_body = snapshot_text[closing + 4 :]
    snapshot.write_text(
        "---\n"
        + yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
        + "---"
        + snapshot_body,
        encoding="utf-8",
    )
    contract["provenance"]["research_plan_snapshot_sha256"] = _sha(snapshot)
    l0_contract.write_contract(project, "C1", contract)

    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")

    assert exc.value.code == "L0_DATA_FEATURE_SPACE_MISMATCH"


def test_upstream_snapshot_tamper_fails_closed(tmp_path):
    project, _contract, snapshot, _data_dir, _files, _artifact_path, _text = (
        _materialize_project(tmp_path)
    )
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")

    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")

    assert exc.value.code == "L0_DATA_UPSTREAM_PLAN_HASH_MISMATCH"
