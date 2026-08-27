import json

import pytest

from research_loop import research_seed
import research_loop.l05_curie as curie


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


def _freeze(tmp_path, *, version=1, run_id=None, parent=None, gap_id=None):
    seed = _seed()
    seed_hash = research_seed.seed_sha256(seed)
    run_id = run_id or f"CURIE{version:03d}"
    plan = {
        "schema_version": curie.QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": "C001",
        "round_id": "1",
        "seed_sha256": seed_hash,
        "plan_id": f"QP{version}",
        "round_index": version,
        "queries": [{"query_id": f"Q{version}", "intent": "gap",
                     "query": "bat cardiac physiology", "providers": ["europe-pmc"]}],
    }
    batch = {
        "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
        "provider": "europe-pmc",
        "query_id": f"Q{version}",
        "receipt": {"request_sha256": "1" * 64, "response_sha256": "2" * 64},
        "records": [{"paper_id": f"P{version}", "title": "Evidence",
                     "identifiers": {"pmid": str(version)},
                     "provenance": {"provider": "europe-pmc",
                                    "raw_record_sha256": str(version) * 64}}],
    }
    evidence = [{
        "schema_version": curie.EVIDENCE_EXTRACT_SCHEMA_VERSION,
        "evidence_id": f"E{version}", "paper_id": f"P{version}",
        "section": "Results", "text": "Located evidence.", "locator": "p1",
        "role": "CONTEXT", "verification_status": "LOCATED",
        "retrieval": {"engine": "fixture", "source_sha256": "3" * 64},
    }]
    coverage = curie.judge_coverage(
        {"covered": ["verified_full_text_source"], "gaps": []},
        round_index=version, max_rounds=3,
    )
    pack = curie.build_evidence_pack(
        candidate_id="C001", round_id="1", seed_sha256=seed_hash,
        version=version, query_plans=[plan], discovery_receipts=[batch],
        selected_papers=[{"paper_id": f"P{version}", "title": "Evidence",
                          "identifiers": {"pmid": str(version)},
                          "selection": {"decision": "INCLUDE", "reason": "direct"}}],
        evidence=evidence, coverage=coverage, gaps=[], source_run_id=run_id,
        parent_pack_sha256=parent, source_gap_request_id=gap_id,
    )
    return curie.freeze_evidence_pack(tmp_path, pack)


def _authorized_retry(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path)
    request = curie.open_gap_request(
        tmp_path, seed, first,
        gaps=[{"gap_id": "G1", "topic": "gap", "reason": "missing",
               "search_directions": ["search more"]}],
    )
    auth = curie.authorize_gap_retry(
        tmp_path, seed, first, request["request_id"]
    )
    return seed, first, request, auth


def test_open_gap_request_is_append_only_and_bound_to_exact_pack(tmp_path):
    seed = _seed()
    manifest = _freeze(tmp_path)
    request = curie.open_gap_request(
        tmp_path, seed, manifest,
        gaps=[{"gap_id": "G1", "topic": "calcium handling",
               "reason": "No direct mechanism evidence.",
               "search_directions": ["search calcium handling in bats"]}],
    )
    assert request["status"] == "OPEN"
    assert request["pack_sha256"] == manifest["content_sha256"]
    loaded = curie.load_open_gap_request(
        tmp_path, seed, manifest, request["request_id"]
    )
    assert loaded == request

    path = tmp_path / "08_Audit" / "l05_gap_requests" / "C001" / "1" / f"{request['request_id']}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == request


def test_gap_request_rejects_forged_parent_pack(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path)
    request = curie.open_gap_request(
        tmp_path, seed, first,
        gaps=[{"gap_id": "G1", "topic": "gap", "reason": "missing",
               "search_directions": ["search more"]}],
    )
    other = _freeze(tmp_path, version=2, run_id="OTHER",
                    parent=first["content_sha256"], gap_id=request["request_id"])
    with pytest.raises(curie.CurieContractError, match="parent|pack"):
        curie.load_open_gap_request(
            tmp_path, seed, other, request["request_id"]
        )


def test_authorize_retry_returns_exact_v2_lineage_and_cannot_be_reused(tmp_path):
    seed, first, request, auth = _authorized_retry(tmp_path)
    assert auth["next_version"] == 2
    assert auth["parent_pack_sha256"] == first["content_sha256"]
    assert auth["source_gap_request_id"] == request["request_id"]

    curie.consume_gap_retry_authorization(tmp_path, seed, auth, "CURIE002")
    with pytest.raises(curie.CurieContractError, match="consumed"):
        curie.authorize_gap_retry(tmp_path, seed, first, request["request_id"])


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("authorization_id", "EGRA_FORGED"),
        ("source_gap_request_id", "EGR_FORGED"),
        ("next_version", 3),
        ("parent_pack_version", 2),
        ("parent_pack_sha256", "f" * 64),
    ],
)
def test_consume_gap_retry_rejects_tampered_authorization_identity(
    tmp_path, field, replacement
):
    project = tmp_path / field
    seed, _first, _request, auth = _authorized_retry(project)
    forged = dict(auth)
    forged[field] = replacement
    with pytest.raises(curie.CurieContractError, match="authorization|lineage|version|parent|request"):
        curie.consume_gap_retry_authorization(project, seed, forged, "CURIE002")


def test_no_fourth_acquisition_round_is_authorized(tmp_path):
    seed = _seed()
    first = _freeze(tmp_path)
    r1 = curie.open_gap_request(
        tmp_path, seed, first,
        gaps=[{"gap_id": "G1", "topic": "gap", "reason": "missing",
               "search_directions": ["search"]}],
    )
    second = _freeze(tmp_path, version=2, run_id="CURIE002",
                     parent=first["content_sha256"], gap_id=r1["request_id"])
    r2 = curie.open_gap_request(
        tmp_path, seed, second,
        gaps=[{"gap_id": "G2", "topic": "gap2", "reason": "missing",
               "search_directions": ["search again"]}],
    )
    third = _freeze(tmp_path, version=3, run_id="CURIE003",
                    parent=second["content_sha256"], gap_id=r2["request_id"])
    r3 = curie.open_gap_request(
        tmp_path, seed, third,
        gaps=[{"gap_id": "G3", "topic": "gap3", "reason": "still missing",
               "search_directions": ["would require fourth round"]}],
    )
    with pytest.raises(curie.CurieContractError, match="maximum|three|round"):
        curie.authorize_gap_retry(tmp_path, seed, third, r3["request_id"])
