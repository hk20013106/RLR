import pytest

from research_loop import research_seed
import research_loop.l05_curie as curie
import research_loop.l05_curie.europepmc as europepmc
import research_loop.l05_curie.europepmc_runtime as europepmc_runtime
from research_loop.l05_curie.multisource import (
    PubMedTransport,
    OpenAlexTransport,
    CrossrefTransport,
    SemanticScholarTransport,
    build_multisource_query_plan,
    canonicalize_pubmed_record,
    canonicalize_openalex_record,
    canonicalize_crossref_record,
    canonicalize_semantic_scholar_record,
    deduplicate_provider_records,
    run_multisource_discovery,
)


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


def test_provider_canonicalizers_emit_one_neutral_identity_shape():
    pubmed = canonicalize_pubmed_record({
        "uid": "123",
        "title": "Bat cardiac physiology",
        "authors": [{"name": "A Author"}],
        "pubdate": "2025 Jan",
        "fulljournalname": "Journal A",
        "articleids": [
            {"idtype": "pubmed", "value": "123"},
            {"idtype": "doi", "value": "10.1000/ABC"},
            {"idtype": "pmc", "value": "PMC999"},
        ],
    })
    openalex = canonicalize_openalex_record({
        "id": "https://openalex.org/W123",
        "title": "Bat cardiac physiology",
        "doi": "https://doi.org/10.1000/abc",
        "publication_year": 2025,
        "authorships": [{"author": {"display_name": "A Author"}}],
        "primary_location": {"source": {"display_name": "Journal A"}},
        "ids": {
            "openalex": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1000/abc",
            "pmid": "https://pubmed.ncbi.nlm.nih.gov/123",
            "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC999",
        },
    })
    crossref = canonicalize_crossref_record({
        "DOI": "10.1000/ABC",
        "title": ["Bat cardiac physiology"],
        "author": [{"given": "A", "family": "Author"}],
        "published": {"date-parts": [[2025, 1, 1]]},
        "container-title": ["Journal A"],
    })
    semantic = canonicalize_semantic_scholar_record({
        "paperId": "S2PAPER",
        "corpusId": 456,
        "title": "Bat cardiac physiology",
        "year": 2025,
        "authors": [{"name": "A Author"}],
        "venue": "Journal A",
        "externalIds": {"DOI": "10.1000/ABC", "PubMed": "123", "PubMedCentral": "PMC999"},
    })

    for record in (pubmed, openalex, crossref, semantic):
        assert set(record) >= {"paper_id", "title", "identifiers", "metadata", "provenance"}
        assert record["identifiers"]["doi"] == "10.1000/abc"
    assert pubmed["identifiers"]["pmid"] == "123"
    assert openalex["identifiers"]["openalex_id"] == "W123"
    assert semantic["identifiers"]["semantic_scholar_paper_id"] == "S2PAPER"
    assert semantic["identifiers"]["semantic_scholar_corpus_id"] == "456"


def test_cross_provider_dedup_merges_identifier_graph_and_provenance():
    records = [
        canonicalize_crossref_record({
            "DOI": "10.1000/abc", "title": ["Bat cardiac physiology"],
            "author": [{"family": "Author"}], "published": {"date-parts": [[2025]]},
        }),
        canonicalize_pubmed_record({
            "uid": "123", "title": "Bat cardiac physiology",
            "articleids": [
                {"idtype": "pubmed", "value": "123"},
                {"idtype": "doi", "value": "10.1000/abc"},
                {"idtype": "pmc", "value": "PMC999"},
            ],
        }),
        canonicalize_openalex_record({
            "id": "https://openalex.org/W123", "title": "Bat cardiac physiology",
            "doi": "https://doi.org/10.1000/abc",
            "ids": {"openalex": "https://openalex.org/W123"},
        }),
    ]
    unique, duplicates = deduplicate_provider_records(records)
    assert len(unique) == 1
    merged = unique[0]
    assert merged["identifiers"]["doi"] == "10.1000/abc"
    assert merged["identifiers"]["pmid"] == "123"
    assert merged["identifiers"]["pmcid"] == "PMC999"
    assert merged["identifiers"]["openalex_id"] == "W123"
    providers = {item["provider"] for item in merged["provenance"]["source_records"]}
    assert providers == {"crossref", "pubmed", "openalex"}
    assert len(duplicates) == 2


def test_dedup_recomputes_canonical_id_independent_of_provider_order():
    europe = europepmc.canonicalize_europepmc_record({
        "id": "EU1", "source": "AGR", "doi": "10.1000/ABC", "pmid": "123",
        "title": "Provider neutral identity", "authorString": "A Author",
        "pubYear": "2025",
    })
    pubmed = canonicalize_pubmed_record({
        "uid": "123", "title": "Provider neutral identity",
        "articleids": [{"idtype": "pubmed", "value": "123"}],
    })

    forward, _forward_duplicates = deduplicate_provider_records([europe, pubmed])
    reverse, _reverse_duplicates = deduplicate_provider_records([pubmed, europe])

    assert len(forward) == len(reverse) == 1
    assert forward[0]["paper_id"] == "P_21e82b6410993caee6a5"
    assert reverse[0]["paper_id"] == "P_21e82b6410993caee6a5"
    assert forward[0]["identifiers"] == {"doi": "10.1000/abc", "pmid": "123"}
    assert reverse[0]["identifiers"] == forward[0]["identifiers"]


def test_dedup_merges_a_transitive_multi_identifier_graph():
    records = [
        canonicalize_crossref_record({"DOI": "10.1000/bridge", "title": ["Bridge"]}),
        canonicalize_pubmed_record({"uid": "456", "title": "Bridge"}),
        europepmc.canonicalize_europepmc_record({
            "id": "EU2", "source": "AGR", "doi": "10.1000/bridge", "pmid": "456",
            "title": "Bridge", "authorString": "A Author", "pubYear": "2025",
        }),
    ]

    unique, duplicates = deduplicate_provider_records(records)

    assert len(unique) == 1
    assert unique[0]["paper_id"] == "P_4b8e31b09e5f55676573"
    assert unique[0]["identifiers"] == {"doi": "10.1000/bridge", "pmid": "456"}
    assert duplicates == sorted(duplicates)


def test_cross_provider_identity_conflict_fails_closed():
    records = [
        canonicalize_pubmed_record({
            "uid": "123", "title": "Paper A",
            "articleids": [{"idtype": "pubmed", "value": "123"},
                           {"idtype": "doi", "value": "10.1000/a"}],
        }),
        canonicalize_crossref_record({"DOI": "10.1000/b", "title": ["Paper B"]}),
        canonicalize_semantic_scholar_record({
            "paperId": "BRIDGE", "title": "Bad bridge",
            "externalIds": {"PubMed": "123", "DOI": "10.1000/b"},
        }),
    ]
    with pytest.raises(curie.CurieContractError, match="cross-provider identity conflict"):
        deduplicate_provider_records(records)


def test_multisource_plan_and_orchestrator_execute_declared_providers(tmp_path):
    seed = _seed()
    seed_hash = research_seed.seed_sha256(seed)
    plan = build_multisource_query_plan(
        seed,
        seed_sha256=seed_hash,
        explicit_queries=["bat cardiac physiology"],
        providers=["pubmed", "openalex", "crossref", "semantic-scholar"],
    )
    assert plan["queries"][0]["providers"] == [
        "pubmed", "openalex", "crossref", "semantic-scholar"
    ]

    def pubmed_http(url, _timeout):
        if "esearch.fcgi" in url:
            return b'{"esearchresult":{"idlist":["123"]}}'
        assert "esummary.fcgi" in url
        return b'{"result":{"uids":["123"],"123":{"uid":"123","title":"Bat cardiac physiology","articleids":[{"idtype":"pubmed","value":"123"},{"idtype":"doi","value":"10.1000/abc"}]}}}'

    fixtures = {
        "openalex": b'{"results":[{"id":"https://openalex.org/W123","title":"Bat cardiac physiology","doi":"https://doi.org/10.1000/abc","ids":{"openalex":"https://openalex.org/W123"}}]}',
        "crossref": b'{"message":{"items":[{"DOI":"10.1000/abc","title":["Bat cardiac physiology"]}]}}',
        "semantic": b'{"data":[{"paperId":"S2PAPER","corpusId":456,"title":"Bat cardiac physiology","externalIds":{"DOI":"10.1000/abc","PubMed":"123"}}]}',
    }

    transports = {
        "pubmed": PubMedTransport(tmp_path, candidate_id="C001", run_id="RUN1", http_get=pubmed_http),
        "openalex": OpenAlexTransport(tmp_path, candidate_id="C001", run_id="RUN1", http_get=lambda _u, _t: fixtures["openalex"]),
        "crossref": CrossrefTransport(tmp_path, candidate_id="C001", run_id="RUN1", http_get=lambda _u, _t: fixtures["crossref"]),
        "semantic-scholar": SemanticScholarTransport(tmp_path, candidate_id="C001", run_id="RUN1", http_get=lambda _u, _t: fixtures["semantic"]),
    }
    result = run_multisource_discovery(plan, transports, page_size=5)
    assert len(result["batches"]) == 4
    assert len(result["records"]) == 1
    assert result["records"][0]["identifiers"]["doi"] == "10.1000/abc"
    assert {batch["provider"] for batch in result["batches"]} == set(transports)
    for batch in result["batches"]:
        assert len(batch["receipt"]["request_sha256"]) == 64
        assert len(batch["receipt"]["response_sha256"]) == 64


def test_multisource_is_the_only_canonical_discovery_orchestration_layer():
    assert callable(europepmc.canonicalize_europepmc_record)
    assert callable(europepmc.EuropePmcTransport)
    assert callable(europepmc.EuropePmcEvidenceRetriever)
    assert callable(europepmc.EuropePmcEvidenceVerifier)

    assert callable(europepmc_runtime.build_multisource_query_plan)
    assert callable(europepmc_runtime.run_multisource_discovery)
    assert callable(europepmc_runtime.select_candidates)

    for name in (
        "build_europepmc_query_plan",
        "deduplicate_discovery_records",
        "select_europepmc_candidates",
    ):
        assert not hasattr(europepmc, name), name
