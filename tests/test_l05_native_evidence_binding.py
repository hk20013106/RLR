import json

import pytest

from research_loop import research_seed
import research_loop.l05_curie as curie


def _seed():
    return {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C001",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "How is carbon dioxide sensed by yeast?",
        "hypothesis_seed": "Rca1p regulates the carbon dioxide response.",
        "l0_contract_schema_version": "L0InputContract/v1.1",
        "l0_contract_path": "00_Preflight/l0_input.yaml",
        "l0_contract_sha256": "a" * 64,
    }


def _pack_manifest(tmp_path, *, run_id="CURIE001", version=1,
                   parent_pack_sha256=None, source_gap_request_id=None):
    seed = _seed()
    seed_hash = research_seed.seed_sha256(seed)
    plan = {
        "schema_version": curie.QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": "C001",
        "round_id": "1",
        "seed_sha256": seed_hash,
        "plan_id": f"QP{version:03d}",
        "round_index": version,
        "queries": [{
            "query_id": f"Q{version:03d}",
            "intent": "mechanism",
            "query": "carbon dioxide Rca1p",
            "providers": ["europe-pmc"],
        }],
    }
    batch = {
        "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
        "provider": "europe-pmc",
        "query_id": f"Q{version:03d}",
        "receipt": {
            "request_sha256": str(version) * 64,
            "response_sha256": str(version + 1) * 64,
        },
        "records": [{
            "paper_id": "PMID:22253597",
            "title": "Rca1p carbon dioxide sensing",
            "identifiers": {"pmid": "22253597", "pmcid": "PMC3257301"},
        }],
    }
    selected = [{
        "paper_id": "PMID:22253597",
        "title": "Rca1p carbon dioxide sensing",
        "identifiers": {"pmid": "22253597", "pmcid": "PMC3257301"},
        "selection": {
            "decision": "INCLUDE",
            "reason": "direct empirical evidence",
        },
    }]
    evidence = [{
        "schema_version": curie.EVIDENCE_EXTRACT_SCHEMA_VERSION,
        "evidence_id": f"E{version:03d}",
        "paper_id": "PMID:22253597",
        "section": "Results",
        "text": "Rca1p was required for the carbon dioxide response.",
        "locator": "Results paragraph 1",
        "role": "CONTEXT",
        "verification_status": "LOCATED",
        "retrieval": {
            "engine": "europe-pmc-fulltext-xml/v1",
            "source_sha256": "3" * 64,
        },
    }]
    coverage = curie.judge_coverage(
        {"covered": ["verified_full_text_source"], "gaps": []},
        round_index=version,
        max_rounds=3,
    )
    pack = curie.build_evidence_pack(
        candidate_id="C001",
        round_id="1",
        seed_sha256=seed_hash,
        version=version,
        query_plans=[plan],
        discovery_receipts=[batch],
        selected_papers=selected,
        evidence=evidence,
        coverage=coverage,
        gaps=[],
        parent_pack_sha256=parent_pack_sha256,
        source_gap_request_id=source_gap_request_id,
        source_run_id=run_id,
    )
    return curie.freeze_evidence_pack(tmp_path, pack)


def test_native_binding_does_not_require_legacy_deep_research_run(tmp_path):
    seed = _seed()
    manifest = _pack_manifest(tmp_path, run_id="CURIE001")

    entry = research_seed.write_l1_native_evidence_binding(
        tmp_path, seed, manifest, "CURIE001"
    )

    assert entry["schema_version"] == "L1NativeEvidenceBinding/v1"
    assert entry["evidence_run_id"] == "CURIE001"
    assert entry["evidence_pack_version"] == 1
    assert not (tmp_path / "08_Audit" / "deep_research").exists()

    payload = research_seed.load_l1_native_evidence_binding(
        tmp_path, seed, "CURIE001"
    )
    assert payload["acquisition_run_id"] == "CURIE001"
    assert payload["evidence_pack"] == manifest


def test_native_binding_revalidates_frozen_pack_at_load(tmp_path):
    seed = _seed()
    manifest = _pack_manifest(tmp_path, run_id="CURIE001")
    research_seed.write_l1_native_evidence_binding(
        tmp_path, seed, manifest, "CURIE001"
    )

    pack_path = tmp_path / manifest["artifact_path"]
    pack_path.write_text(pack_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(research_seed.ResearchSeedError, match="frozen L0.5 EvidencePack"):
        research_seed.load_l1_native_evidence_binding(
            tmp_path, seed, "CURIE001"
        )


def test_native_binding_is_append_only_for_same_acquisition_run(tmp_path):
    seed = _seed()
    first = _pack_manifest(tmp_path, run_id="CURIE001")
    research_seed.write_l1_native_evidence_binding(
        tmp_path, seed, first, "CURIE001"
    )

    forged = dict(first)
    forged["pack_id"] = "EP_FORGED"
    with pytest.raises(research_seed.ResearchSeedError, match="different provenance|invalid"):
        research_seed.write_l1_native_evidence_binding(
            tmp_path, seed, forged, "CURIE001"
        )


def test_native_binding_rejects_pack_from_different_acquisition_run(tmp_path):
    seed = _seed()
    manifest = _pack_manifest(tmp_path, run_id="CURIE001")

    with pytest.raises(research_seed.ResearchSeedError, match="source_run_id"):
        research_seed.write_l1_native_evidence_binding(
            tmp_path, seed, manifest, "CURIE_OTHER"
        )


def test_unique_native_binding_run_id_requires_unambiguous_binding(tmp_path):
    seed = _seed()
    first = _pack_manifest(tmp_path, run_id="CURIE001")
    research_seed.write_l1_native_evidence_binding(
        tmp_path, seed, first, "CURIE001"
    )
    assert research_seed.unique_l1_native_evidence_run_id(tmp_path, seed) == "CURIE001"

    first_pack = curie.load_frozen_evidence_pack(
        tmp_path,
        first,
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    second = _pack_manifest(
        tmp_path,
        run_id="CURIE002",
        version=2,
        parent_pack_sha256=first_pack["content_sha256"],
        source_gap_request_id="EGR_TEST",
    )
    research_seed.write_l1_native_evidence_binding(
        tmp_path, seed, second, "CURIE002"
    )
    assert research_seed.unique_l1_native_evidence_run_id(tmp_path, seed) is None


def test_native_binding_payload_is_self_consistent(tmp_path):
    seed = _seed()
    manifest = _pack_manifest(tmp_path, run_id="CURIE001")
    entry = research_seed.write_l1_native_evidence_binding(
        tmp_path, seed, manifest, "CURIE001"
    )
    path = tmp_path / entry["artifact_path"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["research_seed"] == research_seed.manifest_entry(seed)
    assert payload["evidence_pack"]["content_sha256"] == entry["evidence_pack_content_sha256"]
