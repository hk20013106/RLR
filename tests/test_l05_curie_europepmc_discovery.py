import hashlib
import json
from urllib.parse import parse_qs, urlparse

from research_loop.l05_curie import validate_discovery_batch
from research_loop.l05_curie.europepmc import (
    EuropePmcTransport,
    canonicalize_europepmc_record,
)


def _core_result(**overrides):
    result = {
        "id": "22253597",
        "source": "MED",
        "pmid": "22253597",
        "pmcid": "PMC3257301",
        "doi": "10.1371/journal.ppat.1002485",
        "title": "The bZIP Transcription Factor Rca1p Is a Central Regulator of a Novel CO2 Sensing Pathway in Yeast",
        "authorString": "Cottier F, et al.",
        "pubYear": "2012",
        "journalTitle": "PLoS Pathog",
        "isOpenAccess": "Y",
        "inEPMC": "Y",
        "abstractText": "Rca1p is required for transcriptional responses to carbon dioxide.",
        "pubTypeList": {"pubType": ["research-article"]},
    }
    result.update(overrides)
    return result


def test_europepmc_canonicalizer_normalizes_provider_identity():
    first = canonicalize_europepmc_record(_core_result())
    same_doi = canonicalize_europepmc_record(
        _core_result(
            doi="https://doi.org/10.1371/JOURNAL.PPAT.1002485",
            id="PMC3257301",
            source="PMC",
        )
    )

    assert first["identifiers"]["doi"] == "10.1371/journal.ppat.1002485"
    assert first["identifiers"]["pmid"] == "22253597"
    assert first["identifiers"]["pmcid"] == "PMC3257301"
    assert first["paper_id"] == same_doi["paper_id"]
    assert first["provenance"]["provider"] == "europe-pmc"


def test_europepmc_transport_persists_raw_response_and_binds_receipt(tmp_path):
    payload = {
        "hitCount": 1,
        "nextCursorMark": "AoIIP4q0sig1NTIyMDMxNQ==",
        "resultList": {"result": [_core_result()]},
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    seen = []

    def http_get(url, timeout):
        seen.append((url, timeout))
        parsed = urlparse(url)
        assert parsed.path.endswith("/search")
        query = parse_qs(parsed.query)
        assert query["resultType"] == ["core"]
        assert query["format"] == ["json"]
        assert query["pageSize"] == ["5"]
        return raw

    transport = EuropePmcTransport(
        tmp_path,
        candidate_id="C001",
        run_id="RUN001",
        http_get=http_get,
        timeout=7,
    )
    assert transport.handshake() == {
        "schema_version": "DiscoveryTransport/v1",
        "provider": "europe-pmc",
        "capabilities": ["search:core", "fulltext:xml", "cursor-pagination"],
    }

    batch = transport.search(
        {
            "query_id": "Q001",
            "query": "EXT_ID:22253597 AND SRC:MED",
            "page_size": 5,
        }
    )
    validate_discovery_batch(batch, query_ids={"Q001"})
    assert len(seen) == 1
    assert batch["records"][0]["identifiers"]["pmcid"] == "PMC3257301"
    assert batch["receipt"]["response_sha256"] == hashlib.sha256(raw).hexdigest()
    response_path = tmp_path / batch["receipt"]["response_path"]
    assert response_path.read_bytes() == raw
    assert hashlib.sha256(response_path.read_bytes()).hexdigest() == batch["receipt"]["response_sha256"]
