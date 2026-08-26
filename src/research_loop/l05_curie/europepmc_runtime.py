"""End-to-end Europe PMC acquisition runtime for L0.5 Curie.

The runtime terminates at the immutable EvidencePack freeze boundary. It does
not bind the resulting pack into L1; that migration is intentionally outside
this Phase-2 vertical slice.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from research_loop import research_seed

from .contracts import CurieContractError, judge_coverage, validate_query_plan
from .europepmc import EuropePmcEvidenceRetriever, EuropePmcEvidenceVerifier, EuropePmcTransport
from .multisource import (
    build_multisource_query_plan,
    # Keep legacy module-level re-exports; production calls the strict sibling below.
    run_multisource_discovery,
    run_multisource_discovery_strict,
)
from .native_runtime import bind_initial_curie_pack
from .paperqa2_runtime import (
    PAPERQA2_BACKEND_ID,
    PaperQA2CurieRuntime,
    validate_pinned_paperqa2_runtime,
)
from .semantic_verifier import SemanticEvidenceVerifier, admit_reasoning_evidence
# Keep the legacy selector re-export for callers that imported it here.
from .selector import select_candidates, select_candidates_strict
from .store import build_evidence_pack, freeze_evidence_pack

RESULT_SCHEMA_VERSION = "L05EuropePmcAcquisitionResult/v1"
AUDIT_SCHEMA_VERSION = "L05EuropePmcAcquisitionManifest/v1"
PAPERQA2_RESULT_SCHEMA_VERSION = "L05PaperQA2EuropePmcAcquisitionResult/v1"
PAPERQA2_AUDIT_SCHEMA_VERSION = "L05PaperQA2EuropePmcAcquisitionManifest/v1"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _safe_token(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text).strip("._")
    if not safe:
        raise CurieContractError(f"{name} cannot be normalized to a safe token")
    return safe


def _new_run_id(candidate_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(f"{candidate_id}:{stamp}".encode("utf-8")).hexdigest()[:10]
    return f"EPMC_{stamp}_{digest}"


def _gap(gap_id: str, topic: str, reason: str, directions: list[str]) -> dict:
    return {
        "gap_id": gap_id,
        "topic": topic,
        "reason": reason,
        "search_directions": directions,
    }


def _coverage_for(source_snapshots: list[dict], evidence: list[dict], *, round_index: int) -> dict:
    covered: list[str] = []
    gaps: list[dict] = []
    if source_snapshots and evidence:
        covered.append("verified_full_text_source")
    else:
        gaps.append(_gap(
            "NO_VERIFIED_FULL_TEXT",
            "verified full text",
            "No selected Europe PMC OA source produced independently verified located evidence.",
            [
                "broaden the Europe PMC query while retaining OPEN_ACCESS candidates",
                "search for primary papers with PMCID-backed Europe PMC full text",
            ],
        ))
    interpretation = any(
        any(word in str(item.get("section") or "").casefold()
            for word in ("result", "discussion", "conclusion"))
        for item in evidence
    )
    if interpretation:
        covered.append("located_results_or_interpretation")
    else:
        gaps.append(_gap(
            "NO_LOCATED_INTERPRETIVE_EVIDENCE",
            "located results or interpretation",
            "No verified Results, Discussion, or Conclusion extract was located.",
            [
                "retrieve a different OA primary paper with explicit results or interpretation sections",
                "refine the query toward direct empirical evidence for the ResearchSeed",
            ],
        ))
    return judge_coverage(
        {"covered": covered, "gaps": gaps},
        round_index=round_index,
    )


def _write_audit_manifest(
    project_dir: Path,
    *,
    candidate_id: str,
    run_id: str,
    payload: dict,
) -> tuple[str, str]:
    relative = (
        Path("08_Audit")
        / "l05_acquisition"
        / _safe_token(candidate_id, "candidate_id")
        / _safe_token(run_id, "run_id")
        / "acquisition_manifest.json"
    )
    path = project_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical_bytes(payload)
    if path.exists():
        if path.read_bytes() != raw:
            raise CurieContractError(
                f"Europe PMC acquisition manifest already exists with different content: {relative.as_posix()}"
            )
    else:
        path.write_bytes(raw)
    return relative.as_posix(), hashlib.sha256(raw).hexdigest()


def _europepmc_full_text_eligibility(record: dict) -> tuple[bool, str]:
    """Require a source-qualified Europe PMC OA full text before retrieval."""
    identifiers = record.get("identifiers") if isinstance(record.get("identifiers"), dict) else {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if not identifiers.get("pmcid"):
        return False, "NO_EUROPEPMC_PMCID"
    if metadata.get("is_open_access") is not True:
        return False, "NO_OPEN_FULL_TEXT"
    if metadata.get("in_europe_pmc") is not True:
        return False, "NOT_IN_EUROPEPMC"
    return True, "SOURCE_QUALIFIED"


def _europepmc_selector_score(record: dict, seed: dict) -> dict:
    """Provide deterministic ranking only; eligibility remains authoritative."""
    source = " ".join((
        str(record.get("title") or ""),
        str((record.get("metadata") or {}).get("abstract") or ""),
    )).casefold()
    seed_terms = {
        term for term in (
            str(seed.get("scientific_question") or "") + " "
            + str(seed.get("hypothesis_seed") or "")
        ).casefold().replace("?", " ").replace(",", " ").split()
        if len(term) > 2
    }
    matched = sum(term in source for term in seed_terms)
    relevance = matched / max(1, len(seed_terms))
    source_count = len(
        ((record.get("provenance") or {}).get("source_records") or [])
    )
    return {
        "relevance": relevance,
        "directness": 1.0 if relevance else 0.5,
        "methodological_value": 0.5,
        "contradiction_value": 0.0,
        "evidence_diversity": min(1.0, source_count / 2),
        "reason": "Deterministic source-qualified Europe PMC ranking from the canonical ResearchSeed.",
    }


def _selected_europepmc_papers(discovery: dict, selection: dict) -> list[dict]:
    decisions = {
        str(item["paper_id"]): item
        for item in selection["decisions"]
        if item["decision"] == "INCLUDE"
    }
    selected = []
    for record in discovery["records"]:
        decision = decisions.get(str(record.get("paper_id") or ""))
        if decision is None:
            continue
        selected.append({
            "paper_id": record["paper_id"],
            "title": record["title"],
            "identifiers": dict(record.get("identifiers") or {}),
            "metadata": dict(record.get("metadata") or {}),
            "provenance": dict(record.get("provenance") or {}),
            "selection": {
                "decision": "INCLUDE",
                "reason": decision["reason"],
                "reason_code": decision.get("reason_code"),
            },
        })
    return selected


def _prepare_europepmc_acquisition(
    project: Path,
    candidate_id: str,
    *,
    explicit_queries: list[str] | None,
    max_papers: int,
    page_size: int,
    run_id: str | None,
    http_get: Callable[[str, int], bytes] | None,
    timeout: int,
    round_index: int,
) -> dict:
    """Discover and select Europe PMC records once for each acquisition mode."""
    try:
        seed = research_seed.load_l1_research_seed(project, candidate_id)
    except research_seed.ResearchSeedError as exc:
        raise CurieContractError(f"canonical ResearchSeed is invalid: {exc}") from exc
    seed_digest = research_seed.seed_sha256(seed)
    normalized_run_id = _safe_token(run_id or _new_run_id(candidate_id), "run_id")
    # PaperQA2 retrieval is Europe-PMC source-qualified, but discovery and
    # selection remain in Curie's provider-neutral planner/orchestrator path.
    # The declared one-provider plan is deliberate: every selected record must
    # be retrievable from the exact Europe PMC OA full-text source below.
    query_plan = build_multisource_query_plan(
        seed,
        seed_sha256=seed_digest,
        round_index=round_index,
        explicit_queries=explicit_queries,
        providers=["europe-pmc"],
    )
    validate_query_plan(query_plan, seed_sha256=seed_digest)
    transport = EuropePmcTransport(
        project,
        candidate_id=candidate_id,
        run_id=normalized_run_id,
        http_get=http_get,
        timeout=timeout,
    )
    discovery = run_multisource_discovery_strict(
        query_plan,
        {"europe-pmc": transport},
        seed_sha256=seed_digest,
        page_size=page_size,
    )
    generic_selection = select_candidates_strict(
        discovery["records"],
        seed=seed,
        scorer=_europepmc_selector_score,
        eligibility=_europepmc_full_text_eligibility,
        max_papers=max_papers,
        project_dir=project,
        candidate_id=candidate_id,
        run_id=normalized_run_id,
        query_ids={str(item["query_id"]) for item in query_plan["queries"]},
    )
    selected = _selected_europepmc_papers(discovery, generic_selection)
    return {
        "seed": seed,
        "seed_sha256": seed_digest,
        "run_id": normalized_run_id,
        "query_plan": query_plan,
        "transport_handshake": transport.handshake(),
        "discovery_batches": discovery["batches"],
        "selection": {
            "provider": "europe-pmc",
            "selected": selected,
            "decisions": generic_selection["decisions"],
            "duplicate_paper_ids": discovery["duplicate_paper_ids"],
            "selector_artifact_path": generic_selection.get("artifact_path"),
            "selector_artifact_sha256": generic_selection.get("artifact_sha256"),
        },
    }


def _paperqa_pdf_path(pdf_paths: object, paper_id: str) -> tuple[Path, str]:
    if not isinstance(pdf_paths, dict):
        raise CurieContractError("PaperQA2 PDF map must be an object keyed by canonical paper_id")
    raw_path = pdf_paths.get(paper_id)
    if raw_path is None:
        raise CurieContractError(f"PaperQA2 PDF map has no selected paper_id: {paper_id}")
    path = Path(str(raw_path)).expanduser().resolve()
    if not path.is_file():
        raise CurieContractError(f"PaperQA2 PDF is missing for {paper_id}: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def _paperqa2_semantic_target(seed: dict) -> str:
    question = str(seed.get("scientific_question") or "").strip()
    hypothesis = str(seed.get("hypothesis_seed") or "").strip()
    if not question or not hypothesis:
        raise CurieContractError(
            "PaperQA2 semantic admission requires ResearchSeed question and hypothesis"
        )
    return f"Scientific question: {question}\nHypothesis seed: {hypothesis}"


def _admit_paperqa2_semantic_evidence(
    located: list[dict],
    *,
    semantic_target: str,
    assessor: Callable,
    assessor_id: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Semantically assess LOCATED evidence against the ResearchSeed target.

    Source fidelity and semantic relevance remain separate authorities. Every
    LOCATED extract receives a semantic record for audit; only reasoning-
    authorized extracts and their matching semantic records may enter a
    semantic EvidencePack.
    """
    if not callable(assessor):
        raise CurieContractError("PaperQA2 semantic assessor must be callable")
    semantic_target = str(semantic_target or "").strip()
    assessor_id = str(assessor_id or "").strip()
    if not semantic_target:
        raise CurieContractError("PaperQA2 semantic target must be non-empty")
    if not assessor_id:
        raise CurieContractError("PaperQA2 semantic assessor_id must be non-empty")
    verifier = SemanticEvidenceVerifier(assessor=assessor, assessor_id=assessor_id)
    all_semantics = [
        verifier.verify(extract, claim=semantic_target)
        for extract in located
    ]
    admitted = admit_reasoning_evidence(located, all_semantics)
    admitted_ids = {item["evidence_id"] for item in admitted}
    admitted_semantics = [
        item for item in all_semantics
        if item["evidence_id"] in admitted_ids
    ]
    return admitted, admitted_semantics, all_semantics


def run_europepmc_acquisition(
    project_dir: str | Path,
    cand_id: str,
    *,
    explicit_queries: list[str] | None = None,
    max_papers: int = 3,
    page_size: int = 25,
    run_id: str | None = None,
    http_get: Callable[[str, int], bytes] | None = None,
    timeout: int = 20,
    round_index: int = 1,
) -> dict:
    """Execute one auditable Europe PMC acquisition round through FREEZE."""
    project = Path(project_dir)
    candidate_id = str(cand_id)
    prepared = _prepare_europepmc_acquisition(
        project,
        candidate_id,
        explicit_queries=explicit_queries,
        max_papers=max_papers,
        page_size=page_size,
        run_id=run_id,
        http_get=http_get,
        timeout=timeout,
        round_index=round_index,
    )
    seed = prepared["seed"]
    seed_digest = prepared["seed_sha256"]
    run_id = prepared["run_id"]
    query_plan = prepared["query_plan"]
    handshake = prepared["transport_handshake"]
    discovery_batches = prepared["discovery_batches"]
    selection = prepared["selection"]

    source_snapshots: list[dict] = []
    verified_evidence: list[dict] = []
    if selection["selected"]:
        retriever = EuropePmcEvidenceRetriever(
            project,
            candidate_id=candidate_id,
            run_id=run_id,
            http_get=http_get,
            timeout=timeout,
        )
        verifier = EuropePmcEvidenceVerifier(project, candidate_id=candidate_id)
        for paper in selection["selected"]:
            retrieval = retriever.retrieve(paper, seed=seed)
            source_snapshots.append(retrieval["snapshot"])
            verified_evidence.extend(
                verifier.verify(retrieval["snapshot"], retrieval["candidates"])
            )

    coverage = _coverage_for(
        source_snapshots,
        verified_evidence,
        round_index=round_index,
    )

    evidence_pack_manifest = None
    status = coverage["verdict"]
    if coverage["verdict"] == "PASS":
        pack = build_evidence_pack(
            candidate_id=candidate_id,
            round_id=str(seed["round_id"]),
            seed_sha256=seed_digest,
            version=1,
            query_plans=[query_plan],
            discovery_receipts=discovery_batches,
            selected_papers=selection["selected"],
            evidence=verified_evidence,
            coverage=coverage,
            gaps=coverage["gaps"],
            source_run_id=run_id,
        )
        evidence_pack_manifest = freeze_evidence_pack(project, pack)
        status = "FROZEN"

    audit_payload = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": str(seed["round_id"]),
        "run_id": run_id,
        "seed_sha256": seed_digest,
        "transport_handshake": handshake,
        "query_plan": query_plan,
        "discovery_batches": discovery_batches,
        "selection": selection,
        "source_snapshots": source_snapshots,
        "verified_evidence_ids": [item["evidence_id"] for item in verified_evidence],
        "coverage": coverage,
        "evidence_pack": evidence_pack_manifest,
        "status": status,
    }
    audit_path, audit_sha = _write_audit_manifest(
        project,
        candidate_id=candidate_id,
        run_id=run_id,
        payload=audit_payload,
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": str(seed["round_id"]),
        "run_id": run_id,
        "status": status,
        "coverage": coverage,
        "evidence_pack": evidence_pack_manifest,
        "acquisition_manifest_path": audit_path,
        "acquisition_manifest_sha256": audit_sha,
    }


def run_paperqa2_europepmc_acquisition(
    project_dir: str | Path,
    cand_id: str,
    *,
    paperqa_runtime: PaperQA2CurieRuntime,
    pdf_paths: dict[str, str | Path],
    semantic_assessor: Callable | None = None,
    semantic_assessor_id: str = "l05-paperqa2-semantic-assessor/v2",
    explicit_queries: list[str] | None = None,
    max_papers: int = 3,
    page_size: int = 25,
    run_id: str | None = None,
    http_get: Callable[[str, int], bytes] | None = None,
    timeout: int = 20,
) -> dict:
    """Run pinned PaperQA2 retrieval through independent verification into L1 v1."""
    if not isinstance(paperqa_runtime, PaperQA2CurieRuntime):
        raise CurieContractError("PaperQA2 production runtime must be PaperQA2CurieRuntime")
    if paperqa_runtime.backend_id != PAPERQA2_BACKEND_ID:
        raise CurieContractError("PaperQA2 production runtime backend_id is not the pinned backend")
    if not callable(semantic_assessor):
        raise CurieContractError(
            "PaperQA2 production acquisition requires an explicit semantic assessor; "
            "exact-source self-claims cannot authorize reasoning evidence"
        )
    semantic_assessor_id = str(semantic_assessor_id or "").strip()
    if not semantic_assessor_id:
        raise CurieContractError("PaperQA2 semantic_assessor_id must be non-empty")
    project = Path(project_dir)
    candidate_id = str(cand_id)
    prepared = _prepare_europepmc_acquisition(
        project,
        candidate_id,
        explicit_queries=explicit_queries,
        max_papers=max_papers,
        page_size=page_size,
        run_id=run_id,
        http_get=http_get,
        timeout=timeout,
        round_index=1,
    )
    seed = prepared["seed"]
    seed_digest = prepared["seed_sha256"]
    normalized_run_id = prepared["run_id"]
    selection = prepared["selection"]
    semantic_target = _paperqa2_semantic_target(seed)
    source_snapshots: list[dict] = []
    located_evidence: list[dict] = []
    semantic_verifications: list[dict] = []
    paperqa_audit: list[dict] = []
    if selection["selected"]:
        retriever = EuropePmcEvidenceRetriever(
            project,
            candidate_id=candidate_id,
            run_id=normalized_run_id,
            http_get=http_get,
            timeout=timeout,
        )
        verifier = EuropePmcEvidenceVerifier(project, candidate_id=candidate_id)
        for selected in selection["selected"]:
            paper_id = str(selected["paper_id"])
            pdf_path, pdf_sha256 = _paperqa_pdf_path(pdf_paths, paper_id)
            source = retriever.retrieve(selected, seed=seed)
            source_snapshots.append(source["snapshot"])
            paper = {**selected, "pdf_path": str(pdf_path)}
            result = paperqa_runtime.retrieve_and_verify(
                paper=paper,
                question=str(seed["scientific_question"]),
                source_candidates=source["candidates"],
                verify=lambda candidates, snapshot=source["snapshot"]: verifier.verify(
                    snapshot, candidates
                ),
            )
            for candidate in result["unverified"]:
                runtime = (candidate.get("retrieval") or {}).get("runtime")
                validate_pinned_paperqa2_runtime(
                    runtime, pdf_sha256=pdf_sha256
                )
                if Path(str(runtime["pdf_path"])).resolve() != pdf_path:
                    raise CurieContractError(
                        "PaperQA2 runtime PDF path does not match the selected PDF"
                    )
            located = result["located"]
            admitted, admitted_semantics, all_semantics = _admit_paperqa2_semantic_evidence(
                located,
                semantic_target=semantic_target,
                assessor=semantic_assessor,
                assessor_id=semantic_assessor_id,
            )
            located_evidence.extend(admitted)
            semantic_verifications.extend(admitted_semantics)
            paperqa_audit.append({
                "paper_id": paper_id,
                "pdf_sha256": pdf_sha256,
                "snapshot": source["snapshot"],
                "chunk_count": len(result["chunks"]),
                "unverified_evidence_ids": [item["evidence_id"] for item in result["unverified"]],
                "located_evidence_ids": [item["evidence_id"] for item in located],
                "semantic_verification_ids": [item["verification_id"] for item in all_semantics],
                "reasoning_authorized_evidence_ids": [item["evidence_id"] for item in admitted],
                "semantic_verifications": all_semantics,
            })

    coverage = _coverage_for(source_snapshots, located_evidence, round_index=1)
    evidence_pack_manifest = None
    native_binding = None
    status = coverage["verdict"]
    if coverage["verdict"] == "PASS":
        pack = build_evidence_pack(
            candidate_id=candidate_id,
            round_id=str(seed["round_id"]),
            seed_sha256=seed_digest,
            version=1,
            query_plans=[prepared["query_plan"]],
            discovery_receipts=prepared["discovery_batches"],
            selected_papers=selection["selected"],
            evidence=located_evidence,
            coverage=coverage,
            gaps=coverage["gaps"],
            source_run_id=normalized_run_id,
            semantic_verifications=semantic_verifications,
        )
        evidence_pack_manifest = freeze_evidence_pack(project, pack)
        native_binding = bind_initial_curie_pack(
            project, seed, evidence_pack_manifest, normalized_run_id
        )
        status = "FROZEN"

    audit_payload = {
        "schema_version": PAPERQA2_AUDIT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": str(seed["round_id"]),
        "run_id": normalized_run_id,
        "seed_sha256": seed_digest,
        "transport_handshake": prepared["transport_handshake"],
        "query_plan": prepared["query_plan"],
        "discovery_batches": prepared["discovery_batches"],
        "selection": selection,
        "paperqa2": paperqa_audit,
        "coverage": coverage,
        "evidence_pack": evidence_pack_manifest,
        "native_binding": native_binding,
        "status": status,
    }
    audit_path, audit_sha = _write_audit_manifest(
        project,
        candidate_id=candidate_id,
        run_id=normalized_run_id,
        payload=audit_payload,
    )
    return {
        "schema_version": PAPERQA2_RESULT_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": str(seed["round_id"]),
        "run_id": normalized_run_id,
        "status": status,
        "coverage": coverage,
        "evidence_pack": evidence_pack_manifest,
        "native_binding": native_binding,
        "acquisition_manifest_path": audit_path,
        "acquisition_manifest_sha256": audit_sha,
    }
