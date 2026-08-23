import json
from pathlib import Path
from types import SimpleNamespace

from research_loop import l0_contract, l0_5_runtime
from research_loop.commands import research
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.preresearch import PRE_RESEARCH_MAP
from research_loop.topology import topology_for_profile


def _write_candidate(project: Path, cand_id: str = "C1") -> None:
    candidates = project / "01_Candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    source_input = l0_contract.build_source_input(
        input_type="inline", description="fixture", fmt="text"
    )
    contract = l0_contract.build_initial_contract(
        cand_id,
        "1",
        "CANONICAL question",
        source_input,
        "CANONICAL hypothesis",
    )
    path, digest = l0_contract.write_contract(project, cand_id, contract)
    (candidates / f"{cand_id}.md").write_text(
        "---\n"
        f"candidate_id: {cand_id}\n"
        "question: WRONG duplicate question\n"
        "claim: WRONG duplicate claim\n"
        "round_id: 1\n"
        "round_type: initial\n"
        f"input_contract_path: {path.relative_to(project).as_posix()}\n"
        f"input_contract_hash: {digest}\n"
        "---\n",
        encoding="utf-8",
    )


def test_native_topology_has_explicit_l0_5_research_node_between_l0_and_l1():
    _nodes, node_map, sequence = topology_for_profile(DEFAULT_NATIVE_PROFILE)

    assert "L0.5" in node_map
    assert sequence.index("L0") + 1 == sequence.index("L0.5")
    assert sequence.index("L0.5") + 1 == sequence.index("L1")

    l05 = node_map["L0.5"]
    assert l05["persona"] == "Curie"
    assert l05["node_kind"] == "research"
    assert l05["research_required"] is True
    assert l05["research_persona"] == "Curie"
    assert l05["pre_research"] == "deep_research"
    assert l05["knowledge_base"] == "read-write"

    l1 = node_map["L1"]
    assert "pre_research" not in l1
    assert l1.get("knowledge_base", "none") == "none"


def test_active_pre_research_configuration_contains_no_hardcoded_domain_queries():
    for node, config in PRE_RESEARCH_MAP.items():
        assert config["queries"] == [], f"{node} still owns hardcoded seed queries"

    serialized = json.dumps(PRE_RESEARCH_MAP, ensure_ascii=False).lower()
    for leaked_example in (
        "heart rate",
        "cardiac",
        "wgcna",
        "bat",
        "shrew",
        "ecm",
        "module preservation",
        "clusterprofiler",
    ):
        assert leaked_example not in serialized


def test_deep_research_declares_l0_5_as_native_discovery_stage():
    from research_loop import deep_research

    assert "L0.5" in deep_research._STAGES


def test_l0_5_deep_research_dispatches_only_canonical_l0_semantics(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "P"
    _write_candidate(project)
    captured = {}

    monkeypatch.setattr(
        research,
        "_deep_research_spec_from_args",
        lambda _args: (SimpleNamespace(), "fixture"),
    )
    monkeypatch.setattr(research.deep_research, "host_matches", lambda *_a, **_k: (True, ""))
    monkeypatch.setattr(research.deep_research, "validate_spec_consistency", lambda _s: (True, ""))
    monkeypatch.setattr(research.deep_research, "runtime_ready", lambda _s: (True, ""))
    monkeypatch.setattr(
        l0_5_runtime.research_evidence_binding,
        "binding_state",
        lambda *_a, **_k: ("missing", ""),
    )

    def fake_run_and_persist(*args, **kwargs):
        captured["node"] = args[2]
        captured["question"] = args[3]
        captured["hypothesis"] = args[4]
        captured["round_id"] = kwargs["round_id"]
        return {"run_id": "L05RUN", "status": "completed"}

    monkeypatch.setattr(research.deep_research, "run_and_persist", fake_run_and_persist)
    monkeypatch.setattr(
        research.deep_research,
        "audit_evidence_pack",
        lambda *_a, **_k: (True, ""),
    )
    monkeypatch.setattr(
        l0_5_runtime.research_evidence_binding,
        "write_binding",
        lambda _project, seed, run_id: captured.update(
            {"bound_seed": seed, "bound_run_id": run_id}
        ),
    )

    args = SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        node="L0.5",
        l4a_manifest="",
        backend=None,
        executable=None,
        plugin_dir=None,
        model=None,
        timeout=None,
        skill_path=None,
        skill_version=None,
        allow_host_mismatch=True,
    )
    assert research.cmd_deep_research_run(args) == 0
    capsys.readouterr()

    assert captured["node"] == "L0.5"
    assert captured["question"] == "CANONICAL question"
    assert captured["hypothesis"] == "CANONICAL hypothesis"
    assert captured["round_id"] == "1"
    assert captured["bound_run_id"] == "L05RUN"
    assert captured["bound_seed"]["scientific_question"] == "CANONICAL question"
