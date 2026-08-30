import json
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l05_curie
from research_loop import l4_inventory
from research_loop import l4_method_registry
from research_loop import l4_pipeline as l4p
from research_loop import research_seed


def _provider_payload():
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "method inventory",
            "purpose": "Identify methods required by the hypothesis.",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": [],
        "method_inventory": [{
            "method_id": "deseq2",
            "name": "DESeq2",
            "purpose": "Differential-expression modelling.",
            "inventory_reason": "Required to test the expression contrast.",
            "source_asset_ids": [],
            "source_hints": [],
        }],
    }


def _registry_entry():
    return {
        "canonical_method_id": "deseq2",
        "aliases": ["deseq2", "differential expression deseq2"],
        "source_hints": [{
            "source_ref_id": "deseq2-love-2014",
            "title": "Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2",
            "year": 2014,
            "doi": "10.1186/s13059-014-0550-8",
            "pmid": "25516281",
            "pmcid": "PMC4302049",
            "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
            "source_kind": "method_paper",
            "rationale": "Canonical DESeq2 method paper.",
            "full_text_locations": [
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"
            ],
        }],
    }


def _frozen_pack():
    return {
        "pack_id": "EP_C1_R1_v1",
        "content_sha256": "a" * 64,
        "source_run_id": "RUN1",
        "selected_papers": [{
            "paper_id": "P_GSEA",
            "title": "Gene set enrichment analysis: a knowledge-based approach for interpreting genome-wide expression profiles",
            "identifiers": {
                "doi": "10.1073/pnas.0506580102",
                "pmid": "16199517",
                "pmcid": "PMC1239896",
            },
            "provenance": {
                "provider": "europe-pmc",
                "raw_record_sha256": "b" * 64,
                "originating_query_ids": ["Q001"],
            },
            "selection": {
                "decision": "INCLUDE",
                "reason": "Existing frozen local literature.",
            },
        }],
        "discovery_receipts": [{
            "schema_version": "L05DiscoveryBatch/v1",
            "provider": "europe-pmc",
            "query_id": "Q001",
            "receipt": {
                "request_sha256": "c" * 64,
                "response_sha256": "d" * 64,
                "response_path": "08_Audit/l05_acquisition/C1/RUN1/search_Q001.json",
                "endpoint": "search",
            },
            "records": [],
        }],
        "evidence": [{
            "paper_id": "P_GSEA",
            "retrieval": {
                "engine": "europe-pmc-fulltext-xml/v1",
                "source_sha256": "e" * 64,
                "snapshot_path": "09_Literature_Database/source_snapshots/l05/C1/RUN1/P_GSEA.xml",
                "pmcid": "PMC1239896",
            },
        }],
    }


def test_native_l4a_reuses_frozen_l05_and_registry_before_provider(monkeypatch, tmp_path):
    seed = {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C1",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "Q",
        "hypothesis_seed": "H",
        "l0_contract_path": "00_Preflight/C1.json",
        "l0_contract_sha256": "f" * 64,
    }
    binding = {
        "evidence_pack": {
            "schema_version": "L05EvidencePackManifest/v1",
            "candidate_id": "C1",
            "round_id": "1",
            "seed_sha256": research_seed.seed_sha256(seed),
            "pack_id": "EP_C1_R1_v1",
            "version": 1,
            "artifact_path": "09_Literature_Database/evidence_packs/l05/C1/EP_C1_R1_v1.json",
            "artifact_sha256": "1" * 64,
            "content_sha256": "a" * 64,
            "status": "FROZEN",
        }
    }
    registry_receipt = {
        "schema_version": l4_method_registry.REGISTRY_SCHEMA_VERSION,
        "builtin_path": "research_loop/data/l4_method_source_registry.json",
        "builtin_sha256": "2" * 64,
        "project_path": "",
        "project_sha256": "",
        "canonical_method_ids": ["deseq2"],
    }
    calls = []
    captured = {}

    monkeypatch.setattr(
        research_seed, "load_l1_research_seed",
        lambda project, candidate: calls.append("seed") or seed,
    )
    monkeypatch.setattr(
        research_seed, "active_l1_native_evidence_run_id",
        lambda project, value: calls.append("active") or "RUN1",
    )
    monkeypatch.setattr(
        research_seed, "load_l1_native_evidence_binding",
        lambda project, value, run_id: calls.append("binding") or binding,
    )
    monkeypatch.setattr(
        l05_curie, "load_frozen_evidence_pack",
        lambda *args, **kwargs: calls.append("pack") or _frozen_pack(),
    )

    registry_reads = []

    def load_registry(project):
        registry_reads.append(str(project))
        calls.append("registry")
        return [_registry_entry()], dict(registry_receipt)

    monkeypatch.setattr(l4_method_registry, "load_registry", load_registry)
    monkeypatch.setattr(
        dr,
        "build_invocation",
        lambda *args, **kwargs: (["codex"], "unused generic prompt"),
    )
    monkeypatch.setattr(dr, "resolve_subprocess_executable", lambda value: value)

    def subprocess_invocation(command, prompt):
        captured["prompt"] = prompt
        return command, {}

    monkeypatch.setattr(dr, "subprocess_invocation", subprocess_invocation)

    def execute_provider(command, kwargs, *, timeout, label):
        assert calls[:5] == ["seed", "active", "binding", "pack", "registry"]
        assert len(registry_reads) == 1
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_provider_payload()),
            stderr="",
        )

    monkeypatch.setattr(dr, "execute_provider_invocation", execute_provider)

    manifest = l4_inventory.run_discovery(
        l4p,
        dr,
        tmp_path,
        "C1",
        "Q",
        "H",
        dr.RuntimeSpec("codex", "codex", timeout=3),
        tmp_path / "work",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )

    prompt = captured["prompt"]
    assert "10.1073/pnas.0506580102" in prompt
    assert "10.1186/s13059-014-0550-8" in prompt
    assert "PMC1239896" in prompt
    assert "PMC4302049" in prompt
    assert "known" in prompt.casefold()
    assert "do not" in prompt.casefold()
    assert "method" in prompt.casefold()
    assert len(registry_reads) == 1

    known = manifest["runtime_receipt"]["known_source_catalog"]
    assert known["evidence_pack_id"] == "EP_C1_R1_v1"
    assert known["evidence_pack_content_sha256"] == "a" * 64
    assert len(known["catalog_sha256"]) == 64
    assert manifest["runtime_receipt"]["method_source_registry"] == registry_receipt


def test_native_l4a_fails_closed_without_active_frozen_l05(monkeypatch, tmp_path):
    seed = {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C1",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "Q",
        "hypothesis_seed": "H",
        "l0_contract_path": "00_Preflight/C1.json",
        "l0_contract_sha256": "f" * 64,
    }
    monkeypatch.setattr(research_seed, "load_l1_research_seed", lambda *args: seed)
    monkeypatch.setattr(
        research_seed, "active_l1_native_evidence_run_id", lambda *args: None
    )
    monkeypatch.setattr(
        dr,
        "build_invocation",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not start before the local-literature gate")
        ),
    )

    with pytest.raises(dr.DeepResearchError, match="active frozen L0.5 EvidencePack"):
        l4_inventory.run_discovery(
            l4p,
            dr,
            tmp_path,
            "C1",
            "Q",
            "H",
            dr.RuntimeSpec("codex", "codex", timeout=3),
            tmp_path / "work",
            project_id="P1",
            round_id="1",
            profile_id="v2.1-catalog-1",
        )
