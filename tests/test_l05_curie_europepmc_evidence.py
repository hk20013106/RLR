import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from research_loop.l05_curie import CurieContractError, validate_evidence_extract
from research_loop.l05_curie.europepmc import (
    EuropePmcEvidenceRetriever,
    EuropePmcEvidenceVerifier,
    canonicalize_europepmc_record,
    lookup_exact_identifiers,
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


def test_exact_identifier_lookup_returns_same_paper_pmcid_and_oa_location():
    calls = []
    fulltext_url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3257301/fullTextXML"
    )
    raw = _raw(
        fullTextUrlList={"fullTextUrl": [{"url": fulltext_url}]}
    )
    payload = json.dumps({
        "hitCount": 1,
        "resultList": {"result": [raw]},
    }).encode("utf-8")

    def http_get(url, timeout):
        calls.append((url, timeout))
        return payload

    result = lookup_exact_identifiers(
        doi="10.1371/journal.ppat.1002485",
        http_get=http_get,
        timeout=7,
    )

    assert result == {
        "doi": "10.1371/journal.ppat.1002485",
        "pmid": "22253597",
        "pmcid": "PMC3257301",
        "registered_locations": [fulltext_url],
    }
    assert len(calls) == 1
    parsed = urlsplit(calls[0][0])
    assert parsed.path.endswith("/search")
    assert parse_qs(parsed.query)["query"] == [
        'DOI:"10.1371/journal.ppat.1002485"'
    ]
    assert calls[0][1] == 7


def test_exact_identifier_lookup_classifies_provider_unavailable():
    def http_get(_url, _timeout):
        raise OSError("network unavailable")

    with pytest.raises(CurieContractError) as exc_info:
        lookup_exact_identifiers(
            doi="10.1371/journal.ppat.1002485",
            http_get=http_get,
        )

    assert type(exc_info.value).__name__ == "EuropePmcLookupUnavailableError"


def test_exact_identifier_lookup_classifies_identity_conflict():
    payload = json.dumps({
        "hitCount": 2,
        "resultList": {
            "result": [
                _raw(pmid="22253597", id="22253597"),
                _raw(pmid="99999999", id="99999999", pmcid="PMC9999999"),
            ]
        },
    }).encode("utf-8")

    with pytest.raises(CurieContractError) as exc_info:
        lookup_exact_identifiers(
            doi="10.1371/journal.ppat.1002485",
            http_get=lambda _url, _timeout: payload,
        )

    assert type(exc_info.value).__name__ == "EuropePmcIdentityConflictError"


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


def test_v2_reads_abstract_methods_captions_unsectioned_body():
    from research_loop.l05_curie.europepmc import parse_jats_paragraphs
    raw = b'''<article><front><abstract><p/><p>abstract</p></abstract></front>
      <body><p>body</p><sec><title>Methods</title><p>method</p>
      <fig><caption><p>caption</p></caption></fig></sec>
      <table-wrap><table><tr><td><p>cell excluded</p></td></tr></table></table-wrap>
      <disp-formula><p>formula excluded</p></disp-formula><p>last</p></body>
      <back><ref-list><sec><title>References</title><p>ref excluded</p></sec></ref-list></back></article>'''
    assert parse_jats_paragraphs(raw, parser_profile="jats-paragraphs/v2") == [
        {"locator": "jats:v2/abstract:1/p:2", "section": "Abstract", "text": "abstract"},
        {"locator": "jats:v2/body/p:1", "section": "Body", "text": "body"},
        {"locator": "sec:1/p:1", "section": "Methods", "text": "method"},
        {"locator": "sec:1/p:2", "section": "Methods", "text": "caption"},
        {"locator": "jats:v2/body/p:6", "section": "Body", "text": "last"},
    ]


def test_v2_nested_node_once_deepest_locator():
    from research_loop.l05_curie.europepmc import parse_jats_paragraphs
    raw = b'<article><body><sec><title>A</title><p/><p>same</p><sec><title>B</title><p>same</p></sec><p>tail</p></sec></body></article>'
    units = parse_jats_paragraphs(raw, parser_profile="jats-paragraphs/v2")
    assert [u["locator"] for u in units] == ["sec:1/p:2", "sec:2/p:1", "sec:1/p:4"]
    assert [u["section"] for u in units] == ["A", "B", "A"]
    assert [u["text"] for u in units] == ["same", "same", "tail"]


def test_v2_identical_text_at_distinct_nodes_survives():
    from research_loop.l05_curie.europepmc import parse_jats_paragraphs
    raw = b'<article><body><p>same</p><p>same</p></body></article>'
    assert parse_jats_paragraphs(raw, parser_profile="jats-paragraphs/v2") == [
        {"locator": "jats:v2/body/p:1", "section": "Body", "text": "same"},
        {"locator": "jats:v2/body/p:2", "section": "Body", "text": "same"}]


def test_long_paragraph_not_truncated_and_invalid_encoding_rejected():
    from research_loop.l05_curie.europepmc import parse_jats_paragraphs
    text = "正文 " * 20000
    raw = ("<article><body><p>" + text + "</p></body></article>").encode("utf-8")
    assert parse_jats_paragraphs(raw, parser_profile="jats-paragraphs/v2")[0]["text"] == text.strip()
    latin = b'<?xml version="1.0" encoding="ISO-8859-1"?><article><body><p>caf\xe9</p></body></article>'
    assert parse_jats_paragraphs(latin, parser_profile="jats-paragraphs/v2")[0]["text"] == "café"
    for bad in (b'<article><p>\xff</p></article>', b'<article>', b'<?xml version="1.0" encoding="no-such-encoding"?><article/>'):
        with pytest.raises(CurieContractError):
            parse_jats_paragraphs(bad, parser_profile="jats-paragraphs/v2")
    with pytest.raises(CurieContractError):
        parse_jats_paragraphs(raw, parser_profile="unknown")


def test_v2_retriever_and_independent_verifier_preserve_profile_and_scope(tmp_path):
    raw = b'<article><front><abstract><p>abstract</p></abstract></front><body><sec><title>Methods</title><p>method</p></sec></body></article>'
    retriever = EuropePmcEvidenceRetriever(tmp_path, candidate_id="C001", run_id="R2",
                                         http_get=lambda _url, _timeout: raw)
    result = retriever.retrieve(canonicalize_europepmc_record(_raw()), seed=_seed(),
                                parser_profile="jats-paragraphs/v2")
    assert [c["text"] for c in result["candidates"]] == ["abstract", "method"]
    verified = EuropePmcEvidenceVerifier(tmp_path, candidate_id="C001").verify(
        result["snapshot"], result["candidates"], parser_profile="jats-paragraphs/v2")
    assert [e["text"] for e in verified] == ["abstract", "method"]
    assert all(e["retrieval"]["parser_profile"] == "jats-paragraphs/v2" for e in verified)
    empty = EuropePmcEvidenceRetriever(tmp_path, candidate_id="C001", run_id="R3",
                                       http_get=lambda _url, _timeout: b'<article><body><p/></body></article>')
    assert empty.retrieve(canonicalize_europepmc_record(_raw()), seed=_seed(),
                          parser_profile="jats-paragraphs/v2")["paper_failure"]["reason_code"] == "NO_USABLE_PARAGRAPHS"
