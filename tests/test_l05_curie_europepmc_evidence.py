import hashlib

import pytest

from research_loop.l05_curie import CurieContractError, validate_evidence_extract
from research_loop.l05_curie.europepmc import (
    EuropePmcEvidenceRetriever,
    EuropePmcEvidenceVerifier,
    canonicalize_europepmc_record,
    select_europepmc_candidates,
)


XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec id="s1"><title>Introduction</title><p>Background carbon dioxide biology.</p></sec>
    <sec id="s2"><title>Results</title>
      <p>Rca1p was required for the transcriptional response to carbon dioxide.</p>
      <p>Deletion of RCA1 abolished induction under elevated carbon dioxide.</p>
    </sec>
    <sec id="s3"><title>Discussion</title>
      <p>These results identify Rca1p as a central regulator of carbon dioxide sensing.</p>
    </sec>
    <sec id="s4"><title>Conclusion</title>
      <p>Rca1p links carbon dioxide exposure to downstream transcriptional regulation.</p>
    </sec>
  </body>
</article>
'''


def _seed():
    return {
        "scientific_question": "How is carbon dioxide sensed by yeast?",
        "hypothesis_seed": "Rca1p regulates the carbon dioxide transcriptional response.",
    }


def _raw(**overrides):
    item = {
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
        "abstractText": "Rca1p regulates the response to carbon dioxide.",
        "pubTypeList": {"pubType": ["research-article"]},
    }
    item.update(overrides)
    return item


def test_selector_preserves_include_exclude_reserve_decisions():
    best = canonicalize_europepmc_record(_raw())
    no_fulltext = canonicalize_europepmc_record(
        _raw(
            id="99999999", pmid="99999999", pmcid="", doi="10.1000/no-fulltext",
            title="Related carbon dioxide paper without Europe PMC full text",
            isOpenAccess="N", inEPMC="N",
        )
    )
    reserve = canonicalize_europepmc_record(
        _raw(
            id="88888888", pmid="88888888", pmcid="PMC8888888", doi="10.1000/reserve",
            title="Another open access carbon dioxide response paper",
        )
    )

    result = select_europepmc_candidates(
        [best, no_fulltext, reserve], seed=_seed(), max_papers=1
    )
    assert [item["paper_id"] for item in result["selected"]] == [best["paper_id"]]
    by_id = {item["paper_id"]: item for item in result["decisions"]}
    assert by_id[best["paper_id"]]["decision"] == "INCLUDE"
    assert by_id[no_fulltext["paper_id"]]["decision"] == "EXCLUDE"
    assert by_id[no_fulltext["paper_id"]]["reason_code"] == "NO_OPEN_FULL_TEXT"
    assert by_id[reserve["paper_id"]]["decision"] == "RESERVE"


def test_retriever_snapshots_xml_and_verifier_relocates_exact_text(tmp_path):
    paper = canonicalize_europepmc_record(_raw())

    def http_get(url, timeout):
        assert url.endswith("/PMC3257301/fullTextXML")
        assert timeout == 9
        return XML

    retriever = EuropePmcEvidenceRetriever(
        tmp_path,
        candidate_id="C001",
        run_id="RUN001",
        http_get=http_get,
        timeout=9,
    )
    result = retriever.retrieve(paper, seed=_seed())
    snapshot = result["snapshot"]
    candidates = result["candidates"]

    assert snapshot["artifact_sha256"] == hashlib.sha256(XML).hexdigest()
    assert (tmp_path / snapshot["artifact_path"]).read_bytes() == XML
    assert {item["section"] for item in candidates} == {"Results", "Discussion", "Conclusion"}
    assert all(item["verification_status"] == "UNVERIFIED" for item in candidates)

    verifier = EuropePmcEvidenceVerifier(tmp_path, candidate_id="C001")
    verified = verifier.verify(snapshot, candidates)
    assert len(verified) == len(candidates)
    assert all(item["verification_status"] == "LOCATED" for item in verified)
    assert all(item["retrieval"]["source_sha256"] == snapshot["artifact_sha256"] for item in verified)
    for item in verified:
        validate_evidence_extract(item)


def test_verifier_rejects_tampered_source_snapshot(tmp_path):
    paper = canonicalize_europepmc_record(_raw())
    retriever = EuropePmcEvidenceRetriever(
        tmp_path,
        candidate_id="C001",
        run_id="RUN001",
        http_get=lambda _url, _timeout: XML,
    )
    result = retriever.retrieve(paper, seed=_seed())
    path = tmp_path / result["snapshot"]["artifact_path"]
    path.write_bytes(XML + b"\n<!-- tampered -->\n")

    verifier = EuropePmcEvidenceVerifier(tmp_path, candidate_id="C001")
    with pytest.raises(CurieContractError, match="source snapshot SHA-256"):
        verifier.verify(result["snapshot"], result["candidates"])
