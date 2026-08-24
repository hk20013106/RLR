from pathlib import Path
from types import SimpleNamespace

from research_loop import context, l0_contract, research_seed
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger
import research_loop.l05_curie as curie


def _freeze_native_pack(project: Path, seed: dict, *, run_id="CURIE001"):
    seed_hash = research_seed.seed_sha256(seed)
    plan = {
        "schema_version": curie.QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": "C001",
        "round_id": "1",
        "seed_sha256": seed_hash,
        "plan_id": "QP001",
        "round_index": 1,
        "queries": [{
            "query_id": "Q001",
            "intent": "mechanism",
            "query": "bat high heart rate cardiac physiology",
            "providers": ["europe-pmc"],
        }],
    }
    batch = {
        "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
        "provider": "europe-pmc",
        "query_id": "Q001",
        "receipt": {
            "request_sha256": "1" * 64,
            "response_sha256": "2" * 64,
        },
        "records": [{
            "paper_id": "PMID:123",
            "title": "Bat cardiac physiology",
            "identifiers": {"pmid": "123"},
        }],
    }
    selected = [{
        "paper_id": "PMID:123",
        "title": "Bat cardiac physiology",
        "identifiers": {"pmid": "123"},
        "selection": {
            "decision": "INCLUDE",
            "reason": "direct evidence",
        },
    }]
    evidence = [{
        "schema_version": curie.EVIDENCE_EXTRACT_SCHEMA_VERSION,
        "evidence_id": "NATIVE_SENTINEL_EVIDENCE",
        "paper_id": "PMID:123",
        "section": "Results",
        "text": "NATIVE_CURIE_SENTINEL: bats show a located cardiac physiology result.",
        "locator": "Results paragraph 1",
        "role": "CONTEXT",
        "verification_status": "LOCATED",
        "retrieval": {"engine": "fixture", "source_sha256": "3" * 64},
    }]
    coverage = curie.judge_coverage(
        {"covered": ["verified_full_text_source"], "gaps": []},
        round_index=1,
        max_rounds=3,
    )
    pack = curie.build_evidence_pack(
        candidate_id="C001",
        round_id="1",
        seed_sha256=seed_hash,
        version=1,
        query_plans=[plan],
        discovery_receipts=[batch],
        selected_papers=selected,
        evidence=evidence,
        coverage=coverage,
        gaps=[],
        source_run_id=run_id,
    )
    return curie.freeze_evidence_pack(project, pack)


def _native_project(tmp_path: Path, *, bind_pack=True):
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)

    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="native Curie handoff fixture",
        fmt="text",
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            "C001",
            "1",
            "Why can bats sustain high heart rates?",
            source_input,
            "Cardiac physiology includes adaptive mechanisms.",
        )
    )
    contract_path, contract_hash = l0_contract.write_contract(project, "C001", contract)
    (candidate_dir / "C001.md").write_text(
        "---\n"
        "candidate_id: C001\n"
        "title: Native Curie handoff fixture\n"
        "question: duplicated frontmatter question must not be authoritative\n"
        "claim: duplicated frontmatter claim must not be authoritative\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"schema_version: {contract['schema_version']}\n"
        f"input_contract_path: {contract_path.relative_to(project).as_posix()}\n"
        f"input_contract_hash: {contract_hash}\n"
        "---\n",
        encoding="utf-8",
    )
    seed = research_seed.load_l1_research_seed(project, "C001")
    manifest = _freeze_native_pack(project, seed)
    if bind_pack:
        research_seed.write_l1_native_evidence_binding(
            project, seed, manifest, "CURIE001"
        )
    return project, store, seed, manifest


def _args(project: Path, store: Path):
    return SimpleNamespace(
        project_dir=str(project),
        cand_id="C001",
        node="L1",
        authorization_id=None,
        knowledge_store=str(store),
        template_mode="contract",
        pre_research_mode="full",
        pre_research_token_budget=4000,
        context_token_budget=12000,
        evidence_run_id="CURIE001",
    )


def test_native_l1_consumes_curie_pack_without_legacy_pre_research(
    tmp_path, monkeypatch, capsys
):
    project, store, _seed, _manifest = _native_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    assert not (project / "02_Agent_Notes" / "_pre_research" / "L1_research.md").exists()
    assert not (project / "08_Audit" / "deep_research").exists()

    assert context.cmd_assemble_context(_args(project, store)) == 0
    captured = capsys.readouterr()
    assert "=== L0.5 CURIE FROZEN EVIDENCEPACK ===" in captured.out
    assert "NATIVE_CURIE_SENTINEL" in captured.out
    assert "=== PRE-RESEARCH (deep_research)" not in captured.out
    assert "legacy_summary_injected" not in captured.out


def test_native_v21_without_curie_state_keeps_legacy_gate_until_migrated(
    tmp_path, monkeypatch, capsys
):
    project, store, _seed, _manifest = _native_project(tmp_path, bind_pack=False)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))

    assert context.cmd_assemble_context(_args(project, store)) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "deep-research gate" in captured.err
    assert "native L1 evidence binding gate" not in captured.err


def test_started_native_curie_state_never_falls_back_to_legacy(
    tmp_path, monkeypatch, capsys
):
    project, store, _seed, _manifest = _native_project(tmp_path, bind_pack=False)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    native_root = (
        project / "08_Audit" / "research_seed_bindings" / "native" / "C001" / "1"
    )
    native_root.mkdir(parents=True, exist_ok=True)
    (native_root / "L1_native_broken.json").write_text("{", encoding="utf-8")

    assert context.cmd_assemble_context(_args(project, store)) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "native L1 evidence binding gate" in captured.err
    assert "deep-research gate" not in captured.err


def test_native_l1_revalidates_binding_at_actual_context_use(
    tmp_path, monkeypatch, capsys
):
    project, store, _seed, manifest = _native_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    pack_path = project / manifest["artifact_path"]
    pack_path.write_text(pack_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert context.cmd_assemble_context(_args(project, store)) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "frozen L0.5 EvidencePack" in captured.err
