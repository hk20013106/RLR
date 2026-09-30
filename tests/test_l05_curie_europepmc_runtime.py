import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from research_loop import l0_contract, research_seed
from research_loop import deep_research, structured_execution
from research_loop.l05_curie import CurieContractError, load_frozen_evidence_pack
from research_loop.l05_curie import europepmc_runtime
from research_loop.l05_curie import query_planner
from research_loop.l05_curie.europepmc_runtime import (
    run_europepmc_acquisition as _run_europepmc_acquisition,
)
from research_loop.l05_curie.multisource import build_multisource_query_plan
from research_loop.l05_curie.paperqa2_runtime import (
    MIN_SOURCE_TOKEN_COVERAGE,
    PaperQA2CurieRuntime,
    align_paperqa2_chunks,
)
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop import cli
from test_l05_curie_p1_planning import _planner_schema_plan


XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<article><body>
<sec><title>Results</title><p>Rca1p was required for the transcriptional response to carbon dioxide.</p></sec>
<sec><title>Discussion</title><p>These results identify Rca1p as a central regulator of carbon dioxide sensing.</p></sec>
<sec><title>Conclusion</title><p>Rca1p links carbon dioxide exposure to downstream transcriptional regulation.</p></sec>
</body></article>'''

XML_WITHOUT_TARGET_SECTIONS = b'''<?xml version="1.0" encoding="UTF-8"?>
<article><body>
<sec><title>Introduction</title><p>Background only; no located interpretive evidence.</p></sec>
<sec><title>Methods</title><p>A methods-only record is not Results, Discussion, or Conclusion evidence.</p></sec>
</body></article>'''


def _project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir()
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="synthetic Europe PMC runtime fixture",
        fmt="text",
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            "C001",
            "1",
            "How is carbon dioxide sensed by yeast?",
            source_input,
            "Rca1p regulates the carbon dioxide transcriptional response.",
        )
    )
    contract_path, contract_hash = l0_contract.write_contract(project, "C001", contract)
    (candidate_dir / "C001.md").write_text(
        "---\n"
        "candidate_id: C001\n"
        "title: Europe PMC runtime fixture\n"
        "question: duplicated frontmatter question is not authoritative\n"
        "claim: duplicated frontmatter claim is not authoritative\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"schema_version: {contract['schema_version']}\n"
        f"input_contract_path: {contract_path.relative_to(project).as_posix()}\n"
        f"input_contract_hash: {contract_hash}\n"
        "---\n",
        encoding="utf-8",
    )
    return project, research_seed.load_l1_research_seed(project, "C001")


def _host_planner_plan(seed):
    def anchor(field, snippet, concept_id):
        source = seed[field]
        start = source.index(snippet)
        return {
            "concept_id": concept_id,
            "term": snippet,
            "source_type": "QUESTION" if field == "scientific_question" else "INITIAL_HYPOTHESIS",
            "source_field": field,
            "text_snippet": snippet,
            "source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "start": start,
            "end": start + len(snippet),
            "synonyms": [],
        }

    return {
        "schema_version": query_planner.SCIENTIFIC_QUERY_PLAN_V2,
        "planner": query_planner.SCIENTIFIC_QUERY_PLANNER_V2,
        "seed_sha256": research_seed.seed_sha256(seed),
        "reformulation_index": 0,
        "core_anchors": [
            anchor("scientific_question", "carbon dioxide", "carbon-dioxide"),
            anchor("hypothesis_seed", "Rca1p", "rca1p"),
        ],
        "optional_concepts": [],
        "unresolved_entities": [],
        "advisory_search_constraints": [],
        "intents": [{
            "intent_id": "target-evidence",
            "core_concept_ids": ["carbon-dioxide", "rca1p"],
            "optional_concept_ids": [],
        }],
    }


def test_host_and_headless_planners_compile_identical_query_content(tmp_path, monkeypatch):
    _project_dir, seed = _project(tmp_path)
    payload = {"status": "PLAN", "reason": "direct seed concepts", "plan": _planner_schema_plan(_host_planner_plan(seed))}
    raw_response = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    prepare = getattr(query_planner, "prepare_scientific_query_plan_request", None)
    submit = getattr(query_planner, "validate_scientific_query_plan_response", None)
    assert callable(prepare), (
        "PLANNER_HANDOFF_MISSING: prepare_scientific_query_plan_request is absent"
    )
    assert callable(submit), (
        "PLANNER_HANDOFF_MISSING: validate_scientific_query_plan_response is absent"
    )
    request = prepare(seed, reformulation_index=0, feedback=None)
    host_result = submit(seed, request=request, raw_response=raw_response)

    monkeypatch.setattr(
        structured_execution,
        "run_structured_model",
        lambda *_args, **_kwargs: {
            "payload": payload,
            "receipt": {"validation_status": "PASS"},
            "raw_output": raw_response.decode("utf-8"),
        },
    )
    headless_result = query_planner.propose_scientific_query_plan(
        seed, spec=object(), work_dir=tmp_path / "headless",
        reformulation_index=0,
    )

    host_query_hashes = [item["query_content_hash"] for item in host_result["compiled_queries"]]
    headless_query_hashes = [
        item["query_content_hash"]
        for item in query_planner.compile_scientific_query_plan(
            headless_result["plan"], seed=seed
        )
    ]
    assert host_result["plan"]["plan_content_hash"] == headless_result["plan"]["plan_content_hash"]
    assert host_query_hashes == headless_query_hashes


def _search_record(
    *, pmid="22253597", pmcid="PMC3257301", doi="10.1371/journal.ppat.1002485",
    title=None, open_access=True, abstract=None,
):
    return {
        "id": pmid,
        "source": "MED",
        "pmid": pmid,
        "pmcid": pmcid if open_access else "",
        "doi": doi,
        "title": title or "The bZIP Transcription Factor Rca1p Is a Central Regulator of a Novel CO2 Sensing Pathway in Yeast",
        "authorString": "Cottier F, et al.",
        "pubYear": "2012",
        "journalTitle": "PLoS Pathog",
        "isOpenAccess": "Y" if open_access else "N",
        "inEPMC": "Y" if open_access else "N",
        "abstractText": abstract if abstract is not None else "Rca1p regulates the response to carbon dioxide.",
        "pubTypeList": {"pubType": ["research-article"]},
    }


def _search_payload(*, open_access=True, records=None):
    records = records or [_search_record(open_access=open_access)]
    return json.dumps(
        {"hitCount": len(records), "resultList": {"result": records}}, sort_keys=True
    ).encode("utf-8")


def _supported_semantic_assessment(*, extract, claim):
    assert claim != extract["text"]
    assert "Scientific question:" in claim
    assert "Hypothesis seed:" in claim
    return {
        "entailment": "SUPPORTED",
        "scope_match": True,
        "context_preserved": True,
        "qualification_preserved": True,
        "reason": "The located paragraph directly addresses the ResearchSeed semantic target.",
    }


def _located(evidence_id: str, text: str, locator: str) -> dict:
    return {
        "schema_version": "L05EvidenceExtract/v1",
        "evidence_id": evidence_id,
        "paper_id": "P1",
        "section": "Results",
        "text": text,
        "locator": locator,
        "role": "CONTEXT",
        "verification_status": "LOCATED",
        "retrieval": {"engine": "fixture", "source_sha256": "a" * 64},
    }


def test_runtime_freezes_end_to_end_europepmc_evidence_pack(tmp_path):
    project, seed = _project(tmp_path)
    search = _search_payload()
    calls = []

    def http_get(url, timeout):
        calls.append(url)
        if "/search?" in url:
            return search
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project,
        "C001",
        explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
        max_papers=1,
        page_size=5,
        run_id="RUN001",
        http_get=http_get,
        timeout=7,
    )

    assert result["status"] == "FROZEN"
    assert result["run_id"] == "RUN001"
    assert result["coverage"]["verdict"] == "PASS"
    assert len(calls) == 2
    assert any("/search?" in url for url in calls)
    assert any(url.endswith("/PMC3257301/fullTextXML") for url in calls)

    manifest = result["evidence_pack"]
    frozen = load_frozen_evidence_pack(
        project,
        manifest,
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert frozen["source_run_id"] == "RUN001"
    assert frozen["discovery_receipts"][0]["provider"] == "europe-pmc"
    assert frozen["selected_papers"][0]["identifiers"]["pmcid"] == "PMC3257301"
    assert {item["section"] for item in frozen["evidence"]} == {
        "Results", "Discussion", "Conclusion"
    }
    assert all(item["verification_status"] == "LOCATED" for item in frozen["evidence"])

    audit_path = project / result["acquisition_manifest_path"]
    assert hashlib.sha256(audit_path.read_bytes()).hexdigest() == result["acquisition_manifest_sha256"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["selection"]["decisions"][0]["decision"] == "INCLUDE"
    assert len(audit["source_snapshots"]) == 1
    assert audit["coverage"]["verdict"] == "PASS"
    assert audit["evidence_pack"]["artifact_sha256"] == manifest["artifact_sha256"]


def test_two_empty_plans_stop_without_repeating_a_plan(tmp_path):
    project, _seed = _project(tmp_path)
    requested = []

    def http_get(url, _timeout):
        assert "/search?" in url
        requested.append(parse_qs(urlparse(url).query)["query"][0])
        return json.dumps({"hitCount": 0, "resultList": {"result": []}}).encode()

    result = run_europepmc_acquisition(
        project, "C001", run_id="EMPTY_PLANS", http_get=http_get,
    )
    manifest_path = project / result["acquisition_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "INSUFFICIENT_STOP"
    assert result["terminal_reason"] == "no_admissible_replan"
    assert manifest["schema_version"] == "L05EuropePmcAcquisitionManifest/v2"
    assert [attempt["attempt_index"] for attempt in manifest["attempts"]] == [1, 2]
    assert len({attempt["query_plan"]["plan_id"] for attempt in manifest["attempts"]}) == 2
    assert len(requested) == len(set(requested))
    assert result["evidence_pack"] is None


def test_second_plan_first_success_freezes_canonical_v1(tmp_path):
    project, seed = _project(tmp_path)
    queries = []

    def http_get(url, _timeout):
        if "/search?" in url:
            query = parse_qs(urlparse(url).query)["query"][0]
            queries.append(query)
            if "comparative evidence" in query:
                return _search_payload()
            return json.dumps({"hitCount": 0, "resultList": {"result": []}}).encode()
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project, "C001", run_id="SECOND_SUCCESS", http_get=http_get,
    )
    manifest = json.loads((project / result["acquisition_manifest_path"]).read_text())
    frozen = load_frozen_evidence_pack(
        project, result["evidence_pack"], candidate_id="C001", round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert result["status"] == "FROZEN"
    assert [attempt["attempt_index"] for attempt in manifest["attempts"]] == [1, 2]
    assert frozen["version"] == 1
    assert frozen["coverage"]["round_index"] == 1
    assert all(plan["round_index"] == 1 for plan in frozen["query_plans"])
    assert frozen["source_run_id"] == "SECOND_SUCCESS"
    assert any("comparative evidence" in query for query in queries)


def test_second_attempt_keeps_first_source_and_exact_evidence_lineage(tmp_path):
    project, seed = _project(tmp_path)
    first_paper = _search_record(
        pmid="11111111", pmcid="PMC1111111", doi="10.1000/first",
        title="First source without target sections",
    )
    second_paper = _search_record(
        pmid="22222222", pmcid="PMC2222222", doi="10.1000/second",
        title="Second source with target results",
    )

    def http_get(url, _timeout):
        if "/search?" in url:
            query = parse_qs(urlparse(url).query)["query"][0]
            return _search_payload(records=[second_paper if "comparative evidence" in query
                                            else first_paper])
        if url.endswith("/PMC1111111/fullTextXML"):
            return XML_WITHOUT_TARGET_SECTIONS
        if url.endswith("/PMC2222222/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project, "C001", run_id="SOURCE_ACCUMULATION", http_get=http_get,
    )
    manifest = json.loads((project / result["acquisition_manifest_path"]).read_text())
    frozen = load_frozen_evidence_pack(
        project, result["evidence_pack"], candidate_id="C001", round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert [item["coverage_facts"]["verdict"] for item in manifest["attempts"]] == [
        "INSUFFICIENT_RETRY", "PASS",
    ]
    assert {item["pmcid"] for item in manifest["source_snapshots"]} == {
        "PMC1111111", "PMC2222222",
    }
    assert len({item["query_id"] for plan in frozen["query_plans"]
                for item in plan["queries"]}) == sum(
                    len(plan["queries"]) for plan in frozen["query_plans"]
                )
    assert manifest["verified_evidence_ids"] == [
        item["evidence_id"] for item in frozen["evidence"]
    ]
    assert all(item["retrieval"]["snapshot_path"] for item in frozen["evidence"])


def _structured_fixture_receipt(work_dir, *, prompt, schema, raw):
    work_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "output_path": ("structured_model_stdout.txt", raw),
        "prompt_path": ("structured_model_prompt.txt", prompt),
        "schema_path": ("structured_model_output.schema.json", json.dumps(schema, sort_keys=True)),
    }
    receipt = {"schema_version": structured_execution.SCHEMA_VERSION,
               "validation_status": "PASS"}
    for path_key, (name, content) in files.items():
        path = work_dir / name
        path.write_bytes(content.encode("utf-8"))
        receipt[path_key] = str(path)
        receipt[{"output_path": "stdout_hash", "prompt_path": "prompt_hash",
                 "schema_path": "schema_sha256"}[path_key]] = hashlib.sha256(content.encode()).hexdigest()
    return receipt


@pytest.mark.parametrize("corruption", [None, "prior_bytes", "prompt_rehash", "enumeration_receipt"])
def test_headless_candidate_selection_replays_exact_plan_and_bound_receipts(tmp_path, monkeypatch, corruption):
    project, seed = _project(tmp_path)
    initial = _planner_schema_plan(_host_planner_plan(seed))
    initial["optional_anchors"] = [{"source_field": "scientific_question", "text_snippet": "yeast"}]
    initial["intents"] = [{"optional_anchor_indices": [0]}]
    request = query_planner.prepare_scientific_query_plan_request(seed, reformulation_index=0, feedback=None)
    previous = query_planner.validate_scientific_query_plan_response(
        seed, request=request, raw_response=json.dumps({
            "status": "PLAN", "reason": "initial", "plan": initial,
        }).encode(),
    )["plan"]
    feedback = {
        "previous_plan": previous,
        "executed_queries": query_planner.compile_scientific_query_plan(previous, seed=seed),
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{"gap_id": "G1"}], "semantic_rejections": [],
        "attempt_outcome": {"type": "ZERO_DISCOVERY"},
    }
    candidates, _audit = query_planner._admissible_replan_candidates(previous, seed, feedback, 1)
    calls = []

    def model(_spec, *, prompt, schema, work_dir, purpose):
        calls.append(prompt)
        if len(calls) == 1:
            payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "needs choice", "plan": None}
        else:
            offered = json.loads(prompt.rsplit("\n", 1)[-1])
            payload = {"status": "SELECT_CANDIDATE", "reason": "remove optional restriction",
                       "candidate_id": offered[0]["candidate_id"]}
        raw = json.dumps(payload)
        return {"payload": payload, "raw_output": raw,
                "receipt": _structured_fixture_receipt(work_dir, prompt=prompt, schema=schema, raw=raw)}

    monkeypatch.setattr(structured_execution, "run_structured_model", model)
    run_id = "HEADLESS_SELECTION"
    work_dir = project / "08_Audit" / "l05_acquisition" / "C001" / run_id / "planner_002"
    decision = query_planner.propose_scientific_query_plan(
        seed, spec=object(), work_dir=work_dir, reformulation_index=1, feedback=feedback,
    )
    assert len(calls) == 2
    assert decision["plan"] == candidates[0][1]
    receipt = decision["receipt"]
    if corruption == "prior_bytes":
        Path(receipt["prior_proposal_receipt"]["output_path"]).write_bytes(b"{}")
    elif corruption == "prompt_rehash":
        Path(receipt["prompt_path"]).write_bytes(b"changed candidate summaries")
        receipt["prompt_hash"] = hashlib.sha256(b"changed candidate summaries").hexdigest()
    elif corruption == "enumeration_receipt":
        receipt["replan_enumeration"]["feedback_sha256"] = "0" * 64
    if corruption:
        with pytest.raises(europepmc_runtime.CurieAcquisitionError, match="provenance mismatch|authorized request|enumeration receipt"):
            europepmc_runtime._validated_planner_proposal(
                project, "C001", run_id, 2, receipt, decision["proposal_sha256"], seed=seed, feedback=feedback,
            )
    else:
        recovered = europepmc_runtime._validated_planner_proposal(
            project, "C001", run_id, 2, receipt, decision["proposal_sha256"], seed=seed, feedback=feedback,
        )
        assert recovered["status"] == "PLAN"
        assert recovered["plan"] == candidates[0][1]


def run_europepmc_acquisition(*args, **kwargs):
    """Exercise P0 lifecycle with a controlled planner and semantic assessor."""
    kwargs.setdefault("semantic_assessor", _supported_semantic_assessment)
    kwargs.setdefault("semantic_assessor_id", "fixture-semantic-assessor/v1")
    if kwargs.get("explicit_queries") is None and kwargs.get("plan_builder") is None:
        def legacy_p0_builder(seed, *, reformulation_index, **builder_kwargs):
            if reformulation_index >= 2:
                return None
            builder_kwargs.pop("feedback", None)
            return build_multisource_query_plan(
                seed, reformulation_index=reformulation_index, **builder_kwargs,
            )

        kwargs["plan_builder"] = legacy_p0_builder
    return _run_europepmc_acquisition(*args, **kwargs)


def test_explicit_query_origin_survives_manifest_without_model_rewrite(
    tmp_path, monkeypatch,
):
    project, _seed = _project(tmp_path)
    explicit_query = "EXT_ID:22253597 AND   SRC:MED"
    sent_queries = []

    def http_get(url, _timeout):
        if "/search?" in url:
            sent_queries.append(parse_qs(urlparse(url).query)["query"][0])
            return b'{"hitCount":0,"resultList":{"result":[]}}'
        raise AssertionError(url)

    def forbidden_model_path(*_args, **_kwargs):
        raise AssertionError("explicit query must not enter structured planning")

    monkeypatch.setattr(
        europepmc_runtime.deep_research, "load_runtime_spec", forbidden_model_path,
    )
    monkeypatch.setattr(
        europepmc_runtime, "propose_scientific_query_plan", forbidden_model_path,
    )

    result = run_europepmc_acquisition(
        project, "C001", explicit_queries=[explicit_query],
        max_papers=1, run_id="EXPLICIT_ORIGIN", http_get=http_get,
    )

    manifest = json.loads(
        (project / result["acquisition_manifest_path"]).read_text(encoding="utf-8")
    )
    attempt = manifest["attempts"][0]
    persisted_attempt = json.loads(
        (project / attempt["artifact"]["path"]).read_text(encoding="utf-8")
    )
    for query_plan in (
        manifest["query_plans"][0],
        attempt["query_plan"],
        persisted_attempt["query_plan"],
    ):
        query_record = query_plan["queries"][0]
        assert query_record["origin"] == "explicit"
        assert query_record["query"] == explicit_query
    assert sent_queries == [explicit_query]
    assert manifest["query_plans"][0]["planner"] == "curie-multisource-explicit-query/v1"


@pytest.mark.parametrize("entailment,expected_status", [
    ("SUPPORTED", "FROZEN"),
    ("CONTRADICTED", "FROZEN"),
    ("UNRELATED", "INSUFFICIENT_STOP"),
    ("AMBIGUOUS", "INSUFFICIENT_STOP"),
])
def test_ordinary_europepmc_semantic_admission_preserves_located_audit(
    tmp_path, entailment, expected_status,
):
    project, seed = _project(tmp_path)

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload()
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    def assessor(*, extract, claim):
        result = _supported_semantic_assessment(extract=extract, claim=claim)
        result["entailment"] = entailment
        return result

    result = run_europepmc_acquisition(
        project, "C001", explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
        run_id=f"SEMANTIC_{entailment}", http_get=http_get,
        semantic_assessor=assessor, semantic_assessor_id="fixture-semantic/v1",
    )
    assert result["status"] == expected_status
    manifest = json.loads((project / result["acquisition_manifest_path"]).read_text(encoding="utf-8"))
    attempt = manifest["attempts"][0]
    assert len(attempt["located_evidence"]) == 3
    assert len(attempt["semantic_verifications"]) == 3
    assert all(item["entailment"] == entailment for item in attempt["semantic_verifications"])
    snapshot = attempt["source_snapshots"][0]
    assert (project / snapshot["artifact_path"]).read_bytes() == XML
    if expected_status == "FROZEN":
        frozen = load_frozen_evidence_pack(
            project, result["evidence_pack"], candidate_id="C001",
            round_id="1", seed_sha256=research_seed.seed_sha256(seed),
        )
        assert len(frozen["evidence"]) == len(frozen["semantic_verifications"]) == 3
    else:
        assert attempt["verified_evidence"] == []
        assert result["evidence_pack"] is None


def test_semantic_assessor_execution_failure_keeps_error_category_and_located_audit(tmp_path):
    project, _seed = _project(tmp_path)

    def http_get(url, _timeout):
        return _search_payload() if "/search?" in url else XML

    def failed_assessor(**_kwargs):
        raise europepmc_runtime.CurieAcquisitionError("MODEL_EXECUTION_ERROR", "assessor process failed")

    with pytest.raises(europepmc_runtime.CurieAcquisitionError) as caught:
        _run_europepmc_acquisition(
            project, "C001", run_id="ASSESSOR_FAILURE",
            explicit_queries=["EXT_ID:22253597 AND SRC:MED"], http_get=http_get,
            semantic_assessor=failed_assessor, semantic_assessor_id="failed-assessor/v1",
        )
    assert caught.value.category == "MODEL_EXECUTION_ERROR"
    root = project / "08_Audit" / "l05_acquisition" / "C001" / "ASSESSOR_FAILURE"
    failed = json.loads((root / "attempt_001.json").read_text(encoding="utf-8"))
    assert failed["source_snapshots"]
    assert failed["located_evidence"]
    assert (project / failed["source_snapshots"][0]["artifact_path"]).read_bytes() == XML
    assert not (root / "acquisition_manifest.json").exists()


def test_production_structured_feedback_replan_uses_query_content(tmp_path, monkeypatch):
    project, seed = _project(tmp_path)
    (project / "L4_PRIVATE.txt").write_text("UNAUTHORIZED_L4_SENTINEL_7c9a", encoding="utf-8")
    prompts = []
    from test_l05_curie_p1_planning import _anchor

    def fake_model(_spec, *, prompt, schema, work_dir, purpose):
        prompts.append(prompt)
        index = len(prompts) - 1
        plan = {
            "schema_version": "L05ScientificQueryPlan/v2",
            "planner": "scientific-query-planner/v2",
            "seed_sha256": research_seed.seed_sha256(seed),
            "reformulation_index": index,
            "core_anchors": [
                _anchor(seed, "scientific_question", "carbon dioxide", "co2"),
                _anchor(seed, "hypothesis_seed", "Rca1p", "rca1p"),
            ],
            "optional_concepts": [
                _anchor(seed, "hypothesis_seed", "transcriptional", "transcriptional"),
            ],
            "unresolved_entities": [], "advisory_search_constraints": [],
            "intents": [{"intent_id": "question", "core_concept_ids": ["co2", "rca1p"],
                         "optional_concept_ids": ["transcriptional"] if index == 0 else []}],
        }
        payload = {"status": "PLAN", "reason": "validated gap", "plan": _planner_schema_plan(plan)}
        raw = json.dumps(payload)
        return {"payload": payload,
                "receipt": _structured_fixture_receipt(work_dir, prompt=prompt, schema=schema, raw=raw),
                "raw_output": raw}

    monkeypatch.setattr(deep_research, "load_runtime_spec", lambda *_: (object(), "fixture"))
    monkeypatch.setattr(deep_research, "host_matches", lambda *_: (True, ""))
    monkeypatch.setattr(deep_research, "validate_spec_consistency", lambda *_: (True, ""))
    monkeypatch.setattr(structured_execution, "runtime_ready", lambda *_: (True, ""))
    monkeypatch.setattr(structured_execution, "run_structured_model", fake_model)

    def http_get(url, _timeout):
        if "/search?" in url:
            query = parse_qs(urlparse(url).query)["query"][0]
            return b'{"hitCount":0,"resultList":{"result":[]}}' if "transcriptional" in query else _search_payload()
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = _run_europepmc_acquisition(
        project, "C001", run_id="P1_FEEDBACK", http_get=http_get,
        semantic_assessor=_supported_semantic_assessment,
        semantic_assessor_id="fixture-semantic/v1",
    )
    assert result["status"] == "FROZEN"
    manifest = json.loads((project / result["acquisition_manifest_path"]).read_text(encoding="utf-8"))
    assert len(manifest["attempts"]) == len(prompts) == 2
    assert "ZERO_DISCOVERY" in prompts[1]
    assert all("UNAUTHORIZED_L4_SENTINEL_7c9a" not in prompt for prompt in prompts)
    assert "transcriptional" in manifest["attempts"][0]["query_plan"]["queries"][0]["query"]
    assert "transcriptional" not in manifest["attempts"][1]["query_plan"]["queries"][0]["query"]


def test_production_model_failure_is_typed_and_never_becomes_scientific_retry(tmp_path, monkeypatch):
    project, _seed = _project(tmp_path)
    monkeypatch.setattr(deep_research, "load_runtime_spec", lambda *_: (object(), "fixture"))
    monkeypatch.setattr(deep_research, "host_matches", lambda *_: (True, ""))
    monkeypatch.setattr(deep_research, "validate_spec_consistency", lambda *_: (True, ""))
    monkeypatch.setattr(structured_execution, "runtime_ready", lambda *_: (True, ""))

    def failed_model(*_args, **_kwargs):
        raise structured_execution.StructuredExecutionError(
            "provider unavailable", category="MODEL_EXECUTION_ERROR",
            receipt={"validation_status": "EXECUTION_ERROR"},
        )

    monkeypatch.setattr(structured_execution, "run_structured_model", failed_model)
    with pytest.raises(europepmc_runtime.CurieAcquisitionError, match="MODEL_EXECUTION_ERROR"):
        _run_europepmc_acquisition(
            project, "C001", run_id="MODEL_FAILURE",
            semantic_assessor=_supported_semantic_assessment,
            semantic_assessor_id="fixture-semantic/v1",
            http_get=lambda *_: pytest.fail("model failure reached Europe PMC"),
        )
    root = project / "08_Audit" / "l05_acquisition" / "C001" / "MODEL_FAILURE"
    failed = json.loads((root / "planner_001" / "error.json").read_text(encoding="utf-8"))
    assert failed["category"] == "MODEL_EXECUTION_ERROR"
    assert not (root / "attempt_001.json").exists()


def test_missing_model_configuration_fails_before_search_or_owner_write(tmp_path, monkeypatch):
    project, _seed = _project(tmp_path)
    monkeypatch.setattr(deep_research, "load_runtime_spec",
                        lambda *_: (_ for _ in ()).throw(deep_research.DeepResearchError("missing runtime")))
    with pytest.raises(europepmc_runtime.CurieAcquisitionError) as caught:
        _run_europepmc_acquisition(
            project, "C001", run_id="NO_MODEL_CONFIG",
            semantic_assessor=_supported_semantic_assessment,
            semantic_assessor_id="fixture-semantic/v1",
            http_get=lambda *_: pytest.fail("missing config reached Europe PMC"),
        )
    assert caught.value.category == "MODEL_CONFIG_ERROR"
    assert not (project / "08_Audit" / "l05_acquisition" / "C001" / "first_1.json").exists()


def test_explicit_query_keeps_model_planner_out_of_ordinary_path(tmp_path, monkeypatch):
    project, _seed = _project(tmp_path)
    monkeypatch.setattr(deep_research, "load_runtime_spec",
                        lambda *_: pytest.fail("explicit query entered model planner"))
    result = _run_europepmc_acquisition(
        project, "C001", run_id="EXPLICIT_NO_MODEL",
        explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
        semantic_assessor=_supported_semantic_assessment,
        semantic_assessor_id="fixture-semantic/v1",
        http_get=lambda url, _: _search_payload() if "/search?" in url else XML,
    )
    assert result["status"] == "FROZEN"


def test_production_no_admissible_replan_stops_after_real_zero_discovery(tmp_path, monkeypatch):
    project, seed = _project(tmp_path)
    from test_l05_curie_p1_planning import _anchor

    monkeypatch.setattr(deep_research, "load_runtime_spec", lambda *_: (object(), "fixture"))
    monkeypatch.setattr(deep_research, "host_matches", lambda *_: (True, ""))
    monkeypatch.setattr(deep_research, "validate_spec_consistency", lambda *_: (True, ""))
    monkeypatch.setattr(structured_execution, "runtime_ready", lambda *_: (True, ""))
    prompts = []

    def fake_model(_spec, *, prompt, schema, work_dir, purpose):
        prompts.append(prompt)
        if len(prompts) == 1:
            plan = {
                "schema_version": "L05ScientificQueryPlan/v2",
                "planner": "scientific-query-planner/v2",
                "seed_sha256": research_seed.seed_sha256(seed),
                "reformulation_index": 0,
                "core_anchors": [
                    _anchor(seed, "scientific_question", "carbon dioxide", "co2"),
                    _anchor(seed, "hypothesis_seed", "Rca1p", "rca1p"),
                ],
                "optional_concepts": [], "unresolved_entities": [],
                "advisory_search_constraints": [],
                "intents": [{"intent_id": "question", "core_concept_ids": ["co2", "rca1p"],
                             "optional_concept_ids": []}],
            }
            payload = {"status": "PLAN", "reason": "initial", "plan": _planner_schema_plan(plan)}
        else:
            assert "ZERO_DISCOVERY" in prompt
            payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "finite variants exhausted", "plan": None}
        raw = json.dumps(payload)
        return {"payload": payload,
                "receipt": _structured_fixture_receipt(work_dir, prompt=prompt, schema=schema, raw=raw),
                "raw_output": raw}

    monkeypatch.setattr(structured_execution, "run_structured_model", fake_model)
    searches = []

    def http_get(url, _timeout):
        searches.append(url)
        assert "/search?" in url
        return b'{"hitCount":0,"resultList":{"result":[]}}'

    result = _run_europepmc_acquisition(
        project, "C001", run_id="NO_REPLAN", http_get=http_get,
        semantic_assessor=_supported_semantic_assessment,
        semantic_assessor_id="fixture-semantic/v1",
    )
    assert result["status"] == "INSUFFICIENT_STOP"
    assert result["terminal_reason"] == "no_admissible_replan"
    assert len(prompts) == 2
    assert len(searches) == 1
    manifest = json.loads((project / result["acquisition_manifest_path"]).read_text(encoding="utf-8"))
    assert len(manifest["attempts"]) == 1
    terminal = manifest["planner_terminal"]
    assert terminal["schema_version"] == "L05PlannerTerminal/v1"
    assert terminal["status"] == "NO_ADMISSIBLE_REPLAN"
    assert terminal["receipt"]["validation_status"] == "PASS"
    assert terminal["proposal_sha256"] == terminal["receipt"]["stdout_hash"]


def _controlled_three_plan_builder(seed, *, seed_sha256, round_index,
                                   reformulation_index, query_id_prefix, **_kwargs):
    return build_multisource_query_plan(
        seed, seed_sha256=seed_sha256, round_index=round_index,
        explicit_queries=[f"controlled plan {reformulation_index + 1}"],
        providers=["europe-pmc"], query_id_prefix=query_id_prefix,
    )


@pytest.mark.parametrize("third_succeeds", [True, False])
def test_controlled_third_plan_success_or_budget_exhaustion(tmp_path, third_succeeds):
    project, seed = _project(tmp_path)
    requests = []

    def http_get(url, _timeout):
        if "/search?" in url:
            query = parse_qs(urlparse(url).query)["query"][0]
            requests.append(query)
            return (_search_payload() if third_succeeds and query == "controlled plan 3"
                    else json.dumps({"hitCount": 0, "resultList": {"result": []}}).encode())
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project, "C001", run_id=f"THIRD_{third_succeeds}", http_get=http_get,
        plan_builder=_controlled_three_plan_builder,
    )
    audit = json.loads((project / result["acquisition_manifest_path"]).read_text())
    assert [attempt["attempt_index"] for attempt in audit["attempts"]] == [1, 2, 3]
    assert requests == ["controlled plan 1", "controlled plan 2", "controlled plan 3"]
    if third_succeeds:
        assert result["status"] == "FROZEN"
        frozen = load_frozen_evidence_pack(
            project, result["evidence_pack"], candidate_id="C001", round_id="1",
            seed_sha256=research_seed.seed_sha256(seed),
        )
        assert frozen["version"] == 1
        assert len(frozen["query_plans"]) == 3
    else:
        assert result["status"] == "INSUFFICIENT_STOP"
        assert result["terminal_reason"] == "budget_exhausted"
        assert result["evidence_pack"] is None


def test_frozen_before_manifest_publication_recovers_without_search(tmp_path, monkeypatch):
    project, seed = _project(tmp_path)
    original = europepmc_runtime._write_audit_manifest

    def interrupted(*_args, **_kwargs):
        raise RuntimeError("interrupted before final manifest")

    monkeypatch.setattr(europepmc_runtime, "_write_audit_manifest", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_europepmc_acquisition(
            project, "C001", run_id="RECOVER_ME", explicit_queries=["recovery test"],
            http_get=lambda url, _: _search_payload() if "/search?" in url else XML,
        )
    monkeypatch.setattr(europepmc_runtime, "_write_audit_manifest", original)
    result = run_europepmc_acquisition(
        project, "C001", run_id="RECOVER_ME", explicit_queries=["recovery test"],
        http_get=lambda *_: pytest.fail("recovery performed a search"),
    )
    assert result["status"] == "FROZEN"
    frozen = load_frozen_evidence_pack(
        project, result["evidence_pack"], candidate_id="C001", round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert frozen["source_run_id"] == "RECOVER_ME"


def test_frozen_recovery_does_not_require_new_model_or_assessor_configuration(tmp_path):
    project, _seed = _project(tmp_path)
    first = run_europepmc_acquisition(
        project, "C001", run_id="NO_MODEL_RECOVERY", explicit_queries=["recovery test"],
        http_get=lambda url, _: _search_payload() if "/search?" in url else XML,
    )
    recovered = _run_europepmc_acquisition(
        project, "C001", run_id="NO_MODEL_RECOVERY", explicit_queries=["recovery test"],
        http_get=lambda *_: pytest.fail("frozen recovery performed a search"),
    )
    assert recovered == first


def test_frozen_checkpoint_recovery_binds_and_reuses_without_search(tmp_path, monkeypatch):
    import run_loop

    project, seed = _project(tmp_path)
    original = europepmc_runtime._write_audit_manifest
    monkeypatch.setattr(
        europepmc_runtime, "_write_audit_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("before manifest")),
    )
    with pytest.raises(RuntimeError, match="before manifest"):
        run_europepmc_acquisition(
            project, "C001", run_id="BIND_RECOVERY", explicit_queries=["bind recovery"],
            http_get=lambda url, _: _search_payload() if "/search?" in url else XML,
        )
    monkeypatch.setattr(europepmc_runtime, "_write_audit_manifest", original)

    def fake_ctl(*_argv):
        result = run_europepmc_acquisition(
            project, "C001", run_id="BIND_RECOVERY", explicit_queries=["bind recovery"],
            http_get=lambda *_: pytest.fail("recovery performed a search"),
        )
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

    monkeypatch.setattr(run_loop, "_ctl", fake_ctl)
    monkeypatch.setattr(run_loop, "_l05_command", lambda *_: ["l05-acquire-europepmc"])
    for _ in range(2):
        outcome = run_loop.exec_l05(
            str(project), "C001", {"node": "L0.5"}, SimpleNamespace(),
            SimpleNamespace(), tmp_path / "run", 1,
        )
        assert outcome["terminal_status"] == "FROZEN"
        assert research_seed.active_l1_native_evidence_run_id(project, seed) == "BIND_RECOVERY"
        bound = research_seed.load_l1_native_evidence_binding(
            project, seed, "BIND_RECOVERY"
        )
        assert bound["evidence_pack"]["version"] == 1


def test_concurrent_first_acquisition_has_one_writer(tmp_path):
    project, _seed = _project(tmp_path)
    entered, release = Event(), Event()

    def http_get(url, _timeout):
        entered.set()
        assert release.wait(10)
        return _search_payload() if "/search?" in url else XML

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_europepmc_acquisition, project, "C001",
                            run_id="ONE_WRITER", explicit_queries=["writer"],
                            http_get=http_get)
        assert entered.wait(10)
        with pytest.raises(CurieContractError, match="active writer"):
            run_europepmc_acquisition(
                project, "C001", run_id="ONE_WRITER", explicit_queries=["writer"],
                http_get=lambda *_: pytest.fail("second writer performed a search"),
            )
        release.set()
        assert first.result()["status"] == "FROZEN"


def test_service_failure_is_not_scientific_replan_and_preserves_first_cause(tmp_path):
    project, _seed = _project(tmp_path)
    requests = []

    def http_get(url, _timeout):
        requests.append(url)
        if "/search?" in url:
            raise _fulltext_503("SEARCH")
        raise AssertionError(url)

    with pytest.raises(europepmc_runtime.CurieAcquisitionError,
                       match="SERVICE_ERROR.*last_valid_attempt"):
        run_europepmc_acquisition(
            project, "C001", run_id="SEARCH_OUTAGE", http_get=http_get,
        )
    assert requests
    assert all("/search?" in url for url in requests)
    failed = project / "08_Audit" / "l05_acquisition" / "C001" / "SEARCH_OUTAGE" / "attempt_001.json"
    assert json.loads(failed.read_text())["terminal_status"] == "ERROR"


def test_recovery_rejects_tampered_checkpoint_source_without_search(tmp_path, monkeypatch):
    project, _seed = _project(tmp_path)
    original = europepmc_runtime._write_audit_manifest
    monkeypatch.setattr(europepmc_runtime, "_write_audit_manifest",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupt")))
    with pytest.raises(RuntimeError, match="interrupt"):
        run_europepmc_acquisition(
            project, "C001", run_id="TAMPER_RECOVERY", explicit_queries=["tamper"],
            http_get=lambda url, _: _search_payload() if "/search?" in url else XML,
        )
    monkeypatch.setattr(europepmc_runtime, "_write_audit_manifest", original)
    source = next((project / "09_Literature_Database").rglob("*.xml"))
    source.write_bytes(b"<changed/>")
    with pytest.raises(CurieContractError, match="RECOVERY_ERROR"):
        run_europepmc_acquisition(
            project, "C001", run_id="TAMPER_RECOVERY", explicit_queries=["tamper"],
            http_get=lambda *_: pytest.fail("tampered recovery performed search"),
        )


def test_runner_result_boundary_validates_manifest_hash_and_identity(tmp_path):
    project, _seed = _project(tmp_path)
    result = run_europepmc_acquisition(
        project, "C001", run_id="BOUNDARY", explicit_queries=["boundary"],
        http_get=lambda url, _: _search_payload() if "/search?" in url else XML,
    )
    assert europepmc_runtime.validate_europepmc_acquisition_result(
        project, "C001", result,
    ) == result
    altered = dict(result, acquisition_manifest_sha256="0" * 64)
    with pytest.raises(CurieContractError, match="bytes/hash mismatch"):
        europepmc_runtime.validate_europepmc_acquisition_result(
            project, "C001", altered,
        )


def test_terminal_first_acquisition_rejects_new_run_id_without_search(tmp_path):
    project, _seed = _project(tmp_path)
    empty = b'{"hitCount":0,"resultList":{"result":[]}}'
    first = run_europepmc_acquisition(
        project, "C001", run_id="FIRST", explicit_queries=["first"],
        http_get=lambda *_: empty,
    )
    assert first["status"] == "INSUFFICIENT_STOP"
    with pytest.raises(CurieContractError, match="owner conflicts"):
        run_europepmc_acquisition(
            project, "C001", run_id="SECOND", explicit_queries=["second"],
            http_get=lambda *_: pytest.fail("second acquisition searched"),
        )


def test_new_query_ids_cannot_disguise_repeated_plan_content(tmp_path):
    project, _seed = _project(tmp_path)
    searches = []

    def same_content_builder(seed, *, seed_sha256, round_index,
                             query_id_prefix, **_kwargs):
        return build_multisource_query_plan(
            seed, seed_sha256=seed_sha256, round_index=round_index,
            explicit_queries=["identical scientific query"],
            providers=["europe-pmc"], query_id_prefix=query_id_prefix,
        )

    def http_get(url, _timeout):
        searches.append(url)
        return b'{"hitCount":0,"resultList":{"result":[]}}'

    with pytest.raises(CurieContractError, match="repeated executed query content"):
        run_europepmc_acquisition(
            project, "C001", run_id="DUPLICATE_CONTENT",
            plan_builder=same_content_builder, http_get=http_get,
        )
    assert len(searches) == 1


def test_runtime_does_not_freeze_when_no_oa_full_text_is_available(tmp_path):
    project, _seed = _project(tmp_path)

    result = run_europepmc_acquisition(
        project,
        "C001",
        explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
        max_papers=1,
        run_id="RUN_NO_OA",
        http_get=lambda _url, _timeout: _search_payload(open_access=False),
    )

    assert result["status"] == "INSUFFICIENT_STOP"
    assert result["evidence_pack"] is None
    assert result["coverage"]["verdict"] == "INSUFFICIENT_RETRY"
    assert result["coverage"]["gaps"][0]["gap_id"] == "NO_VERIFIED_FULL_TEXT"
    assert not list((project / "09_Literature_Database" / "evidence_packs" / "l05").rglob("*.json"))


def test_runtime_promotes_reserve_after_include_has_no_target_sections(tmp_path):
    project, seed = _project(tmp_path)
    include = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1000/include", title="First selected paper")
    reserve = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1000/reserve", title="Reserve paper with Results")

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[include, reserve])
        if url.endswith("/PMC1111111/fullTextXML"):
            return XML_WITHOUT_TARGET_SECTIONS
        if url.endswith("/PMC2222222/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project,
        "C001",
        explicit_queries=["reserve regression"],
        max_papers=1,
        run_id="RUN_RESERVE_PROMOTION",
        http_get=http_get,
    )

    assert result["status"] == "FROZEN"
    frozen = load_frozen_evidence_pack(
        project,
        result["evidence_pack"],
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert [paper["identifiers"]["pmcid"] for paper in frozen["selected_papers"]] == ["PMC2222222"]
    assert {item["section"] for item in frozen["evidence"]} == {"Results", "Discussion", "Conclusion"}

    audit = json.loads((project / result["acquisition_manifest_path"]).read_text(encoding="utf-8"))
    assert audit["paper_failures"][0]["pmcid"] == "PMC1111111"
    assert audit["paper_failures"][0]["reason_code"] == "NO_TARGET_SECTIONS"
    assert audit["reserve_promotions"][0]["promoted_pmcid"] == "PMC2222222"
    assert audit["coverage"]["verdict"] == "PASS"


def test_runtime_routes_all_no_target_sections_through_coverage_gap(tmp_path):
    project, _seed = _project(tmp_path)
    include = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1000/include", title="First selected paper")
    reserve = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1000/reserve", title="Reserve paper")

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[include, reserve])
        if url.endswith(("/PMC1111111/fullTextXML", "/PMC2222222/fullTextXML")):
            return XML_WITHOUT_TARGET_SECTIONS
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project,
        "C001",
        explicit_queries=["all no-target regression"],
        max_papers=1,
        run_id="RUN_ALL_NO_TARGET",
        http_get=http_get,
    )

    assert result["status"] == "INSUFFICIENT_STOP"
    assert result["evidence_pack"] is None
    assert result["coverage"]["verdict"] == "INSUFFICIENT_RETRY"
    assert {gap["gap_id"] for gap in result["coverage"]["gaps"]} == {
        "NO_VERIFIED_FULL_TEXT",
        "NO_LOCATED_INTERPRETIVE_EVIDENCE",
    }
    audit = json.loads((project / result["acquisition_manifest_path"]).read_text(encoding="utf-8"))
    assert [failure["reason_code"] for failure in audit["paper_failures"]] == [
        "NO_TARGET_SECTIONS",
        "NO_TARGET_SECTIONS",
    ]


def test_paperqa2_production_runtime_requires_explicit_semantic_assessor(tmp_path):
    project, _seed = _project(tmp_path)
    runtime = PaperQA2CurieRuntime(
        backend=lambda **_kwargs: [],
        backend_id="paperqa2-fork-v2026.08.12/sparse-docs-v1",
    )

    with pytest.raises(CurieContractError, match="semantic assessor|self-claims"):
        europepmc_runtime.run_paperqa2_europepmc_acquisition(
            project,
            "C001",
            paperqa_runtime=runtime,
            pdf_paths={},
        )


def test_confusable_above_threshold_extract_requires_real_semantic_authorization():
    source_candidates = [
        {
            "paper_id": "P1",
            "text": "WGCNA pseudocells were constructed before module detection and GO enrichment.",
            "section": "Methods",
            "locator": "sec:7/p:7",
        },
        {
            "paper_id": "P1",
            "text": (
                "WGCNA modules were visualized in a generic network figure without "
                "describing the pseudocell workflow."
            ),
            "section": "Results",
            "locator": "sec:7/p:9",
        },
    ]
    aligned = align_paperqa2_chunks(
        chunks=[{
            "text": (
                "WGCNA pseudocells were constructed before module detection and GO enrichment. "
                "WGCNA modules were visualized in a generic network figure."
            ),
            "locator": "PDF pages 7-9",
            "score": 0.9,
        }],
        source_candidates=source_candidates,
    )
    assert [item["locator"] for item in aligned] == ["sec:7/p:7", "sec:7/p:9"]
    assert all(
        item["source_alignment"]["source_token_coverage"] >= MIN_SOURCE_TOKEN_COVERAGE
        for item in aligned
    )

    target = _located("E_target", aligned[0]["text"], aligned[0]["locator"])
    confusable = _located("E_confusable", aligned[1]["text"], aligned[1]["locator"])
    semantic_target = (
        "Scientific question: How was the scWGCNA workflow implemented?\n"
        "Hypothesis seed: The workflow constructs pseudocells before WGCNA module detection."
    )
    seen_claims = []

    def assessor(*, extract, claim):
        seen_claims.append((extract["evidence_id"], claim))
        if extract["evidence_id"] == "E_target":
            return {
                "entailment": "SUPPORTED",
                "scope_match": True,
                "context_preserved": True,
                "qualification_preserved": True,
                "reason": "The methods paragraph directly describes the requested workflow.",
            }
        return {
            "entailment": "UNRELATED",
            "scope_match": True,
            "context_preserved": True,
            "qualification_preserved": True,
            "reason": "Shared WGCNA vocabulary does not make the figure paragraph evidence for the workflow.",
        }

    admitted, admitted_semantics, all_semantics = (
        europepmc_runtime._admit_paperqa2_semantic_evidence(
            [target, confusable],
            semantic_target=semantic_target,
            assessor=assessor,
            assessor_id="fixture-semantic-assessor/v1",
        )
    )

    assert [item["evidence_id"] for item in admitted] == ["E_target"]
    assert [item["evidence_id"] for item in admitted_semantics] == ["E_target"]
    assert {item["evidence_id"] for item in all_semantics} == {"E_target", "E_confusable"}
    assert all(claim == semantic_target for _evidence_id, claim in seen_claims)
    assert all(
        claim != extract["text"]
        for extract, (_evidence_id, claim) in zip(
            [target, confusable], seen_claims, strict=True
        )
    )


def test_paperqa2_production_runtime_composes_selected_source_to_native_pack(
    tmp_path, monkeypatch
):
    """The public production runtime—not a test-only assembly—owns the full path."""
    project, seed = _project(tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-real-paper")

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload()
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    seen_question = {}

    def paperqa_backend(**kwargs):
        seen_question["value"] = kwargs["question"]
        return [{
            "text": "Rca1p was required for the transcriptional response to carbon dioxide.",
            "section": "PaperQA2",
            "locator": "PDF page 1",
            "score": 0.91,
            "runtime": {
                "schema_version": "PaperQA2Runtime/v1",
                "package": "paper-qa",
                "version": "2026.8.12",
                "upstream_repo": "https://github.com/Future-House/paper-qa",
                "upstream_tag": "v2026.08.12",
                "upstream_commit": "57e89f7223b0960d5ee5ea048c69e3c47e088572",
                "fork_repo": "https://github.com/hk20013106/paper-qa",
                "python_executable": "test-python",
                "paperqa_repo": "test-paperqa-repo",
                "pqa_home": "test-pqa-home",
                "pdf_path": str(pdf),
                "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            },
        }]

    runtime = PaperQA2CurieRuntime(
        backend=paperqa_backend,
        backend_id="paperqa2-fork-v2026.08.12/sparse-docs-v1",
    )

    observed = {"planner": 0, "discovery": 0, "selector": 0}
    original_plan = europepmc_runtime.build_multisource_query_plan
    original_discovery = europepmc_runtime.run_multisource_discovery_strict
    original_selector = europepmc_runtime.select_candidates_strict

    def observe_plan(*args, **kwargs):
        observed["planner"] += 1
        assert kwargs["providers"] == ["europe-pmc"]
        return original_plan(*args, **kwargs)

    def observe_discovery(*args, **kwargs):
        observed["discovery"] += 1
        assert set(args[1]) == {"europe-pmc"}
        return original_discovery(*args, **kwargs)

    def observe_selector(*args, **kwargs):
        observed["selector"] += 1
        return original_selector(*args, **kwargs)

    monkeypatch.setattr(europepmc_runtime, "build_multisource_query_plan", observe_plan)
    monkeypatch.setattr(europepmc_runtime, "run_multisource_discovery_strict", observe_discovery)
    monkeypatch.setattr(europepmc_runtime, "select_candidates_strict", observe_selector)

    result = europepmc_runtime.run_paperqa2_europepmc_acquisition(
        project,
        "C001",
        paperqa_runtime=runtime,
        pdf_paths={"P_3cab82183e94295123ee": str(pdf)},
        semantic_assessor=_supported_semantic_assessment,
        semantic_assessor_id="fixture-semantic-assessor/v1",
        explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
        max_papers=1,
        page_size=5,
        run_id="PQA001",
        http_get=http_get,
    )

    assert result["status"] == "FROZEN"
    assert result["native_binding"]["evidence_pack_version"] == 1
    assert research_seed.active_l1_native_evidence_run_id(project, seed) == "PQA001"
    frozen = load_frozen_evidence_pack(
        project,
        result["evidence_pack"],
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert frozen["semantic_verifications"]
    assert all(
        item["retrieval"]["upstream_engine"] == "paperqa2"
        for item in frozen["evidence"]
    )
    assert "The bZIP Transcription Factor Rca1p" in seen_question["value"]
    assert "carbon" in seen_question["value"].casefold()
    assert seen_question["value"] != seed["scientific_question"]
    audit = json.loads(
        (project / result["acquisition_manifest_path"]).read_text(encoding="utf-8")
    )
    assert audit["paperqa2"][0]["retrieval_query"] == seen_question["value"]
    assert audit["paperqa2"][0]["reasoning_authorized_evidence_ids"] == [
        item["evidence_id"] for item in frozen["evidence"]
    ]
    assert observed == {"planner": 1, "discovery": 1, "selector": 1}


def test_cli_registers_thin_europepmc_acquisition_command(tmp_path, monkeypatch, capsys):
    project, _seed = _project(tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args([
        "l05-acquire-europepmc",
        str(project),
        "C001",
        "--query", "EXT_ID:22253597 AND SRC:MED",
        "--max-papers", "1",
        "--page-size", "5",
        "--timeout", "7",
        "--run-id", "CLI001",
        "--semantic-assessor-command", "fixture {prompt_file} {output_file}",
    ])

    seen = {}

    def fake_run(project_dir, cand_id, **kwargs):
        seen.update({"project_dir": project_dir, "cand_id": cand_id, **kwargs})
        return {"schema_version": "L05EuropePmcAcquisitionResult/v1", "status": "FROZEN"}

    import research_loop.l05_curie_cli as extension
    monkeypatch.setattr(extension, "run_europepmc_acquisition", fake_run)
    assert args.func(args) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "FROZEN"
    assert seen["cand_id"] == "C001"
    assert seen["explicit_queries"] == ["EXT_ID:22253597 AND SRC:MED"]
    assert seen["run_id"] == "CLI001"


def test_cli_reports_persistence_error_with_nonzero_exit(tmp_path, monkeypatch, capsys):
    project, _seed = _project(tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args([
        "l05-acquire-europepmc", str(project), "C001",
        "--semantic-assessor-command", "fixture {prompt_file} {output_file}",
    ])
    import research_loop.l05_curie_cli as extension
    monkeypatch.setattr(
        extension, "run_europepmc_acquisition",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    assert args.func(args) == 2
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["status"] == "ERROR"
    assert outcome["error_category"] == "PERSISTENCE_ERROR"


def test_cli_registers_pinned_paperqa2_production_command(tmp_path, monkeypatch, capsys):
    project, _seed = _project(tmp_path)
    pdf_map = tmp_path / "pdf-map.json"
    pdf_map.write_text(json.dumps({"P1": "paper.pdf"}), encoding="utf-8")
    parser = cli.build_parser()
    args = parser.parse_args([
        "l05-acquire-paperqa2-europepmc",
        str(project),
        "C001",
        "--paperqa-python", "paperqa-python",
        "--paperqa-bridge", "bridge.py",
        "--paperqa-repo", "paperqa-repo",
        "--pqa-home", "pqa-home",
        "--pdf-map", str(pdf_map),
        "--semantic-assessor-command", "semantic-agent {prompt_file} {output_file}",
        "--query", "EXT_ID:22253597 AND SRC:MED",
        "--run-id", "PQA_CLI001",
    ])

    seen = {}
    semantic_assessor = lambda **_kwargs: {
        "entailment": "SUPPORTED",
        "scope_match": True,
        "context_preserved": True,
        "qualification_preserved": True,
        "reason": "fixture",
    }

    class FakeBackend:
        backend_id = "paperqa2-fork-v2026.08.12/sparse-docs-v1"

        def __init__(self, **kwargs):
            seen["backend"] = kwargs

        def __call__(self, **_kwargs):
            raise AssertionError("CLI test must not invoke the backend")

    def fake_run(project_dir, cand_id, **kwargs):
        seen.update({"project_dir": project_dir, "cand_id": cand_id, **kwargs})
        return {"schema_version": "L05PaperQA2EuropePmcAcquisitionResult/v1", "status": "FROZEN"}

    import research_loop.l05_curie_cli as extension
    monkeypatch.setattr(extension, "PaperQA2SubprocessBackend", FakeBackend)
    monkeypatch.setattr(
        extension,
        "_semantic_assessor_from_command",
        lambda *_args, **_kwargs: (semantic_assessor, "fixture-semantic-command/v1"),
    )
    monkeypatch.setattr(extension, "run_paperqa2_europepmc_acquisition", fake_run)
    assert args.func(args) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "FROZEN"
    assert seen["cand_id"] == "C001"
    assert seen["backend"]["bridge_script"] == "bridge.py"
    assert seen["pdf_paths"] == {"P1": "paper.pdf"}
    assert seen["semantic_assessor"] is semantic_assessor
    assert seen["semantic_assessor_id"] == "fixture-semantic-command/v1"
    assert seen["run_id"] == "PQA_CLI001"


def test_paperqa2_retrieval_query_combines_paper_anchor_and_targeted_method_intent():
    selected = {"title": "General developmental transcriptomics study"}
    seed = {
        "scientific_question": (
            "Which WGCNA pseudocell construction and module detection method "
            "best captures developmental cell-state programs?"
        ),
        "hypothesis_seed": "WGCNA modules expose coordinated developmental programs.",
    }
    query_plan = {
        "queries": [{
            "query": "WGCNA pseudocell construction module detection",
            "intent": "operator_reproducible_query",
        }],
    }

    query = europepmc_runtime._paperqa2_retrieval_query(
        selected, seed, query_plan
    )

    assert selected["title"] in query
    assert "WGCNA" in query
    assert "pseudocell" in query
    assert "module" in query
    assert query != selected["title"]


def test_paperqa2_retrieval_query_bounds_long_non_ascii_seed():
    selected = {"title": "Paper-local anchor"}
    long_question = "这是一个用于检验检索边界的超长科学问题" * 200
    seed = {
        "scientific_question": long_question,
        "hypothesis_seed": "需要定位具体方法机制",
    }
    query_plan = {"queries": [{"query": long_question, "intent": "seed_question_hypothesis"}]}

    query = europepmc_runtime._paperqa2_retrieval_query(
        selected, seed, query_plan
    )

    assert selected["title"] in query
    assert len(query) < len(long_question)
    assert query != long_question


def test_paperqa2_retrieval_query_fails_closed_without_title_or_target_terms():
    with pytest.raises(CurieContractError, match="paper title"):
        europepmc_runtime._paperqa2_retrieval_query(
            {}, {"scientific_question": "method", "hypothesis_seed": "target"}, {}
        )

    with pytest.raises(CurieContractError, match="targeted scientific retrieval terms"):
        europepmc_runtime._paperqa2_retrieval_query(
            {"title": "Paper"},
            {"scientific_question": "", "hypothesis_seed": ""},
            {"queries": []},
        )


def _fulltext_500(pmcid):
    return HTTPError(
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        500,
        "Internal Server Error",
        {},
        None,
    )


def _fulltext_404(pmcid, code=404):
    return HTTPError(
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        code,
        "Not Found",
        {},
        None,
    )


def _fulltext_503(pmcid):
    return HTTPError(
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        503,
        "Service Unavailable",
        {},
        None,
    )


# --- Title fixtures giving deterministic INCLUDE selection regardless of
# discovery/paper_id canonicalization order. All use empty abstract so relevance
# is driven purely by title-term overlap with the ResearchSeed below:
#   question  : "How is carbon dioxide sensed by yeast?"
#   hypothesis: "Rca1p regulates the carbon dioxide transcriptional response."
# Seed terms (len>2): how, carbon, dioxide, sensed, yeast, rca1p, regulates, response.
_GOOD_TITLE = "Rca1p carbon dioxide sensing in yeast pathway"      # 5 matches -> INCLUDE
_BAD_TITLE = "Metabolic control of carbon dioxide response"        # 3 matches -> INCLUDE
_RESERVE_TITLE = "General methods overview"                        # 0 matches -> RESERVE


# --- H1: current real type: 500 on a known-good pool degrades to RESOURCE_LEVEL ---
# Deterministic regardless of discovery/include order: the first fullTextXML request
# succeeds (becomes the known-good control), the second returns HTTP 500 and is then
# probed against the first -> RESOURCE_LEVEL -> reserve promoted -> FROZEN.
def test_h1_500_after_known_good_control_degrades_to_resource_failure(tmp_path):
    project, seed = _project(tmp_path)
    good_bad = _search_record(
        pmid="11111111", pmcid="PMC1111111", doi="10.1/A", title=_GOOD_TITLE, abstract="")
    bad = _search_record(
        pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_BAD_TITLE, abstract="")
    reserve = _search_record(
        pmid="33333333", pmcid="PMC3333333", doi="10.1/R", title=_RESERVE_TITLE, abstract="")
    fulltext_calls = {"n": 0}

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[good_bad, bad, reserve])  # high/med/low relevance
        if url.endswith("/fullTextXML"):
            fulltext_calls["n"] += 1
            if fulltext_calls["n"] == 1:
                return XML  # first processed paper becomes known-good control
            if fulltext_calls["n"] == 2:
                pmcid = url.rsplit("/", 2)[0].rsplit("/", 1)[-1]
                raise _fulltext_500(pmcid)  # second processed paper -> 500
            return XML  # promoted reserve (3rd) succeeds -> coverage FROZEN
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project, "C001", explicit_queries=["h1 control"],
        max_papers=2, run_id="H1", http_get=http_get,
    )
    audit = json.loads((project / result["acquisition_manifest_path"]).read_text())
    assert len(audit["paper_failures"]) == 1
    failure = audit["paper_failures"][0]
    assert failure["reason_code"] == "RESOURCE_UNAVAILABLE"
    assert failure["retrieval"]["failure_scope"] == "RESOURCE_LEVEL"
    assert failure["retrieval"]["control"]["control_result"] == "HEALTHY"
    assert failure["retrieval"]["control"]["control_http_status"] == 200
    assert len(audit["reserve_promotions"]) == 1
    assert audit["reserve_promotions"][0]["promoted_pmcid"] == "PMC3333333"
    # control probe is a pure diagnostic: no extra source_snapshot
    assert len(audit["source_snapshots"]) == 2  # the 2 successful retrievals (control + promoted reserve)
    assert result["status"] == "FROZEN"


# --- H2: control probe fails => SOURCE_LEVEL fail closed, no promotion ---
def test_h2_500_with_unhealthy_control_fails_closed(tmp_path):
    project, _seed = _project(tmp_path)
    good = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1/A", title=_GOOD_TITLE, abstract="")
    bad = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_BAD_TITLE, abstract="")
    probe_state = {"good_served": False}

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[good, bad])
        if url.endswith("/PMC1111111/fullTextXML"):
            # first call = good retrieval succeeds; second call = control probe -> 503
            if probe_state["good_served"]:
                raise _fulltext_503("PMC1111111")
            probe_state["good_served"] = True
            return XML
        if url.endswith("/PMC2222222/fullTextXML"):
            raise _fulltext_500("PMC2222222")
        raise AssertionError(url)

    with pytest.raises(CurieContractError, match="SOURCE_LEVEL"):
        run_europepmc_acquisition(
            project, "C001", explicit_queries=["h2 unhealthy control"],
            max_papers=2, run_id="H2", http_get=http_get,
        )


# --- H3: first paper 500, no control => SOURCE_LEVEL fail closed, 0 control requests ---
def test_h3_500_first_paper_no_known_good_fail_closed(tmp_path):
    project, _seed = _project(tmp_path)
    bad = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_BAD_TITLE)
    fulltext_calls = []

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[bad, _search_record(pmid="99999999", pmcid="", doi="10.1/X", title=_RESERVE_TITLE)])
        if url.endswith("/PMC2222222/fullTextXML"):
            fulltext_calls.append(url)
            raise _fulltext_500("PMC2222222")
        raise AssertionError(url)  # no control probe possible

    with pytest.raises(CurieContractError, match="no known-good control"):
        run_europepmc_acquisition(
            project, "C001", explicit_queries=["h3 no control"],
            max_papers=1, run_id="H3", http_get=http_get,
        )
    # exactly one failure probe: the original bad paper's URL; no control probe issued
    assert fulltext_calls == [
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC2222222/fullTextXML",
    ]


# --- H4: 404/410 => RESOURCE_LEVEL, no control probe ---
def test_h4_404_is_resource_level_no_control_probe(tmp_path):
    project, _seed = _project(tmp_path)
    good = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1/A", title=_GOOD_TITLE, abstract="")
    missing = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_BAD_TITLE, open_access=True, abstract="")
    reserve = _search_record(pmid="33333333", pmcid="PMC3333333", doi="10.1/R", title=_RESERVE_TITLE, abstract="")
    control_calls = []

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[good, missing, reserve])
        if url.endswith("/PMC1111111/fullTextXML"):
            return XML  # good succeeds first (becomes known-good)
        if url.endswith("/PMC2222222/fullTextXML"):
            raise _fulltext_404("PMC2222222", 404)  # missing -> RESOURCE_LEVEL
        if url.endswith("/PMC3333333/fullTextXML"):
            return XML  # promoted reserve succeeds
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project, "C001", explicit_queries=["h4 404"],
        max_papers=2, run_id="H4", http_get=http_get,
    )
    audit = json.loads((project / result["acquisition_manifest_path"]).read_text())
    failure = audit["paper_failures"][0]
    assert failure["pmcid"] == "PMC2222222"
    assert failure["reason_code"] == "RESOURCE_UNAVAILABLE"
    assert failure["retrieval"]["failure_scope"] == "RESOURCE_LEVEL"
    assert "control" not in failure["retrieval"]  # no control probe for 404
    assert control_calls == []  # no control probe requested at all for 404
    assert audit["reserve_promotions"][0]["promoted_pmcid"] == "PMC3333333"
    assert result["status"] == "FROZEN"


# --- H5: 429 keeps existing retry semantics, not resource downgrade ---
def test_h5_429_does_not_become_resource_failure(tmp_path):
    project, _seed = _project(tmp_path)
    bad = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_BAD_TITLE)

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[bad])
        if url.endswith("/PMC2222222/fullTextXML"):
            raise _fulltext_404("PMC2222222", 429)
        raise AssertionError(url)

    with pytest.raises(CurieContractError):
        run_europepmc_acquisition(
            project, "C001", explicit_queries=["h5 429"],
            max_papers=1, run_id="H5", http_get=http_get,
        )


# --- H6: 502/503/504 retry to exhaustion => SOURCE_LEVEL ---
def test_h6_503_exhaustion_is_source_level(tmp_path):
    project, _seed = _project(tmp_path)
    bad = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_BAD_TITLE)

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[bad])
        if url.endswith("/PMC2222222/fullTextXML"):
            raise _fulltext_503("PMC2222222")
        raise AssertionError(url)

    with pytest.raises(CurieContractError):
        run_europepmc_acquisition(
            project, "C001", explicit_queries=["h6 503"],
            max_papers=1, run_id="H6", http_get=http_get,
        )


# --- H7: control returns 200 but malformed XML => SOURCE_LEVEL ---
def test_h7_malformed_control_xml_is_not_healthy(tmp_path):
    project, _seed = _project(tmp_path)
    good = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1/A", title=_GOOD_TITLE, abstract="")
    bad = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_BAD_TITLE, abstract="")
    probe_state = {"good_served": False}

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[good, bad])
        if url.endswith("/PMC1111111/fullTextXML"):
            if probe_state["good_served"]:
                return b"<not<valid xml"  # control probe: 200 but malformed
            probe_state["good_served"] = True
            return XML
        if url.endswith("/PMC2222222/fullTextXML"):
            raise _fulltext_500("PMC2222222")
        raise AssertionError(url)

    with pytest.raises(CurieContractError, match="SOURCE_LEVEL"):
        run_europepmc_acquisition(
            project, "C001", explicit_queries=["h7 malformed"],
            max_papers=2, run_id="H7", http_get=http_get,
        )


# --- H8: NO_TARGET_SECTIONS zero regression ---
def test_h8_no_target_sections_promote_unchanged(tmp_path):
    project, _seed = _project(tmp_path)
    include = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1000/include", title="First selected paper")
    reserve = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1000/reserve", title="Reserve paper with Results")

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[include, reserve])
        if url.endswith("/PMC1111111/fullTextXML"):
            return XML_WITHOUT_TARGET_SECTIONS
        if url.endswith("/PMC2222222/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project, "C001", explicit_queries=["h8 nts"],
        max_papers=1, run_id="H8", http_get=http_get,
    )
    audit = json.loads((project / result["acquisition_manifest_path"]).read_text())
    assert audit["paper_failures"][0]["reason_code"] == "NO_TARGET_SECTIONS"
    assert audit["reserve_promotions"][0]["promoted_pmcid"] == "PMC2222222"


# --- Systemic outage cannot be masked by already-sufficient evidence ---
def test_systemic_outage_fails_closed_even_with_prior_evidence(tmp_path):
    project, _seed = _project(tmp_path)
    p1 = _search_record(pmid="11111111", pmcid="PMC1111111", doi="10.1/A", title=_GOOD_TITLE, abstract="")
    p2 = _search_record(pmid="22222222", pmcid="PMC2222222", doi="10.1/B", title=_GOOD_TITLE, abstract="")
    p3 = _search_record(pmid="33333333", pmcid="PMC3333333", doi="10.1/C", title=_GOOD_TITLE, abstract="")
    p4 = _search_record(pmid="44444444", pmcid="PMC4444444", doi="10.1/D", title=_GOOD_TITLE, abstract="")
    probe_state = {"pmcs_probed": []}

    def http_get(url, _timeout):
        if "/search?" in url:
            return _search_payload(records=[p1, p2, p3, p4])
        if url.endswith("/PMC1111111/fullTextXML"):
            return XML  # prior evidence
        if url.endswith("/PMC2222222/fullTextXML"):
            return XML  # prior evidence
        if url.endswith("/PMC3333333/fullTextXML"):
            if "PMC3333333" in probe_state["pmcs_probed"]:
                raise _fulltext_503("PMC3333333")  # outage hits control probe
            probe_state["pmcs_probed"].append("PMC3333333")
            return XML  # prior evidence
        if url.endswith("/PMC4444444/fullTextXML"):
            raise _fulltext_500("PMC4444444")  # outage starts on final paper
        raise AssertionError(url)

    with pytest.raises(CurieContractError, match="SOURCE_LEVEL"):
        run_europepmc_acquisition(
            project, "C001", explicit_queries=["outage masked by evidence"],
            max_papers=4, run_id="SYSOUT", http_get=http_get,
        )


def _acquisition_host_api():
    prepare = getattr(europepmc_runtime, "prepare_acquisition_host_step", None)
    assert callable(prepare), (
        "ACQUISITION_HANDOFF_MISSING: prepare_acquisition_host_step is absent"
    )
    submit = getattr(europepmc_runtime, "submit_acquisition_host_response", None)
    assert callable(submit), (
        "ACQUISITION_HANDOFF_MISSING: submit_acquisition_host_response is absent"
    )
    continue_run = getattr(europepmc_runtime, "continue_acquisition", None)
    assert callable(continue_run), (
        "ACQUISITION_HANDOFF_MISSING: continue_acquisition is absent"
    )
    return prepare, submit, continue_run


def _host_project(tmp_path, monkeypatch):
    project, seed = _project(tmp_path)
    store = tmp_path / "host-hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    ledger.bind_project(
        project, "PROJECT:l05-host-test", profile_id=PROFILE_V21_CATALOG_1,
    )
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    return project, seed


def test_host_acquisition_checkpoint_is_versioned_and_resumes_same_request(
    tmp_path, monkeypatch,
):
    project, _seed = _host_project(tmp_path, monkeypatch)
    prepare, _submit, continue_run = _acquisition_host_api()
    prepared = prepare(project, "C001", run_id="HOST_RESUME")

    assert prepared["kind"] == "needs_host"
    checkpoint = prepared["checkpoint"]
    assert checkpoint["schema_version"] == "L05AcquisitionCheckpoint/v1"
    assert checkpoint["phase"] == "REQUEST_PREPARED"
    assert checkpoint["attempt_index"] == 1
    assert checkpoint["execution_mode"] == "agent_native"
    request = prepared["request"]
    assert request["request_id"] == prepared["request_id"]
    assert request["request_sha256"] == hashlib.sha256(
        Path(request["request_path"]).read_bytes()
    ).hexdigest()

    monkeypatch.setattr(
        europepmc_runtime, "_default_http_get",
        lambda *_args: pytest.fail("resume issued HTTP before host submission"),
    )
    resumed = continue_run(project, "C001", run_id="HOST_RESUME")
    assert resumed["kind"] == "needs_host"
    assert resumed["request_id"] == prepared["request_id"]
    assert resumed["checkpoint"]["attempt_index"] == 1
    assert resumed["checkpoint"]["phase"] == "REQUEST_PREPARED"


def test_host_planner_invalid_contract_is_rejected_before_persist_and_same_request_can_be_corrected(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, _continue_run = _acquisition_host_api()
    prepared = prepare(project, "C001", run_id="HOST_INVALID_CORRECTION")
    request_id = prepared["request_id"]
    response_dir = project / "08_Audit" / "host_handoff" / "responses"
    raw_path = response_dir / f"{request_id}.raw"
    receipt_path = response_dir / f"{request_id}.json"

    invalid_plan = _host_planner_plan(seed)
    invalid_plan["core_anchors"][0]["source_type"] = "question"
    invalid_response = project / "invalid-planner-response.json"
    invalid_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "invalid source type", "plan": invalid_plan,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    rejection = None
    try:
        submit(project, "C001", request_id, invalid_response)
    except CurieContractError as exc:
        rejection = exc

    if rejection is None:
        checkpoint_after_invalid_submit = json.loads(
            (project / prepared["checkpoint_path"]).read_text(encoding="utf-8")
        )
        assert raw_path.is_file()
        assert receipt_path.is_file()
        assert request_id in checkpoint_after_invalid_submit["planner_responses"]
        pytest.fail(
            "contract-invalid planner response was durably persisted before validation"
        )

    assert "MODEL_CONTRACT_ERROR" in str(rejection)
    assert "schema invalid" in str(rejection)
    assert not raw_path.exists()
    assert not receipt_path.exists()
    checkpoint_after_rejection = json.loads(
        (project / prepared["checkpoint_path"]).read_text(encoding="utf-8")
    )
    assert checkpoint_after_rejection["phase"] == "REQUEST_PREPARED"
    assert checkpoint_after_rejection["current_request_id"] == request_id
    assert request_id not in checkpoint_after_rejection["planner_responses"]
    assert checkpoint_after_rejection.get("response_sha256") is None

    corrected_response = project / "corrected-planner-response.json"
    corrected_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "valid fixture plan",
        "plan": _planner_schema_plan(_host_planner_plan(seed)),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    receipt = submit(project, "C001", request_id, corrected_response)

    assert receipt["request_id"] == request_id
    assert raw_path.is_file()
    assert receipt_path.is_file()
    checkpoint_after_correction = json.loads(
        (project / prepared["checkpoint_path"]).read_text(encoding="utf-8")
    )
    assert checkpoint_after_correction["phase"] == "RESPONSE_RECORDED"
    assert checkpoint_after_correction["planner_responses"][request_id] == receipt
    assert checkpoint_after_correction["response_sha256"] == receipt["raw_response_sha256"]


def test_host_acquisition_resume_after_validated_checkpoint_does_not_repeat_http(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, continue_run = _acquisition_host_api()
    prepared = prepare(project, "C001", run_id="VALIDATED_RESUME")
    response_path = project / "validated-planner-response.json"
    response_path.write_bytes(json.dumps({
        "status": "PLAN", "reason": "fixture plan",
        "plan": _planner_schema_plan(_host_planner_plan(seed)),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", prepared["request_id"], response_path)
    http_calls = []
    monkeypatch.setattr(europepmc_runtime, "_default_http_get", lambda url, _timeout: (
        http_calls.append(url) or b'{"hitCount":0,"resultList":{"result":[]}}'
    ))

    original_save = europepmc_runtime._save_acquisition_checkpoint
    interrupted = {"done": False}
    def interrupt_after_validated(path, checkpoint):
        saved = original_save(path, checkpoint)
        if checkpoint.get("phase") == "VALIDATED" and not interrupted["done"]:
            interrupted["done"] = True
            raise RuntimeError("simulated interruption after VALIDATED")
        return saved
    monkeypatch.setattr(europepmc_runtime, "_save_acquisition_checkpoint", interrupt_after_validated)
    with pytest.raises(RuntimeError, match="after VALIDATED"):
        continue_run(project, "C001", run_id="VALIDATED_RESUME")
    checkpoint_path = project / prepared["checkpoint_path"]
    saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert saved_checkpoint["phase"] == "VALIDATED"

    monkeypatch.setattr(europepmc_runtime, "_save_acquisition_checkpoint", original_save)
    resumed = continue_run(project, "C001", run_id="VALIDATED_RESUME")
    assert resumed["kind"] == "needs_host"
    assert resumed["request_id"] != prepared["request_id"]
    assert len(http_calls) == 1
    same_request = continue_run(project, "C001", run_id="VALIDATED_RESUME")
    assert same_request["request_id"] == resumed["request_id"]
    assert len(http_calls) == 1


@pytest.mark.parametrize(
    "tampered_field",
    ["seed_sha256", "feedback_sha256", "source_sha256", "attempt_index", "execution_mode"],
)
def test_host_acquisition_resume_rejects_checkpoint_identity_tampering(
    tmp_path, monkeypatch, tampered_field,
):
    project, _seed = _host_project(tmp_path, monkeypatch)
    prepare, _submit, continue_run = _acquisition_host_api()
    prepared = prepare(project, "C001", run_id="HOST_TAMPER")
    checkpoint_path = project / prepared["checkpoint_path"]
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint[tampered_field] = (
        999 if tampered_field == "attempt_index"
        else "headless" if tampered_field == "execution_mode"
        else "0" * 64
    )
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    with pytest.raises((CurieContractError, europepmc_runtime.CurieAcquisitionError),
                       match="(?i)(checkpoint|hash|attempt|seed|feedback|source|mode)"):
        continue_run(project, "C001", run_id="HOST_TAMPER")


def test_uncertain_http_result_blocks_and_resume_does_not_retry(tmp_path, monkeypatch):
    project, _seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, continue_run = _acquisition_host_api()
    prepared = prepare(project, "C001", run_id="UNCERTAIN_HTTP")
    plan_response = project / "planner-response.json"
    plan_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "fixture plan",
        "plan": _planner_schema_plan(_host_planner_plan(_seed)),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submitted = submit(project, "C001", prepared["request_id"], plan_response)
    assert submitted["raw_response_sha256"] == hashlib.sha256(
        plan_response.read_bytes()
    ).hexdigest()
    checkpoint = json.loads(
        (project / prepared["checkpoint_path"]).read_text(encoding="utf-8")
    )
    assert checkpoint["phase"] == "RESPONSE_RECORDED"
    assert checkpoint["response_sha256"] == submitted["raw_response_sha256"]
    requests = []

    def sent_then_lost(url, _timeout):
        requests.append(url)
        raise TimeoutError("request may have reached Europe PMC; response was lost")

    monkeypatch.setattr(europepmc_runtime, "_default_http_get", sent_then_lost)
    first = continue_run(project, "C001", run_id="UNCERTAIN_HTTP")
    second = continue_run(project, "C001", run_id="UNCERTAIN_HTTP")

    assert first["kind"] == second["kind"] == "blocked"
    assert first["reason"] == second["reason"] == "uncertain_external_result"
    assert len(requests) == 1


def test_host_and_headless_receipt_variants_use_shared_manifest_validator(
    tmp_path, monkeypatch,
):
    project, _seed = _host_project(tmp_path, monkeypatch)
    seed = _seed
    semantic_step, submit, continue_run, _http_calls = _host_semantic_pending(
        project, seed, "HOST_MANIFEST", monkeypatch,
    )
    submitted_evidence = []
    while semantic_step["kind"] == "needs_host":
        request = semantic_step["request"]
        evidence_id = request["inputs"]["extract"]["evidence_id"]
        response_path = project / f"host-manifest-semantic-{len(submitted_evidence) + 1}.json"
        response_path.write_bytes(json.dumps({
            "entailment": "SUPPORTED", "scope_match": True,
            "context_preserved": True, "qualification_preserved": True,
            "reason": "manifest receipt dispatch fixture",
        }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        submit(project, "C001", semantic_step["request_id"], response_path)
        submitted_evidence.append(evidence_id)
        semantic_step = continue_run(project, "C001", run_id="HOST_MANIFEST")
    attempt_path = project / "08_Audit" / "l05_acquisition" / "C001" / "HOST_MANIFEST" / "attempt_001.json"
    located = json.loads(attempt_path.read_text(encoding="utf-8"))["located_evidence"]
    assert submitted_evidence == [item["evidence_id"] for item in located]
    assert semantic_step["kind"] in {"FROZEN", "INSUFFICIENT_STOP"}
    manifest = json.loads((project / semantic_step["acquisition_manifest_path"]).read_text(
        encoding="utf-8"
    ))
    assert manifest["attempts"][0]["query_plan"]["planning_provenance"]["receipt"]["schema_version"] == (
        "L05PlannerHostReceipt/v1"
    )
    assert callable(europepmc_runtime._validate_acquisition_manifest)
    assert callable(europepmc_runtime.validate_europepmc_acquisition_result)


def _host_semantic_pending(project, seed, run_id, monkeypatch, *, xml=XML):
    prepare, submit, continue_run = _acquisition_host_api()
    prepared = prepare(project, "C001", run_id=run_id)
    plan_response = project / f"{run_id}-planner-response.json"
    plan_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "fixture plan",
        "plan": _planner_schema_plan(_host_planner_plan(seed)),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", prepared["request_id"], plan_response)
    paper = _search_record(title=_GOOD_TITLE)

    http_calls = []
    def http_get(url, _timeout):
        http_calls.append(url)
        if "/search?" in url:
            return _search_payload(records=[paper])
        if url.endswith(f"/{paper['pmcid']}/fullTextXML"):
            return xml
        raise AssertionError(url)

    monkeypatch.setattr(europepmc_runtime, "_default_http_get", http_get)
    semantic_step = continue_run(project, "C001", run_id=run_id)
    return semantic_step, submit, continue_run, http_calls


def test_single_located_host_receipt_is_bound_into_manifest_attempt(tmp_path, monkeypatch):
    project, seed = _host_project(tmp_path, monkeypatch)
    one_located_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <article><body><sec><title>Results</title>
    <p>Rca1p was required for the transcriptional response to carbon dioxide.</p>
    </sec></body></article>'''
    semantic_step, submit, continue_run, http_calls = _host_semantic_pending(
        project, seed, "HOST_SINGLE_LOCATED", monkeypatch, xml=one_located_xml,
    )
    assert semantic_step["kind"] == "needs_host"
    request = semantic_step["request"]
    inputs = request["inputs"]
    assert inputs["extract"]["verification_status"] == "LOCATED"
    assert inputs["extract_sha256"] == hashlib.sha256(
        json.dumps(inputs["extract"], ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    response_path = project / "single-located-semantic-response.json"
    response_path.write_bytes(json.dumps({
        "entailment": "SUPPORTED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True,
        "reason": "single extract manifest provenance fixture",
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    response_receipt = submit(project, "C001", semantic_step["request_id"], response_path)
    completed = continue_run(project, "C001", run_id="HOST_SINGLE_LOCATED")
    assert completed["kind"] in {"FROZEN", "INSUFFICIENT_STOP"}
    assert len(http_calls) == 2
    canonical_result = {key: value for key, value in completed.items() if key != "kind"}
    assert europepmc_runtime.validate_europepmc_acquisition_result(
        project, "C001", canonical_result,
    ) == canonical_result
    response_artifact = Path(response_receipt["raw_response_path"])
    original_response_bytes = response_artifact.read_bytes()
    response_artifact.write_bytes(original_response_bytes + b"\nchanged")
    with pytest.raises((CurieContractError, europepmc_runtime.CurieAcquisitionError),
                       match="(?i)(response|receipt|hash|changed|provenance)"):
        europepmc_runtime.validate_europepmc_acquisition_result(
            project, "C001", canonical_result,
        )
    response_artifact.write_bytes(original_response_bytes)
    manifest = json.loads((project / completed["acquisition_manifest_path"]).read_text(
        encoding="utf-8"
    ))
    attempt = manifest["attempts"][0]
    host_receipts = attempt["semantic_host_receipts"]
    assert len(host_receipts) == 1
    provenance = host_receipts[0]
    assert provenance["evidence_id"] == inputs["extract"]["evidence_id"]
    assert provenance["host_request"] == {
        "request_id": request["request_id"],
        "request_path": request["request_path"],
        "request_sha256": request["request_sha256"],
    }
    assert provenance["host_response_receipt"] == response_receipt
    assert provenance["extract_sha256"] == inputs["extract_sha256"]
    assert provenance["claim_sha256"] == inputs["claim_sha256"]
    assert provenance["source_sha256"] == inputs["source_sha256"]
    assert hashlib.sha256(Path(request["request_path"]).read_bytes()).hexdigest() == (
        request["request_sha256"]
    )
    assert hashlib.sha256(Path(response_receipt["raw_response_path"]).read_bytes()).hexdigest() == (
        response_receipt["raw_response_sha256"]
    )


def test_host_located_semantic_handoff_binds_source_and_uses_shared_manifest_owner(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    verify_calls = []
    original_verify = europepmc_runtime.SemanticEvidenceVerifier.verify
    def counted_verify(verifier, *args, **kwargs):
        verify_calls.append(args[0].get("evidence_id"))
        return original_verify(verifier, *args, **kwargs)
    monkeypatch.setattr(
        europepmc_runtime.SemanticEvidenceVerifier, "verify", counted_verify,
    )
    semantic_step, submit, continue_run, http_calls = _host_semantic_pending(
        project, seed, "HOST_SEMANTIC", monkeypatch,
    )
    request_ids = []
    request_evidence_ids = []
    request_hashes = {}
    expected_receipts = {}
    final_inputs = {}
    original_save = europepmc_runtime._save_acquisition_checkpoint
    interrupted = {"done": False}
    def interrupt_after_commit(path, checkpoint):
        saved = original_save(path, checkpoint)
        if checkpoint.get("phase") == "COMMITTED" and not interrupted["done"]:
            interrupted["done"] = True
            raise RuntimeError("simulated interruption after COMMITTED")
        return saved
    while semantic_step["kind"] == "needs_host":
        request = semantic_step["request"]
        inputs = request["inputs"]
        extract = inputs["extract"]
        assert extract["verification_status"] == "LOCATED"
        assert inputs["extract_sha256"] == hashlib.sha256(
            json.dumps(extract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert inputs["claim_sha256"] == hashlib.sha256(inputs["claim"].encode("utf-8")).hexdigest()
        assert inputs["source_sha256"] == extract["retrieval"]["source_sha256"]
        assert request["request_id"] not in request_ids
        request_ids.append(request["request_id"])
        request_evidence_ids.append(extract["evidence_id"])
        request_hashes[extract["evidence_id"]] = inputs["extract_sha256"]
        final_inputs = inputs
        assessor_response = project / f"semantic-response-{len(request_ids)}.json"
        assessor_response.write_bytes(json.dumps({
            "entailment": "SUPPORTED", "scope_match": True,
            "context_preserved": True, "qualification_preserved": True,
            "reason": "The located passage supports the scoped claim.",
        }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        response_receipt = submit(project, "C001", request["request_id"], assessor_response)
        expected_receipts[extract["evidence_id"]] = {
            "request_id": request["request_id"],
            "request_path": request["request_path"],
            "request_sha256": request["request_sha256"],
            "raw_response_path": response_receipt["raw_response_path"],
            "raw_response_sha256": response_receipt["raw_response_sha256"],
            "extract_sha256": inputs["extract_sha256"],
            "claim_sha256": inputs["claim_sha256"],
            "source_sha256": inputs["source_sha256"],
        }
        monkeypatch.setattr(
            europepmc_runtime, "_save_acquisition_checkpoint", interrupt_after_commit,
        )
        try:
            next_step = continue_run(project, "C001", run_id="HOST_SEMANTIC")
        except RuntimeError as exc:
            if "after COMMITTED" not in str(exc):
                raise
            monkeypatch.setattr(
                europepmc_runtime, "_save_acquisition_checkpoint", original_save,
            )
            completed = continue_run(project, "C001", run_id="HOST_SEMANTIC")
            break
        monkeypatch.setattr(
            europepmc_runtime, "_save_acquisition_checkpoint", original_save,
        )
        semantic_step = next_step
    attempt_path = project / "08_Audit" / "l05_acquisition" / "C001" / "HOST_SEMANTIC" / "attempt_001.json"
    located = json.loads(attempt_path.read_text(encoding="utf-8"))["located_evidence"]
    assert request_evidence_ids == [item["evidence_id"] for item in located]
    assert len(set(request_ids)) == len(located)
    assert len(http_calls) == 2
    verify_counts = {evidence_id: verify_calls.count(evidence_id) for evidence_id in request_evidence_ids}
    assert verify_counts == {evidence_id: 2 for evidence_id in request_evidence_ids}
    assert completed["kind"] in {"FROZEN", "INSUFFICIENT_STOP"}
    canonical_result = {key: value for key, value in completed.items() if key != "kind"}
    assert europepmc_runtime.validate_europepmc_acquisition_result(
        project, "C001", canonical_result,
    ) == canonical_result
    manifest = json.loads((project / completed["acquisition_manifest_path"]).read_text(
        encoding="utf-8"
    ))
    semantic = manifest["attempts"][0]["semantic_verifications"]
    assert [item["evidence_id"] for item in semantic] == request_evidence_ids
    assert all(item["verdict"] == "PASS" and item["assessor_id"] for item in semantic)
    assert {item["evidence_id"]: item["extract_sha256"] for item in semantic} == request_hashes
    assert {item["evidence_id"]: item["claim_sha256"] for item in semantic} == {
        item["evidence_id"]: final_inputs["claim_sha256"] for item in semantic
    }
    assert [item["evidence_id"] for item in manifest["attempts"][0]["verified_evidence"]] == (
        request_evidence_ids
    )
    from research_loop import host_handoff
    semantic_host_receipts = manifest["attempts"][0]["semantic_host_receipts"]
    manifest_host_receipts = {
        item["evidence_id"]: item for item in semantic_host_receipts
    }
    assert set(manifest_host_receipts) == set(request_evidence_ids)
    for evidence_id, expected in expected_receipts.items():
        provenance = manifest_host_receipts[evidence_id]
        assert provenance["extract_sha256"] == expected["extract_sha256"]
        assert provenance["claim_sha256"] == expected["claim_sha256"]
        assert provenance["source_sha256"] == expected["source_sha256"]
        request_ref = provenance["host_request"]
        response_receipt = provenance["host_response_receipt"]
        assert response_receipt["schema_version"] == "HostResponseReceipt/v1"
        assert request_ref["request_id"] == expected["request_id"]
        assert request_ref["request_path"] == expected["request_path"]
        assert request_ref["request_sha256"] == expected["request_sha256"]
        assert response_receipt["request_id"] == expected["request_id"]
        assert response_receipt["request_path"] == expected["request_path"]
        assert response_receipt["request_sha256"] == expected["request_sha256"]
        assert response_receipt["raw_response_path"] == expected["raw_response_path"]
        assert response_receipt["raw_response_sha256"] == expected["raw_response_sha256"]
        assert hashlib.sha256(Path(request_ref["request_path"]).read_bytes()).hexdigest() == (
            expected["request_sha256"]
        )
        assert hashlib.sha256(Path(response_receipt["raw_response_path"]).read_bytes()).hexdigest() == (
            expected["raw_response_sha256"]
        )
        host_request = host_handoff.load_request(project, expected["request_id"])
        assert host_request["request_sha256"] == expected["request_sha256"]
        inputs = host_request["inputs"]
        assert inputs["extract_sha256"] == expected["extract_sha256"]
        assert inputs["claim_sha256"] == expected["claim_sha256"]
        assert inputs["source_sha256"] == expected["source_sha256"]
        assert inputs["extract"]["evidence_id"] == evidence_id
    verification_calls_after_completion = list(verify_calls)
    resumed = continue_run(project, "C001", run_id="HOST_SEMANTIC")
    assert resumed == completed
    assert len(http_calls) == 2
    assert verify_calls == verification_calls_after_completion


@pytest.mark.parametrize(
    "forged_field",
    ["verdict", "source_fidelity", "evidence_id", "verification_id"],
)
def test_host_semantic_response_cannot_supply_verifier_authority(
    tmp_path, monkeypatch, forged_field,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    semantic_step, submit, _continue_run, _http_calls = _host_semantic_pending(
        project, seed, "HOST_FORGED_SEMANTIC", monkeypatch,
    )
    assert "extract_sha256" in semantic_step["request"]["inputs"]
    response = {
        "entailment": "SUPPORTED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True,
        "reason": "fixture", forged_field: "PASS",
    }
    response_path = project / "forged-semantic-response.json"
    response_path.write_bytes(json.dumps(response).encode("utf-8"))
    with pytest.raises((CurieContractError, europepmc_runtime.CurieAcquisitionError),
                       match="(?i)(semantic|unsupported|assessor|authority|response)"):
        submit(project, "C001", semantic_step["request_id"], response_path)


def test_host_semantic_response_rejects_changed_located_extract(tmp_path, monkeypatch):
    project, seed = _host_project(tmp_path, monkeypatch)
    semantic_step, submit, _continue_run, _http_calls = _host_semantic_pending(
        project, seed, "HOST_CHANGED_EXTRACT", monkeypatch,
    )
    assert "extract_sha256" in semantic_step["request"]["inputs"]
    request_path = Path(semantic_step["request"]["request_path"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["inputs"]["extract"]["text"] += " changed after review"
    request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    response_path = project / "changed-extract-response.json"
    response_path.write_bytes(json.dumps({
        "entailment": "SUPPORTED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True,
        "reason": "fixture",
    }).encode("utf-8"))
    with pytest.raises((CurieContractError, europepmc_runtime.CurieAcquisitionError),
                       match="(?i)(request|extract|hash|changed|checkpoint)"):
        submit(project, "C001", semantic_step["request_id"], response_path)


def test_host_acquisition_without_located_extract_creates_no_semantic_request(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    result, _submit, _continue_run, _http_calls = _host_semantic_pending(
        project, seed, "HOST_NO_LOCATED", monkeypatch,
        xml=XML_WITHOUT_TARGET_SECTIONS,
    )
    request = result.get("request") or {}
    assert result["kind"] in {"needs_host", "deterministic", "FROZEN", "INSUFFICIENT_STOP"}
    assert "extract_sha256" not in request.get("inputs", {})


def test_agent_native_prepare_rejects_active_headless_acquisition_owner(
    tmp_path, monkeypatch,
):
    project, _seed = _host_project(tmp_path, monkeypatch)
    empty = b'{"hitCount":0,"resultList":{"result":[]}}'
    run_europepmc_acquisition(
        project, "C001", explicit_queries=["headless owner"],
        run_id="MODE_HEADLESS_OWNER", http_get=lambda *_args: empty,
    )
    prepare, _submit, _continue_run = _acquisition_host_api()
    with pytest.raises((CurieContractError, europepmc_runtime.CurieAcquisitionError),
                       match="(?i)(mode|headless|owner|execution)"):
        prepare(project, "C001", run_id="MODE_HEADLESS_OWNER")


def test_headless_run_rejects_active_agent_native_acquisition_owner(
    tmp_path, monkeypatch,
):
    project, _seed = _host_project(tmp_path, monkeypatch)
    prepare, _submit, _continue_run = _acquisition_host_api()
    prepare(project, "C001", run_id="MODE_AGENT_NATIVE_OWNER")
    with pytest.raises((CurieContractError, europepmc_runtime.CurieAcquisitionError),
                       match="(?i)(mode|agent.native|owner|execution)"):
        run_europepmc_acquisition(
            project, "C001", explicit_queries=["must not switch mode"],
            run_id="MODE_AGENT_NATIVE_OWNER",
            http_get=lambda *_args: pytest.fail("mode mismatch performed HTTP"),
        )


def test_host_resume_rejects_legacy_orphan_without_versioned_checkpoint(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    run_id = "LEGACY_ORPHAN"
    audit_root = project / "08_Audit" / "l05_acquisition" / "C001"
    owner_path = audit_root / "first_1.json"
    owner_path.parent.mkdir(parents=True, exist_ok=True)
    owner_path.write_text(json.dumps({
        "schema_version": "L05FirstAcquisitionOwner/v1",
        "candidate_id": "C001", "round_id": "1",
        "seed_sha256": research_seed.seed_sha256(seed),
        "acquisition_run_id": run_id,
    }), encoding="utf-8")
    orphan = audit_root / run_id / "planner_001" / "proposal.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text('{"status":"PLAN"}', encoding="utf-8")

    prepare, _submit, _continue_run = _acquisition_host_api()
    with pytest.raises((CurieContractError, europepmc_runtime.CurieAcquisitionError),
                       match="(?i)(incomplete|checkpoint|recovery|owner)"):
        prepare(project, "C001", run_id=run_id)


def test_host_idempotent_old_planner_response_does_not_rewind_current_semantic_request(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, continue_run = _acquisition_host_api()
    run_id = "IDEMPOTENT_OLD_PLANNER"
    planner = prepare(project, "C001", run_id=run_id)
    planner_response = project / "idempotent-planner-response.json"
    planner_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "fixture plan",
        "plan": _planner_schema_plan(_host_planner_plan(seed)),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", planner["request_id"], planner_response)
    paper = _search_record(title=_GOOD_TITLE)
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <article><body><sec><title>Results</title>
    <p>Rca1p was required for the transcriptional response to carbon dioxide.</p>
    </sec></body></article>'''
    monkeypatch.setattr(europepmc_runtime, "_default_http_get", lambda url, _timeout: (
        _search_payload(records=[paper]) if "/search?" in url else xml
    ))
    semantic = continue_run(project, "C001", run_id=run_id)
    assert semantic["kind"] == "needs_host"
    assert semantic["request"]["identity"]["stage"].startswith("semantic:")
    checkpoint_path = project / semantic["checkpoint_path"]
    before = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert before["current_request_id"] == semantic["request_id"]
    assert before["phase"] == "REQUEST_PREPARED"

    submit(project, "C001", planner["request_id"], planner_response)

    after = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert after["current_request_id"] == semantic["request_id"]
    assert after["phase"] == "REQUEST_PREPARED"
    semantic_response = project / "semantic-response-after-old-idempotent-submit.json"
    semantic_response.write_bytes(json.dumps({
        "entailment": "SUPPORTED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True,
        "reason": "the current semantic request remains submit-able",
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    receipt = submit(project, "C001", semantic["request_id"], semantic_response)
    assert receipt["request_id"] == semantic["request_id"]


def test_host_terminal_no_admissible_replan_persists_validated_planner_receipt(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, continue_run = _acquisition_host_api()
    run_id = "HOST_NO_ADMISSIBLE"
    planner = prepare(project, "C001", run_id=run_id)
    first_plan_response = project / "host-no-admissible-plan.json"
    first_plan_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "fixture plan",
        "plan": _planner_schema_plan(_host_planner_plan(seed)),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", planner["request_id"], first_plan_response)
    http_calls = []
    monkeypatch.setattr(europepmc_runtime, "_default_http_get", lambda url, _timeout: (
        http_calls.append(url) or b'{"hitCount":0,"resultList":{"result":[]}}'
    ))
    replan = continue_run(project, "C001", run_id=run_id)
    assert replan["kind"] == "needs_host"
    assert replan["request"]["identity"]["stage"] == "planner"
    terminal_response = project / "host-no-admissible-terminal.json"
    terminal_response.write_bytes(json.dumps({
        "status": "NO_ADMISSIBLE_REPLAN", "reason": "finite candidates exhausted",
        "plan": None,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    terminal_receipt = submit(project, "C001", replan["request_id"], terminal_response)
    completed = continue_run(project, "C001", run_id=run_id)
    assert completed["kind"] == "INSUFFICIENT_STOP"
    assert len(http_calls) == 1
    canonical = {key: value for key, value in completed.items() if key != "kind"}
    assert europepmc_runtime.validate_europepmc_acquisition_result(
        project, "C001", canonical,
    ) == canonical
    manifest = json.loads((project / completed["acquisition_manifest_path"]).read_text(
        encoding="utf-8"
    ))
    terminal = manifest["planner_terminal"]
    assert terminal["status"] == "NO_ADMISSIBLE_REPLAN"
    assert terminal["receipt"]["host_response_receipt"] == terminal_receipt
    assert terminal["receipt"]["schema_version"] == "L05PlannerHostReceipt/v1"
    assert terminal["proposal_sha256"] == terminal_receipt["raw_response_sha256"]


def test_host_reproposal_required_issues_distinct_followup_handoff(tmp_path, monkeypatch):
    project, seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, continue_run = _acquisition_host_api()
    run_id = "HOST_REPROPOSAL_REQUIRED"
    initial_plan = _host_planner_plan(seed)
    question = seed["scientific_question"]
    yeast_start = question.index("yeast")
    initial_plan["optional_concepts"] = [{
        "concept_id": "yeast", "term": "yeast",
        "source_type": "QUESTION", "source_field": "scientific_question",
        "text_snippet": "yeast",
        "source_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "start": yeast_start, "end": yeast_start + len("yeast"), "synonyms": [],
    }]
    initial_plan["intents"][0]["optional_concept_ids"] = ["yeast"]

    first = prepare(project, "C001", run_id=run_id)
    first_response = project / "host-reproposal-initial.json"
    first_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "fixture plan with optional concept",
        "plan": _planner_schema_plan(initial_plan),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", first["request_id"], first_response)

    http_calls = []
    paper = _search_record(title=_GOOD_TITLE)
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <article><body><sec><title>Results</title>
    <p>Rca1p was required for the transcriptional response to carbon dioxide.</p>
    </sec></body></article>'''
    search_count = {"value": 0}
    def http_get(url, _timeout):
        http_calls.append(url)
        if "/search?" not in url:
            return xml
        search_count["value"] += 1
        if search_count["value"] == 1:
            return b'{"hitCount":0,"resultList":{"result":[]}}'
        return _search_payload(records=[paper])
    monkeypatch.setattr(europepmc_runtime, "_default_http_get", http_get)
    replan = continue_run(project, "C001", run_id=run_id)
    assert replan["kind"] == "needs_host"
    assert replan["request"]["identity"]["stage"] == "planner"
    first_replan_request = replan["request"]["inputs"]["planner_request"]
    feedback = first_replan_request["feedback"]
    candidates, _enumeration = query_planner._admissible_replan_candidates(
        feedback["previous_plan"], seed, feedback, 1,
    )
    assert candidates

    no_plan = project / "host-reproposal-no-plan.json"
    no_plan.write_bytes(json.dumps({
        "status": "NO_ADMISSIBLE_REPLAN", "reason": "no plan proposed",
        "plan": None,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    no_plan_receipt = submit(project, "C001", replan["request_id"], no_plan)

    followup = continue_run(project, "C001", run_id=run_id)
    assert followup["kind"] == "needs_host"
    assert followup["request"]["identity"]["stage"] == "planner"
    assert followup["request_id"] != replan["request_id"]
    next_request = followup["request"]["inputs"]["planner_request"]
    assert next_request["prompt"] != first_replan_request["prompt"]
    assert candidates[0][1]["plan_content_hash"] in next_request["prompt"]

    response_dir = project / "08_Audit" / "host_handoff" / "responses"
    checkpoint_before = (project / followup["checkpoint_path"]).read_bytes()
    invalid_choice = project / "host-invalid-candidate-choice.json"
    for response in (
        {"status": "SELECT_CANDIDATE", "reason": "unknown", "candidate_id": "unknown"},
        {"status": "SELECT_CANDIDATE", "reason": "forged",
         "candidate_id": next_request["candidates"][0]["candidate_id"], "plan": candidates[0][1]},
    ):
        invalid_choice.write_bytes(json.dumps(response).encode("utf-8"))
        with pytest.raises(europepmc_runtime.CurieAcquisitionError, match="planner host response rejected"):
            submit(project, "C001", followup["request_id"], invalid_choice)
        assert not (response_dir / f"{followup['request_id']}.raw").exists()
        assert not (response_dir / f"{followup['request_id']}.json").exists()
        assert (project / followup["checkpoint_path"]).read_bytes() == checkpoint_before

    _operation, candidate_plan = candidates[0]
    accepted_response = project / "host-reproposal-accepted-plan.json"
    accepted_response.write_bytes(json.dumps({
        "status": "SELECT_CANDIDATE", "reason": f"validated candidate: {_operation}",
        "candidate_id": next_request["candidates"][0]["candidate_id"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    followup_receipt = submit(project, "C001", followup["request_id"], accepted_response)

    semantic = continue_run(project, "C001", run_id=run_id)
    assert semantic["kind"] == "needs_host"
    assert semantic["request"]["identity"]["stage"].startswith("semantic:")
    semantic_response = project / "host-reproposal-semantic.json"
    semantic_response.write_bytes(json.dumps({
        "entailment": "SUPPORTED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True,
        "reason": "fixture semantic support",
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", semantic["request_id"], semantic_response)

    completed = continue_run(project, "C001", run_id=run_id)
    assert completed["kind"] in {"FROZEN", "INSUFFICIENT_STOP"}
    canonical = {key: value for key, value in completed.items() if key != "kind"}
    assert europepmc_runtime.validate_europepmc_acquisition_result(
        project, "C001", canonical,
    ) == canonical
    manifest = json.loads((project / completed["acquisition_manifest_path"]).read_text(
        encoding="utf-8"
    ))
    accepted_attempt = next(
        attempt for attempt in manifest["attempts"]
        if attempt["query_plan"].get("planning_provenance", {}).get("proposal_sha256")
        == followup_receipt["raw_response_sha256"]
    )
    assert accepted_attempt["query_plan"]["planning"] == candidate_plan
    planner_receipt = accepted_attempt["query_plan"]["planning_provenance"]["receipt"]
    assert planner_receipt["host_response_receipt"] == followup_receipt
    assert planner_receipt["reproposal"]["source_request_id"] == replan["request_id"]
    assert planner_receipt["reproposal"]["source_response_receipt"] == no_plan_receipt
    assert planner_receipt["reproposal"]["followup_request"]["request_id"] == followup["request_id"]
    assert len(http_calls) >= 2
    stripped_receipt = dict(planner_receipt)
    stripped_receipt.pop("reproposal")
    with pytest.raises(europepmc_runtime.CurieAcquisitionError, match="selection reproposal provenance is missing"):
        europepmc_runtime._validated_planner_proposal(
            project, "C001", run_id, accepted_attempt["attempt_index"], stripped_receipt,
            followup_receipt["raw_response_sha256"], seed=seed,
        )


def test_host_reproposal_budget_rejects_second_no_admissible_response(tmp_path, monkeypatch):
    project, seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, continue_run = _acquisition_host_api()
    run_id = "HOST_REPROPOSAL_BUDGET"
    initial_plan = _host_planner_plan(seed)
    question = seed["scientific_question"]
    yeast_start = question.index("yeast")
    initial_plan["optional_concepts"] = [{
        "concept_id": "yeast", "term": "yeast",
        "source_type": "QUESTION", "source_field": "scientific_question",
        "text_snippet": "yeast",
        "source_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "start": yeast_start, "end": yeast_start + len("yeast"), "synonyms": [],
    }]
    initial_plan["intents"][0]["optional_concept_ids"] = ["yeast"]
    first = prepare(project, "C001", run_id=run_id)
    first_response = project / "host-reproposal-budget-initial.json"
    first_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "fixture plan with optional concept",
        "plan": _planner_schema_plan(initial_plan),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", first["request_id"], first_response)
    monkeypatch.setattr(europepmc_runtime, "_default_http_get", lambda *_: (
        b'{"hitCount":0,"resultList":{"result":[]}}'
    ))

    replan = continue_run(project, "C001", run_id=run_id)
    feedback = replan["request"]["inputs"]["planner_request"]["feedback"]
    candidates, _enumeration = query_planner._admissible_replan_candidates(
        feedback["previous_plan"], seed, feedback, 1,
    )
    assert candidates
    first_no_plan = project / "host-reproposal-budget-first-no-plan.json"
    first_no_plan.write_bytes(json.dumps({
        "status": "NO_ADMISSIBLE_REPLAN", "reason": "first no-plan proposal",
        "plan": None,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", replan["request_id"], first_no_plan)
    followup = continue_run(project, "C001", run_id=run_id)
    assert followup["kind"] == "needs_host"
    assert followup["request_id"] != replan["request_id"]

    second_no_plan = project / "host-reproposal-budget-second-no-plan.json"
    second_no_plan.write_bytes(json.dumps({
        "status": "NO_ADMISSIBLE_REPLAN", "reason": "second no-plan proposal",
        "plan": None,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    with pytest.raises(europepmc_runtime.CurieAcquisitionError, match="schema invalid"):
        submit(project, "C001", followup["request_id"], second_no_plan)
    response_dir = project / "08_Audit" / "host_handoff" / "responses"
    assert not (response_dir / f"{followup['request_id']}.json").exists()
    assert not (response_dir / f"{followup['request_id']}.raw").exists()
    checkpoint = json.loads((project / followup["checkpoint_path"]).read_text(encoding="utf-8"))
    assert checkpoint["current_request_id"] == followup["request_id"]
    assert len(checkpoint["planner_requests"]) == 3


def test_host_replan_rebinds_same_located_evidence_to_attempt_specific_extract(
    tmp_path, monkeypatch,
):
    project, seed = _host_project(tmp_path, monkeypatch)
    prepare, submit, continue_run = _acquisition_host_api()
    run_id = "HOST_CROSS_ATTEMPT_EVIDENCE"
    first_plan = _host_planner_plan(seed)
    question = seed["scientific_question"]
    yeast_start = question.index("yeast")
    first_plan["optional_concepts"] = [{
        "concept_id": "yeast",
        "term": "yeast",
        "source_type": "QUESTION",
        "source_field": "scientific_question",
        "text_snippet": "yeast",
        "source_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "start": yeast_start,
        "end": yeast_start + len("yeast"),
        "synonyms": [],
    }]
    first_plan["intents"][0]["optional_concept_ids"] = ["yeast"]
    planner = prepare(project, "C001", run_id=run_id)
    first_planner_response = project / "cross-attempt-planner-1.json"
    first_planner_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": "include seed-bound optional term",
        "plan": _planner_schema_plan(first_plan),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", planner["request_id"], first_planner_response)

    paper = _search_record(title=_GOOD_TITLE)
    one_located_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <article><body><sec><title>Results</title>
    <p>Rca1p was required for the transcriptional response to carbon dioxide.</p>
    </sec></body></article>'''
    http_calls = []
    def http_get(url, _timeout):
        http_calls.append(url)
        if "/search?" in url:
            return _search_payload(records=[paper])
        return one_located_xml
    monkeypatch.setattr(europepmc_runtime, "_default_http_get", http_get)

    semantic_attempt_1 = continue_run(project, "C001", run_id=run_id)
    assert semantic_attempt_1["kind"] == "needs_host"
    first_extract = semantic_attempt_1["request"]["inputs"]["extract"]
    first_evidence_id = first_extract["evidence_id"]
    first_extract_sha = semantic_attempt_1["request"]["inputs"]["extract_sha256"]
    first_path = first_extract["retrieval"]["snapshot_path"]
    first_semantic_response = project / "cross-attempt-semantic-1.json"
    first_semantic_response.write_bytes(json.dumps({
        "entailment": "UNRELATED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True,
        "reason": "first acquisition attempt is semantically unrelated",
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", semantic_attempt_1["request_id"], first_semantic_response)

    replan = continue_run(project, "C001", run_id=run_id)
    assert replan["kind"] == "needs_host"
    assert replan["request"]["identity"]["stage"] == "planner"
    planner_request = replan["request"]["inputs"]["planner_request"]
    feedback = planner_request["feedback"]
    request_inputs = replan["request"]["inputs"]
    canonical_feedback_sha256 = hashlib.sha256(
        query_planner._canonical(feedback)
    ).hexdigest()
    assert request_inputs["feedback"] == feedback
    assert request_inputs["feedback_sha256"] == planner_request["feedback_sha256"]
    assert planner_request["feedback_sha256"] == canonical_feedback_sha256
    candidates, _enumeration = query_planner._admissible_replan_candidates(
        feedback["previous_plan"], seed, feedback, 1,
    )
    assert candidates
    _operation, candidate_plan = candidates[0]
    proposal_plan = {
        key: candidate_plan[key]
        for key in (
            "schema_version", "planner", "seed_sha256", "reformulation_index",
            "core_anchors", "optional_concepts", "unresolved_entities",
            "advisory_search_constraints", "intents",
        )
    }
    second_planner_response = project / "cross-attempt-planner-2.json"
    second_planner_response.write_bytes(json.dumps({
        "status": "PLAN", "reason": f"validated replan: {_operation}",
        "plan": _planner_schema_plan(proposal_plan),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", replan["request_id"], second_planner_response)

    semantic_attempt_2 = continue_run(project, "C001", run_id=run_id)
    assert semantic_attempt_2["kind"] == "needs_host"
    second_extract = semantic_attempt_2["request"]["inputs"]["extract"]
    assert second_extract["evidence_id"] == first_evidence_id
    assert semantic_attempt_2["request"]["inputs"]["extract_sha256"] != first_extract_sha
    assert second_extract["retrieval"]["snapshot_path"] != first_path
    assert semantic_attempt_2["request_id"] != semantic_attempt_1["request_id"]
    second_semantic_response = project / "cross-attempt-semantic-2.json"
    second_semantic_response.write_bytes(json.dumps({
        "entailment": "SUPPORTED", "scope_match": True,
        "context_preserved": True, "qualification_preserved": True,
        "reason": "the second attempt independently supports the claim",
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    submit(project, "C001", semantic_attempt_2["request_id"], second_semantic_response)
    completed = continue_run(project, "C001", run_id=run_id)
    assert completed["kind"] in {"FROZEN", "INSUFFICIENT_STOP"}
    canonical = {key: value for key, value in completed.items() if key != "kind"}
    assert europepmc_runtime.validate_europepmc_acquisition_result(
        project, "C001", canonical,
    ) == canonical
    manifest = json.loads((project / completed["acquisition_manifest_path"]).read_text(
        encoding="utf-8"
    ))
    assert [attempt["attempt_index"] for attempt in manifest["attempts"]] == [1, 2]
    assert manifest["attempts"][0]["semantic_verifications"][0]["verdict"] == "FAIL"
    assert manifest["attempts"][1]["semantic_verifications"][0]["verdict"] == "PASS"
    assert manifest["attempts"][0]["located_evidence"][0]["evidence_id"] == first_evidence_id
    assert manifest["attempts"][1]["located_evidence"][0]["evidence_id"] == first_evidence_id
    assert len(http_calls) == 4
