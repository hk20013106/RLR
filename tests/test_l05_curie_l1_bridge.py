import json
from pathlib import Path

import pytest

from research_loop import deep_research, research_seed
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
                "source_metadata_response": {"id": "10.1000/curie.1", "title": "Bat cardiac physiology"},
                "open_access": False,
                "content_type": "text/plain",
                "source_payload": "",
                "paper_type": "primary",
                "extracts": extracts,
            }
        ],
        "review_search": {"query": "", "status": "none_found", "receipt": "not required for L1"},
        "verification": [],
    }


def _persist_l1(project: Path, *, include_conclusion=True):
    return deep_research.persist_run(
        project,
        "C001",
        "L1",
        _payload(include_conclusion=include_conclusion),
        deep_research.skill_receipt(
            "codex", ["fixture"], "fixture", "test", stdout_hash="f" * 64
        ),
        project_id="PROJECT:1",
        round_id="1",
        profile_id="native-v2.1",
        research_persona="Curie",
    )


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
    pack_path.write_text(pack_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(research_seed.ResearchSeedError, match="frozen L0.5 EvidencePack"):
        research_seed.load_l1_evidence_binding(
            tmp_path, seed, artifact["run_id"]
        )
