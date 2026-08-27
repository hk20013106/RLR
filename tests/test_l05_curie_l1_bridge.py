import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_loop import context, deep_research, l0_contract, l05_context, research_seed
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.hypothesis_ledger import HypothesisLedger
import research_loop.l05_curie as curie


def _seed():
    return {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C001",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "Why can bats sustain high heart rates?",
        "hypothesis_seed": "Cardiac physiology includes adaptive mechanisms.",
        "l0_contract_schema_version": "L0InputContract/v1.1",
        "l0_contract_path": "00_Preflight/l0_input.yaml",
        "l0_contract_sha256": "a" * 64,
    }


def _payload(*, include_conclusion=True):
    extracts = [
        {
            "section": "Results",
            "text": "A located result.",
            "locator": "Results paragraph 2",
            "extraction_method": "fixture",
            "verification_status": "located",
        },
        {
            "section": "Discussion",
            "text": "A located discussion statement.",
            "locator": "Discussion paragraph 1",
            "extraction_method": "fixture",
            "verification_status": "located",
        },
    ]
    if include_conclusion:
        extracts.append(
            {
                "section": "Conclusion",
                "text": "A located conclusion.",
                "locator": "Conclusion paragraph 1",
                "extraction_method": "fixture",
                "verification_status": "located",
            }
        )
    return {
        "schema_version": deep_research.SCHEMA_VERSION,
        "queries": ["bat high heart rate cardiac physiology"],
        "papers": [
            {
                "doi": "10.1000/curie.1",
                "pmid": "",
                "url": "https://example.org/paper",
                "title": "Bat cardiac physiology",
                "source_database": "pubmed",
                "metadata": {"year": 2025, "journal": "Example"},
                "source_metadata_response": {
                    "id": "10.1000/curie.1",
                    "title": "Bat cardiac physiology",
                },
                "open_access": False,
                "content_type": "text/plain",
                "source_payload": "",
                "paper_type": "primary",
                "extracts": extracts,
            }
        ],
        "review_search": {
            "query": "",
            "status": "none_found",
            "receipt": "not required for L1",
        },
        "verification": [],
    }


def _persist_l1(project: Path, *, include_conclusion=True, project_id="PROJECT:1",
                profile_id="native-v2.1"):
    return deep_research.persist_run(
        project,
        "C001",
        "L1",
        _payload(include_conclusion=include_conclusion),
        deep_research.skill_receipt(
            "codex", ["fixture"], "fixture", "test", stdout_hash="f" * 64
        ),
        project_id=project_id,
        round_id="1",
        profile_id=profile_id,
        research_persona="Curie",
    )


def _native_l1_project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(project, profile_id=DEFAULT_NATIVE_PROFILE)
    binding = ledger.require_binding(project)

    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir(parents=True)
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="synthetic L0.5 bridge fixture",
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
    contract_path, contract_hash = l0_contract.write_contract(
        project, "C001", contract
    )
    (candidate_dir / "C001.md").write_text(
        "---\n"
        "candidate_id: C001\n"
        "title: Frozen evidence context fixture\n"
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
    artifact = _persist_l1(
        project,
        project_id=str(binding["project_id"]),
        profile_id=DEFAULT_NATIVE_PROFILE,
    )
    source_summary = project / artifact["summary_path"]
    canonical_summary = (
        project / "02_Agent_Notes" / "_pre_research" / "L1_research.md"
    )
    canonical_summary.parent.mkdir(parents=True, exist_ok=True)
    canonical_summary.write_bytes(source_summary.read_bytes())
    research_seed.write_l1_evidence_binding(project, seed, artifact["run_id"])
    return project, store, artifact


def test_legacy_l1_run_is_snapshotted_into_frozen_l05_pack(tmp_path):
    artifact = _persist_l1(tmp_path)
    seed = _seed()

    manifest = curie.freeze_l1_deep_research_run(
        tmp_path,
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
        run_id=artifact["run_id"],
    )
    frozen = curie.load_frozen_evidence_pack(
        tmp_path,
        manifest,
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )

    assert frozen["status"] == "FROZEN"
    assert frozen["source_run_id"] == artifact["run_id"]
    assert frozen["coverage"]["verdict"] == "PASS"
    assert frozen["coverage"]["covered"] == [
        "located_results_extract",
        "located_discussion_extract",
        "located_conclusion_extract",
    ]
    assert {item["role"] for item in frozen["evidence"]} == {"CONTEXT"}
    assert "A located result." in curie.render_evidence_context(frozen)


def test_legacy_bridge_refuses_run_that_fails_existing_l1_evidence_audit(tmp_path):
    artifact = _persist_l1(tmp_path, include_conclusion=False)

    with pytest.raises(curie.CurieContractError, match="Conclusion"):
        curie.freeze_l1_deep_research_run(
            tmp_path,
            candidate_id="C001",
            round_id="1",
            seed_sha256=research_seed.seed_sha256(_seed()),
            run_id=artifact["run_id"],
        )


def test_research_seed_binding_v2_binds_and_revalidates_frozen_pack(tmp_path):
    artifact = _persist_l1(tmp_path)
    seed = _seed()

    entry = research_seed.write_l1_evidence_binding(
        tmp_path, seed, artifact["run_id"]
    )
    assert entry["schema_version"] == "L1ResearchEvidenceBinding/v2"
    assert entry["evidence_pack_sha256"]
    assert entry["evidence_pack_content_sha256"]

    payload = research_seed.load_l1_evidence_binding(
        tmp_path, seed, artifact["run_id"]
    )
    manifest = payload["evidence_pack"]
    frozen = curie.load_frozen_evidence_pack(
        tmp_path,
        manifest,
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert frozen["source_run_id"] == artifact["run_id"]

    pack_path = tmp_path / manifest["artifact_path"]
    pack_path.write_text(
        pack_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    with pytest.raises(
        research_seed.ResearchSeedError, match="frozen L0.5 EvidencePack"
    ):
        research_seed.load_l1_evidence_binding(
            tmp_path, seed, artifact["run_id"]
        )


def test_research_seed_binding_rejects_non_object_json(tmp_path):
    seed = _seed()
    path = research_seed._evidence_binding_path(tmp_path, seed, "RUN_BAD")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(research_seed.ResearchSeedError, match="object"):
        research_seed.load_l1_evidence_binding(tmp_path, seed, "RUN_BAD")


def test_context_distinguishes_missing_legacy_marker_from_malformed_native_marker():
    assert l05_context._legacy_source_identity_mode({}) is True
    assert l05_context._legacy_source_identity_mode(
        {"native_evidence_binding": {"schema_version": "L1NativeEvidenceBinding/v1"}}
    ) is False
    with pytest.raises(l05_context.L05ContextError, match="native_evidence_binding"):
        l05_context._legacy_source_identity_mode({"native_evidence_binding": None})


def test_native_l1_rejects_legacy_only_evidence_binding(
    tmp_path, monkeypatch, capsys
):
    project, store, artifact = _native_l1_project(tmp_path)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    args = SimpleNamespace(
        project_dir=str(project),
        cand_id="C001",
        node="L1",
        authorization_id=None,
        knowledge_store=str(store),
        template_mode="contract",
        pre_research_mode="full",
        pre_research_token_budget=4000,
        context_token_budget=12000,
        evidence_run_id=artifact["run_id"],
    )

    assert context.cmd_assemble_context(args) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "native L1 evidence binding" in captured.err
