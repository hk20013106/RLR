import pytest

from research_loop import research_seed
import research_loop.l05_curie as curie
from research_loop.l05_curie.native_runtime import (
    bind_initial_curie_pack,
    run_authorized_retry,
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


def _freeze(tmp_path, *, version, run_id, parent=None, gap_id=None):
    seed = _seed()
    sh = research_seed.seed_sha256(seed)
    plan = {
        "schema_version": curie.QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": "C001", "round_id": "1", "seed_sha256": sh,
        "plan_id": f"QP{version}", "round_index": version,
        "queries": [{"query_id": f"Q{version}", "intent": "mechanism",
                     "query": "cardiac physiology", "providers": ["europe-pmc"]}],
    }
    batch = {
        "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
        "provider": "europe-pmc", "query_id": f"Q{version}",
        "receipt": {"request_sha256": "1" * 64, "response_sha256": "2" * 64},
        "records": [{"paper_id": f"P{version}", "title": "Evidence",
                     "identifiers": {"pmid": str(version)},
                     "provenance": {"provider": "europe-pmc",
                                    "raw_record_sha256": str(version) * 64}}],
    }
    evidence = [{
        "schema_version": curie.EVIDENCE_EXTRACT_SCHEMA_VERSION,
        "evidence_id": f"E{version}", "paper_id": f"P{version}",
        "section": "Results", "text": f"Evidence round {version}.",
        "locator": "p1", "role": "CONTEXT", "verification_status": "LOCATED",
        "retrieval": {"engine": "fixture", "source_sha256": "3" * 64},
    }]
    coverage = curie.judge_coverage(
        {"covered": ["verified_full_text_source"], "gaps": []},
        round_index=version, max_rounds=3,
    )
    pack = curie.build_evidence_pack(
        candidate_id="C001", round_id="1", seed_sha256=sh, version=version,
        query_plans=[plan], discovery_receipts=[batch],
        selected_papers=[{"paper_id": f"P{version}", "title": "Evidence",
                          "identifiers": {"pmid": str(version)},
                          "selection": {"decision": "INCLUDE", "reason": "direct"}}],
        evidence=evidence, coverage=coverage, gaps=[], source_run_id=run_id,
        parent_pack_sha256=parent, source_gap_request_id=gap_id,
    )
    return curie.freeze_evidence_pack(tmp_path, pack)


def _gap(tmp_path, seed, manifest, gap_id):
    return curie.open_gap_request(
        tmp_path, seed, manifest,
        gaps=[{"gap_id": gap_id, "topic": "mechanism", "reason": "missing",
               "search_directions": ["search more direct evidence"]}],
    )


def _initialized_retry_fixture(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path, version=1, run_id="CURIE001")
    bind_initial_curie_pack(tmp_path, seed, first, "CURIE001")
    request = _gap(tmp_path, seed, first, "G1")
    authorization = curie.authorize_gap_retry(
        tmp_path, seed, first, request["request_id"]
    )
    return seed, first, request, authorization


def _retry_acquire(tmp_path):
    def acquire(auth):
        return _freeze(
            tmp_path,
            version=auth["next_version"],
            run_id="CURIE002",
            parent=auth["parent_pack_sha256"],
            gap_id=auth["source_gap_request_id"],
        )

    return acquire


def _transaction_root(tmp_path):
    return (
        tmp_path / "08_Audit" / "research_seed_bindings" / "native"
        / "C001" / "1" / "retry_transactions"
    )


def test_bind_initial_pack_establishes_native_active_v1(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path, version=1, run_id="CURIE001")
    result = bind_initial_curie_pack(tmp_path, seed, first, "CURIE001")
    assert result["evidence_pack_version"] == 1
    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE001"


def test_authorized_retry_advances_v1_to_v2_without_mutating_v1(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path, version=1, run_id="CURIE001")
    bind_initial_curie_pack(tmp_path, seed, first, "CURIE001")
    request = _gap(tmp_path, seed, first, "G1")
    first_bytes = (tmp_path / first["artifact_path"]).read_bytes()

    def acquire(auth):
        return _freeze(
            tmp_path, version=auth["next_version"], run_id="CURIE002",
            parent=auth["parent_pack_sha256"], gap_id=auth["source_gap_request_id"],
        )

    result = run_authorized_retry(
        tmp_path, seed, first, request["request_id"], "CURIE002", acquire
    )
    assert result["binding"]["evidence_pack_version"] == 2
    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE002"
    assert (tmp_path / first["artifact_path"]).read_bytes() == first_bytes


def test_retry_rejects_pack_with_wrong_parent_or_gap_lineage(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path, version=1, run_id="CURIE001")
    bind_initial_curie_pack(tmp_path, seed, first, "CURIE001")
    request = _gap(tmp_path, seed, first, "G1")

    def bad_acquire(auth):
        return _freeze(
            tmp_path, version=2, run_id="CURIE002",
            parent="f" * 64, gap_id=auth["source_gap_request_id"],
        )

    with pytest.raises(curie.CurieContractError, match="parent_pack_sha256"):
        run_authorized_retry(
            tmp_path, seed, first, request["request_id"], "CURIE002", bad_acquire
        )
    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE001"


def test_v3_is_last_authorized_native_pack(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path, version=1, run_id="CURIE001")
    bind_initial_curie_pack(tmp_path, seed, first, "CURIE001")
    r1 = _gap(tmp_path, seed, first, "G1")
    second = run_authorized_retry(
        tmp_path, seed, first, r1["request_id"], "CURIE002",
        lambda auth: _freeze(tmp_path, version=2, run_id="CURIE002",
                             parent=auth["parent_pack_sha256"],
                             gap_id=auth["source_gap_request_id"]),
    )["evidence_pack"]
    r2 = _gap(tmp_path, seed, second, "G2")
    third = run_authorized_retry(
        tmp_path, seed, second, r2["request_id"], "CURIE003",
        lambda auth: _freeze(tmp_path, version=3, run_id="CURIE003",
                             parent=auth["parent_pack_sha256"],
                             gap_id=auth["source_gap_request_id"]),
    )["evidence_pack"]
    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE003"
    r3 = _gap(tmp_path, seed, third, "G3")
    with pytest.raises(curie.CurieContractError, match="maximum|three|round"):
        run_authorized_retry(
            tmp_path, seed, third, r3["request_id"], "CURIE004",
            lambda _auth: None,
        )


@pytest.mark.parametrize(
    "failure_step",
    ["before_stage", "after_binding", "after_consumption", "during_activation"],
)
def test_interrupted_retry_has_no_committed_intermediate_state(tmp_path, failure_step):
    seed, first, request, authorization = _initialized_retry_fixture(tmp_path)
    first_bytes = (tmp_path / first["artifact_path"]).read_bytes()

    with pytest.raises(curie.CurieContractError, match="injected"):
        run_authorized_retry(
            tmp_path,
            seed,
            first,
            request["request_id"],
            "CURIE002",
            _retry_acquire(tmp_path),
            failure_step=failure_step,
        )

    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE001"
    assert not list(_transaction_root(tmp_path).glob("*/commit.json"))
    with pytest.raises(curie.CurieContractError, match="missing|invalid"):
        curie.load_gap_retry_consumption(
            tmp_path, seed, authorization, "CURIE002"
        )
    assert (tmp_path / first["artifact_path"]).read_bytes() == first_bytes


def test_interrupted_retry_replays_to_one_committed_transaction(tmp_path):
    seed, first, request, _authorization = _initialized_retry_fixture(tmp_path)
    with pytest.raises(curie.CurieContractError, match="injected"):
        run_authorized_retry(
            tmp_path,
            seed,
            first,
            request["request_id"],
            "CURIE002",
            _retry_acquire(tmp_path),
            failure_step="after_consumption",
        )

    result = run_authorized_retry(
        tmp_path,
        seed,
        first,
        request["request_id"],
        "CURIE002",
        _retry_acquire(tmp_path),
    )
    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE002"
    assert len(list(_transaction_root(tmp_path).glob("*/commit.json"))) == 1
    assert result["activation"]["evidence_pack_version"] == 2


def test_committed_retry_replay_is_idempotent_and_rejects_different_run(tmp_path):
    seed, first, request, _authorization = _initialized_retry_fixture(tmp_path)
    acquire = _retry_acquire(tmp_path)
    first_result = run_authorized_retry(
        tmp_path, seed, first, request["request_id"], "CURIE002", acquire
    )
    replay = run_authorized_retry(
        tmp_path, seed, first, request["request_id"], "CURIE002", acquire
    )
    assert replay == first_result
    assert len(list(_transaction_root(tmp_path).glob("*/commit.json"))) == 1
    with pytest.raises(curie.CurieContractError, match="run|provenance|replay"):
        run_authorized_retry(
            tmp_path,
            seed,
            first,
            request["request_id"],
            "CURIE_OTHER",
            acquire,
        )
