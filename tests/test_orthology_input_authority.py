"""Regression tests for the canonical completed-upstream input authority."""
from __future__ import annotations

import hashlib
import json
import copy
import os
from pathlib import Path

import pytest
import yaml

from research_loop import l0_contract, l0_data, l0_intake, l0_plan_intake
from research_loop.authority import project_context_authorities


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
    assert result["missing_fields"] == []
    assert l0_contract.validate_l0_input_contract(result["contract"], {}, tmp_path, "C1") == []
    authority = result["contract"]["upstream_completed_inputs"]["orthology"]
    assert all(set(item) == {"role", "path"} for item in authority["feature_space"]["aligned_source_files"])
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

    l0_data.write_current_round_data_binding(project, "C1")
    binding = l0_data.verify_current_round_data_binding(project, "C1")
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
        manifest = next(item for item in _contract["source_input"]["file_manifest"] if item["role"] == role)
        current = next(item for item in binding["authorized_inputs"] if item["role"] == role)
        assert source_files[role] == current
        assert source_files[role]["sha256"] == manifest["sha256"]
        assert source_files[role]["bytes"] == manifest["bytes"]

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
    assert l0_contract.validate_l0_input_contract(contract, {}, project, "REAL-C1") == []
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
    sections, _manifest_rows = project_context_authorities(
        project,
        "REAL-C1",
        {"node": "L4", "requires_authorities": ["current_round_data_binding"]},
    )
    projection = json.loads(sections[1])
    assert projection["upstream_completed_inputs"]["orthology"]["feature_space"][
        "validation"
    ]["row_order_matches"] is True


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


def _rewrite_snapshot(project, contract, snapshot, parsed):
    """Re-freeze a synthetic fixture after an intentional declaration change."""
    snapshot.write_text(
        "---\n" + yaml.safe_dump(parsed, sort_keys=False) + "---\n",
        encoding="utf-8",
    )
    contract["provenance"]["research_plan_snapshot_sha256"] = _sha(snapshot)
    l0_contract.write_contract(project, "C1", contract)


@pytest.mark.parametrize("field,value", [
    ("role", "different_role"), ("path", "different.tsv"),
    ("bytes", 999), ("sha256", "f" * 64),
])
def test_frozen_manifest_identity_must_match_contract(tmp_path, field, value):
    project, contract, snapshot, *_ = _materialize_project(tmp_path)
    parsed, errors = l0_plan_intake.parse_plan_text_strict(snapshot.read_text(encoding="utf-8"))
    assert not errors
    parsed["source_input"]["file_manifest"][0][field] = value
    _rewrite_snapshot(project, contract, snapshot, parsed)

    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")
    assert exc.value.code == "L0_DATA_UPSTREAM_PLAN_MISMATCH"


def test_frozen_upstream_declaration_must_match_contract(tmp_path):
    project, contract, snapshot, *_ = _materialize_project(tmp_path)
    parsed, errors = l0_plan_intake.parse_plan_text_strict(snapshot.read_text(encoding="utf-8"))
    assert not errors
    parsed["research_plan"]["scientific_provenance"]["upstream_completed_inputs"]["orthology"]["orthogroup_count"] = 3
    _rewrite_snapshot(project, contract, snapshot, parsed)

    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")
    assert exc.value.code == "L0_DATA_UPSTREAM_PLAN_MISMATCH"


@pytest.mark.parametrize("mutation", [
    "missing_role", "duplicate_role", "unknown_role", "duplicate_path",
    "wrong_path_role", "empty_path", "invalid_path", "missing_list",
])
def test_invalid_aligned_references_fail_at_contract_boundary(tmp_path, mutation):
    result, *_ = _normalized_plan(tmp_path)
    contract = result["contract"]
    feature = contract["upstream_completed_inputs"]["orthology"]["feature_space"]
    aligned = feature["aligned_source_files"]
    if mutation == "missing_role":
        aligned.pop(0)
    elif mutation == "duplicate_role":
        aligned.append(copy.deepcopy(aligned[1]))
    elif mutation == "unknown_role":
        aligned[0]["role"] = "unrecognized_role"
    elif mutation == "duplicate_path":
        aligned[0]["path"] = aligned[1]["path"]
    elif mutation == "wrong_path_role":
        aligned[0]["path"], aligned[1]["path"] = aligned[1]["path"], aligned[0]["path"]
    elif mutation == "empty_path":
        aligned[0]["path"] = ""
    elif mutation == "invalid_path":
        aligned[0]["path"] = "bad\x00path"
    else:
        feature.pop("aligned_source_files")

    errors = l0_contract.validate_l0_input_contract(contract, {}, tmp_path, "C1")
    assert any("aligned_source_files" in error for error in errors), errors


@pytest.mark.parametrize("field,value", [
    ("status", "pending"), ("method", "inferred"), ("policy", "many_to_many"),
    ("species_tree", "different_tree"), ("formal_species", ["Mmus"]),
    ("orthogroup_count", 0), ("orthogroup_count", True),
    ("rows", 0), ("rows", True), ("rows", "2"), ("rows", 3),
    ("key", "gene_id"),
])
def test_invalid_typed_facts_fail_at_contract_boundary(tmp_path, field, value):
    result, *_ = _normalized_plan(tmp_path)
    contract = result["contract"]
    orthology = contract["upstream_completed_inputs"]["orthology"]
    target = orthology["feature_space"] if field in {"rows", "key"} else orthology
    target[field] = value
    errors = l0_contract.validate_l0_input_contract(contract, {}, tmp_path, "C1")
    assert any(field in error for error in errors), errors


@pytest.mark.parametrize("field", ["research_plan_snapshot_path", "research_plan_snapshot_sha256"])
def test_typed_authority_requires_snapshot_provenance(tmp_path, field):
    result, *_ = _normalized_plan(tmp_path)
    contract = result["contract"]
    contract["provenance"].pop(field)
    errors = l0_contract.validate_l0_input_contract(contract, {}, tmp_path, "C1")
    assert any(field in error for error in errors), errors


@pytest.mark.parametrize("table", [
    b"Mmus_symbol\tS1\nG2\t2\nG1\t1\n",
    b"Mmus_symbol\tS1\nG1\t1\n\t2\nG2\t2\n",
    b"Mmus_symbol\tS1\nG1\t1\n\nG2\t2\n",
    b"Mmus_symbol\tS1\nG1\t1\nG1\t2\n",
    b"gene_id\tS1\nG1\t1\nG2\t2\n",
    b"Mmus_symbol\nG1\nG2\n",
    b"Mmus_symbol\tS1\nG1\t1\n\xff\t2\n",
])
def test_invalid_physical_feature_space_fails_with_consistent_manifest(tmp_path, table):
    project, contract, snapshot, _, files, *_ = _materialize_project(tmp_path)
    raw = files["raw_counts"]
    raw.write_bytes(table)
    parsed, errors = l0_plan_intake.parse_plan_text_strict(snapshot.read_text(encoding="utf-8"))
    assert not errors
    for source in (contract["source_input"], parsed["source_input"]):
        entry = next(item for item in source["file_manifest"] if item["role"] == "raw_counts")
        entry.update(bytes=raw.stat().st_size, sha256=_sha(raw))
    _rewrite_snapshot(project, contract, snapshot, parsed)

    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")
    assert exc.value.code == "L0_DATA_FEATURE_SPACE_MISMATCH"


@pytest.mark.parametrize("raw", [b"\xff", b"---\nkey: 1\nkey: 2\n---\n"])
def test_frozen_snapshot_requires_utf8_and_strict_parse(tmp_path, raw):
    project, contract, snapshot, *_ = _materialize_project(tmp_path)
    snapshot.write_bytes(raw)
    contract["provenance"]["research_plan_snapshot_sha256"] = _sha(snapshot)
    l0_contract.write_contract(project, "C1", contract)
    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")
    assert exc.value.code == "L0_DATA_UPSTREAM_PLAN_INVALID"


def test_missing_frozen_snapshot_fails_closed(tmp_path):
    project, _, snapshot, *_ = _materialize_project(tmp_path)
    snapshot.unlink()
    with pytest.raises(l0_data.L0DataError) as exc:
        l0_data.build_current_round_data_binding(project, "C1")
    assert exc.value.code == "L0_DATA_UPSTREAM_PLAN_MISSING"


def test_canonical_join_accepts_equivalent_paths_and_manifest_order(tmp_path):
    project, contract, snapshot, _, files, *_ = _materialize_project(tmp_path)
    parsed, errors = l0_plan_intake.parse_plan_text_strict(snapshot.read_text(encoding="utf-8"))
    assert not errors
    parsed["source_input"]["file_manifest"].reverse()
    for item in contract["source_input"]["file_manifest"]:
        path = Path(item["path"])
        item["path"] = str(path.parent / "unused" / ".." / path.name)
        if os.name == "nt":
            item["path"] = item["path"].upper()
    _rewrite_snapshot(project, contract, snapshot, parsed)
    assert l0_contract.validate_l0_input_contract(contract, {}, project, "C1") == []
    binding = l0_data.build_current_round_data_binding(project, "C1")
    assert len(binding["upstream_completed_inputs"]["orthology"]["feature_space"]["source_files"]) == len(files)


def test_upstream_join_resolves_project_relative_current_records(tmp_path):
    project, contract, _, _, files, *_ = _materialize_project(tmp_path)
    current, _ = l0_data._current_file_records(project, contract["source_input"])
    for record in current:
        record["path"] = os.path.relpath(files[record["role"]], project)
    bound = l0_data._bind_upstream_completed_inputs(project, contract, current)
    assert bound["orthology"]["feature_space"]["source_files"] == current
