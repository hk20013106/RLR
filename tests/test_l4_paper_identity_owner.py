from research_loop import deep_research as dr
from research_loop import l4_evidence_bundle as bundle


def test_l4b_reuses_frozen_canonical_paper_id_instead_of_rehashing_source_bytes():
    asset = {
        "asset_id": "L05_P_21e82b6410993caee6a5",
        "source_metadata_response": {
            "paper_id": "P_21e82b6410993caee6a5",
        },
    }

    first = bundle._paper_id(
        dr,
        asset,
        {"receipt": {"content_hash": "a" * 64}},
    )
    second = bundle._paper_id(
        dr,
        asset,
        {"receipt": {"content_hash": "b" * 64}},
    )

    assert first == "P_21e82b6410993caee6a5"
    assert second == "P_21e82b6410993caee6a5"
