"""Compatibility bridge from the existing L1 Deep Research store into L0.5.

The existing Academic Research runtime remains an acquisition backend.  Its
validated run is snapshotted into the new immutable L0.5 EvidencePack before
Einstein is allowed to consume literature evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import (
    EVIDENCE_EXTRACT_SCHEMA_VERSION,
    QUERY_PLAN_SCHEMA_VERSION,
    CurieContractError,
    judge_coverage,
)
from .store import (
    _L05_ROOT,
    _pack_filename,
    _safe_token,
    _validate_pack_structure,
    build_evidence_pack,
    freeze_evidence_pack,
    load_frozen_evidence_pack,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _existing_v1_manifest(
    project_dir: Path,
    *,
    candidate_id: str,
    round_id: str,
    seed_sha256: str,
    run_id: str,
) -> dict | None:
    relative = (
        _L05_ROOT
        / _safe_token(candidate_id, "candidate_id")
        / _pack_filename(candidate_id, round_id, 1)
    )
    path = project_dir / relative
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        pack = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurieContractError(
            f"existing frozen L0.5 EvidencePack is unreadable: {exc}"
        ) from exc
    pack = _validate_pack_structure(pack, expected_status="FROZEN")
    if pack.get("source_run_id") != run_id:
        raise CurieContractError(
            "an L0.5 EvidencePack is already frozen for this candidate/round "
            "from a different acquisition run"
        )
    manifest = {
        "schema_version": "L05EvidencePackManifest/v1",
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": seed_sha256,
        "pack_id": pack["pack_id"],
        "version": 1,
        "artifact_path": relative.as_posix(),
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "content_sha256": pack["content_sha256"],
        "status": "FROZEN",
    }
    load_frozen_evidence_pack(
        project_dir,
        manifest,
        candidate_id=candidate_id,
        round_id=round_id,
        seed_sha256=seed_sha256,
    )
    return manifest


def freeze_l1_deep_research_run(
    project_dir: str | Path,
    *,
    candidate_id: str,
    round_id: str,
    seed_sha256: str,
    run_id: str,
) -> dict:
    """Snapshot one already-audited legacy L1 run into a frozen L0.5 pack.

    This bridge is intentionally conservative.  It first reuses the existing
    strict L1 evidence audit, then converts only source-located extracts.  A
    second call for the same exact run is idempotent; a different run cannot
    overwrite an already-frozen v1 pack.
    """
    from research_loop import deep_research

    project_dir = Path(project_dir)
    candidate_id = str(candidate_id)
    round_id = str(round_id)
    seed_sha256 = str(seed_sha256).lower()
    run_id = str(run_id)

    existing = _existing_v1_manifest(
        project_dir,
        candidate_id=candidate_id,
        round_id=round_id,
        seed_sha256=seed_sha256,
        run_id=run_id,
    )
    if existing is not None:
        return existing

    ok, reason = deep_research.audit_evidence_pack(
        project_dir, candidate_id, "L1", run_id=run_id
    )
    if not ok:
        raise CurieContractError(
            f"legacy L1 acquisition run failed evidence audit: {reason}"
        )

    try:
        run_manifest = deep_research.evidence_artifact_manifest(
            project_dir, candidate_id, "L1", run_id
        )
    except deep_research.DeepResearchError as exc:
        raise CurieContractError(
            f"legacy L1 acquisition manifest is invalid: {exc}"
        ) from exc
    if str(run_manifest.get("candidate_id") or "") != candidate_id:
        raise CurieContractError("legacy L1 acquisition candidate identity mismatch")
    if str(run_manifest.get("round_id") or "") != round_id:
        raise CurieContractError("legacy L1 acquisition round identity mismatch")

    run_file = next(
        (item for item in run_manifest.get("files", []) if item.get("kind") == "run"),
        None,
    )
    if not isinstance(run_file, dict):
        raise CurieContractError("legacy L1 acquisition has no immutable run file")
    run_path = project_dir / str(run_file["path"])
    try:
        artifact = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurieContractError(
            f"legacy L1 acquisition run file is unreadable: {exc}"
        ) from exc
    if str(artifact.get("run_id") or "") != run_id:
        raise CurieContractError("legacy L1 acquisition run_id mismatch")

    paper_records: list[dict] = []
    selected_papers: list[dict] = []
    evidence: list[dict] = []
    providers: set[str] = set()
    for ref in artifact.get("papers", []):
        try:
            paper_path = project_dir / str(ref["path"])
            paper = json.loads(paper_path.read_text(encoding="utf-8"))
        except (KeyError, OSError, json.JSONDecodeError) as exc:
            raise CurieContractError(
                f"legacy L1 acquisition references an unreadable paper record: {exc}"
            ) from exc
        paper_records.append(paper)
        provider = str(paper.get("source_database") or "legacy-academic-research")
        providers.add(provider)
        identifiers = {
            key: str(value)
            for key, value in (
                ("doi", paper.get("doi")),
                ("pmid", paper.get("pmid")),
                ("url", paper.get("url")),
            )
            if str(value or "").strip()
        }
        selected_papers.append(
            {
                "paper_id": str(paper["paper_id"]),
                "title": str(paper["title"]),
                "identifiers": identifiers,
                "selection": {
                    "decision": "INCLUDE",
                    "reason": (
                        "selected by the legacy Academic Research acquisition run; "
                        "source-located extracts passed the existing L1 evidence audit"
                    ),
                },
                "provenance": {
                    "source_run_id": run_id,
                    "source_database": provider,
                    "paper_record_path": str(ref["path"]),
                    "paper_record_sha256": _sha256_file(paper_path),
                },
            }
        )
        fallback_source_hash = str(paper.get("metadata_response_hash") or "")
        if len(fallback_source_hash) != 64:
            fallback_source_hash = _sha256_file(paper_path)
        for extract in paper.get("evidence_extracts", []):
            if (
                extract.get("verification_status") != "located"
                or not str(extract.get("locator") or "").strip()
            ):
                continue
            source_hash = str(extract.get("source_hash") or "")
            if len(source_hash) != 64:
                source_hash = fallback_source_hash
            evidence.append(
                {
                    "schema_version": EVIDENCE_EXTRACT_SCHEMA_VERSION,
                    "evidence_id": str(extract["evidence_id"]),
                    "paper_id": str(paper["paper_id"]),
                    "section": str(extract["section"]),
                    "text": str(extract["text"]),
                    "locator": str(extract["locator"]),
                    "role": "CONTEXT",
                    "verification_status": "LOCATED",
                    "retrieval": {
                        "engine": "legacy-deep-research-bridge",
                        "source_sha256": source_hash,
                        "source_run_id": run_id,
                        "extraction_method": str(
                            extract.get("extraction_method") or "source-located"
                        ),
                    },
                }
            )

    queries = [str(query) for query in artifact.get("queries", []) if str(query).strip()]
    if not queries:
        raise CurieContractError("legacy L1 acquisition run contains no executed queries")
    query_providers = sorted(providers) or ["legacy-academic-research"]
    plan_id = f"QP_LEGACY_{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:16]}"
    query_plan = {
        "schema_version": QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": seed_sha256,
        "plan_id": plan_id,
        "round_index": 1,
        "queries": [
            {
                "query_id": f"Q{index:03d}",
                "intent": "legacy_acquisition_query",
                "query": query,
                "providers": query_providers,
            }
            for index, query in enumerate(queries, 1)
        ],
    }
    coverage = judge_coverage(
        {
            "covered": [
                "located_results_extract",
                "located_discussion_extract",
                "located_conclusion_extract",
            ],
            "gaps": [],
        },
        round_index=1,
    )
    ready = build_evidence_pack(
        candidate_id=candidate_id,
        round_id=round_id,
        seed_sha256=seed_sha256,
        version=1,
        query_plans=[query_plan],
        discovery_receipts=[],
        selected_papers=selected_papers,
        evidence=evidence,
        coverage=coverage,
        gaps=[],
        source_run_id=run_id,
    )
    return freeze_evidence_pack(project_dir, ready)
