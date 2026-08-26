"""Immutable EvidencePack construction and freeze boundary for L0.5 Curie."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from .contracts import (
    EVIDENCE_PACK_MANIFEST_SCHEMA_VERSION,
    EVIDENCE_PACK_SCHEMA_VERSION,
    MAX_ACQUISITION_ROUNDS,
    CurieContractError,
    _require_sha256,
    _require_text,
    validate_coverage_decision,
    validate_discovery_batch,
    validate_evidence_extract,
    validate_gap_request,
    validate_query_plan,
)

_L05_ROOT = Path("09_Literature_Database") / "evidence_packs" / "l05"
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _content_sha256(pack: dict) -> str:
    payload = {key: value for key, value in pack.items() if key != "content_sha256"}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _safe_token(value: str, name: str) -> str:
    value = _require_text(value, name)
    token = _SAFE_TOKEN.sub("_", value).strip("_.")
    if not token:
        raise CurieContractError(f"{name} cannot be normalized to an artifact token")
    return token


def _pack_filename(candidate_id: str, round_id: str, version: int) -> str:
    candidate = _safe_token(candidate_id, "candidate_id")
    round_token = _safe_token(round_id, "round_id")
    if not round_token.upper().startswith("R"):
        round_token = f"R{round_token}"
    return f"EP_{candidate}_{round_token}_v{version}.json"


def _validate_selected_papers(selected_papers: object) -> list[dict]:
    if not isinstance(selected_papers, list) or not selected_papers:
        raise CurieContractError("selected_papers must be a non-empty list")
    validated: list[dict] = []
    seen: set[str] = set()
    for paper in selected_papers:
        if not isinstance(paper, dict):
            raise CurieContractError("selected paper records must be objects")
        paper_id = _require_text(paper.get("paper_id"), "selected paper paper_id")
        if paper_id in seen:
            raise CurieContractError(f"duplicate selected paper_id: {paper_id}")
        seen.add(paper_id)
        _require_text(paper.get("title"), "selected paper title")
        if not isinstance(paper.get("identifiers"), dict):
            raise CurieContractError("selected paper identifiers must be an object")
        selection = paper.get("selection")
        if not isinstance(selection, dict):
            raise CurieContractError("selected paper selection must be an object")
        if selection.get("decision") != "INCLUDE":
            raise CurieContractError("selected paper decision must be INCLUDE")
        _require_text(selection.get("reason"), "selected paper selection reason")
        validated.append(copy.deepcopy(paper))
    return validated


def _validate_semantic_pack(pack: dict) -> dict:
    """Validate optional semantic admission at the EvidencePack owner boundary."""
    if not isinstance(pack, dict) or "semantic_verifications" not in pack:
        return pack
    values = pack.get("semantic_verifications")
    if not isinstance(values, list) or not values:
        raise CurieContractError(
            "EvidencePack semantic_verifications must be a non-empty list when present"
        )
    from .semantic_verifier import (
        evidence_extract_sha256,
        reasoning_authorized,
        validate_semantic_verification,
    )

    evidence = pack.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise CurieContractError("semantic EvidencePack requires non-empty evidence")
    if any(not isinstance(item, dict) for item in evidence):
        raise CurieContractError("semantic EvidencePack evidence must contain objects")
    evidence_by_id = {str(item.get("evidence_id") or ""): item for item in evidence}
    if "" in evidence_by_id or len(evidence_by_id) != len(evidence):
        raise CurieContractError(
            "semantic EvidencePack evidence identities are invalid or duplicated"
        )
    semantic_by_id = {}
    for value in values:
        result = validate_semantic_verification(value)
        evidence_id = result["evidence_id"]
        if evidence_id in semantic_by_id:
            raise CurieContractError(
                f"duplicate semantic verification for evidence {evidence_id}"
            )
        semantic_by_id[evidence_id] = result
    if set(semantic_by_id) != set(evidence_by_id):
        raise CurieContractError(
            "semantic verification evidence IDs must match EvidencePack evidence exactly"
        )
    for evidence_id, result in semantic_by_id.items():
        extract = evidence_by_id[evidence_id]
        if str(result["paper_id"]) != str(extract.get("paper_id") or ""):
            raise CurieContractError(
                f"semantic verification paper identity mismatch for evidence {evidence_id}"
            )
        if str(result["extract_sha256"]) != evidence_extract_sha256(extract):
            raise CurieContractError(
                f"semantic verification exact extract SHA mismatch for evidence {evidence_id}; evidence changed"
            )
        if not reasoning_authorized(result):
            raise CurieContractError(
                f"semantic verification for evidence {evidence_id} is not reasoning-authorized"
            )
    return pack


def _validate_pack_structure(
    pack: dict,
    *,
    expected_status: str | None = None,
    allow_legacy_frozen_acquisition_metadata: bool = False,
    allow_legacy_frozen_source_identity: bool = False,
) -> dict:
    if not isinstance(pack, dict):
        raise CurieContractError("EvidencePack must be an object")
    if pack.get("schema_version") != EVIDENCE_PACK_SCHEMA_VERSION:
        raise CurieContractError("EvidencePack schema_version is invalid")
    candidate_id = _require_text(pack.get("candidate_id"), "EvidencePack candidate_id")
    round_id = _require_text(pack.get("round_id"), "EvidencePack round_id")
    seed_sha256 = _require_sha256(pack.get("seed_sha256"), "EvidencePack seed_sha256")
    _require_text(pack.get("pack_id"), "EvidencePack pack_id")
    source_run_id = pack.get("source_run_id")
    if source_run_id is not None:
        _require_text(source_run_id, "EvidencePack source_run_id")
    version = pack.get("version")
    if (not isinstance(version, int) or isinstance(version, bool)
            or not 1 <= version <= MAX_ACQUISITION_ROUNDS):
        raise CurieContractError(
            f"EvidencePack version must be an integer from 1 to {MAX_ACQUISITION_ROUNDS}"
        )
    status = pack.get("status")
    if status not in {"READY_TO_FREEZE", "FROZEN"}:
        raise CurieContractError("EvidencePack status must be READY_TO_FREEZE or FROZEN")
    if expected_status is not None and status != expected_status:
        raise CurieContractError(f"EvidencePack status must be {expected_status}")
    # Historical FROZEN artifacts predate strict retry/round metadata.  This
    # compatibility mode is never used by build, freeze, or retry creation.
    legacy_frozen_acquisition_metadata = (
        allow_legacy_frozen_acquisition_metadata
        and expected_status == "FROZEN"
        and status == "FROZEN"
    )
    legacy_frozen_source_identity = (
        allow_legacy_frozen_source_identity
        and expected_status == "FROZEN"
        and status == "FROZEN"
    )
    # The only relaxed path is an explicit historical frozen-artifact load.
    # New packs and all normal in-memory validation must carry source identity.
    require_source_identity = not legacy_frozen_source_identity

    parent_hash = pack.get("parent_pack_sha256")
    source_gap_request_id = pack.get("source_gap_request_id")
    if version == 1:
        if parent_hash not in (None, ""):
            raise CurieContractError("EvidencePack v1 must not have parent_pack_sha256")
        if source_gap_request_id not in (None, ""):
            raise CurieContractError("EvidencePack v1 must not have source_gap_request_id")
    else:
        _require_sha256(parent_hash, "EvidencePack parent_pack_sha256")
        if not (
            legacy_frozen_acquisition_metadata
            and source_gap_request_id in (None, "")
        ):
            _require_text(source_gap_request_id, "EvidencePack source_gap_request_id")

    query_plans = pack.get("query_plans")
    if not isinstance(query_plans, list) or not query_plans:
        raise CurieContractError("EvidencePack query_plans must be a non-empty list")
    query_ids: set[str] = set()
    query_providers: dict[str, set[str]] = {}
    plan_ids: set[str] = set()
    for plan in query_plans:
        plan = validate_query_plan(plan, seed_sha256=seed_sha256)
        if plan["candidate_id"] != candidate_id or plan["round_id"] != round_id:
            raise CurieContractError("QueryPlan identity does not match EvidencePack")
        if plan["round_index"] != version and not legacy_frozen_acquisition_metadata:
            raise CurieContractError("QueryPlan round_index must match EvidencePack version")
        if plan["plan_id"] in plan_ids:
            raise CurieContractError(f"duplicate QueryPlan plan_id: {plan['plan_id']}")
        plan_ids.add(plan["plan_id"])
        for query in plan["queries"]:
            if query["query_id"] in query_ids:
                raise CurieContractError(f"duplicate EvidencePack query_id: {query['query_id']}")
            query_ids.add(query["query_id"])
            query_providers[query["query_id"]] = set(query["providers"])

    discovery_receipts = pack.get("discovery_receipts")
    if not isinstance(discovery_receipts, list):
        raise CurieContractError("EvidencePack discovery_receipts must be a list")
    for batch in discovery_receipts:
        validate_discovery_batch(
            batch,
            query_ids=query_ids,
            expected_providers=query_providers.get(str(batch.get("query_id")), set()),
            require_source_identity=require_source_identity,
        )

    selected_papers = _validate_selected_papers(pack.get("selected_papers"))
    selected_ids = {paper["paper_id"] for paper in selected_papers}

    evidence = pack.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise CurieContractError("EvidencePack evidence must be a non-empty list")
    evidence_ids: set[str] = set()
    for extract in evidence:
        extract = validate_evidence_extract(extract)
        if extract["paper_id"] not in selected_ids:
            raise CurieContractError(
                f"evidence {extract['evidence_id']} refers to an unselected paper"
            )
        if extract["evidence_id"] in evidence_ids:
            raise CurieContractError(f"duplicate evidence_id: {extract['evidence_id']}")
        evidence_ids.add(extract["evidence_id"])

    coverage = validate_coverage_decision(pack.get("coverage"))
    if coverage["round_index"] != version and not legacy_frozen_acquisition_metadata:
        raise CurieContractError("coverage decision round_index must match EvidencePack version")
    gaps = pack.get("gaps")
    if not isinstance(gaps, list):
        raise CurieContractError("EvidencePack gaps must be a list")
    if gaps != coverage["gaps"]:
        raise CurieContractError("EvidencePack gaps must match coverage gaps exactly")

    content_sha = _require_sha256(pack.get("content_sha256"), "EvidencePack content_sha256")
    if content_sha != _content_sha256(pack):
        raise CurieContractError("EvidencePack content_sha256 does not match its content")
    return copy.deepcopy(pack)


def build_evidence_pack(*, candidate_id: str, round_id: str, seed_sha256: str,
                        version: int, query_plans: list[dict],
                        discovery_receipts: list[dict], selected_papers: list[dict],
                        evidence: list[dict], coverage: dict, gaps: list[dict],
                        parent_pack_sha256: str | None = None,
                        source_gap_request_id: str | None = None,
                        source_run_id: str | None = None,
                        semantic_verifications: list[dict] | None = None) -> dict:
    """Build a deterministic, validated pack that is not yet authorized for L1."""
    candidate_id = _require_text(candidate_id, "candidate_id")
    round_id = _require_text(round_id, "round_id")
    seed_sha256 = _require_sha256(seed_sha256, "seed_sha256")
    if (not isinstance(version, int) or isinstance(version, bool)
            or not 1 <= version <= MAX_ACQUISITION_ROUNDS):
        raise CurieContractError(
            f"version must be an integer from 1 to {MAX_ACQUISITION_ROUNDS}"
        )
    if version == 1:
        if parent_pack_sha256 not in (None, ""):
            raise CurieContractError("version 1 cannot declare parent_pack_sha256")
        if source_gap_request_id not in (None, ""):
            raise CurieContractError("version 1 cannot declare source_gap_request_id")
        parent_pack_sha256 = None
    else:
        parent_pack_sha256 = _require_sha256(parent_pack_sha256, "parent_pack_sha256")
        source_gap_request_id = _require_text(
            source_gap_request_id, "source_gap_request_id"
        )
    if source_gap_request_id is not None:
        source_gap_request_id = _require_text(source_gap_request_id, "source_gap_request_id")
    if source_run_id is not None:
        source_run_id = _require_text(source_run_id, "source_run_id")

    pack = {
        "schema_version": EVIDENCE_PACK_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": seed_sha256,
        "pack_id": f"EP_{_safe_token(candidate_id, 'candidate_id')}_{_safe_token(round_id, 'round_id')}_v{version}",
        "version": version,
        "parent_pack_sha256": parent_pack_sha256,
        "source_gap_request_id": source_gap_request_id,
        "source_run_id": source_run_id,
        "query_plans": copy.deepcopy(query_plans),
        "discovery_receipts": copy.deepcopy(discovery_receipts),
        "selected_papers": copy.deepcopy(selected_papers),
        "evidence": copy.deepcopy(evidence),
        "coverage": copy.deepcopy(coverage),
        "gaps": copy.deepcopy(gaps),
        "status": "READY_TO_FREEZE",
    }
    if semantic_verifications is not None:
        pack["semantic_verifications"] = copy.deepcopy(semantic_verifications)
    _validate_semantic_pack(pack)
    pack["content_sha256"] = _content_sha256(pack)
    return _validate_pack_structure(pack, expected_status="READY_TO_FREEZE")


def freeze_evidence_pack(project_dir: str | Path, pack: dict) -> dict:
    """Persist one immutable FROZEN pack and return its exact artifact manifest."""
    _validate_semantic_pack(pack)
    ready = _validate_pack_structure(pack, expected_status="READY_TO_FREEZE")
    if ready["coverage"]["verdict"] != "PASS":
        raise CurieContractError("EvidencePack coverage verdict must be PASS before freeze")
    frozen = copy.deepcopy(ready)
    frozen["status"] = "FROZEN"
    frozen["content_sha256"] = _content_sha256(frozen)
    frozen = _validate_pack_structure(frozen, expected_status="FROZEN")

    project_dir = Path(project_dir)
    relative_path = (
        _L05_ROOT
        / _safe_token(frozen["candidate_id"], "candidate_id")
        / _pack_filename(frozen["candidate_id"], frozen["round_id"], frozen["version"])
    )
    path = project_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise CurieContractError(f"frozen EvidencePack already exists: {relative_path.as_posix()}")
    raw = _canonical_bytes(frozen)
    path.write_bytes(raw)
    return {
        "schema_version": EVIDENCE_PACK_MANIFEST_SCHEMA_VERSION,
        "candidate_id": frozen["candidate_id"],
        "round_id": frozen["round_id"],
        "seed_sha256": frozen["seed_sha256"],
        "pack_id": frozen["pack_id"],
        "version": frozen["version"],
        "artifact_path": relative_path.as_posix(),
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "content_sha256": frozen["content_sha256"],
        "status": "FROZEN",
    }


def _validated_manifest_identity(manifest: dict, *, candidate_id: str,
                                 round_id: str, seed_sha256: str) -> dict:
    if not isinstance(manifest, dict):
        raise CurieContractError("EvidencePack manifest must be an object")
    if manifest.get("schema_version") != EVIDENCE_PACK_MANIFEST_SCHEMA_VERSION:
        raise CurieContractError("EvidencePack manifest schema_version is invalid")
    candidate_id = _require_text(candidate_id, "candidate_id")
    round_id = _require_text(round_id, "round_id")
    seed_sha256 = _require_sha256(seed_sha256, "seed_sha256")
    if manifest.get("candidate_id") != candidate_id:
        raise CurieContractError("EvidencePack manifest candidate_id does not match active candidate")
    if manifest.get("round_id") != round_id:
        raise CurieContractError("EvidencePack manifest round_id does not match active round")
    manifest_seed = _require_sha256(manifest.get("seed_sha256"), "EvidencePack manifest seed_sha256")
    if manifest_seed != seed_sha256:
        raise CurieContractError("EvidencePack manifest seed_sha256 does not match active ResearchSeed")
    _require_text(manifest.get("pack_id"), "EvidencePack manifest pack_id")
    version = manifest.get("version")
    if (not isinstance(version, int) or isinstance(version, bool)
            or not 1 <= version <= MAX_ACQUISITION_ROUNDS):
        raise CurieContractError(
            f"EvidencePack manifest version must be an integer from 1 to {MAX_ACQUISITION_ROUNDS}"
        )
    _require_text(manifest.get("artifact_path"), "EvidencePack manifest artifact_path")
    _require_sha256(manifest.get("artifact_sha256"), "EvidencePack manifest artifact_sha256")
    _require_sha256(manifest.get("content_sha256"), "EvidencePack manifest content_sha256")
    if manifest.get("status") != "FROZEN":
        raise CurieContractError("EvidencePack manifest status must be FROZEN")
    return copy.deepcopy(manifest)


def load_frozen_evidence_pack(project_dir: str | Path, manifest: dict, *,
                              candidate_id: str, round_id: str,
                              seed_sha256: str,
                              allow_legacy_source_identity: bool = False) -> dict:
    """Revalidate file path, artifact hash, content hash and identity at L1 use."""
    manifest = _validated_manifest_identity(
        manifest, candidate_id=candidate_id, round_id=round_id, seed_sha256=seed_sha256
    )
    project_dir = Path(project_dir).resolve()
    expected_root = (project_dir / _L05_ROOT / _safe_token(candidate_id, "candidate_id")).resolve()
    relative = Path(manifest["artifact_path"])
    if relative.is_absolute():
        raise CurieContractError("EvidencePack manifest artifact_path must be relative")
    path = (project_dir / relative).resolve()
    try:
        path.relative_to(expected_root)
    except ValueError as exc:
        raise CurieContractError("EvidencePack manifest artifact_path escapes the L0.5 evidence root") from exc
    if not path.is_file():
        raise CurieContractError(f"frozen EvidencePack artifact missing: {relative.as_posix()}")
    raw = path.read_bytes()
    artifact_sha = hashlib.sha256(raw).hexdigest()
    if artifact_sha != manifest["artifact_sha256"]:
        raise CurieContractError("EvidencePack artifact_sha256 does not match the frozen file")
    try:
        pack = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurieContractError(f"frozen EvidencePack is unreadable: {exc}") from exc
    _validate_semantic_pack(pack)
    pack = _validate_pack_structure(
        pack,
        expected_status="FROZEN",
        allow_legacy_frozen_acquisition_metadata=True,
        allow_legacy_frozen_source_identity=allow_legacy_source_identity,
    )
    for field, expected in (
        ("candidate_id", candidate_id),
        ("round_id", round_id),
        ("seed_sha256", seed_sha256.lower()),
        ("pack_id", manifest["pack_id"]),
        ("version", manifest["version"]),
        ("content_sha256", manifest["content_sha256"]),
    ):
        if pack.get(field) != expected:
            raise CurieContractError(f"frozen EvidencePack {field} does not match its manifest")
    if pack["coverage"]["verdict"] != "PASS":
        raise CurieContractError("frozen EvidencePack coverage verdict must be PASS")
    return pack


def next_pack_version(previous_pack: dict, *, gap_request: dict,
                      query_plans: list[dict], discovery_receipts: list[dict],
                      selected_papers: list[dict], evidence: list[dict],
                      coverage: dict, gaps: list[dict]) -> dict:
    """Create, never mutate, the next pack version authorized by an exact gap request."""
    previous = _validate_pack_structure(previous_pack, expected_status="FROZEN")
    request = validate_gap_request(gap_request)
    for field in ("candidate_id", "round_id", "seed_sha256"):
        if request[field] != previous[field]:
            raise CurieContractError(f"gap request {field} does not match the frozen EvidencePack")
    if request["pack_sha256"] != previous["content_sha256"]:
        raise CurieContractError(
            "gap request pack_sha256 does not match the frozen EvidencePack content_sha256"
        )
    return build_evidence_pack(
        candidate_id=previous["candidate_id"],
        round_id=previous["round_id"],
        seed_sha256=previous["seed_sha256"],
        version=previous["version"] + 1,
        parent_pack_sha256=previous["content_sha256"],
        source_gap_request_id=request["request_id"],
        source_run_id=None,
        query_plans=query_plans,
        discovery_receipts=discovery_receipts,
        selected_papers=selected_papers,
        evidence=evidence,
        coverage=coverage,
        gaps=gaps,
    )


def render_evidence_context(
    pack: dict, *, allow_legacy_frozen_acquisition_metadata: bool = False
) -> str:
    """Render only verified frozen evidence for Einstein's isolated L1 context."""
    frozen = _validate_pack_structure(
        pack,
        expected_status="FROZEN",
        allow_legacy_frozen_acquisition_metadata=allow_legacy_frozen_acquisition_metadata,
    )
    if frozen["coverage"]["verdict"] != "PASS":
        raise CurieContractError("L1 evidence context requires coverage PASS")
    papers = {paper["paper_id"]: paper for paper in frozen["selected_papers"]}
    lines = [
        "=== L0.5 CURIE FROZEN EVIDENCEPACK ===",
        "AUTHORITY: immutable, verified evidence state; Einstein may reason over these extracts but may not search or retrieve new literature.",
        f"pack_id: {frozen['pack_id']}",
        f"content_sha256: {frozen['content_sha256']}",
        f"version: {frozen['version']}",
        "## Verified EvidenceExtracts",
    ]
    for extract in frozen["evidence"]:
        paper = papers[extract["paper_id"]]
        identifier = next(
            (str(value) for value in paper.get("identifiers", {}).values() if str(value).strip()),
            extract["paper_id"],
        )
        lines.append(
            f"- [{extract['evidence_id']}] role={extract['role']} | {paper['title']} | {identifier} | "
            f"{extract['section']} @ {extract['locator']}: {extract['text']}"
        )
    return "\n".join(lines)
