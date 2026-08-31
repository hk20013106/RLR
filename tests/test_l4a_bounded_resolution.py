import json
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l05_curie
from research_loop import l4_inventory
from research_loop import l4_method_registry
from research_loop import l4_pipeline as l4p
from research_loop import research_seed


def _registry_receipt():
    return {
        "schema_version": l4_method_registry.REGISTRY_SCHEMA_VERSION,
        "builtin_path": "research_loop/data/l4_method_source_registry.json",
        "builtin_sha256": "2" * 64,
        "project_path": "",
        "project_sha256": "",
        "canonical_method_ids": [],
    }


def _registry_entry():
    return {
        "canonical_method_id": "deseq2",
        "aliases": ["deseq2"],
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


def _local_catalog():
    return {
        "evidence_pack": {
            "pack_id": "EP_C1_R1_v1",
            "content_sha256": "a" * 64,
            "artifact_path": "09_Literature_Database/evidence_packs/l05/C1/EP_C1_R1_v1.json",
            "artifact_sha256": "1" * 64,
            "source_run_id": "RUN1",
        },
        "sources": [{
            "asset_id": "L05_P_GSEA",
            "paper_id": "P_GSEA",
            "doi": "10.1073/pnas.0506580102",
            "pmid": "16199517",
            "pmcid": "PMC1239896",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1239896/",
            "title": "Gene set enrichment analysis: a knowledge-based approach for interpreting genome-wide expression profiles",
            "year": 2005,
            "source_path": "09_Literature_Database/source_snapshots/l05/C1/RUN1/P_GSEA.xml",
            "source_sha256": "e" * 64,
            "evidence_status": "frozen",
        }],
    }


def _empty_catalog():
    catalog = _local_catalog()
    catalog["sources"] = []
    return catalog


def _provider_payload(methods):
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "OFFLINE",
            "query": "offline method inventory",
            "purpose": "Inventory methods without literature lookup.",
            "status": "completed",
            "receipt": "controller-bounded offline cognition",
        }],
        "assets": [],
        "method_inventory": methods,
    }


def _method(method_id, name, *, source_asset_ids=None):
    return {
        "method_id": method_id,
        "name": name,
        "purpose": f"Use {name} for the selected hypothesis.",
        "inventory_reason": f"{name} is required by the selected hypothesis.",
        "source_asset_ids": list(source_asset_ids or []),
        "source_hints": [],
    }


def _search_asset(asset_id, title, *, method_ids, doi="10.1000/contextual"):
    return {
        "asset_id": asset_id,
        "doi": doi,
        "pmid": "12345678",
        "url": f"https://doi.org/{doi}",
        "title": title,
        "year": 2024,
        "journal": "Methods",
        "role": "method",
        "abstract": "",
        "source_database": "academic-research-suite",
        "source_metadata_response": json.dumps(
            {"id": asset_id, "title": title},
            sort_keys=True,
            separators=(",", ":"),
        ),
        "open_access_status": "open",
        "full_text_status": "available_oa",
        "full_text_locations": [f"https://doi.org/{doi}"],
        "relevance_score": 9.0,
        "selection_status": "selected",
        "selection_reason": "Method precedent for the supplied scientific context.",
        "hypothesis_ids": [],
        "method_component_hints": list(method_ids),
        "diagnostic_requirements": [],
    }


def _search_payload(assets, *, query="cross-species transcriptomics similar-study methods"):
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "CTX001",
            "query": query,
            "purpose": "Find methods actually used in similar studies.",
            "status": "completed",
            "receipt": "academic-research-suite contextual literature search",
        }],
        "assets": list(assets),
    }


def _install_provider_sequence(monkeypatch, payloads, captured):
    monkeypatch.setattr(
        dr,
        "build_invocation",
        lambda *args, **kwargs: (["codex"], "unused generic prompt"),
    )
    monkeypatch.setattr(dr, "resolve_subprocess_executable", lambda value: value)
    captured["prompts"] = []
    captured["commands"] = []

    def subprocess_invocation(command, prompt):
        captured["prompts"].append(prompt)
        captured["commands"].append(list(command))
        return command, {}

    queue = list(payloads)

    def execute_provider_invocation(*args, **kwargs):
        if not queue:
            raise AssertionError("unexpected extra provider invocation")
        payload = queue.pop(0)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(dr, "subprocess_invocation", subprocess_invocation)
    monkeypatch.setattr(dr, "execute_provider_invocation", execute_provider_invocation)


def test_native_catalog_keeps_registry_out_of_cognitive_context(monkeypatch, tmp_path):
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
    frozen = {
        "pack_id": "EP_C1_R1_v1",
        "content_sha256": "a" * 64,
        "selected_papers": [{
            "paper_id": "P_GSEA",
            "title": _local_catalog()["sources"][0]["title"],
            "identifiers": {
                "doi": "10.1073/pnas.0506580102",
                "pmid": "16199517",
                "pmcid": "PMC1239896",
            },
            "metadata": {
                "year": "2005",
                "abstract": "FULLTEXT_SENTINEL must never reach L4A cognition",
            },
            "provenance": {"provider": "europe-pmc"},
        }],
        "discovery_receipts": [],
        "evidence": [{
            "paper_id": "P_GSEA",
            "text": "EXTRACT_SENTINEL must never reach L4A cognition",
            "retrieval": {
                "source_sha256": "e" * 64,
                "snapshot_path": _local_catalog()["sources"][0]["source_path"],
                "pmcid": "PMC1239896",
            },
        }],
    }
    registry_receipt = _registry_receipt()
    registry_receipt["canonical_method_ids"] = ["deseq2"]

    monkeypatch.setattr(research_seed, "load_l1_research_seed", lambda *args: seed)
    monkeypatch.setattr(research_seed, "active_l1_native_evidence_run_id", lambda *args: "RUN1")
    monkeypatch.setattr(research_seed, "load_l1_native_evidence_binding", lambda *args: binding)
    monkeypatch.setattr(l05_curie, "load_frozen_evidence_pack", lambda *args, **kwargs: frozen)
    monkeypatch.setattr(
        l4_method_registry,
        "load_registry",
        lambda *args: ([_registry_entry()], registry_receipt),
    )

    catalog, registry_snapshot = l4_inventory._native_known_source_catalog(
        tmp_path, "C1", "v2.1-catalog-1", dr
    )

    serialized = json.dumps(catalog, sort_keys=True)
    assert "method_source_registry" not in catalog
    assert "10.1186/s13059-014-0550-8" not in serialized
    assert "FULLTEXT_SENTINEL" not in serialized
    assert "EXTRACT_SENTINEL" not in serialized
    assert catalog["sources"][0]["asset_id"] == "L05_P_GSEA"
    assert catalog["sources"][0]["source_sha256"] == "e" * 64
    assert registry_snapshot[0][0]["canonical_method_id"] == "deseq2"


def test_l4a_prompt_is_offline_inventory_only():
    prompt = l4_inventory.build_prompt("Q", "H", _local_catalog())
    lowered = prompt.casefold()

    assert "academic research skills" not in lowered
    assert "literature-search capability" not in lowered
    assert "do not use network" in lowered
    assert "do not access the filesystem" in lowered
    assert "assets must be an empty array" in lowered
    assert "source_hints" in lowered
    assert "must be empty" in lowered
    assert "source_payload" not in prompt
    assert "extract" not in prompt


def test_local_identifier_reuse_skips_contextual_search(monkeypatch, tmp_path):
    catalog = _local_catalog()
    registry_snapshot = ([], _registry_receipt())
    payload = _provider_payload([
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    captured = {}
    _install_provider_sequence(monkeypatch, [payload], captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    assert len(captured["prompts"]) == 1
    assert manifest["method_inventory"][0]["source_asset_ids"] == ["L05_P_GSEA"]
    assert manifest["assets"][0]["doi"] == "10.1073/pnas.0506580102"


def test_registry_resolution_happens_after_cognition_without_contextual_search(monkeypatch, tmp_path):
    catalog = _local_catalog()
    receipt = _registry_receipt()
    receipt["canonical_method_ids"] = ["deseq2"]
    registry_snapshot = ([_registry_entry()], receipt)
    payload = _provider_payload([
        _method("deseq2", "DESeq2"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    captured = {}
    _install_provider_sequence(monkeypatch, [payload], captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    assert len(captured["prompts"]) == 1
    deseq2 = next(item for item in manifest["method_inventory"] if item["method_id"] == "deseq2")
    assert deseq2["source_asset_ids"]
    assert manifest["runtime_receipt"]["method_source_registry"]["matches"] == [{
        "method_id": "deseq2",
        "canonical_method_ids": ["deseq2"],
    }]


def test_unresolved_methods_use_one_contextual_similar_study_search(monkeypatch, tmp_path):
    catalog = _local_catalog()
    registry_snapshot = ([], _registry_receipt())
    offline = _provider_payload([
        _method("novel_a", "Cross-species expression normalization"),
        _method("novel_b", "Phylogenetic comparative model"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    contextual = _search_payload([
        _search_asset(
            "CTX_P1",
            "A comparative transcriptomics framework across mammalian species",
            method_ids=["novel_a", "novel_b"],
        ),
    ])
    captured = {}
    _install_provider_sequence(monkeypatch, [offline, contextual], captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Cross-species transcriptome question", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    assert len(captured["prompts"]) == 2
    search_prompt = captured["prompts"][1]
    assert "Cross-species transcriptome question" in search_prompt
    assert "novel_a" in search_prompt
    assert "Cross-species expression normalization" in search_prompt
    assert "novel_b" in search_prompt
    assert "Phylogenetic comparative model" in search_prompt
    assert "similar studies" in search_prompt.casefold()
    assert 'TITLE:"' not in search_prompt

    methods = {item["method_id"]: item for item in manifest["method_inventory"]}
    assert methods["novel_a"]["source_asset_ids"] == ["CTX_P1"]
    assert methods["novel_b"]["source_asset_ids"] == ["CTX_P1"]
    assert methods["gsea"]["source_asset_ids"] == ["L05_P_GSEA"]
    assert "metadata_resolution" not in manifest["runtime_receipt"]
    contextual_receipt = manifest["runtime_receipt"]["contextual_literature_search"]
    assert contextual_receipt["method_ids"] == ["novel_a", "novel_b"]
    assert contextual_receipt["query_ids"] == ["CTX001"]


def test_contextual_search_miss_is_persisted_as_unresolved_inventory(monkeypatch, tmp_path):
    catalog = _local_catalog()
    registry_snapshot = ([], _registry_receipt())
    offline = _provider_payload([
        _method("unfindable", "UnfindableMethod"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    contextual = _search_payload([], query="contextual search with no retained source")
    captured = {}
    _install_provider_sequence(monkeypatch, [offline, contextual], captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    unresolved = next(
        item for item in manifest["method_inventory"]
        if item["method_id"] == "unfindable"
    )
    assert unresolved["source_asset_ids"] == []
    assert unresolved["source_hints"] == []
    assert manifest["runtime_receipt"]["contextual_literature_search"]["method_ids"] == [
        "unfindable"
    ]
    assert "metadata_resolution" not in manifest["runtime_receipt"]


def test_all_contextual_misses_still_persist_l4a_manifest(monkeypatch, tmp_path):
    catalog = _empty_catalog()
    registry_snapshot = ([], _registry_receipt())
    offline = _provider_payload([
        _method("unfindable", "UnfindableMethod"),
    ])
    contextual = _search_payload([], query="contextual search with no retained source")
    captured = {}
    _install_provider_sequence(monkeypatch, [offline, contextual], captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    assert manifest["selected_asset_ids"] == []
    assert manifest["method_inventory"][0]["source_asset_ids"] == []
    assert (tmp_path / manifest["path"]).is_file()
