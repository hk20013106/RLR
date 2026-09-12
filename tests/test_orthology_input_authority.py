import hashlib

import yaml

from research_loop import l0_contract, l0_data


def test_declared_upstream_orthology_must_have_the_typed_authority_shape():
    contract = {
        "schema_version": "1.1",
        "candidate_id": "C1",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "Which orthology input is authoritative?",
        "hypothesis_seed": "The completed upstream input must remain byte-bound.",
        "source_input": {"input_type": "inline", "description": "fixture", "files": []},
        "current_round": {"hypothesis": "The binding is authoritative."},
        "upstream_completed_inputs": {"orthology": {"status": "completed_upstream"}},
    }

    errors = l0_contract.validate_l0_input_contract(contract, {}, ".", "C1")

    assert any("upstream_completed_inputs.orthology.method" in error for error in errors)


def test_completed_orthology_projection_rechecks_snapshot_bytes_and_row_order(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sources = []
    for role in l0_contract.ORTHOLOGY_SOURCE_ROLES:
        path = project / f"{role}.tsv"
        path.write_text("Mmus_symbol\tS1\nG1\t1\nG2\t2\n", encoding="utf-8")
        sources.append({
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "role": role,
        })
    orthology = {
        "status": "completed_upstream",
        "method": l0_contract.ORTHOLOGY_METHOD,
        "policy": l0_contract.ORTHOLOGY_POLICY,
        "species_tree": l0_contract.ORTHOLOGY_SPECIES_TREE,
        "orthogroup_count": 2,
        "formal_species": list(l0_contract.ORTHOLOGY_FORMAL_SPECIES),
        "feature_space": {
            "key": l0_contract.ORTHOLOGY_FEATURE_KEY,
            "rows": 2,
            "aligned_source_files": sources,
        },
    }
    snapshot = project / "plan.md"
    snapshot.write_text("---\n" + yaml.safe_dump({
        "research_plan": {"scientific_provenance": {"upstream_completed_inputs": {"orthology": orthology}}},
    }, sort_keys=False) + "---\n", encoding="utf-8")
    contract = {
        "upstream_completed_inputs": {"orthology": orthology},
        "provenance": {
            "research_plan_snapshot_path": snapshot.name,
            "research_plan_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        },
    }
    current = [{
        "path": l0_data._stored_path(project, project / source["path"]),
        "sha256": source["sha256"], "bytes": 1, "role": source["role"],
        "origin": "current_round", "reason": "declared preplan source",
    } for source in sources]

    bound = l0_data._bind_upstream_completed_inputs(project, contract, current)

    assert bound["source_preplan"]["sha256"] == contract["provenance"]["research_plan_snapshot_sha256"]
    assert bound["orthology"]["feature_space"]["validation"]["row_order_matches"] is True
