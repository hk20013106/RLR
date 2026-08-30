import json
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l05_curie
from research_loop.l05_curie import europepmc
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


def _install_provider(monkeypatch, payload, captured):
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
    monkeypatch.setattr(
        dr,
        "execute_provider_invocation",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )


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


def test_local_identifier_reuse_never_calls_metadata_resolver(monkeypatch, tmp_path):
    catalog = _local_catalog()
    registry_snapshot = ([], _registry_receipt())
    payload = _provider_payload([
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    captured = {}
    _install_provider(monkeypatch, payload, captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    class NoNetwork:
        def __init__(self, *args, **kwargs):
            raise AssertionError("metadata resolver must not start for a local exact source")

    monkeypatch.setattr(europepmc, "EuropePmcTransport", NoNetwork)

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    assert manifest["method_inventory"][0]["source_asset_ids"] == ["L05_P_GSEA"]
    assert manifest["assets"][0]["doi"] == "10.1073/pnas.0506580102"
    assert "10.1186/s13059-014-0550-8" not in captured["prompt"]


def test_registry_resolution_happens_after_cognition_without_network(monkeypatch, tmp_path):
    catalog = _local_catalog()
    receipt = _registry_receipt()
    receipt["canonical_method_ids"] = ["deseq2"]
    registry_snapshot = ([_registry_entry()], receipt)
    payload = _provider_payload([
        _method("deseq2", "DESeq2"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    captured = {}
    _install_provider(monkeypatch, payload, captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    class NoNetwork:
        def __init__(self, *args, **kwargs):
            raise AssertionError("metadata resolver must not start when registry resolves the gap")

    monkeypatch.setattr(europepmc, "EuropePmcTransport", NoNetwork)

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    deseq2 = next(item for item in manifest["method_inventory"] if item["method_id"] == "deseq2")
    assert deseq2["source_asset_ids"]
    assert "10.1186/s13059-014-0550-8" not in captured["prompt"]
    assert manifest["runtime_receipt"]["method_source_registry"]["matches"] == [{
        "method_id": "deseq2",
        "canonical_method_ids": ["deseq2"],
    }]


def test_duplicate_unresolved_method_names_resolve_once(monkeypatch, tmp_path):
    catalog = _local_catalog()
    registry_snapshot = ([], _registry_receipt())
    payload = _provider_payload([
        _method("novel_a", "NovelMethod"),
        _method("novel_b", "NovelMethod"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    captured = {}
    _install_provider(monkeypatch, payload, captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    calls = []

    class FakeEuropePmcTransport:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, request):
            calls.append(dict(request))
            return {
                "provider": "europe-pmc",
                "query_id": request["query_id"],
                "receipt": {
                    "request_sha256": "3" * 64,
                    "response_sha256": "4" * 64,
                    "response_path": "08_Audit/l4/C1/metadata_novel.json",
                    "endpoint": "search",
                },
                "records": [{
                    "paper_id": "P_NOVEL",
                    "title": "NovelMethod: a reproducible analysis framework",
                    "identifiers": {
                        "doi": "10.1000/novelmethod",
                        "pmid": "12345678",
                    },
                    "metadata": {
                        "year": "2024",
                        "journal": "Methods",
                        "authors": "A. Author",
                        "publication_types": [],
                        "is_open_access": False,
                    },
                    "provenance": {"provider": "europe-pmc"},
                }],
                "hit_count": 1,
            }

    monkeypatch.setattr(europepmc, "EuropePmcTransport", FakeEuropePmcTransport)

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    assert len(calls) == 1
    assert calls[0]["query"] == 'TITLE:"NovelMethod"'
    novel = [
        item for item in manifest["method_inventory"]
        if item["method_id"].startswith("novel_")
    ]
    assert all(item["source_asset_ids"] for item in novel)
    assert novel[0]["source_asset_ids"] == novel[1]["source_asset_ids"]


def test_metadata_miss_becomes_explicit_gap_without_query_expansion(monkeypatch, tmp_path):
    catalog = _local_catalog()
    registry_snapshot = ([], _registry_receipt())
    payload = _provider_payload([
        _method("unfindable", "UnfindableMethod"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    captured = {}
    _install_provider(monkeypatch, payload, captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (catalog, registry_snapshot),
    )

    calls = []

    class EmptyEuropePmcTransport:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, request):
            calls.append(dict(request))
            return {
                "provider": "europe-pmc",
                "query_id": request["query_id"],
                "receipt": {
                    "request_sha256": "5" * 64,
                    "response_sha256": "6" * 64,
                    "response_path": "08_Audit/l4/C1/metadata_missing.json",
                    "endpoint": "search",
                },
                "records": [],
                "hit_count": 0,
            }

    monkeypatch.setattr(europepmc, "EuropePmcTransport", EmptyEuropePmcTransport)

    manifest = l4_inventory.run_discovery(
        l4p, dr, tmp_path, "C1", "Q", "H",
        dr.RuntimeSpec("codex", "codex", timeout=3), tmp_path / "work",
        project_id="P1", round_id="1", profile_id="v2.1-catalog-1",
    )

    assert [item["query"] for item in calls] == ['TITLE:"UnfindableMethod"']
    unresolved = next(
        item for item in manifest["method_inventory"]
        if item["method_id"] == "unfindable"
    )
    assert unresolved["source_asset_ids"] == []
    assert unresolved["source_hints"] == []
    resolver = manifest["runtime_receipt"]["metadata_resolution"]
    assert resolver["gaps"] == [{
        "method_ids": ["unfindable"],
        "method_name": "UnfindableMethod",
        "query": 'TITLE:"UnfindableMethod"',
        "reason": "no exact metadata match",
    }]
    assert len(resolver["attempts"]) == 1
