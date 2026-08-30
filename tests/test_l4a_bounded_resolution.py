from research_loop import l4_inventory
from research_loop.l05_curie import multisource as l05_multisource


def _method(method_id, name):
    return {
        "method_id": method_id,
        "name": name,
        "purpose": "Test the selected hypothesis.",
        "inventory_reason": "Required by the selected hypothesis.",
        "source_asset_ids": [],
        "source_hints": [],
    }


def _record():
    return {
        "paper_id": "P_DESEQ2",
        "title": "Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2",
        "identifiers": {
            "doi": "10.1186/s13059-014-0550-8",
            "pmid": "25516281",
            "pmcid": "PMC4302049",
        },
        "metadata": {
            "authors": "Love MI, Huber W, Anders S",
            "year": "2014",
            "journal": "Genome Biology",
            "abstract": "metadata only",
            "publication_types": [],
            "is_open_access": True,
        },
        "provenance": {"provider": "pubmed", "raw_record_sha256": "a" * 64},
    }


def test_l4a_prompt_is_offline_and_registry_blind():
    catalog = {
        "evidence_pack": {"pack_id": "EP1", "content_sha256": "a" * 64},
        "sources": [{
            "paper_id": "P1",
            "doi": "10.1000/local",
            "pmid": "123",
            "pmcid": "PMC123",
            "url": "https://example.org/local",
            "title": "Local paper",
            "year": 2025,
            "source_path": "09_Literature_Database/source_snapshots/P1.xml",
            "source_sha256": "b" * 64,
            "evidence_status": "frozen",
        }],
    }

    prompt = l4_inventory.build_prompt("Q", "H", catalog)
    lowered = prompt.casefold()

    assert "10.1000/local" in prompt
    assert "do not use network" in lowered
    assert "do not search the web" in lowered
    assert "academic research skills literature-search capability" not in lowered
    assert "method_source_registry" not in prompt
    assert "source_payload" not in prompt
    assert "extracts" not in prompt


def test_bounded_resolver_queries_same_method_name_once(monkeypatch, tmp_path):
    calls = []

    class FakePubMedTransport:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, request):
            calls.append(dict(request))
            return {
                "schema_version": "L05DiscoveryBatch/v1",
                "provider": "pubmed",
                "query_id": request["query_id"],
                "receipt": {
                    "request_sha256": "c" * 64,
                    "response_sha256": "d" * 64,
                    "response_path": "08_Audit/l4a_metadata/Q1.json",
                },
                "records": [_record()],
                "hit_count": 1,
            }

    monkeypatch.setattr(l05_multisource, "PubMedTransport", FakePubMedTransport)

    inventory, assets, receipt = l4_inventory._resolve_missing_inventory_sources(
        tmp_path,
        "C1",
        [_method("deseq2-a", "DESeq2"), _method("deseq2-b", "DESeq2")],
    )

    assert len(calls) == 1
    assert calls[0]["query"] == "DESeq2"
    assert len(assets) == 1
    assert inventory[0]["source_asset_ids"] == inventory[1]["source_asset_ids"]
    assert inventory[0]["source_asset_ids"] == [assets[0]["asset_id"]]
    assert receipt["queries"] == [{
        "method_name": "DESeq2",
        "status": "resolved",
        "attempt_count": 1,
        "paper_id": "P_DESEQ2",
    }]
    assert receipt["gaps"] == []


def test_bounded_resolver_miss_becomes_gap_without_query_expansion(monkeypatch, tmp_path):
    calls = []

    class FakePubMedTransport:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, request):
            calls.append(dict(request))
            return {
                "schema_version": "L05DiscoveryBatch/v1",
                "provider": "pubmed",
                "query_id": request["query_id"],
                "receipt": {
                    "request_sha256": "c" * 64,
                    "response_sha256": "d" * 64,
                    "response_path": "08_Audit/l4a_metadata/Q1.json",
                },
                "records": [],
                "hit_count": 0,
            }

    monkeypatch.setattr(l05_multisource, "PubMedTransport", FakePubMedTransport)

    inventory, assets, receipt = l4_inventory._resolve_missing_inventory_sources(
        tmp_path,
        "C1",
        [_method("unknown", "UnknownMethodXYZ")],
    )

    assert len(calls) == 1
    assert calls[0]["query"] == "UnknownMethodXYZ"
    assert inventory[0]["source_asset_ids"] == []
    assert assets == []
    assert receipt["queries"] == [{
        "method_name": "UnknownMethodXYZ",
        "status": "gap",
        "attempt_count": 1,
        "paper_id": "",
    }]
    assert receipt["gaps"] == [{
        "method_ids": ["unknown"],
        "method_name": "UnknownMethodXYZ",
        "reason": "NO_UNAMBIGUOUS_METADATA_MATCH",
    }]
