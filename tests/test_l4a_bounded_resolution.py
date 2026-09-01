import json
from types import SimpleNamespace

import pytest

from research_loop import deep_research as dr
from research_loop import l05_curie
from research_loop import l4_inventory
from research_loop import l4_method_registry
from research_loop import l4_pipeline as l4p
from research_loop import research_seed
import research_loop.l4_contextual_literature as contextual
from research_loop.l05_curie import multisource


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


def _seed():
    return {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C1",
        "round_id": "1",
        "round_type": "initial",
        "scientific_question": "How do mammals use cross-species transcriptomics to adapt cardiac expression?",
        "hypothesis_seed": "Ortholog-aware normalization reveals convergent cardiac transcriptional adaptations.",
        "l0_contract_schema_version": "L0InputContract/v1.1",
        "l0_contract_path": "00_Preflight/C1.json",
        "l0_contract_sha256": "f" * 64,
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


def _planner_query(query_id, query, method_ids):
    return {
        "query_id": query_id,
        "query": query,
        "purpose": "Find comparable studies that used the unresolved analysis action.",
        "status": "planned",
        "receipt": "contextual query planner",
        "method_ids": list(method_ids),
    }


def _planner_payload(queries):
    return {
        "schema_version": "L4AContextualQueryPlan/v1",
        "queries": list(queries),
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
        "abstract": "A contextual method paper.",
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


def _canonical_record(
    *,
    doi="10.5555/contextual",
    title="Cross-species transcriptomics in comparable mammalian studies",
):
    record = multisource.canonicalize_crossref_record({
        "DOI": doi,
        "title": [title],
        "author": [{"family": "Researcher"}],
        "published": {"date-parts": [[2024]]},
        "abstract": "Comparable mammalian studies use ortholog-aware transcriptomics normalization.",
    })
    record["provenance"]["originating_query_ids"] = ["Q001"]
    return record


def _canonical_record_with_identifiers(paper_id, identifiers):
    return {
        "paper_id": paper_id,
        "title": f"Contextual method paper {paper_id}",
        "identifiers": dict(identifiers),
        "metadata": {
            "abstract": "Comparable mammalian studies use this method.",
            "authors": "Researcher",
            "year": "2024",
            "journal": "Methods",
            "is_open_access": bool(identifiers.get("pmcid")),
            "publication_types": ["journal article"],
        },
        "provenance": {
            "provider": "test-provider",
            "originating_query_ids": ["Q001"],
            "source_records": [{"provider": "test-provider"}],
        },
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


def _install_native_seed(monkeypatch):
    seed = _seed()
    monkeypatch.setattr(research_seed, "load_l1_research_seed", lambda *args: seed)
    return seed


def _install_multisource(monkeypatch, records, *, failures=None):
    observed = {}
    original_build = multisource.build_multisource_query_plan

    def build_plan(seed, *, seed_sha256, round_index=1, explicit_queries=None, providers=None):
        observed["seed"] = seed
        observed["seed_sha256"] = seed_sha256
        observed["explicit_queries"] = list(explicit_queries or [])
        observed["providers"] = list(providers or [])
        return original_build(
            seed,
            seed_sha256=seed_sha256,
            round_index=round_index,
            explicit_queries=explicit_queries,
            providers=providers,
        )

    def run_discovery(plan, transports, *, seed_sha256, page_size=25, allow_partial=False):
        observed["plan"] = plan
        observed["transports"] = dict(transports)
        observed["allow_partial"] = allow_partial
        return {
            "schema_version": "L05MultiSourceDiscovery/v1",
            "query_plan_id": plan["plan_id"],
            "batches": [],
            "records": [json.loads(json.dumps(item)) for item in records],
            "duplicate_paper_ids": [],
            "failures": list(failures or []),
        }

    monkeypatch.setattr(multisource, "build_multisource_query_plan", build_plan)
    monkeypatch.setattr(multisource, "run_multisource_discovery_strict", run_discovery)
    return observed


def _run_native(
    monkeypatch,
    tmp_path,
    payloads,
    *,
    catalog=None,
    registry_snapshot=None,
    question=None,
):
    _install_native_seed(monkeypatch)
    captured = {}
    _install_provider_sequence(monkeypatch, payloads, captured)
    monkeypatch.setattr(
        l4_inventory,
        "_native_known_source_catalog",
        lambda *args: (
            catalog or _empty_catalog(),
            registry_snapshot or ([], _registry_receipt()),
        ),
    )
    manifest = l4_inventory.run_discovery(
        l4p,
        dr,
        tmp_path,
        "C1",
        question or _seed()["scientific_question"],
        _seed()["hypothesis_seed"],
        dr.RuntimeSpec("codex", "codex", timeout=3),
        tmp_path / "work",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )
    return manifest, captured


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


def test_contextual_provider_is_a_query_planner_and_cannot_return_assets():
    payload = _planner_payload([
        _planner_query("Q001", "cross species transcriptomics normalization", ["novel_a"]),
    ])
    payload["assets"] = [
        _search_asset(
            "PROVIDER_PAPER",
            "Provider-created paper must be rejected",
            method_ids=["novel_a"],
        )
    ]

    with pytest.raises(dr.DeepResearchError, match="assets"):
        contextual._validate_contextual_payload(l4p, dr, payload, ["novel_a"])


def test_contextual_prompt_forbids_provider_literature_retrieval():
    prompt = contextual._contextual_prompt(
        "Q",
        "H",
        [_method("novel_a", "Cross-species expression normalization")],
        "codex",
    )
    lowered = prompt.casefold()

    assert "query planning" in lowered
    assert "$academic-research-suite" not in lowered
    assert "return only contextual queries" in lowered
    assert "do not return" in lowered
    assert "doi" in lowered
    assert "paper title" in lowered


def test_local_identifier_reuse_skips_contextual_query_planning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        multisource,
        "build_multisource_query_plan",
        lambda *args, **kwargs: pytest.fail("local literature must not create a query plan"),
    )
    payload = _provider_payload([
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    manifest, captured = _run_native(
        monkeypatch,
        tmp_path,
        [payload],
        catalog=_local_catalog(),
        registry_snapshot=([], _registry_receipt()),
    )

    assert len(captured["prompts"]) == 1
    assert manifest["method_inventory"][0]["source_asset_ids"] == ["L05_P_GSEA"]
    assert manifest["assets"][0]["doi"] == "10.1073/pnas.0506580102"


def test_registry_resolution_happens_without_contextual_query_planning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        multisource,
        "run_multisource_discovery_strict",
        lambda *args, **kwargs: pytest.fail("registry-resolved methods must not search"),
    )
    receipt = _registry_receipt()
    receipt["canonical_method_ids"] = ["deseq2"]
    payload = _provider_payload([
        _method("deseq2", "DESeq2"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    manifest, captured = _run_native(
        monkeypatch,
        tmp_path,
        [payload],
        catalog=_local_catalog(),
        registry_snapshot=([_registry_entry()], receipt),
    )

    assert len(captured["prompts"]) == 1
    deseq2 = next(item for item in manifest["method_inventory"] if item["method_id"] == "deseq2")
    assert deseq2["source_asset_ids"]
    assert manifest["runtime_receipt"]["method_source_registry"]["matches"] == [{
        "method_id": "deseq2",
        "canonical_method_ids": ["deseq2"],
    }]


def test_unresolved_methods_use_explicit_queries_in_canonical_multisource(monkeypatch, tmp_path):
    offline = _provider_payload([
        _method("novel_a", "Cross-species expression normalization"),
        _method("novel_b", "Phylogenetic comparative model"),
        _method("gsea", "Gene set enrichment analysis", source_asset_ids=["L05_P_GSEA"]),
    ])
    planner = _planner_payload([
        _planner_query(
            "PLAN_A",
            "cross species transcriptomics ortholog normalization mammals",
            ["novel_a", "novel_b"],
        ),
    ])
    record = _canonical_record()
    observed = _install_multisource(monkeypatch, [record])
    manifest, captured = _run_native(
        monkeypatch,
        tmp_path,
        [offline, planner],
        catalog=_local_catalog(),
        registry_snapshot=([], _registry_receipt()),
        question="Cross-species transcriptome question",
    )

    assert len(captured["prompts"]) == 2
    planner_prompt = captured["prompts"][1].casefold()
    assert "query planning" in planner_prompt
    assert "$academic-research-suite" not in planner_prompt
    assert "novel_a" in planner_prompt
    assert "novel_b" in planner_prompt
    assert "assets" in planner_prompt
    assert 'TITLE:"' not in planner_prompt

    assert observed["explicit_queries"] == [
        "cross species transcriptomics ortholog normalization mammals"
    ]
    assert set(observed["providers"]) == {
        "europe-pmc", "pubmed", "openalex", "crossref", "semantic-scholar",
    }
    assert set(observed["transports"]) == set(observed["providers"])
    assert observed["allow_partial"] is True

    methods = {item["method_id"]: item for item in manifest["method_inventory"]}
    assert methods["novel_a"]["source_asset_ids"] == [record["paper_id"]]
    assert methods["novel_b"]["source_asset_ids"] == [record["paper_id"]]
    assert methods["gsea"]["source_asset_ids"] == ["L05_P_GSEA"]
    contextual_asset = next(
        asset for asset in manifest["assets"]
        if asset["asset_id"] == record["paper_id"]
    )
    assert contextual_asset["asset_id"] == record["paper_id"]
    receipt = manifest["runtime_receipt"]["contextual_literature_search"]
    assert receipt["planner_query_ids"] == ["PLAN_A"]
    assert receipt["query_plan"]["queries"][0]["query"] == observed["plan"]["queries"][0]["query"]
    assert receipt["discovery"]["query_plan_id"] == observed["plan"]["plan_id"]


def test_contextual_discovery_uses_multisource_deduped_identity_without_l4a_dedup(monkeypatch, tmp_path):
    offline = _provider_payload([_method("novel_a", "Cross-species expression normalization")])
    planner = _planner_payload([
        _planner_query("PLAN_A", "cross species expression normalization mammals", ["novel_a"]),
    ])
    record = _canonical_record()
    record["provenance"]["source_records"] = [
        {"provider": "crossref", "raw_record_sha256": "a" * 64},
        {"provider": "pubmed", "raw_record_sha256": "b" * 64},
        {"provider": "openalex", "raw_record_sha256": "c" * 64},
    ]
    _install_multisource(monkeypatch, [record])
    monkeypatch.setattr(
        l4p,
        "deduplicate_l4a_assets",
        lambda *args, **kwargs: pytest.fail("L4A must not deduplicate canonical multisource records"),
    )

    manifest, _captured = _run_native(
        monkeypatch,
        tmp_path,
        [offline, planner],
        catalog=_empty_catalog(),
        registry_snapshot=([], _registry_receipt()),
    )

    assert manifest["assets"][0]["asset_id"] == record["paper_id"]
    assert manifest["assets"][0]["source_metadata_response"]["provenance"]["source_records"] == record["provenance"]["source_records"]


def test_one_multisource_record_can_be_candidate_support_for_multiple_methods(monkeypatch, tmp_path):
    offline = _provider_payload([
        _method("novel_a", "Cross-species expression normalization"),
        _method("novel_b", "Phylogenetic comparative model"),
    ])
    planner = _planner_payload([
        _planner_query("PLAN_A", "comparative transcriptomics phylogenetic mammals", ["novel_a", "novel_b"]),
    ])
    record = _canonical_record(title="Comparative transcriptomics and phylogenetic analysis in mammals")
    _install_multisource(monkeypatch, [record])

    manifest, _captured = _run_native(
        monkeypatch,
        tmp_path,
        [offline, planner],
        catalog=_empty_catalog(),
        registry_snapshot=([], _registry_receipt()),
    )

    methods = {item["method_id"]: item for item in manifest["method_inventory"]}
    assert methods["novel_a"]["source_asset_ids"] == [record["paper_id"]]
    assert methods["novel_b"]["source_asset_ids"] == [record["paper_id"]]
    assert manifest["assets"][0]["method_component_hints"] == ["novel_a", "novel_b"]


def test_zero_multisource_results_keep_methods_unresolved_and_persist_manifest(monkeypatch, tmp_path):
    offline = _provider_payload([_method("unfindable", "Unfindable analysis action")])
    planner = _planner_payload([
        _planner_query("PLAN_A", "similar study unfindable analysis action", ["unfindable"]),
    ])
    _install_multisource(
        monkeypatch,
        [],
        failures=[{
            "provider": "semantic-scholar",
            "query_id": "Q001",
            "error": "transport unavailable",
        }],
    )

    manifest, _captured = _run_native(
        monkeypatch,
        tmp_path,
        [offline, planner],
        catalog=_empty_catalog(),
        registry_snapshot=([], _registry_receipt()),
    )

    assert manifest["selected_asset_ids"] == []
    assert manifest["method_inventory"][0]["source_asset_ids"] == []
    assert (tmp_path / manifest["path"]).is_file()
    receipt = manifest["runtime_receipt"]["contextual_literature_search"]
    assert receipt["discovery"]["records"] == []
    assert receipt["discovery"]["failures"][0]["provider"] == "semantic-scholar"


def test_contextual_path_never_uses_exact_title_method_resolver(monkeypatch, tmp_path):
    offline = _provider_payload([_method("novel_a", "Abstract cross-species method")])
    planner = _planner_payload([
        _planner_query("PLAN_A", "cross species study method normalization", ["novel_a"]),
    ])
    _install_multisource(monkeypatch, [_canonical_record()])
    monkeypatch.setattr(
        l4_inventory,
        "_fixed_title_query",
        lambda *args, **kwargs: pytest.fail('TITLE:"MethodName" resolver must be retired'),
    )

    manifest, _captured = _run_native(
        monkeypatch,
        tmp_path,
        [offline, planner],
        catalog=_empty_catalog(),
        registry_snapshot=([], _registry_receipt()),
    )

    assert all(
        'TITLE:"' not in str(item.get("query") or "")
        for item in manifest["runtime_receipt"]["contextual_literature_search"]["query_plan"]["queries"]
    )


@pytest.mark.parametrize(
    ("label", "identifiers", "expected_decision", "expected_reason"),
    [
        (
            "openalex-only",
            {"openalex_id": "W3114257308"},
            "EXCLUDE",
            "NO_L4B_RETRIEVAL_LOCATOR",
        ),
        (
            "doi",
            {"doi": "10.1000/retrievable-doi"},
            "INCLUDE",
            None,
        ),
        (
            "pmcid",
            {"pmcid": "PMC1234567"},
            "INCLUDE",
            None,
        ),
        (
            "semantic-scholar-only",
            {"semantic_scholar_paper_id": "S2PAPER"},
            "EXCLUDE",
            "NO_L4B_RETRIEVAL_LOCATOR",
        ),
    ],
)
def test_contextual_selector_requires_l4b_retrieval_locator(
    monkeypatch,
    tmp_path,
    label,
    identifiers,
    expected_decision,
    expected_reason,
):
    offline = _provider_payload([_method("novel_a", "Contextual method")])
    planner = _planner_payload([
        _planner_query("PLAN_A", "contextual method paper", ["novel_a"]),
    ])
    record = _canonical_record_with_identifiers(f"P_{label}", identifiers)
    _install_multisource(monkeypatch, [record])
    manifest, _captured = _run_native(
        monkeypatch,
        tmp_path,
        [offline, planner],
        catalog=_empty_catalog(),
        registry_snapshot=([], _registry_receipt()),
    )

    selection = manifest["runtime_receipt"]["contextual_literature_search"]["selection"]
    decision = selection["decisions"][0]
    assert decision["paper_id"] == record["paper_id"]
    assert decision["decision"] == expected_decision
    if expected_reason:
        assert decision["reason_code"] == expected_reason
        assert record["paper_id"] not in selection["included_paper_ids"]
        assert record["paper_id"] not in {
            asset["asset_id"] for asset in manifest["assets"]
        }
    else:
        assert record["paper_id"] in selection["included_paper_ids"]


def test_contextual_selector_closes_native_l4b_manifest_after_filtering(
    monkeypatch, tmp_path
):
    offline = _provider_payload([_method("novel_a", "Contextual method")])
    planner = _planner_payload([
        _planner_query("PLAN_A", "contextual method paper", ["novel_a"]),
    ])
    invalid = _canonical_record_with_identifiers(
        "P_OPENALEX_ONLY", {"openalex_id": "W3114257308"}
    )
    valid_records = [
        _canonical_record_with_identifiers(
            f"P_VALID_{index}", {"doi": f"10.1000/contextual-{index}"}
        )
        for index in range(285)
    ]
    records = [invalid, *valid_records]
    _install_multisource(monkeypatch, records)

    def scorer(record, _seed):
        return {
            "relevance": 1.0 if record["paper_id"] == invalid["paper_id"] else 0.5,
            "directness": 1.0,
            "methodological_value": 1.0,
            "contradiction_value": 0.0,
            "evidence_diversity": 1.0,
            "reason": "Deterministic integration-test score.",
        }

    monkeypatch.setattr(contextual, "_build_selector_scorer", lambda *_: scorer)
    manifest, _captured = _run_native(
        monkeypatch,
        tmp_path,
        [offline, planner],
        catalog=_empty_catalog(),
        registry_snapshot=([], _registry_receipt()),
    )

    contextual_receipt = manifest["runtime_receipt"]["contextual_literature_search"]
    selection = contextual_receipt["selection"]
    assert len(contextual_receipt["discovery"]["records"]) == 286
    assert len(selection["decisions"]) == 286
    invalid_decision = next(
        item for item in selection["decisions"]
        if item["paper_id"] == invalid["paper_id"]
    )
    assert invalid_decision["decision"] == "EXCLUDE"
    assert invalid_decision["reason_code"] == "NO_L4B_RETRIEVAL_LOCATOR"
    assert invalid["paper_id"] not in selection["included_paper_ids"]
    assert len(selection["included_paper_ids"]) == 5

    selected = [
        asset for asset in manifest["assets"]
        if asset["asset_id"] in manifest["selected_asset_ids"]
    ]
    assert len(selected) == 5
    assert all(asset.get("doi") or asset.get("pmid") or asset.get("pmcid") or asset.get("url") for asset in selected)
    ok, reason = l4p.validate_native_l4a_manifest(tmp_path, manifest)
    assert (ok, reason) == (True, "")
