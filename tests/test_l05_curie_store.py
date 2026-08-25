import hashlib
import json
from pathlib import Path

import pytest

import research_loop.l05_curie as curie
from research_loop.l05_curie import store as store_module


def _query_plan():
    return {
        "schema_version": curie.QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": "C001",
        "round_id": "R1",
        "seed_sha256": "a" * 64,
        "plan_id": "QP001",
        "round_index": 1,
        "queries": [
            {
                "query_id": "Q001",
                "intent": "mechanism",
                "query": "bat cardiac calcium handling",
                "providers": ["pubmed"],
            }
        ],
    }


def _discovery_batch():
    return {
        "schema_version": curie.DISCOVERY_BATCH_SCHEMA_VERSION,
        "provider": "pubmed",
        "query_id": "Q001",
        "receipt": {
            "request_sha256": "1" * 64,
            "response_sha256": "2" * 64,
        },
        "records": [
            {
                "paper_id": "PMID:123",
                "title": "Cardiac physiology in bats",
                "identifiers": {"pmid": "123"},
            }
        ],
    }


def _selected_papers():
    return [
        {
            "paper_id": "PMID:123",
            "title": "Cardiac physiology in bats",
            "identifiers": {"pmid": "123"},
            "selection": {
                "decision": "INCLUDE",
                "reason": "direct mechanistic evidence",
            },
        }
    ]


def _evidence():
    return [
        {
            "schema_version": curie.EVIDENCE_EXTRACT_SCHEMA_VERSION,
            "evidence_id": "E001",
            "paper_id": "PMID:123",
            "section": "Results",
            "text": "Calcium handling differed from the comparison group.",
            "locator": "Results, paragraph 2",
            "role": "SUPPORTING",
            "verification_status": "LOCATED",
            "retrieval": {
                "engine": "paperqa2",
                "source_sha256": "3" * 64,
            },
        }
    ]


def _pass_coverage():
    return curie.judge_coverage(
        {"covered": ["calcium_handling"], "gaps": []},
        round_index=1,
        max_rounds=3,
    )


def _build_pack(**overrides):
    kwargs = {
        "candidate_id": "C001",
        "round_id": "R1",
        "seed_sha256": "a" * 64,
        "version": 1,
        "query_plans": [_query_plan()],
        "discovery_receipts": [_discovery_batch()],
        "selected_papers": _selected_papers(),
        "evidence": _evidence(),
        "coverage": _pass_coverage(),
        "gaps": [],
    }
    kwargs.update(overrides)
    return curie.build_evidence_pack(**kwargs)


def _query_plan_for_round(round_index: int) -> dict:
    plan = _query_plan()
    plan["round_index"] = round_index
    plan["plan_id"] = f"QP{round_index:03d}"
    return plan


def _artifact_path(project_dir: Path, manifest: dict) -> Path:
    return project_dir / manifest["artifact_path"]


def _build_retry_pack(version: int):
    coverage = curie.judge_coverage(
        {"covered": ["calcium_handling"], "gaps": []},
        round_index=version,
        max_rounds=3,
    )
    return _build_pack(
        version=version,
        parent_pack_sha256="f" * 64,
        source_gap_request_id=f"EGR_V{version}",
        query_plans=[_query_plan_for_round(version)],
        coverage=coverage,
        gaps=[],
    )


def test_build_is_deterministic_and_freeze_loads_exact_pack(tmp_path):
    first = _build_pack()
    second = _build_pack()

    assert first["status"] == "READY_TO_FREEZE"
    assert first["content_sha256"] == second["content_sha256"]

    manifest = curie.freeze_evidence_pack(tmp_path, first)
    assert manifest["schema_version"] == curie.EVIDENCE_PACK_MANIFEST_SCHEMA_VERSION
    assert manifest["status"] == "FROZEN"
    assert manifest["artifact_path"].startswith(
        "09_Literature_Database/evidence_packs/l05/C001/"
    )

    loaded = curie.load_frozen_evidence_pack(
        tmp_path,
        manifest,
        candidate_id="C001",
        round_id="R1",
        seed_sha256="a" * 64,
    )
    assert loaded["status"] == "FROZEN"
    assert loaded["content_sha256"] == manifest["content_sha256"]
    assert loaded["evidence"][0]["evidence_id"] == "E001"


def test_freeze_requires_coverage_pass(tmp_path):
    insufficient = curie.judge_coverage(
        {
            "covered": [],
            "gaps": [
                {
                    "gap_id": "G001",
                    "topic": "autonomic_regulation",
                    "reason": "not covered",
                    "search_directions": ["bat vagal cardiac control"],
                }
            ],
        },
        round_index=1,
        max_rounds=3,
    )
    pack = _build_pack(coverage=insufficient, gaps=insufficient["gaps"])

    with pytest.raises(curie.CurieContractError, match="coverage.*PASS"):
        curie.freeze_evidence_pack(tmp_path, pack)


@pytest.mark.parametrize(
    ("version", "source_gap_request_id", "message"),
    [
        (1, "EGR_UNEXPECTED", "version 1.*source_gap_request_id"),
        (2, None, "source_gap_request_id"),
    ],
)
def test_build_enforces_gap_request_direction_for_each_pack_version(
    version, source_gap_request_id, message
):
    kwargs = {
        "version": version,
        "query_plans": [_query_plan_for_round(version)],
        "source_gap_request_id": source_gap_request_id,
    }
    if version > 1:
        kwargs["parent_pack_sha256"] = "f" * 64

    with pytest.raises(curie.CurieContractError, match=message):
        _build_pack(**kwargs)


def test_build_rejects_pack_versions_beyond_bounded_acquisition_rounds():
    with pytest.raises(curie.CurieContractError, match="1 to 3"):
        _build_pack(
            version=4,
            parent_pack_sha256="f" * 64,
            source_gap_request_id="EGR_V4",
            query_plans=[_query_plan_for_round(3)],
        )


def test_load_and_render_allow_a_byte_verified_legacy_frozen_retry_pack(tmp_path):
    manifest = curie.freeze_evidence_pack(tmp_path, _build_retry_pack(3))
    path = _artifact_path(tmp_path, manifest)
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("source_gap_request_id")
    legacy["query_plans"][0]["round_index"] = 2
    legacy["coverage"] = curie.judge_coverage(
        {"covered": ["calcium_handling"], "gaps": []},
        round_index=1,
        max_rounds=3,
    )
    legacy["gaps"] = legacy["coverage"]["gaps"]
    legacy["content_sha256"] = store_module._content_sha256(legacy)
    raw = store_module._canonical_bytes(legacy)
    path.write_bytes(raw)
    legacy_manifest = {
        **manifest,
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "content_sha256": legacy["content_sha256"],
    }

    loaded = curie.load_frozen_evidence_pack(
        tmp_path,
        legacy_manifest,
        candidate_id="C001",
        round_id="R1",
        seed_sha256="a" * 64,
    )

    assert loaded["version"] == 3
    assert "source_gap_request_id" not in loaded
    with pytest.raises(curie.CurieContractError, match="source_gap_request_id"):
        curie.render_evidence_context(loaded)
    assert "L0.5 CURIE FROZEN EVIDENCEPACK" in curie.render_evidence_context(
        loaded,
        allow_legacy_frozen_acquisition_metadata=True,
    )


def test_freeze_keeps_retry_lineage_required_for_new_v2_packs(tmp_path):
    malformed_ready = _build_retry_pack(2)
    malformed_ready.pop("source_gap_request_id")
    malformed_ready["content_sha256"] = store_module._content_sha256(malformed_ready)

    with pytest.raises(curie.CurieContractError, match="source_gap_request_id"):
        curie.freeze_evidence_pack(tmp_path, malformed_ready)


@pytest.mark.parametrize(("field", "value"), [("query_plans", [_query_plan_for_round(1)]), ("coverage", _pass_coverage())])
def test_build_requires_query_and_coverage_round_to_match_pack_version(field, value):
    with pytest.raises(curie.CurieContractError, match="round_index.*EvidencePack version"):
        _build_pack(
            version=2,
            parent_pack_sha256="f" * 64,
            source_gap_request_id="EGR_V2",
            **{field: value},
        )


def test_freeze_is_append_only_and_refuses_overwrite(tmp_path):
    pack = _build_pack()
    curie.freeze_evidence_pack(tmp_path, pack)

    with pytest.raises(curie.CurieContractError, match="already exists"):
        curie.freeze_evidence_pack(tmp_path, pack)


def test_load_detects_artifact_tampering(tmp_path):
    manifest = curie.freeze_evidence_pack(tmp_path, _build_pack())
    path = _artifact_path(tmp_path, manifest)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(curie.CurieContractError, match="artifact_sha256"):
        curie.load_frozen_evidence_pack(
            tmp_path,
            manifest,
            candidate_id="C001",
            round_id="R1",
            seed_sha256="a" * 64,
        )


def test_load_recomputes_internal_content_hash(tmp_path):
    manifest = curie.freeze_evidence_pack(tmp_path, _build_pack())
    path = _artifact_path(tmp_path, manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["selected_papers"][0]["title"] = "Tampered title"
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    forged_manifest = dict(manifest)
    forged_manifest["artifact_sha256"] = hashlib.sha256(raw).hexdigest()

    with pytest.raises(curie.CurieContractError, match="content_sha256"):
        curie.load_frozen_evidence_pack(
            tmp_path,
            forged_manifest,
            candidate_id="C001",
            round_id="R1",
            seed_sha256="a" * 64,
        )


def test_load_fails_closed_on_identity_mismatch(tmp_path):
    manifest = curie.freeze_evidence_pack(tmp_path, _build_pack())

    with pytest.raises(curie.CurieContractError, match="seed_sha256"):
        curie.load_frozen_evidence_pack(
            tmp_path,
            manifest,
            candidate_id="C001",
            round_id="R1",
            seed_sha256="b" * 64,
        )


def test_load_rejects_manifest_path_outside_l05_root(tmp_path):
    manifest = curie.freeze_evidence_pack(tmp_path, _build_pack())
    malicious = dict(manifest)
    malicious["artifact_path"] = "../../outside.json"

    with pytest.raises(curie.CurieContractError, match="artifact_path"):
        curie.load_frozen_evidence_pack(
            tmp_path,
            malicious,
            candidate_id="C001",
            round_id="R1",
            seed_sha256="a" * 64,
        )


def test_gap_request_creates_new_version_with_parent_hash(tmp_path):
    manifest_v1 = curie.freeze_evidence_pack(tmp_path, _build_pack())
    frozen_v1 = curie.load_frozen_evidence_pack(
        tmp_path,
        manifest_v1,
        candidate_id="C001",
        round_id="R1",
        seed_sha256="a" * 64,
    )
    gap_request = curie.build_gap_request(
        candidate_id="C001",
        round_id="R1",
        seed_sha256="a" * 64,
        pack_sha256=frozen_v1["content_sha256"],
        gaps=[
            {
                "gap_id": "G002",
                "topic": "autonomic_regulation",
                "reason": "Einstein identified an unresolved mechanism",
                "search_directions": ["bat autonomic cardiac regulation"],
            }
        ],
    )

    v2 = curie.next_pack_version(
        frozen_v1,
        gap_request=gap_request,
        query_plans=[dict(_query_plan(), plan_id="QP002", round_index=2)],
        discovery_receipts=[_discovery_batch()],
        selected_papers=_selected_papers(),
        evidence=_evidence(),
        coverage=curie.judge_coverage(
            {"covered": ["calcium_handling"], "gaps": []},
            round_index=2,
            max_rounds=3,
        ),
        gaps=[],
    )

    assert v2["version"] == 2
    assert v2["parent_pack_sha256"] == frozen_v1["content_sha256"]
    assert v2["status"] == "READY_TO_FREEZE"
    assert frozen_v1["version"] == 1
