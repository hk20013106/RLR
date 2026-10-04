import copy
import hashlib
import json
from urllib.error import HTTPError

import pytest

from research_loop.l05_curie import contracts, europepmc_runtime as owner, multisource, selector
from test_l05_curie_corpus_contracts import api


def record(name, *, query_ids=None):
    identity = str(ord(name)) if len(name) == 1 else str(int(hashlib.sha256(name.encode()).hexdigest()[:8], 16))
    return {"paper_id": name, "title": "Paper " + name,
            "identifiers": {"pmcid": "PMC" + identity, "pmid": identity},
            "metadata": {"is_open_access": True, "in_europe_pmc": True},
            "provenance": {"originating_query_ids": query_ids or ["Q1"]}}


def discovery_fixture():
    a, b, c, d = [record(name, query_ids=["Q1", "Q2"] if name == "A" else ["Q1"] if name == "B" else ["Q2"])
                  for name in "ABCD"]
    plan = {"queries": [{"query_id": "Q1", "providers": ["europe-pmc"]},
                        {"query_id": "Q2", "providers": ["europe-pmc"]}]}
    discovery = {"records": [d, c, b, a], "batches": [
        {"query_id": "Q1", "provider": "europe-pmc", "records": [a, b]},
        {"query_id": "Q2", "provider": "europe-pmc", "records": [c, a, d]}]}
    return discovery, plan


def allocate(discovery, plan, **kwargs):
    defaults = dict(existing_papers=[], failed_aliases=[], max_new_papers=30,
                    eligibility=owner._europepmc_full_text_eligibility)
    defaults.update(kwargs)
    return api(selector, "allocate_corpus_candidates")(discovery, query_plan=plan, **defaults)


def test_round_robin_preserves_query_provider_order(monkeypatch):
    discovery, plan = discovery_fixture()
    def forbidden(*args, **kwargs): raise AssertionError("scientific ranking retired")
    monkeypatch.setattr(selector, "_ranking", forbidden)
    monkeypatch.setattr(owner, "_europepmc_selector_score", forbidden)
    result = allocate(discovery, plan)
    assert [p["paper_id"] for p in result["selected"]] == ["A", "C", "B", "D"]
    assert result["selected"][0]["provenance"]["originating_query_ids"] == ["Q1", "Q2"]
    assert set(result) == {"selected", "reserves", "excluded", "provenance"}
    assert allocate(discovery, plan) == result


def test_alias_enrichment_keeps_id_and_skips_refetch(tmp_path):
    match = api(multisource, "match_existing_corpus_record")
    old = record("A")
    enriched = {**record("A"), "paper_id": "NEW_DOI_ID",
                "identifiers": {**old["identifiers"], "doi": "10.1000/new"}}
    assert match(enriched, existing_papers=[old]) == old
    discovery = {"records": [enriched], "batches": [{"query_id": "Q1", "provider": "europe-pmc", "records": [enriched]}]}
    result = allocate(discovery, {"queries": [{"query_id": "Q1", "providers": ["europe-pmc"]}]}, existing_papers=[old])
    assert result["selected"] == [] and result["reserves"] == []
    prepared = {"seed": {"scientific_question": "question", "hypothesis_seed": "claim"},
                "run_id": "run", "worker_mode": "corpus-evidence-v1", "attempt_index": 2,
                "selection": result, "max_new_papers": 30}
    calls = []
    output = owner._execute_europepmc_attempt(prepared, tmp_path, "C1", lambda *a: calls.append(a), 5)
    assert calls == [] and output["source_snapshots"] == []


def test_conflicting_frozen_alias_identity_blocks():
    match = api(multisource, "match_existing_corpus_record")
    old = record("A")
    with pytest.raises(contracts.CurieContractError):
        match(old, existing_papers=[old, {**old, "paper_id": "OTHER"}])
    left = {**old, "identifiers": {**old["identifiers"], "doi": "10.1000/a"}}
    right = {**old, "identifiers": {**old["identifiers"], "doi": "10.1000/b"}}
    with pytest.raises(contracts.CurieContractError): match(right, existing_papers=[left])


def test_alias_conflict_check_never_enriches_frozen_origin():
    old = record("A")
    old["provenance"]["source_records"] = [{"provider": "europe-pmc", "ext_id": "65",
        "raw_record_sha256": "a" * 64, "originating_query_ids": ["Q1"]}]
    new = copy.deepcopy(old)
    new["provenance"]["originating_query_ids"] = ["Q2"]
    new["provenance"]["source_records"][0]["originating_query_ids"] = ["Q2"]
    before = copy.deepcopy(old)
    assert multisource.match_existing_corpus_record(new, existing_papers=[old]) == before
    assert old == before


def entry(name, attempt=1):
    paper = record(name)
    return {"paper": paper, "origin_attempt": attempt,
            "snapshot": {"paper_id": name, "artifact_path": f"sources/{name}.xml", "artifact_sha256": "a" * 64},
            "source_units": [{"source_locator": "sec:1/p:1", "section": "Methods", "source_text": "full text"}]}


def test_limits_30_new_90_total():
    extend = api(owner, "_extend_corpus")
    previous = [entry(f"old{i}") for i in range(70)]
    additions = [entry(f"new{i}", 2) for i in range(20)]
    cumulative = extend(previous, additions, new_limit=30, cumulative_limit=90)
    assert cumulative[:70] == previous and len(cumulative) == 90
    assert extend(previous, additions, new_limit=30, cumulative_limit=90) == cumulative
    for values in ([*additions, entry("overflow", 2)], [entry("old0", 2)]):
        with pytest.raises(contracts.CurieContractError):
            extend(previous, values, new_limit=30, cumulative_limit=90)
    changed = copy.deepcopy(previous[0]); changed["snapshot"]["artifact_sha256"] = "b" * 64
    with pytest.raises(contracts.CurieContractError):
        extend([previous[0], changed], [], new_limit=30, cumulative_limit=90)
    for kwargs in ({"new_limit": True, "cumulative_limit": 90}, {"new_limit": 31, "cumulative_limit": 90},
                   {"new_limit": 30, "cumulative_limit": 91}):
        with pytest.raises(contracts.CurieContractError): extend([], [], **kwargs)


@pytest.mark.parametrize("failure", [404, 410, "empty"])
def test_failed_aliases_and_finite_reserve(tmp_path, failure):
    discovery, plan = discovery_fixture()
    result = allocate(discovery, plan, max_new_papers=1)
    assert [p["paper_id"] for p in result["selected"]] == ["A"]
    assert [p["paper_id"] for p in result["reserves"]] == ["C", "B", "D"]
    calls = []
    def http(url, timeout):
        calls.append(url)
        if "PMC65/" in url:
            if failure == "empty": return b'<article><body><p/></body></article>'
            raise HTTPError(url, failure, "missing", {}, None)
        return b'<article><body><sec><title>Methods</title><p>complete source</p></sec></body></article>'
    prepared = {"seed": {"scientific_question": "question", "hypothesis_seed": "claim"},
                "run_id": "run", "worker_mode": "corpus-evidence-v1", "attempt_index": 1,
                "selection": result, "max_new_papers": 1}
    output = owner._execute_europepmc_attempt(prepared, tmp_path, "C1", http, 5)
    assert len(calls) == 2
    assert [p["paper_id"] for p in output["acquired_papers"]] == ["C"]
    assert len(output["source_snapshots"]) == 1
    assert output["corpus_additions"][0]["source_units"][0]["source_text"] == "complete source"
    assert output["paper_failures"][0]["paper_id"] == "A"
    again = allocate(discovery, plan, existing_papers=[record("C")], failed_aliases=[record("A")], max_new_papers=1)
    assert [p["paper_id"] for p in again["selected"]] == ["B"]


def test_corpus_systemic_source_failure_does_not_promote_reserve(tmp_path):
    discovery, plan = discovery_fixture()
    result = allocate(discovery, plan, max_new_papers=1)
    prepared = {"seed": {"scientific_question": "question", "hypothesis_seed": "claim"},
                "run_id": "run", "worker_mode": "corpus-evidence-v1", "attempt_index": 1,
                "selection": result, "max_new_papers": 1}
    calls = []
    def http(url, timeout): calls.append(url); return b'<malformed'
    with pytest.raises(contracts.CurieContractError):
        owner._execute_europepmc_attempt(prepared, tmp_path, "C1", http, 5)
    assert len(calls) == 1


def test_cumulative_rejects_multiple_frozen_ids_for_one_alias():
    extend = api(owner, "_extend_corpus")
    original = entry("A")
    alias = {**copy.deepcopy(original), "paper": {**original["paper"], "paper_id": "OTHER"},
             "snapshot": {**original["snapshot"], "paper_id": "OTHER"}, "origin_attempt": 2}
    with pytest.raises(contracts.CurieContractError):
        extend([original], [alias], new_limit=30, cumulative_limit=90)


def test_prepare_uses_mechanical_allocator_with_remaining_capacity(tmp_path, monkeypatch):
    from test_l05_curie_europepmc_runtime import _project
    project, seed = _project(tmp_path)
    raw = {"id": "1", "source": "MED", "pmid": "1", "pmcid": "PMC1", "title": "New source",
           "isOpenAccess": "Y", "inEPMC": "Y"}
    response = json.dumps({"hitCount": 1, "resultList": {"result": [raw]}}).encode()
    def forbidden(*args, **kwargs): raise AssertionError("scientific scorer retired")
    monkeypatch.setattr(owner, "_europepmc_selector_score", forbidden)
    prepared = owner._prepare_europepmc_acquisition(
        project, "C001", explicit_queries=["q"], max_papers=1, page_size=25, run_id="run",
        http_get=lambda *_: response, timeout=5, round_index=1,
        worker_mode="corpus-evidence-v1", existing_papers=[], failed_aliases=[])
    assert len(prepared["selection"]["selected"]) == 1
    assert "decisions" not in prepared["selection"]
    assert prepared["worker_mode"] == "corpus-evidence-v1"


def test_allocation_caps_new_sources_at_remaining_90_budget():
    papers = [record(f"new{i}") for i in range(40)]
    old = [record(f"old{i}") for i in range(70)]
    discovery = {"records": papers, "batches": [{"query_id": "Q1", "provider": "europe-pmc", "records": papers}]}
    plan = {"queries": [{"query_id": "Q1", "providers": ["europe-pmc"]}]}
    assert len(allocate(discovery, plan, existing_papers=old)["selected"]) == 20
