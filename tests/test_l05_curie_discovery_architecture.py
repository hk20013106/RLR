import research_loop.l05_curie.europepmc as europepmc
import research_loop.l05_curie.europepmc_runtime as europepmc_runtime


def test_multisource_is_the_only_canonical_discovery_orchestration_layer():
    # Europe PMC remains a provider-specific primitive: normalization,
    # transport, full-text retrieval, and independent source verification.
    assert callable(europepmc.canonicalize_europepmc_record)
    assert callable(europepmc.EuropePmcTransport)
    assert callable(europepmc.EuropePmcEvidenceRetriever)
    assert callable(europepmc.EuropePmcEvidenceVerifier)

    # Canonical discovery orchestration belongs to the provider-neutral layer.
    assert callable(europepmc_runtime.build_multisource_query_plan)
    assert callable(europepmc_runtime.run_multisource_discovery)
    assert callable(europepmc_runtime.select_candidates)

    # Superseded provider-specific orchestration must not survive in parallel.
    for name in (
        "build_europepmc_query_plan",
        "deduplicate_discovery_records",
        "select_europepmc_candidates",
    ):
        assert not hasattr(europepmc, name), name
