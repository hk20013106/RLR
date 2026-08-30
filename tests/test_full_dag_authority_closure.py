import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from native_v2_helpers import seed_selected_hypothesis
from test_l4b_to_l4c_context import _fetcher, _manifest

from research_loop import deep_research as dr
from research_loop import l0_contract, l0_data
from research_loop import l4_evidence_bundle as bundle
from research_loop import l4_pipeline as l4p
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.context import cmd_assemble_context
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.topology import topology_for_profile


def _goal10_regression_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    binding = ledger.bind_project(project, profile_id=PROFILE_V21_CATALOG_1)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\n"
        "candidate_id: C1\n"
        "question: Which method should test H1?\n"
        "claim: H1 predicts differential expression.\n"
        "round_id: 1\n"
        "current_status: IDEA_SELECTED\n"
        "---\n",
        encoding="utf-8",
    )

    orthology = project / "data" / "MC1OrthologyBinding_v1.json"
    orthology.parent.mkdir(parents=True)
    orthology.write_text(
        json.dumps(
            {
                "schema_version": "MC1OrthologyBinding/v1",
                "mapping_policy": "strict_single_copy",
                "strict_single_copy_orthogroups": 14385,
                "provenance": "FastOMA v0.5.1 with OMAmer",
                "species": [
                    "Mus musculus",
                    "Rattus norvegicus",
                    "Scotophilus kuhlii",
                    "Suncus murinus",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    source = l0_contract.build_source_input(
        input_type="files",
        files=[str(orthology)],
        description="verified strict single-copy orthology authority",
        fmt="json",
    )
    contract = l0_contract.build_initial_contract(
        "C1",
        "1",
        "Which method should test H1?",
        source,
        "H1 predicts differential expression.",
    )
    l0_contract.promote_to_current_schema(contract)
    l0_contract.write_contract(project, "C1", contract)
    l0_data.write_current_round_data_binding(project, "C1")

    seed_selected_hypothesis(project, "C1")
    l4a = _manifest(project, str(binding["project_id"]))
    evidence = bundle.run_l4b_evidence(
        l4p,
        dr,
        project,
        "C1",
        l4a,
        tmp_path / "work",
        project_id=str(binding["project_id"]),
        round_id="1",
        profile_id=PROFILE_V21_CATALOG_1,
        research_persona="Curie",
        fetcher=_fetcher,
    )
    return project, store, evidence


def test_goal10_regression_current_round_authority_reaches_l4(
    tmp_path, monkeypatch, capsys
):
    project, store, evidence = _goal10_regression_project(tmp_path, monkeypatch)
    args = SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        node="L4",
        authorization_id=None,
        knowledge_store=str(store),
        template_mode="contract",
        pre_research_mode="digest",
        pre_research_token_budget=None,
        context_token_budget=12000,
        evidence_run_id=evidence["run_id"],
    )

    assert cmd_assemble_context(args) == 0
    rendered = capsys.readouterr().out
    assert "=== AUTHORITY: current_round_data_binding ===" in rendered
    assert "MC1OrthologyBinding/v1" in rendered
    assert "strict_single_copy_orthogroups" in rendered
    assert "14385" in rendered
    assert "FastOMA v0.5.1 with OMAmer" in rendered

    manifest_path = sorted(
        (project / "08_Audit").glob("context_manifest_L4_*.json")
    )[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "current_round_data_binding" in manifest["required_authorities"]
    injected = {
        item["authority"]: item for item in manifest["injected_authorities"]
    }
    assert injected["current_round_data_binding"]["schema_version"] == (
        "CurrentRoundDataBinding/v1"
    )
    assert injected["current_round_data_binding"]["authorized_input_count"] == 1


def test_native_l4_and_l7_share_one_current_round_authority_owner():
    from research_loop.authority import AUTHORITY_REGISTRY

    _nodes, node_map, _sequence = topology_for_profile(PROFILE_V21_CATALOG_1)
    assert "current_round_data_binding" in node_map["L4"]["requires_authorities"]
    assert "current_round_data_binding" in node_map["L7"]["requires_authorities"]

    spec = AUTHORITY_REGISTRY["current_round_data_binding"]
    assert spec.producer == "L0"
    assert spec.context_consumers == frozenset({"L4"})
    assert spec.execution_consumers == frozenset({"L7"})


def test_l7_execution_consumes_current_round_binding_through_authority_resolver(
    tmp_path, monkeypatch
):
    from research_loop import authority
    from research_loop.commands import execution

    project, _store, _evidence = _goal10_regression_project(tmp_path, monkeypatch)
    calls = []
    original = authority.resolve_authority

    def tracked(project_dir, cand_id, authority_name, *, consumer_node, mode):
        calls.append((authority_name, consumer_node, mode))
        return original(
            project_dir,
            cand_id,
            authority_name,
            consumer_node=consumer_node,
            mode=mode,
        )

    monkeypatch.setattr(authority, "resolve_authority", tracked)
    binding, local_inputs = execution._bound_local_inputs(project, "C1")

    assert binding["schema_version"] == "CurrentRoundDataBinding/v1"
    assert len(local_inputs) == 1
    assert calls == [("current_round_data_binding", "L7", "execution")]


def test_native_full_dag_static_closure_is_closed():
    from research_loop.pre_e2e_closure import audit_static_closure

    report = audit_static_closure(PROFILE_V21_CATALOG_1)
    expected_nodes = {
        "L0", "L0.5", "L1", "L2", "L3", "L4", "L5", "L6", "L7",
        "L8", "L8.5", "L9a", "L9b", "L10a", "L10b", "L10c",
    }
    assert set(report["nodes"]) == expected_nodes
    assert report["e2e_start_allowed"] is True
    assert report["unresolved_required_paths"] == []
    assert all(row["overall"] == "CLOSED" for row in report["nodes"].values())


def test_native_contract_and_execution_closure_are_systematic():
    from research_loop.pre_e2e_closure import audit_static_closure

    report = audit_static_closure(PROFILE_V21_CATALOG_1)
    contract = report["contract_transforms"]
    for node in (
        "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8",
        "L8.5", "L9a", "L9b", "L10a", "L10b",
    ):
        assert contract[node]["wire"] == "CLOSED"
        assert contract[node]["persisted"] == "CLOSED"
    assert contract["L4"]["binding"] == "CLOSED"
    assert report["execution_receipt"]["overall"] == "CLOSED"
    assert report["state_recovery"]["overall"] == "CLOSED"


@pytest.mark.parametrize("provider_override", [None, "manual"])
def test_runner_blocks_before_provider_when_static_closure_is_open(
    tmp_path, monkeypatch, provider_override
):
    import run_loop
    from research_loop import pre_e2e_closure

    project = tmp_path / "project"
    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\ncandidate_id: C1\ncurrent_status: NEW\nround_id: 1\n---\n",
        encoding="utf-8",
    )
    config = tmp_path / "rlr_runner.yaml"
    config.write_text(run_loop.DEFAULT_CONFIG, encoding="utf-8")

    monkeypatch.setattr(
        run_loop,
        "_ctl",
        lambda *args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        run_loop,
        "restore_previous_round",
        lambda *_args, **_kwargs: {"binding_status": "NONE"},
    )
    monkeypatch.setattr(
        run_loop,
        "next_step",
        lambda *_args, **_kwargs: {"profile_id": PROFILE_V21_CATALOG_1},
    )
    monkeypatch.setattr(
        pre_e2e_closure,
        "audit_static_closure",
        lambda _profile_id: {
            "e2e_start_allowed": False,
            "unresolved_required_paths": [
                {"node": "L4", "status": "UNREACHABLE"}
            ],
        },
    )
    provider_started = []

    def forbidden_provider_preflight(*_args, **_kwargs):
        provider_started.append(True)
        return True

    monkeypatch.setattr(run_loop, "preflight_providers", forbidden_provider_preflight)
    args = SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        knowledge_store=None,
        config=str(config),
        max_rounds=None,
        dry_run=False,
        no_review=True,
        provider=provider_override,
    )

    assert run_loop.cmd_run(args) == 3
    assert provider_started == []
