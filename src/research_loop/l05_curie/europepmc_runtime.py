"""End-to-end Europe PMC acquisition runtime for L0.5 Curie.

The runtime terminates at the immutable EvidencePack freeze boundary. It does
not bind the resulting pack into L1; that migration is intentionally outside
this Phase-2 vertical slice.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from research_loop import deep_research, research_seed, structured_execution
from research_loop.external_resilience import classify_http_failure

from .contracts import (
    CurieContractError, judge_coverage, validate_coverage_decision,
    validate_evidence_extract, validate_query_plan,
)
from .europepmc import (
    EuropePmcEvidenceRetriever, EuropePmcEvidenceVerifier, EuropePmcTransport,
    _default_http_get,
)
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
from .semantic_verifier import (
    SemanticEvidenceVerifier, admit_reasoning_evidence, validate_semantic_verification,
    evidence_extract_sha256,
)
from .query_planner import (
    SCIENTIFIC_QUERY_PLAN_V2, compile_scientific_query_plan,
    propose_scientific_query_plan, validate_scientific_query_plan,
    prepare_scientific_query_plan_request,
    validate_scientific_query_plan_response,
)
# Keep the legacy selector re-export for callers that imported it here.
from .selector import select_candidates, select_candidates_strict
from .store import (
    build_evidence_pack, freeze_evidence_pack, initial_evidence_pack_path,
    load_frozen_evidence_pack,
    preview_frozen_evidence_pack,
)

RESULT_SCHEMA_VERSION = "L05EuropePmcAcquisitionResult/v1"
AUDIT_SCHEMA_VERSION = "L05EuropePmcAcquisitionManifest/v2"
PAPERQA2_RESULT_SCHEMA_VERSION = "L05PaperQA2EuropePmcAcquisitionResult/v1"
PAPERQA2_AUDIT_SCHEMA_VERSION = "L05PaperQA2EuropePmcAcquisitionManifest/v1"
ACQUISITION_CHECKPOINT_SCHEMA_VERSION = "L05AcquisitionCheckpoint/v1"
ACQUISITION_MODE_SCHEMA_VERSION = "L05AcquisitionExecutionMode/v1"
PLANNER_HOST_RECEIPT_SCHEMA_VERSION = "L05PlannerHostReceipt/v1"
PLANNER_TERMINAL_SCHEMA_VERSION = "L05PlannerTerminal/v1"
PLANNER_REPROPOSAL_SCHEMA_VERSION = "L05PlannerReproposal/v1"
SEMANTIC_HOST_RECEIPT_SCHEMA_VERSION = "L05SemanticHostReceipt/v1"
_ACQUISITION_HOST_TOOLS_POLICY = (
    "Use only the exact ResearchSeed, feedback, and request prompt/schema provided. "
    "Do not perform retrieval, alter provenance, or assert validation outcomes."
)
_SEMANTIC_HOST_TOOLS_POLICY = (
    "Assess only the exact LOCATED extract and claim in this request. "
    "Return only the five requested assessor fields."
)
_PAPERQA2_MAX_INTENT_CHARS = 320
_PAPERQA2_MAX_INTENT_TOKENS = 32
_PAPERQA2_STOPWORDS = frozenset({
    "a", "an", "and", "are", "be", "best", "by", "can", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "these",
    "this", "to", "was", "what", "which", "with",
})


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _atomic_json(path: Path, payload: dict, *, immutable: bool = False) -> str:
    raw = _canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != raw:
            raise CurieAcquisitionError("RECOVERY_ERROR", f"immutable acquisition artifact conflicts: {path}")
        return hashlib.sha256(raw).hexdigest()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable and path.exists():
            if path.read_bytes() != raw:
                raise CurieAcquisitionError("RECOVERY_ERROR", f"immutable acquisition artifact conflicts: {path}")
        else:
            os.replace(temporary, path)
            temporary = None
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def _acquisition_paths(project: Path, candidate_id: str, round_id: str, run_id: str):
    root = (project / "08_Audit" / "l05_acquisition"
            / _safe_token(candidate_id, "candidate_id"))
    return {
        "root": root,
        "owner": root / f"first_{_safe_token(round_id, 'round_id')}.json",
        "mode": root / f"first_{_safe_token(round_id, 'round_id')}.mode.json",
        "run": root / _safe_token(run_id, "acquisition_run_id"),
        "checkpoint": root / _safe_token(run_id, "acquisition_run_id") / "host_checkpoint.json",
    }


def _bind_acquisition_mode(project: Path, candidate_id: str, round_id: str,
                           run_id: str, mode: str) -> None:
    if mode not in {"headless", "agent_native"}:
        raise CurieAcquisitionError("CONTRACT_ERROR", "acquisition execution mode is invalid")
    paths = _acquisition_paths(project, candidate_id, round_id, run_id)
    marker = {
        "schema_version": ACQUISITION_MODE_SCHEMA_VERSION,
        "candidate_id": candidate_id, "round_id": round_id,
        "acquisition_run_id": run_id, "execution_mode": mode,
    }
    path = paths["mode"]
    if path.exists():
        existing = _read_object(path)
        if existing == marker:
            return
        if (paths["owner"].exists()
                and existing.get("candidate_id") == candidate_id
                and existing.get("round_id") == round_id
                and existing.get("acquisition_run_id") != run_id):
            # Let the canonical owner reject a different run ID. The round-level
            # mode marker belongs to that existing owner and must not mask its
            # more specific identity conflict.
            return
        if existing != marker:
            raise CurieAcquisitionError(
                "RECOVERY_ERROR", "active first acquisition execution mode conflicts"
            )
    if paths["owner"].exists():
        owner = _read_object(paths["owner"])
        if owner.get("acquisition_run_id") != run_id:
            # Preserve the existing owner identity error for a second run ID.
            return
        # Owner v1 artifacts predate explicit mode binding and remain headless-only.
        if mode != "headless":
            raise CurieAcquisitionError(
                "RECOVERY_ERROR", "legacy active acquisition owner is headless and cannot switch mode"
            )
        return
    _atomic_json(path, marker, immutable=True)


def _checkpoint_digest(checkpoint: dict) -> str:
    value = {key: item for key, item in checkpoint.items() if key != "checkpoint_sha256"}
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _save_acquisition_checkpoint(path: Path, checkpoint: dict) -> dict:
    value = dict(checkpoint)
    value["schema_version"] = ACQUISITION_CHECKPOINT_SCHEMA_VERSION
    value["checkpoint_sha256"] = _checkpoint_digest(value)
    _atomic_json(path, value)
    return value


def _load_acquisition_checkpoint(path: Path, *, project: Path,
                                 candidate_id: str, round_id: str,
                                 run_id: str, seed_sha256: str) -> dict:
    checkpoint = _read_object(path)
    if checkpoint.get("schema_version") != ACQUISITION_CHECKPOINT_SCHEMA_VERSION:
        raise CurieAcquisitionError("RECOVERY_ERROR", "acquisition checkpoint version is unsupported")
    if checkpoint.get("checkpoint_sha256") != _checkpoint_digest(checkpoint):
        raise CurieAcquisitionError("RECOVERY_ERROR", "acquisition checkpoint content/hash mismatch")
    expected = {
        "candidate_id": candidate_id, "round_id": round_id,
        "acquisition_run_id": run_id, "seed_sha256": seed_sha256,
        "execution_mode": "agent_native",
    }
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise CurieAcquisitionError("RECOVERY_ERROR", "acquisition checkpoint identity/mode mismatch")
    if checkpoint.get("external_state") == "HTTP_IN_FLIGHT":
        checkpoint["external_state"] = "uncertain_external_result"
        checkpoint["phase"] = "uncertain_external_result"
        _save_acquisition_checkpoint(path, checkpoint)
    for table in (checkpoint.get("planner_requests", {}), checkpoint.get("semantic_requests", {})):
        for _key, ref in table.items():
            request_id = str(ref.get("request_id") or "")
            request_path = Path(ref.get("request_path") or "").resolve()
            try:
                request_path.relative_to(project.resolve())
            except ValueError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", "host request path escapes project") from exc
            if (not request_path.is_file()
                    or hashlib.sha256(request_path.read_bytes()).hexdigest() != ref.get("request_sha256")):
                raise CurieAcquisitionError("RECOVERY_ERROR", "host request bytes/hash changed")
            if not request_id:
                raise CurieAcquisitionError("RECOVERY_ERROR", "host request identity is missing")
            from research_loop import host_handoff
            try:
                host_handoff.load_request(project, request_id)
            except (ValueError, OSError) as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", f"host request store is invalid: {exc}") from exc
    for ref in checkpoint.get("http_responses", []):
        response_path = Path(ref.get("path") or "").resolve()
        try:
            response_path.relative_to(project.resolve())
        except ValueError as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", "HTTP response path escapes project") from exc
        if (not response_path.is_file()
                or hashlib.sha256(response_path.read_bytes()).hexdigest() != ref.get("sha256")):
            raise CurieAcquisitionError("RECOVERY_ERROR", "HTTP response bytes/hash changed")
    for table in (checkpoint.get("planner_responses", {}), checkpoint.get("semantic_responses", {})):
        for request_id, receipt in table.items():
            if (not isinstance(receipt, dict)
                    or receipt.get("schema_version") != "HostResponseReceipt/v1"
                    or receipt.get("request_id") != request_id):
                raise CurieAcquisitionError("RECOVERY_ERROR", "host response receipt identity is invalid")
            raw_path = Path(str(receipt.get("raw_response_path") or "")).resolve()
            try:
                raw_path.relative_to(project.resolve())
            except ValueError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", "host response path escapes project") from exc
            if (not raw_path.is_file()
                    or hashlib.sha256(raw_path.read_bytes()).hexdigest() != receipt.get("raw_response_sha256")):
                raise CurieAcquisitionError("RECOVERY_ERROR", "host response bytes/hash changed")
    return checkpoint


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
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".acquisition-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                if path.read_bytes() != raw:
                    raise CurieContractError("Europe PMC acquisition manifest publication collision")
            else:
                os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
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


def _reserve_europepmc_papers(discovery: dict, selection: dict) -> list[dict]:
    decisions = {
        str(item["paper_id"]): item
        for item in selection["decisions"]
        if item["decision"] == "RESERVE"
    }
    reserves = []
    for record in discovery["records"]:
        decision = decisions.get(str(record.get("paper_id") or ""))
        if decision is None:
            continue
        reserves.append({
            "paper_id": record["paper_id"],
            "title": record["title"],
            "identifiers": dict(record.get("identifiers") or {}),
            "metadata": dict(record.get("metadata") or {}),
            "provenance": dict(record.get("provenance") or {}),
            "selection": {
                "decision": "RESERVE",
                "reason": decision["reason"],
                "reason_code": decision.get("reason_code"),
            },
        })
    return reserves


def _promote_reserve_after_failure(reserve: dict, failed_paper_id: str, reason: str) -> dict:
    """Make one selector-approved reserve eligible for the same acquisition slot.

    Single owner for reserve promotion across resource-failure reason codes.
    """
    reason_code = f"PROMOTED_AFTER_{reason}"
    return {
        **reserve,
        "selection": {
            "decision": "INCLUDE",
            "reason": (
                "Promoted from selector-approved RESERVE after "
                f"{failed_paper_id} produced {reason}."
            ),
            "reason_code": reason_code,
            "original_decision": "RESERVE",
        },
    }


def _promote_reserve_after_no_target_sections(reserve: dict, failed_paper_id: str) -> dict:
    """Backwards-compatible alias for the NO_TARGET_SECTIONS promotion path."""
    return _promote_reserve_after_failure(
        reserve, failed_paper_id, reason="NO_TARGET_SECTIONS"
    )


def _root_cause(exc: BaseException) -> BaseException:
    """Walk the __cause__/__context__ chain to the originating transport/HTTP exception."""
    current = exc
    while current.__cause__ is not None or current.__context__ is not None:
        nxt = current.__cause__ if current.__cause__ is not None else current.__context__
        if nxt is exc:
            break
        current = nxt
    return current


def _classify_resource_failure(
    *,
    failure: BaseException,
    pmcid: str,
    known_good_snapshots: list[dict],
    retriever: EuropePmcEvidenceRetriever,
    seed: dict,
) -> dict | None:
    """Classify a single fullTextXML failure as RESOURCE_LEVEL (paper_failure) or None.

    Returns a paper_failure record (to be promoted) when the failure is a resource-level
    problem; returns None to signal SOURCE_LEVEL: the caller must re-raise `failure`
    verbatim (fail-closed). Uses the sole HTTP classifier (`classify_http_failure`) for
    retry semantics; this layer only adds resource-vs-source *context*.
    """
    original = _root_cause(failure)
    decision = classify_http_failure(original)
    if decision.retry:
        # 429/502/503/504 that exhausted the shared retry policy => service-level.
        raise CurieContractError(
            "Europe PMC fullTextXML retry-exhausted source-level failure: "
            f"pmcid={pmcid} retry={decision.reason} failure_scope=SOURCE_LEVEL"
        ) from failure
    # Non-retryable outcome: 500/404/410/transport.
    if isinstance(original, HTTPError):
        code = int(original.code)
        if code in (404, 410):
            # 4xx resource-absent semantics are per-resource; no control probe needed.
            return {
                "paper_id": pmcid,
                "pmcid": pmcid,
                "reason_code": "RESOURCE_UNAVAILABLE",
                "retrieval": {
                    "requested_url": str(getattr(original, "url", f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")),
                    "http_status": code,
                    "failure_class": decision.reason,
                    "failure_scope": "RESOURCE_LEVEL",
                },
            }
        if code == 500:
            return _classify_500_with_control(
                failure=failure, pmcid=pmcid, original=original,
                known_good_snapshots=known_good_snapshots,
                retriever=retriever, seed=seed,
            )
        # Other non-retryable HTTP status (4xx except 429, other 5xx) => unknown => fail closed.
        raise CurieContractError(
            f"Europe PMC fullTextXML non-retryable HTTP {code} not classified as "
            f"resource-level: pmcid={pmcid} failure_scope=SOURCE_LEVEL"
        ) from failure
    # Non-HTTP transport error (DNS/TLS/connection/timeout) => source-level.
    raise CurieContractError(
        f"Europe PMC fullTextXML transport-level failure: pmcid={pmcid} "
        f"failure_class={decision.reason} failure_scope=SOURCE_LEVEL"
    ) from failure


def _classify_500_with_control(
    *, failure: BaseException, pmcid: str, original: HTTPError,
    known_good_snapshots: list[dict], retriever: EuropePmcEvidenceRetriever, seed: dict,
) -> dict | None:
    """Distinguish a single-resource 500 from a fullTextXML subsystem outage."""
    if not known_good_snapshots:
        raise CurieContractError(
            "Europe PMC fullTextXML HTTP 500 with no known-good control: "
            f"pmcid={pmcid} failure_scope=SOURCE_LEVEL"
        ) from failure
    control_pmcid = known_good_snapshots[-1].get("pmcid")
    if not control_pmcid:
        raise CurieContractError(
            "Europe PMC fullTextXML HTTP 500 known-good snapshot lacks pmcid: "
            f"pmcid={pmcid} failure_scope=SOURCE_LEVEL"
        ) from failure
    try:
        control = retriever.health_probe(control_pmcid, seed=seed)
    except Exception as control_exc:
        raise CurieContractError(
            "Europe PMC fullTextXML HTTP 500 failed contemporaneous known-good control "
            f"probe: pmcid={pmcid} control_pmcid={control_pmcid} "
            f"control_failure={classify_http_failure(_root_cause(control_exc)).reason} "
            f"failure_scope=SOURCE_LEVEL"
        ) from failure
    return {
        "paper_id": pmcid,
        "pmcid": pmcid,
        "reason_code": "RESOURCE_UNAVAILABLE",
        "retrieval": {
            "requested_url": str(getattr(original, "url", f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")),
            "http_status": 500,
            "failure_class": "http_500",
            "failure_scope": "RESOURCE_LEVEL",
            "control": {
                "control_pmcid": control["control_pmcid"],
                "control_url": control["control_url"],
                "control_result": control["control_result"],
                "control_http_status": control["control_http_status"],
            },
        },
    }



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
    reformulation_index: int = 0,
    query_id_prefix: str = "Q",
    prebuilt_query_plan: dict | None = None,
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
    query_plan = prebuilt_query_plan
    if query_plan is None:
        query_plan = build_multisource_query_plan(
            seed,
            seed_sha256=seed_digest,
            round_index=round_index,
            explicit_queries=explicit_queries,
            providers=["europe-pmc"],
            reformulation_index=reformulation_index,
            query_id_prefix=query_id_prefix,
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
        "discovery": discovery,
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


def _paperqa2_retrieval_query(selected: dict, seed: dict, query_plan: dict) -> str:
    """Build a bounded, paper-local query without changing evidence authority.

    The selected title anchors retrieval to one paper. Existing QueryPlan text
    and the canonical ResearchSeed provide the scientific focus, but the focus
    is token-bounded so a long seed is not forwarded verbatim to PaperQA2.
    This helper only returns a retrieval string; source verification and
    semantic admission remain downstream authorities.
    """
    if not isinstance(selected, dict):
        raise CurieContractError("PaperQA2 retrieval requires a selected paper object")
    title = str(selected.get("title") or "").strip()
    if not title:
        raise CurieContractError("PaperQA2 retrieval requires a non-empty paper title anchor")
    seed = seed if isinstance(seed, dict) else {}
    query_plan = query_plan if isinstance(query_plan, dict) else {}
    fragments = [
        str(seed.get("scientific_question") or ""),
        str(seed.get("hypothesis_seed") or ""),
    ]
    for item in query_plan.get("queries") or []:
        if isinstance(item, dict):
            fragments.append(str(item.get("query") or ""))
    terms: list[str] = []
    seen_terms: set[str] = set()
    total_chars = 0
    for raw in re.findall(
        r"[^\W_]+(?:[-'][^\W_]+)*",
        " ".join(fragments),
        flags=re.UNICODE,
    ):
        token = raw.strip()
        if not token or token.casefold() in _PAPERQA2_STOPWORDS or token.isdigit():
            continue
        token = token[:80]
        folded = token.casefold()
        if folded in seen_terms:
            continue
        if terms and total_chars + len(token) + 1 > _PAPERQA2_MAX_INTENT_CHARS:
            break
        terms.append(token)
        seen_terms.add(folded)
        total_chars += len(token) + (1 if len(terms) > 1 else 0)
        if len(terms) >= _PAPERQA2_MAX_INTENT_TOKENS:
            break
    if not terms:
        raise CurieContractError(
            "PaperQA2 retrieval requires targeted scientific retrieval terms"
        )
    return f"{title} | retrieval focus: {' '.join(terms)}"


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


class CurieAcquisitionError(CurieContractError):
    """Typed first-acquisition failure passed through the CLI to the runner."""

    def __init__(self, category: str, detail: str):
        self.category = category
        super().__init__(f"{category}: {detail}")


class _AcquisitionHostPending(Exception):
    def __init__(self, result: dict):
        self.result = result
        super().__init__("agent-native acquisition is waiting for a host response")


def _typed_attempt_error(exc: CurieContractError, attempts: list[dict]) -> CurieAcquisitionError:
    if isinstance(exc, CurieAcquisitionError):
        return exc
    root = _root_cause(exc)
    category = (
        "SERVICE_ERROR" if isinstance(root, (URLError, TimeoutError, ConnectionError))
        or "SOURCE_LEVEL" in str(exc) else "CONTRACT_ERROR"
    )
    last = attempts[-1]["artifact"] if attempts else None
    return CurieAcquisitionError(
        category, f"{exc}; last_valid_attempt={last!r}"
    )


@contextmanager
def _first_acquisition_writer(project: Path, candidate_id: str, round_id: str):
    """Hold one OS-owned candidate/round lock; a crash releases the OS lock."""
    lock_path = (project / "08_Audit" / "l05_acquisition"
                 / _safe_token(candidate_id, "candidate_id")
                 / f"first_{_safe_token(round_id, 'round_id')}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CurieAcquisitionError(
                "PERSISTENCE_ERROR", "first acquisition already has an active writer"
            ) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _write_immutable(path: Path, payload: dict) -> str:
    raw = _canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise CurieAcquisitionError(
            "PERSISTENCE_ERROR", f"acquisition artifact already exists: {path}"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _write_attempt_immutable(path: Path, payload: dict) -> str:
    """Persist an attempt once, accepting only an exact replay of its bytes."""
    raw = _canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        try:
            existing = path.read_bytes()
        except OSError as read_exc:
            raise CurieAcquisitionError(
                "PERSISTENCE_ERROR", f"existing attempt artifact is unreadable: {path}"
            ) from read_exc
        if existing != raw:
            raise CurieAcquisitionError(
                "PERSISTENCE_ERROR", f"attempt artifact already exists with different bytes: {path}"
            ) from exc
    return hashlib.sha256(raw).hexdigest()


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurieAcquisitionError(
            "RECOVERY_ERROR", f"acquisition artifact is unreadable: {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise CurieAcquisitionError("RECOVERY_ERROR", f"acquisition artifact is not an object: {path}")
    return value


def _verify_acquisition_reference(project: Path, relative: str, digest: str,
                                  run_id: str, candidate_id: str) -> None:
    candidate_root = (project / "08_Audit" / "l05_acquisition").resolve()
    source_root = (project / "09_Literature_Database").resolve()
    path = (project / str(relative)).resolve()
    if not (path.is_relative_to(candidate_root) or path.is_relative_to(source_root)):
        raise CurieAcquisitionError("RECOVERY_ERROR", f"source reference escapes acquisition roots: {relative}")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise CurieAcquisitionError("RECOVERY_ERROR", f"source reference bytes/hash mismatch: {relative}")
    if run_id not in path.parts or _safe_token(candidate_id, "candidate_id") not in path.parts:
        raise CurieAcquisitionError("RECOVERY_ERROR", f"source reference run provenance mismatch: {relative}")


def _validated_planner_proposal(
    project: Path, candidate_id: str, run_id: str, planner_index: int,
    receipt: dict, proposal_sha256: str, *, seed: dict | None = None,
    feedback: dict | None = None,
    expected_status: str = "PLAN", expected_proposal_status: str | None = None,
) -> dict:
    if isinstance(receipt, dict) and receipt.get("schema_version") == PLANNER_HOST_RECEIPT_SCHEMA_VERSION:
        host_receipt = receipt.get("host_response_receipt")
        if (not isinstance(host_receipt, dict)
                or host_receipt.get("schema_version") != "HostResponseReceipt/v1"
                or host_receipt.get("raw_response_sha256") != proposal_sha256
                or receipt.get("proposal_sha256") != proposal_sha256):
            raise CurieAcquisitionError("RECOVERY_ERROR", "host planner receipt identity is invalid")
        from research_loop import host_handoff
        try:
            request = host_handoff.load_request(project, str(host_receipt.get("request_id") or ""))
        except (ValueError, OSError) as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", f"host planner request is invalid: {exc}") from exc
        request_path = Path(str(host_receipt.get("request_path") or "")).resolve()
        response_path = Path(str(host_receipt.get("raw_response_path") or "")).resolve()
        project_root = project.resolve()
        for path, label in ((request_path, "request"), (response_path, "response")):
            try:
                path.relative_to(project_root)
            except ValueError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", f"host planner {label} escapes project") from exc
        request_raw = request_path.read_bytes() if request_path.is_file() else b""
        response_raw = response_path.read_bytes() if response_path.is_file() else b""
        if (hashlib.sha256(request_raw).hexdigest() != host_receipt.get("request_sha256")
                or request.get("request_sha256") != host_receipt.get("request_sha256")
                or hashlib.sha256(response_raw).hexdigest() != proposal_sha256
                or host_receipt.get("raw_response_sha256") != hashlib.sha256(response_raw).hexdigest()):
            raise CurieAcquisitionError("RECOVERY_ERROR", "host planner request/response bytes changed")
        generic_receipt_path = (
            project_root / "08_Audit" / "host_handoff" / "responses"
            / f"{host_receipt['request_id']}.json"
        )
        if not generic_receipt_path.is_file() or _read_object(generic_receipt_path) != host_receipt:
            raise CurieAcquisitionError("RECOVERY_ERROR", "host planner response receipt changed")
        planner_request = (request.get("inputs") or {}).get("planner_request")
        if (not isinstance(planner_request, dict)
                or planner_request.get("request_sha256") != receipt.get("planner_request_sha256")):
            raise CurieAcquisitionError("RECOVERY_ERROR", "host planner prompt/schema binding changed")
        try:
            proposal = deep_research._parse_cli_output(response_raw.decode("utf-8"))
            if seed is None:
                raise CurieContractError("host planner manifest validation requires ResearchSeed")
            decision = validate_scientific_query_plan_response(
                seed, request=planner_request, raw_response=response_raw,
            )
            proposal_status = ("SELECT_CANDIDATE" if planner_request.get("schema_version") ==
                               "L05ScientificQueryPlanSelectionRequest/v1" else expected_status)
            if (proposal.get("status") != (expected_proposal_status or proposal_status)
                    or decision.get("status") != expected_status):
                raise CurieContractError("host planner proposal status differs from its manifest role")
            reproposal = receipt.get("reproposal")
            if (proposal_status == "SELECT_CANDIDATE" and reproposal is None):
                raise CurieContractError("selection reproposal provenance is missing")
            if reproposal is not None:
                expected_reproposal_keys = {
                    "schema_version", "acquisition_attempt_index", "proposal_index",
                    "source_request_id", "source_request", "source_planner_request_sha256",
                    "source_response_receipt", "source_proposal_sha256",
                    "candidate_set_sha256", "followup_request", "followup_prompt_sha256",
                }
                if (not isinstance(reproposal, dict)
                        or set(reproposal) != expected_reproposal_keys
                        or reproposal.get("schema_version") != PLANNER_REPROPOSAL_SCHEMA_VERSION
                        or reproposal.get("acquisition_attempt_index") != planner_index
                        or reproposal.get("proposal_index") != 2
                        or expected_status != "PLAN"):
                    raise CurieContractError("host planner reproposal provenance is invalid")
                source_receipt = reproposal.get("source_response_receipt")
                source_request_ref = reproposal.get("source_request")
                if (not isinstance(source_receipt, dict)
                        or not isinstance(source_request_ref, dict)
                        or reproposal.get("source_request_id") != source_receipt.get("request_id")
                        or source_request_ref.get("request_id") != source_receipt.get("request_id")):
                    raise CurieContractError("host planner reproposal source receipt is invalid")
                source_wrapper = {
                    "schema_version": PLANNER_HOST_RECEIPT_SCHEMA_VERSION,
                    "host_response_receipt": source_receipt,
                    "planner_request_sha256": reproposal.get("source_planner_request_sha256"),
                    "proposal_sha256": reproposal.get("source_proposal_sha256"),
                }
                source_proposal = _validated_planner_proposal(
                    project, candidate_id, run_id, planner_index,
                    source_wrapper, reproposal.get("source_proposal_sha256"),
                        seed=seed, expected_status="REPROPOSAL_REQUIRED",
                        expected_proposal_status="NO_ADMISSIBLE_REPLAN",
                )
                source_request = host_handoff.load_request(
                    project, str(source_receipt.get("request_id") or "")
                )
                source_request_ref_expected = {
                    "request_id": source_request["request_id"],
                    "request_path": source_request["request_path"],
                    "request_sha256": source_request["request_sha256"],
                }
                source_planner_request = (source_request.get("inputs") or {}).get("planner_request")
                if (source_request_ref != source_request_ref_expected
                        or source_request.get("identity", {}).get("stage") != "planner"
                        or source_request.get("identity", {}).get("attempt") != planner_index
                        or not isinstance(source_planner_request, dict)
                        or source_planner_request.get("request_sha256")
                        != reproposal.get("source_planner_request_sha256")):
                    raise CurieContractError("host planner reproposal source request binding differs")
                source_path = Path(source_receipt["raw_response_path"]).resolve()
                source_raw = source_path.read_bytes()
                source_decision = validate_scientific_query_plan_response(
                    seed, request=source_planner_request, raw_response=source_raw,
                )
                expected_candidate_sha = hashlib.sha256(
                    _canonical_bytes(source_decision.get("candidates"))
                ).hexdigest()
                expected_followup = source_decision.get("next_request")
                expected_followup_identity = dict(source_request["identity"])
                expected_followup_identity["attempt"] = planner_index * 10 + 1
                expected_followup_ref = {
                    "request_id": request["request_id"],
                    "request_path": request["request_path"],
                    "request_sha256": request["request_sha256"],
                    "attempt_index": planner_index * 10 + 1,
                    "stage": "planner",
                }
                expected_inputs = dict(source_request["inputs"])
                expected_inputs["planner_request"] = expected_followup
                if (source_decision.get("status") != "REPROPOSAL_REQUIRED"
                        or source_proposal.get("status") != "NO_ADMISSIBLE_REPLAN"
                        or reproposal.get("candidate_set_sha256") != expected_candidate_sha
                        or reproposal.get("followup_prompt_sha256") != hashlib.sha256(
                            expected_followup["prompt"].encode("utf-8")
                        ).hexdigest()
                        or reproposal.get("followup_request") != expected_followup_ref
                        or request.get("identity") != expected_followup_identity
                        or request.get("output_contract") != {"type": "object", "schema": expected_followup["schema"]}
                        or request.get("inputs") != expected_inputs):
                    raise CurieContractError("host planner reproposal candidate/prompt/request binding differs")
            return {**proposal, "status": "PLAN" if decision["status"] == "PLAN" else proposal["status"],
                    "plan": decision["plan"]}
        except (UnicodeError, deep_research.DeepResearchError, CurieContractError) as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", f"host planner proposal invalid: {exc}") from exc
    expected_dir = (project / "08_Audit" / "l05_acquisition" / candidate_id
                    / run_id / f"planner_{planner_index:03d}").resolve()
    if (not isinstance(receipt, dict)
            or receipt.get("schema_version") != structured_execution.SCHEMA_VERSION
            or receipt.get("validation_status") != "PASS"):
        raise CurieAcquisitionError("RECOVERY_ERROR", "structured planner receipt is invalid")
    for path_key, hash_key, expected_hash in (
        ("output_path", "stdout_hash", proposal_sha256),
        ("prompt_path", "prompt_hash", receipt.get("prompt_hash")),
        ("schema_path", "schema_sha256", receipt.get("schema_sha256")),
    ):
        path = Path(str(receipt.get(path_key) or "")).resolve()
        digest = receipt.get(hash_key)
        if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or digest != expected_hash or not path.is_file()
                or not path.is_relative_to(expected_dir)
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise CurieAcquisitionError("RECOVERY_ERROR", f"structured planner {path_key} provenance mismatch")
    try:
        raw = Path(receipt["output_path"]).read_text(encoding="utf-8")
        proposal = deep_research._parse_cli_output(raw)
        if seed is None:
            raise CurieContractError("planner manifest validation requires ResearchSeed")
        planner_request = prepare_scientific_query_plan_request(
            seed, reformulation_index=planner_index - 1, feedback=feedback,
        )
        if "prior_proposal_receipt" in receipt:
            prior_receipt = receipt["prior_proposal_receipt"]
            prior_sha = receipt.get("prior_proposal_sha256")
            _validated_planner_proposal(
                project, candidate_id, run_id, planner_index, prior_receipt, prior_sha,
                seed=seed, feedback=feedback, expected_status="REPROPOSAL_REQUIRED",
                expected_proposal_status="NO_ADMISSIBLE_REPLAN",
            )
            prior_raw = Path(prior_receipt["output_path"]).read_bytes()
            prior_decision = validate_scientific_query_plan_response(
                seed, request=planner_request, raw_response=prior_raw,
            )
            if receipt.get("replan_enumeration") != prior_decision.get("replan_enumeration"):
                raise CurieContractError("planner selection enumeration receipt changed")
            planner_request = prior_decision["next_request"]
        if (Path(receipt["prompt_path"]).read_text(encoding="utf-8") != planner_request["prompt"]
                or _read_object(Path(receipt["schema_path"])) != planner_request["schema"]):
            raise CurieContractError("planner prompt/schema differs from authorized request")
        decision = validate_scientific_query_plan_response(
            seed, request=planner_request, raw_response=raw.encode("utf-8"),
        )
        proposal_status = ("SELECT_CANDIDATE" if planner_request.get("schema_version") ==
                           "L05ScientificQueryPlanSelectionRequest/v1" else expected_status)
        if (proposal.get("status") != (expected_proposal_status or proposal_status)
                or decision.get("status") != expected_status):
            raise CurieContractError("planner proposal status differs from its manifest role")
        return {**proposal, "status": "PLAN" if decision["status"] == "PLAN" else proposal["status"],
                "plan": decision["plan"]}
    except (UnicodeError, deep_research.DeepResearchError, CurieContractError) as exc:
        raise CurieAcquisitionError("RECOVERY_ERROR", f"structured planner proposal invalid: {exc}") from exc


def _validate_semantic_host_receipts(
    project: Path, *, candidate_id: str, round_id: str, attempt_index: int,
    attempt: dict, located: list[dict], semantics: list[dict], seed: dict,
) -> None:
    provenance = ((attempt.get("query_plan") or {}).get("planning_provenance") or {})
    planner_receipt = provenance.get("receipt") or {}
    is_host = planner_receipt.get("schema_version") == PLANNER_HOST_RECEIPT_SCHEMA_VERSION
    rows = attempt.get("semantic_host_receipts")
    if not is_host:
        if rows not in (None, []):
            raise CurieAcquisitionError("RECOVERY_ERROR", "headless attempt carries host semantic receipts")
        return
    if not isinstance(rows, list):
        raise CurieAcquisitionError("RECOVERY_ERROR", "host attempt lacks semantic host receipts")
    located_by_id = {item["evidence_id"]: item for item in located}
    semantics_by_id = {item["evidence_id"]: item for item in semantics}
    receipts_by_id = {
        item.get("evidence_id"): item for item in rows if isinstance(item, dict)
    }
    if (len(receipts_by_id) != len(rows)
            or set(receipts_by_id) != set(located_by_id)
            or set(semantics_by_id) != set(located_by_id)):
        raise CurieAcquisitionError("RECOVERY_ERROR", "host semantic receipt evidence set differs")
    expected_claim = _paperqa2_semantic_target(seed)
    project_root = project.resolve()
    source_snapshots = {
        (item.get("artifact_path"), item.get("artifact_sha256"))
        for item in attempt.get("source_snapshots", []) if isinstance(item, dict)
    }
    from research_loop import host_handoff
    for evidence_id, extract in located_by_id.items():
        row = receipts_by_id[evidence_id]
        verification = semantics_by_id[evidence_id]
        request_ref = row.get("host_request")
        receipt = row.get("host_response_receipt")
        if not isinstance(request_ref, dict) or not isinstance(receipt, dict):
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host request/response reference is missing")
        request_id = str(request_ref.get("request_id") or "")
        try:
            request = host_handoff.load_request(project, request_id)
        except (ValueError, OSError) as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", f"semantic host request is invalid: {exc}") from exc
        if (request.get("schema_version") != "HostRequest/v1"
                or request_ref.get("request_path") != request.get("request_path")
                or request_ref.get("request_sha256") != request.get("request_sha256")
                or set(request_ref) != {"request_id", "request_path", "request_sha256"}):
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host request reference differs")
        request_path = Path(request["request_path"]).resolve()
        try:
            request_path.relative_to(project_root)
        except ValueError as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host request escapes project") from exc
        request_raw = request_path.read_bytes() if request_path.is_file() else b""
        if hashlib.sha256(request_raw).hexdigest() != request["request_sha256"]:
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host request bytes/hash changed")
        identity = request.get("identity") or {}
        inputs = request.get("inputs") or {}
        source = extract.get("retrieval") or {}
        extract_sha = evidence_extract_sha256(extract)
        claim_sha = hashlib.sha256(expected_claim.encode("utf-8")).hexdigest()
        if (identity.get("candidate_id") != candidate_id
                or identity.get("round_id") != round_id
                or identity.get("node") != "L0.5"
                or identity.get("stage") != f"semantic:{evidence_id}"
                or identity.get("attempt") != attempt_index
                or request.get("kind") != f"l05_semantic:{evidence_id}"
                or inputs.get("extract") != extract
                or inputs.get("extract_sha256") != extract_sha
                or inputs.get("claim") != expected_claim
                or inputs.get("claim_sha256") != claim_sha
                or inputs.get("source_sha256") != source.get("source_sha256")
                or row.get("extract_sha256") != extract_sha
                or row.get("claim_sha256") != claim_sha
                or row.get("source_sha256") != source.get("source_sha256")
                or verification.get("extract_sha256") != extract_sha
                or verification.get("claim_sha256") != claim_sha):
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host request/evidence binding differs")
        if (source.get("snapshot_path"), source.get("source_sha256")) not in source_snapshots:
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host source is absent from attempt snapshots")
        if (receipt.get("schema_version") != "HostResponseReceipt/v1"
                or receipt.get("request_id") != request_id
                or receipt.get("request_path") != request["request_path"]
                or receipt.get("request_sha256") != request["request_sha256"]
                or receipt.get("cursor") != identity.get("cursor")):
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host response receipt binding differs")
        response_path = Path(str(receipt.get("raw_response_path") or "")).resolve()
        try:
            response_path.relative_to(project_root)
        except ValueError as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host response escapes project") from exc
        response_raw = response_path.read_bytes() if response_path.is_file() else b""
        response_sha = hashlib.sha256(response_raw).hexdigest()
        if response_sha != receipt.get("raw_response_sha256"):
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host response bytes/hash changed")
        receipt_path = (project_root / "08_Audit" / "host_handoff" / "responses"
                        / f"{request_id}.json")
        if not receipt_path.is_file() or _read_object(receipt_path) != receipt:
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host response receipt artifact changed")
        try:
            answer = json.loads(response_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", f"semantic host response is invalid: {exc}") from exc
        if (not isinstance(answer, dict)
                or set(answer) != {"entailment", "scope_match", "context_preserved",
                                   "qualification_preserved", "reason"}
                or any(verification.get(key) != answer.get(key) for key in (
                    "entailment", "scope_match", "context_preserved",
                    "qualification_preserved", "reason",
                ))):
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic host response differs from verification")


def _validate_acquisition_manifest(project: Path, manifest: dict, *,
                                    candidate_id: str, round_id: str,
                                    seed_sha256: str, run_id: str,
                                    seed: dict) -> None:
    """One validation owner for new v2 first-acquisition manifests."""
    expected = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "candidate_id": candidate_id, "round_id": round_id,
        "seed_sha256": seed_sha256, "acquisition_run_id": run_id,
        "target_pack_version": 1, "max_attempts": 3,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition manifest identity/contract mismatch")
    owner_path = (project / "08_Audit" / "l05_acquisition"
                  / _safe_token(candidate_id, "candidate_id")
                  / f"first_{_safe_token(round_id, 'round_id')}.json")
    if _read_object(owner_path) != {
        "schema_version": "L05FirstAcquisitionOwner/v1",
        "candidate_id": candidate_id, "round_id": round_id,
        "seed_sha256": seed_sha256, "acquisition_run_id": run_id,
    }:
        raise CurieAcquisitionError("RECOVERY_ERROR", "first acquisition owner mismatch")
    attempts = manifest.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
        raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition attempts are missing or out of bounds")
    plan_ids: set[str] = set()
    query_ids: set[str] = set()
    generated_content_hashes: set[str] = set()
    generated_plan_hashes: set[str] = set()
    all_evidence: dict[str, dict] = {}
    all_semantics: dict[str, dict] = {}
    all_papers: dict[str, dict] = {}
    all_batches: list[dict] = []
    for index, attempt in enumerate(attempts, 1):
        if attempt.get("attempt_index") != index:
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition attempt indexes are not contiguous")
        plan = validate_query_plan(attempt.get("query_plan"), seed_sha256=seed_sha256)
        planning = plan.get("planning")
        if isinstance(planning, dict) and planning.get("schema_version") == SCIENTIFIC_QUERY_PLAN_V2:
            validated_planning = validate_scientific_query_plan(planning, seed=seed)
            if index > 1:
                prior = attempts[index - 2]
                prior_plan = prior["query_plan"].get("planning") or {}
                prior_feedback = prior.get("planner_feedback")
                if (not isinstance(prior_feedback, dict)
                        or validated_planning["parent_plan_content_hash"] != prior_plan.get("plan_content_hash")
                        or validated_planning["feedback_sha256"] != hashlib.sha256(
                            json.dumps(prior_feedback, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                        or validated_planning["feedback_gap_ids"] != sorted(
                            item["gap_id"] for item in prior_feedback["validated_coverage_gaps"]
                        )):
                    raise CurieAcquisitionError("RECOVERY_ERROR", "scientific replan parent/feedback mismatch")
            compiled = compile_scientific_query_plan(validated_planning, seed=seed)
            if len(plan["queries"]) != len(compiled):
                raise CurieAcquisitionError("RECOVERY_ERROR", "generated query count differs from compiler output")
            for query, expected_query in zip(plan["queries"], compiled):
                if (query.get("query") != expected_query["query"]
                        or query.get("query_content_hash") != expected_query["query_content_hash"]
                        or query.get("origin") != "generated"):
                    raise CurieAcquisitionError("RECOVERY_ERROR", "generated query differs from validated compiler output")
                if query["query_content_hash"] in generated_content_hashes:
                    raise CurieAcquisitionError("RECOVERY_ERROR", "generated query content repeats across attempts")
                generated_content_hashes.add(query["query_content_hash"])
            if validated_planning["plan_content_hash"] in generated_plan_hashes:
                raise CurieAcquisitionError("RECOVERY_ERROR", "generated plan content repeats across attempts")
            generated_plan_hashes.add(validated_planning["plan_content_hash"])
            provenance = plan.get("planning_provenance")
            if not isinstance(provenance, dict):
                raise CurieAcquisitionError("RECOVERY_ERROR", "generated plan lacks structured planning provenance")
            receipt = provenance.get("receipt") or {}
            proposal = _validated_planner_proposal(
                project, candidate_id, run_id, index, receipt,
                provenance.get("proposal_sha256"), seed=seed,
                feedback=attempts[index - 2].get("planner_feedback") if index > 1 else None,
            )
            model_plan = proposal.get("plan") if isinstance(proposal, dict) else None
            if (proposal.get("status") != "PLAN" or not isinstance(model_plan, dict)
                    or proposal.get("reason") != provenance.get("reason")
                    or validated_planning != model_plan):
                raise CurieAcquisitionError("RECOVERY_ERROR", "validated scientific plan differs from model proposal")
        if plan["candidate_id"] != candidate_id or plan["round_id"] != round_id or plan["round_index"] != 1:
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition QueryPlan identity mismatch")
        if plan["plan_id"] in plan_ids:
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition repeats a QueryPlan ID")
        plan_ids.add(plan["plan_id"])
        local_queries = {query["query_id"] for query in plan["queries"]}
        if local_queries & query_ids:
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition repeats a query ID")
        query_ids.update(local_queries)
        artifact = attempt.get("artifact")
        if not isinstance(artifact, dict):
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 attempt artifact reference is missing")
        relative = artifact.get("path")
        digest = artifact.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 attempt artifact reference is invalid")
        expected_attempt = (project / "08_Audit" / "l05_acquisition"
                            / _safe_token(candidate_id, "candidate_id") / run_id
                            / f"attempt_{index:03d}.json").resolve()
        if (project / relative).resolve() != expected_attempt:
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 attempt artifact path mismatch")
        _verify_acquisition_reference(project, relative, digest, run_id, candidate_id)
        persisted = _read_object(project / relative)
        if persisted != {key: value for key, value in attempt.items() if key != "artifact"}:
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 attempt artifact content mismatch")
        http_hashes = {
            request.get("response_sha256") for request in attempt.get("http_requests", [])
            if isinstance(request, dict) and request.get("response_sha256")
        }
        for batch in attempt.get("discovery_batches", []):
            if batch.get("query_id") not in local_queries:
                raise CurieAcquisitionError("RECOVERY_ERROR", "discovery batch belongs to another attempt")
            receipt = batch.get("receipt") or {}
            if receipt.get("response_sha256") not in http_hashes:
                raise CurieAcquisitionError("RECOVERY_ERROR", "discovery response lacks an actual HTTP request")
            _verify_acquisition_reference(
                project, receipt.get("response_path"), receipt.get("response_sha256"),
                f"{run_id}_A{index}", candidate_id,
            )
            if isinstance(planning, dict) and planning.get("schema_version") == SCIENTIFIC_QUERY_PLAN_V2:
                matching = [item for item in plan["queries"] if item["query_id"] == batch["query_id"]]
                matching_requests = [
                    request for request in attempt.get("http_requests", [])
                    if request.get("response_sha256") == receipt.get("response_sha256")
                    and "/search?" in str(request.get("url") or "")
                ]
                if (len(matching) != 1 or not matching_requests
                        or not any(parse_qs(urlparse(request["url"]).query).get("query") == [matching[0]["query"]]
                                   for request in matching_requests)):
                    raise CurieAcquisitionError("RECOVERY_ERROR", "actual Europe PMC request differs from compiled query")
            all_batches.append(batch)
        for snapshot in attempt.get("source_snapshots", []):
            if (snapshot.get("run_id") != f"{run_id}_A{index}"
                    or snapshot.get("artifact_sha256") not in http_hashes):
                raise CurieAcquisitionError("RECOVERY_ERROR", "source snapshot lacks attempt HTTP provenance")
            _verify_acquisition_reference(
                project, snapshot.get("artifact_path"), snapshot.get("artifact_sha256"),
                f"{run_id}_A{index}", candidate_id,
            )
        validate_coverage_decision(attempt.get("coverage_facts"))
        planner_feedback = attempt.get("planner_feedback")
        if planner_feedback is not None:
            if (not isinstance(planner_feedback, dict)
                    or planner_feedback.get("previous_plan") != planning
                    or planner_feedback.get("previous_plan_id") != plan["plan_id"]
                    or planner_feedback.get("validated_coverage_gaps") != attempt["coverage_facts"]["gaps"]
                    or planner_feedback.get("cumulative_admitted_evidence_ids") != attempt.get("cumulative_verified_evidence_ids")):
                raise CurieAcquisitionError("RECOVERY_ERROR", "persisted planner feedback differs from attempt facts")
        for paper in attempt.get("acquired_papers", []):
            all_papers.setdefault(paper["paper_id"], paper)
        for evidence in attempt.get("verified_evidence", []):
            evidence = validate_evidence_extract(evidence)
            previous = all_evidence.setdefault(evidence["evidence_id"], evidence)
            if previous != evidence:
                raise CurieAcquisitionError("RECOVERY_ERROR", "evidence ID collision across attempts")
        if "located_evidence" in attempt or "semantic_verifications" in attempt:
            located = [validate_evidence_extract(item) for item in attempt.get("located_evidence", [])]
            semantics = [validate_semantic_verification(item) for item in attempt.get("semantic_verifications", [])]
            admitted = admit_reasoning_evidence(located, semantics)
            if admitted != attempt.get("verified_evidence"):
                raise CurieAcquisitionError("RECOVERY_ERROR", "semantic admission differs from attempt evidence")
            _validate_semantic_host_receipts(
                project, candidate_id=candidate_id, round_id=round_id,
                attempt_index=index, attempt=attempt, located=located,
                semantics=semantics, seed=seed,
            )
            admitted_ids = {item["evidence_id"] for item in admitted}
            for verification in semantics:
                if verification["evidence_id"] not in admitted_ids:
                    continue
                prior = all_semantics.setdefault(verification["evidence_id"], verification)
                if prior != verification:
                    raise CurieAcquisitionError("RECOVERY_ERROR", "semantic verification collision across attempts")
        if attempt.get("cumulative_verified_evidence_ids") != list(all_evidence):
            raise CurieAcquisitionError("RECOVERY_ERROR", "cumulative evidence IDs do not match attempts")
    if (manifest.get("query_plans") != [item["query_plan"] for item in attempts]
            or manifest.get("discovery_batches") != all_batches
            or manifest.get("coverage") != attempts[-1]["coverage_facts"]):
        raise CurieAcquisitionError("RECOVERY_ERROR", "v2 manifest cumulative facts do not match attempts")
    status = manifest.get("terminal_status")
    if status not in {"FROZEN", "INSUFFICIENT_STOP"}:
        raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition terminal status is invalid")
    if manifest.get("status") != status:
        raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition status fields disagree")
    if status == "FROZEN":
        evidence_pack = manifest.get("evidence_pack")
        checkpoint = manifest.get("checkpoint")
        if not isinstance(evidence_pack, dict) or not isinstance(checkpoint, dict):
            raise CurieAcquisitionError("RECOVERY_ERROR", "frozen v2 acquisition lacks checkpoint/pack")
        _verify_acquisition_reference(
            project, checkpoint.get("path"), checkpoint.get("sha256"),
            run_id, candidate_id,
        )
        expected_checkpoint = (project / "08_Audit" / "l05_acquisition"
                               / _safe_token(candidate_id, "candidate_id") / run_id
                               / "freeze_input.json").resolve()
        if (project / str(checkpoint.get("path"))).resolve() != expected_checkpoint:
            raise CurieAcquisitionError("RECOVERY_ERROR", "freeze checkpoint path mismatch")
        frozen_input = _read_object(expected_checkpoint)
        ready_pack = frozen_input.get("ready_pack")
        if (frozen_input.get("schema_version") != "L05EuropePmcFreezeInput/v1"
                or not isinstance(ready_pack, dict)
                or preview_frozen_evidence_pack(project, ready_pack) != evidence_pack
                or frozen_input.get("expected_evidence_pack") != evidence_pack
                or frozen_input.get("manifest") != {
                    key: value for key, value in manifest.items() if key != "checkpoint"
                }):
            raise CurieAcquisitionError("RECOVERY_ERROR", "freeze checkpoint input/provenance mismatch")
        pack = load_frozen_evidence_pack(
            project, evidence_pack, candidate_id=candidate_id,
            round_id=round_id, seed_sha256=seed_sha256,
        )
        if pack.get("source_run_id") != run_id or pack["version"] != 1:
            raise CurieAcquisitionError("RECOVERY_ERROR", "frozen pack acquisition provenance mismatch")
        if (pack["query_plans"] != manifest["query_plans"]
                or pack["discovery_receipts"] != all_batches
                or pack["selected_papers"] != list(all_papers.values())
                or pack["evidence"] != list(all_evidence.values())
                or pack["coverage"] != manifest["coverage"]):
            raise CurieAcquisitionError("RECOVERY_ERROR", "frozen pack content does not match v2 attempts")
        if all_semantics and pack.get("semantic_verifications") != list(all_semantics.values()):
            raise CurieAcquisitionError("RECOVERY_ERROR", "frozen pack semantic verification mismatch")
    elif manifest.get("evidence_pack") is not None:
        raise CurieAcquisitionError("RECOVERY_ERROR", "insufficient acquisition carries a frozen pack")
    elif manifest.get("terminal_reason") not in {"budget_exhausted", "no_admissible_replan"}:
        raise CurieAcquisitionError("RECOVERY_ERROR", "insufficient acquisition reason is invalid")
    planner_terminal = manifest.get("planner_terminal")
    if planner_terminal is not None:
        if (not isinstance(planner_terminal, dict)
                or planner_terminal.get("schema_version") != PLANNER_TERMINAL_SCHEMA_VERSION):
            raise CurieAcquisitionError("RECOVERY_ERROR", "terminal planner provenance is invalid")
        receipt = planner_terminal.get("receipt")
        terminal_proposal = _validated_planner_proposal(
            project, candidate_id, run_id, len(attempts) + 1,
            receipt, planner_terminal.get("proposal_sha256"), seed=seed,
            feedback=attempts[-1].get("planner_feedback"),
            expected_status="NO_ADMISSIBLE_REPLAN",
        )
        if (manifest.get("terminal_reason") != "no_admissible_replan"
                or planner_terminal.get("status") != "NO_ADMISSIBLE_REPLAN"
                or terminal_proposal.get("status") != "NO_ADMISSIBLE_REPLAN"
                or terminal_proposal.get("plan") is not None
                or terminal_proposal.get("reason") != planner_terminal.get("reason")):
            raise CurieAcquisitionError("RECOVERY_ERROR", "terminal planner proposal/receipt mismatch")


def _result_from_manifest(manifest: dict, relative: str, digest: str) -> dict:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "candidate_id": manifest["candidate_id"],
        "round_id": manifest["round_id"],
        "run_id": manifest["acquisition_run_id"],
        "status": manifest["terminal_status"],
        "terminal_reason": manifest.get("terminal_reason"),
        "coverage": manifest["coverage"],
        "evidence_pack": manifest.get("evidence_pack"),
        "acquisition_manifest_path": relative,
        "acquisition_manifest_sha256": digest,
    }


def validate_europepmc_acquisition_result(project_dir: str | Path,
                                          candidate_id: str, result: dict) -> dict:
    """Revalidate the exact v2 result at the CLI-to-runner use boundary."""
    if not isinstance(result, dict):
        raise CurieAcquisitionError("CONTRACT_ERROR", "acquisition result is not an object")
    project = Path(project_dir).resolve()
    seed = research_seed.load_l1_research_seed(project, candidate_id)
    run_id = _safe_token(result.get("run_id"), "acquisition run_id")
    relative = Path(str(result.get("acquisition_manifest_path") or ""))
    expected = (project / "08_Audit" / "l05_acquisition"
                / _safe_token(candidate_id, "candidate_id") / run_id
                / "acquisition_manifest.json").resolve()
    if relative.is_absolute() or (project / relative).resolve() != expected:
        raise CurieAcquisitionError("CONTRACT_ERROR", "acquisition manifest path/identity mismatch")
    raw = expected.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != result.get("acquisition_manifest_sha256"):
        raise CurieAcquisitionError("CONTRACT_ERROR", "acquisition manifest bytes/hash mismatch")
    manifest = _read_object(expected)
    _validate_acquisition_manifest(
        project, manifest, candidate_id=str(candidate_id),
        round_id=str(seed["round_id"]), seed_sha256=research_seed.seed_sha256(seed),
        run_id=run_id, seed=seed,
    )
    canonical = _result_from_manifest(manifest, relative.as_posix(), digest)
    if result != canonical:
        raise CurieAcquisitionError("CONTRACT_ERROR", "acquisition result differs from v2 manifest")
    return canonical


def _execute_europepmc_attempt(prepared: dict, project: Path, candidate_id: str,
                               http_get: Callable[[str, int], bytes] | None,
                               timeout: int) -> dict:
    seed = prepared["seed"]
    run_id = prepared["run_id"]
    selection = prepared["selection"]
    source_snapshots: list[dict] = []
    verified_evidence: list[dict] = []
    acquired_papers: list[dict] = []
    paper_failures: list[dict] = []
    reserve_promotions: list[dict] = []
    if selection["selected"]:
        retriever = EuropePmcEvidenceRetriever(
            project,
            candidate_id=candidate_id,
            run_id=run_id,
            http_get=http_get,
            timeout=timeout,
        )
        verifier = EuropePmcEvidenceVerifier(project, candidate_id=candidate_id)

        def retrieve_one(paper: dict) -> bool:
            paper_id = str(paper.get("paper_id"))
            pmcid = (paper.get("identifiers") or {}).get("pmcid")
            try:
                retrieval = retriever.retrieve(paper, seed=seed)
            except CurieContractError as exc:
                # Resource-vs-source classification owner for fullTextXML failures.
                # Source-level (DNS/connection/timeout/5xx-exhaustion/unknown 5xx) re-raises
                # verbatim (fail closed). Resource-level (404/410; or 500 w/ healthy control)
                # becomes a paper_failure so reserves can be promoted.
                classified = _classify_resource_failure(
                    failure=exc, pmcid=pmcid,
                    known_good_snapshots=source_snapshots,
                    retriever=retriever, seed=seed,
                )
                # Resource-level (404/410; 500 w/ healthy control) -> record + promote.
                # Source-level raises inside _classify_resource_failure (fail closed).
                paper_failures.append(classified)
                return False
            source_snapshots.append(retrieval["snapshot"])
            failure = retrieval.get("paper_failure")
            if failure is not None:
                if (
                    not isinstance(failure, dict)
                    or failure.get("paper_id") != paper_id
                    or failure.get("pmcid") != pmcid
                    or failure.get("reason_code") != "NO_TARGET_SECTIONS"
                ):
                    raise CurieContractError(
                        "Europe PMC retriever returned an invalid paper-level insufficiency"
                    )
                paper_failures.append({
                    "paper_id": failure["paper_id"],
                    "pmcid": failure["pmcid"],
                    "reason_code": failure["reason_code"],
                })
                return False
            verified_evidence.extend(
                verifier.verify(retrieval["snapshot"], retrieval["candidates"])
            )
            acquired_papers.append(paper)
            return True

        reserves = iter(_reserve_europepmc_papers(prepared["discovery"], selection))
        for paper in selection["selected"]:
            if retrieve_one(paper):
                continue
            while (reserve := next(reserves, None)) is not None:
                last_reason = paper_failures[-1]["reason_code"]
                promoted = _promote_reserve_after_failure(
                    reserve, str(paper.get("paper_id")),
                    reason=last_reason,
                )
                reserve_promotions.append({
                    "replaced_paper_id": paper.get("paper_id"),
                    "promoted_paper_id": promoted["paper_id"],
                    "promoted_pmcid": promoted["identifiers"].get("pmcid"),
                    "reason_code": f"PROMOTED_AFTER_{last_reason}",
                })
                if retrieve_one(promoted):
                    break
    return {
        "source_snapshots": source_snapshots,
        "verified_evidence": verified_evidence,
        "acquired_papers": acquired_papers,
        "paper_failures": paper_failures,
        "reserve_promotions": reserve_promotions,
    }


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
    plan_builder: Callable | None = None,
    semantic_assessor: Callable | None = None,
    semantic_assessor_id: str | None = None,
    execution_mode: str = "headless",
    _host_context: dict | None = None,
) -> dict:
    """Run the bounded first acquisition and publish one terminal v2 manifest."""
    if round_index != 1:
        raise CurieAcquisitionError("CONTRACT_ERROR", "first acquisition round_index must be 1")
    project = Path(project_dir)
    candidate_id = str(cand_id)
    try:
        seed = research_seed.load_l1_research_seed(project, candidate_id)
    except research_seed.ResearchSeedError as exc:
        raise CurieAcquisitionError("CONTRACT_ERROR", f"canonical ResearchSeed is invalid: {exc}") from exc
    seed_digest = research_seed.seed_sha256(seed)
    round_id = str(seed["round_id"])
    acquisition_run_id = _safe_token(
        run_id or f"EPMC_{seed_digest[:24]}", "acquisition_run_id"
    )
    _bind_acquisition_mode(project, candidate_id, round_id, acquisition_run_id, execution_mode)
    if execution_mode == "agent_native" and not isinstance(_host_context, dict):
        raise CurieAcquisitionError(
            "CONTRACT_ERROR", "agent-native acquisition must use the host checkpoint controller"
        )
    run_root = (project / "08_Audit" / "l05_acquisition"
                / _safe_token(candidate_id, "candidate_id") / acquisition_run_id)
    final_path = run_root / "acquisition_manifest.json"
    checkpoint_path = run_root / "freeze_input.json"
    host_checkpoint_path = run_root / "host_checkpoint.json"
    semantic_verifier = None
    model_spec = None
    if not final_path.exists() and not checkpoint_path.exists():
        if (not callable(semantic_assessor) or not isinstance(semantic_assessor_id, str)
                or not semantic_assessor_id.strip()):
            raise CurieAcquisitionError("MODEL_CONTRACT_ERROR", "ordinary Europe PMC requires a bound semantic assessor")
        semantic_verifier = SemanticEvidenceVerifier(
            assessor=semantic_assessor, assessor_id=semantic_assessor_id,
        )
        if plan_builder is None and explicit_queries is None:
            try:
                model_spec, _ = deep_research.load_runtime_spec(project)
                for valid, reason in (
                    deep_research.host_matches(model_spec),
                    deep_research.validate_spec_consistency(model_spec),
                    structured_execution.runtime_ready(model_spec),
                ):
                    if not valid:
                        raise CurieAcquisitionError("MODEL_CONFIG_ERROR", reason)
            except deep_research.DeepResearchError as exc:
                raise CurieAcquisitionError("MODEL_CONFIG_ERROR", str(exc)) from exc
    semantic_target = _paperqa2_semantic_target(seed)
    with _first_acquisition_writer(project, candidate_id, round_id):
        owner_path = (project / "08_Audit" / "l05_acquisition"
                      / _safe_token(candidate_id, "candidate_id")
                      / f"first_{_safe_token(round_id, 'round_id')}.json")
        owner = {
            "schema_version": "L05FirstAcquisitionOwner/v1",
            "candidate_id": candidate_id, "round_id": round_id,
            "seed_sha256": seed_digest, "acquisition_run_id": acquisition_run_id,
        }
        created_owner = not owner_path.exists()
        if created_owner:
            if initial_evidence_pack_path(project, candidate_id, round_id).exists():
                raise CurieAcquisitionError(
                    "RECOVERY_ERROR", "legacy frozen first pack lacks v2 recovery owner"
                )
            _write_immutable(owner_path, owner)
        elif _read_object(owner_path) != owner:
            raise CurieAcquisitionError(
                "RECOVERY_ERROR", "first acquisition owner conflicts with candidate/round/seed/run"
            )
        if final_path.exists():
            manifest = _read_object(final_path)
            try:
                _validate_acquisition_manifest(
                    project, manifest, candidate_id=candidate_id, round_id=round_id,
                    seed_sha256=seed_digest, run_id=acquisition_run_id,
                    seed=seed,
                )
            except CurieContractError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", str(exc)) from exc
            relative = final_path.relative_to(project).as_posix()
            return _result_from_manifest(
                manifest, relative, hashlib.sha256(final_path.read_bytes()).hexdigest()
            )
        if checkpoint_path.exists():
            checkpoint = _read_object(checkpoint_path)
            manifest = checkpoint.get("manifest")
            ready_pack = checkpoint.get("ready_pack")
            expected_pack = checkpoint.get("expected_evidence_pack")
            if not isinstance(manifest, dict) or not isinstance(ready_pack, dict) or not isinstance(expected_pack, dict):
                raise CurieAcquisitionError("RECOVERY_ERROR", "freeze checkpoint is incomplete")
            try:
                if preview_frozen_evidence_pack(project, ready_pack) != expected_pack:
                    raise CurieAcquisitionError(
                        "RECOVERY_ERROR", "freeze checkpoint canonical pack mismatch"
                    )
            except CurieContractError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", str(exc)) from exc
            if manifest.get("evidence_pack") != expected_pack:
                raise CurieAcquisitionError("RECOVERY_ERROR", "freeze checkpoint manifest/pack mismatch")
            manifest = dict(manifest)
            manifest["checkpoint"] = {
                "path": checkpoint_path.relative_to(project).as_posix(),
                "sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
            }
            try:
                _validate_acquisition_manifest(
                    project, manifest, candidate_id=candidate_id, round_id=round_id,
                    seed_sha256=seed_digest, run_id=acquisition_run_id,
                    seed=seed,
                )
            except CurieContractError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", str(exc)) from exc
            relative, digest = _write_audit_manifest(
                project, candidate_id=candidate_id,
                run_id=acquisition_run_id, payload=manifest,
            )
            return _result_from_manifest(manifest, relative, digest)
        host_resume = (
            execution_mode == "agent_native"
            and host_checkpoint_path.is_file()
        )
        if ((not created_owner and not host_resume)
                or (run_root.exists() and not host_resume)
                or initial_evidence_pack_path(project, candidate_id, round_id).exists()):
            raise CurieAcquisitionError(
                "RECOVERY_ERROR", "incomplete or conflicting first acquisition; preserved for inspection"
            )
        run_root.mkdir(parents=True, exist_ok=True)
        planner_terminal = None

        def production_plan_builder(seed, *, seed_sha256, round_index,
                                    explicit_queries, providers,
                                    reformulation_index, query_id_prefix,
                                    feedback=None):
            nonlocal planner_terminal
            planner_dir = run_root / f"planner_{reformulation_index + 1:03d}"
            try:
                decision = propose_scientific_query_plan(
                    seed, spec=model_spec, work_dir=planner_dir,
                    reformulation_index=reformulation_index, feedback=feedback,
                )
            except (structured_execution.StructuredExecutionError, CurieContractError) as exc:
                category = (exc.category if isinstance(exc, structured_execution.StructuredExecutionError)
                            else "MODEL_CONTRACT_ERROR")
                planner_dir.mkdir(parents=True, exist_ok=True)
                _write_immutable(planner_dir / "error.json", {
                    "category": category, "detail": str(exc),
                    "receipt": getattr(exc, "receipt", None),
                    "feedback_sha256": hashlib.sha256(_canonical_bytes(feedback)).hexdigest()
                    if feedback is not None else None,
                })
                raise CurieAcquisitionError(category, f"planner attempt {reformulation_index + 1}: {exc}") from exc
            if decision["status"] == "NO_ADMISSIBLE_REPLAN":
                planner_terminal = {
                    "schema_version": PLANNER_TERMINAL_SCHEMA_VERSION,
                    **{key: value for key, value in decision.items() if key != "plan"},
                }
                return None
            return build_multisource_query_plan(
                seed, seed_sha256=seed_sha256, round_index=round_index,
                explicit_queries=explicit_queries, providers=providers,
                reformulation_index=reformulation_index, query_id_prefix=query_id_prefix,
                scientific_plan=decision["plan"],
                planning_provenance={
                    "proposal_sha256": decision["proposal_sha256"],
                    "receipt": decision["receipt"],
                    "reason": decision["reason"],
                },
            )

        builder = plan_builder or (production_plan_builder if model_spec is not None else build_multisource_query_plan)
        attempts: list[dict] = []
        plans: list[dict] = []
        discovery_batches: list[dict] = []
        source_snapshots: list[dict] = []
        verified_evidence: list[dict] = []
        semantic_verifications: list[dict] = []
        acquired_papers: list[dict] = []
        paper_failures: list[dict] = []
        reserve_promotions: list[dict] = []
        seen_evidence: dict[str, dict] = {}
        seen_semantics: dict[str, dict] = {}
        seen_papers: set[str] = set()
        coverage = None
        terminal_reason = None
        feedback = None
        for attempt_index in range(1, 4):
            if attempt_index > 1 and explicit_queries is not None:
                terminal_reason = "no_admissible_replan"
                break
            prefix = f"{acquisition_run_id}_A{attempt_index}_Q"
            builder_args = dict(
                seed_sha256=seed_digest, round_index=1,
                explicit_queries=explicit_queries, providers=["europe-pmc"],
                reformulation_index=attempt_index - 1, query_id_prefix=prefix,
            )
            if feedback is not None:
                builder_args["feedback"] = feedback
            plan = builder(seed, **builder_args)
            if plan is None:
                terminal_reason = "no_admissible_replan"
                if isinstance(_host_context, dict):
                    checkpoint = _host_context["checkpoint"]
                    terminal = checkpoint.get("planner_terminal")
                    if (not isinstance(terminal, dict)
                            or terminal.get("schema_version") != PLANNER_TERMINAL_SCHEMA_VERSION
                            or terminal.get("status") != "NO_ADMISSIBLE_REPLAN"
                            or not isinstance(terminal.get("reason"), str)
                            or not terminal.get("reason")
                            or not isinstance(terminal.get("proposal_sha256"), str)
                            or not isinstance(terminal.get("receipt"), dict)):
                        raise CurieAcquisitionError(
                            "RECOVERY_ERROR", "host planner terminal provenance is missing or invalid"
                        )
                    planner_terminal = dict(terminal)
                break
            plan = validate_query_plan(plan, seed_sha256=seed_digest)
            planning = plan.get("planning")
            if isinstance(planning, dict) and planning.get("schema_version") == SCIENTIFIC_QUERY_PLAN_V2:
                validated_planning = validate_scientific_query_plan(planning, seed=seed)
                compiled = compile_scientific_query_plan(validated_planning, seed=seed)
                if (len(compiled) != len(plan["queries"]) or any(
                    item["query"] != compiled[index]["query"]
                    or item.get("query_content_hash") != compiled[index]["query_content_hash"]
                    for index, item in enumerate(plan["queries"])
                )):
                    raise CurieAcquisitionError("CONTRACT_ERROR", "generated QueryPlan differs from validated compiler output")
                if validated_planning["plan_content_hash"] in {
                    prior["planning"]["plan_content_hash"] for prior in plans
                    if isinstance(prior.get("planning"), dict)
                    and prior["planning"].get("schema_version") == SCIENTIFIC_QUERY_PLAN_V2
                }:
                    raise CurieAcquisitionError("CONTRACT_ERROR", "planner repeated generated plan content")
                executed_content = {
                    item.get("query_content_hash") for prior in plans for item in prior["queries"]
                }
                if any(item["query_content_hash"] in executed_content for item in plan["queries"]):
                    raise CurieAcquisitionError("CONTRACT_ERROR", "planner repeated generated query content")
            if plan["candidate_id"] != candidate_id or plan["round_id"] != round_id or plan["round_index"] != 1:
                raise CurieAcquisitionError("CONTRACT_ERROR", "planner returned a plan for another first acquisition")
            if any(plan["plan_id"] == old["plan_id"] for old in plans):
                raise CurieAcquisitionError("CONTRACT_ERROR", "planner repeated an executed plan")
            rendered_queries = tuple(
                query["query"].strip().casefold() for query in plan["queries"]
            )
            if any(rendered_queries == tuple(
                query["query"].strip().casefold() for query in old["queries"]
            ) for old in plans):
                raise CurieAcquisitionError(
                    "CONTRACT_ERROR", "planner repeated executed query content"
                )
            if {q["query_id"] for q in plan["queries"]} & {
                q["query_id"] for old in plans for q in old["queries"]
            }:
                raise CurieAcquisitionError("CONTRACT_ERROR", "planner repeated an executed query ID")
            plans.append(plan)
            http_requests: list[dict] = []
            underlying_get = http_get or _default_http_get

            def recorded_get(url: str, request_timeout: int) -> bytes:
                try:
                    response = underlying_get(url, request_timeout)
                except Exception as request_exc:
                    http_requests.append({
                        "url": url, "timeout": request_timeout,
                        "failure_type": type(request_exc).__name__,
                        "failure_detail": str(request_exc),
                    })
                    raise
                if not isinstance(response, (bytes, bytearray)):
                    raise CurieAcquisitionError(
                        "CONTRACT_ERROR", "Europe PMC HTTP response must be bytes"
                    )
                http_requests.append({
                    "url": url, "timeout": request_timeout,
                    "response_sha256": hashlib.sha256(response).hexdigest(),
                })
                return response

            attempt_path = run_root / f"attempt_{attempt_index:03d}.json"
            actual = None
            semantic_results: list[dict] = []
            try:
                prepared = _prepare_europepmc_acquisition(
                    project, candidate_id, explicit_queries=explicit_queries,
                    max_papers=max_papers, page_size=page_size,
                    run_id=f"{acquisition_run_id}_A{attempt_index}",
                    http_get=recorded_get, timeout=timeout, round_index=1,
                    prebuilt_query_plan=plan,
                )
                actual = _execute_europepmc_attempt(
                    prepared, project, candidate_id, recorded_get, timeout,
                )
                located = actual["verified_evidence"]
                for extract in located:
                    try:
                        cached_semantic = None
                        if isinstance(_host_context, dict):
                            cached_semantic = (_host_context.get("checkpoint", {})
                                               .get("semantic_verifications", {})
                                               .get(_semantic_checkpoint_key(
                                                   attempt_index, extract["evidence_id"]
                                               )))
                        if cached_semantic is not None:
                            cached_semantic = validate_semantic_verification(cached_semantic)
                            if (cached_semantic["extract_sha256"] != evidence_extract_sha256(extract)
                                    or cached_semantic["claim_sha256"] != hashlib.sha256(
                                        semantic_target.encode("utf-8")
                                    ).hexdigest()):
                                raise CurieAcquisitionError(
                                    "RECOVERY_ERROR", "cached semantic verification input hash changed"
                                )
                            semantic_results.append(cached_semantic)
                        else:
                            verification = semantic_verifier.verify(extract, claim=semantic_target)
                            semantic_results.append(verification)
                            if isinstance(_host_context, dict):
                                checkpoint = _host_context["checkpoint"]
                                provenance = checkpoint.get("semantic_host_receipts", {}).get(
                                    _semantic_checkpoint_key(
                                        attempt_index, extract["evidence_id"]
                                    )
                                )
                                if not isinstance(provenance, dict):
                                    raise CurieAcquisitionError(
                                        "RECOVERY_ERROR", "semantic verification lacks its host receipt"
                                    )
                                checkpoint.setdefault("semantic_verifications", {})[
                                    _semantic_checkpoint_key(
                                        attempt_index, extract["evidence_id"]
                                    )
                                ] = verification
                                checkpoint["phase"] = "VALIDATED"
                                _save_acquisition_checkpoint(host_checkpoint_path, checkpoint)
                    except CurieAcquisitionError:
                        raise
                    except CurieContractError as exc:
                        source_error = exc.__cause__
                        while source_error is not None and not isinstance(source_error, CurieAcquisitionError):
                            source_error = source_error.__cause__
                        category = (
                            source_error.category if isinstance(source_error, CurieAcquisitionError)
                            else "MODEL_EXECUTION_ERROR" if str(exc).startswith("semantic assessor failed:")
                            else "MODEL_CONTRACT_ERROR"
                        )
                        raise CurieAcquisitionError(category, str(exc)) from exc
                    except Exception as exc:
                        raise CurieAcquisitionError("MODEL_EXECUTION_ERROR", str(exc)) from exc
                admitted = admit_reasoning_evidence(located, semantic_results)
                admitted_ids = {item["evidence_id"] for item in admitted}
                actual["located_evidence"] = located
                actual["verified_evidence"] = admitted
                actual["semantic_verifications"] = semantic_results
                if isinstance(_host_context, dict):
                    host_receipts = _host_context["checkpoint"].get("semantic_host_receipts", {})
                    actual["semantic_host_receipts"] = [
                        host_receipts[_semantic_checkpoint_key(
                            attempt_index, item["evidence_id"]
                        )]
                        for item in semantic_results
                        if _semantic_checkpoint_key(
                            attempt_index, item["evidence_id"]
                        ) in host_receipts
                    ]
                actual["admitted_semantic_verifications"] = [
                    item for item in semantic_results if item["evidence_id"] in admitted_ids
                ]
            except CurieContractError as exc:
                root_exc = _root_cause(exc)
                if isinstance(root_exc, _AcquisitionHostPending):
                    raise root_exc
                failed_attempt = {
                    "attempt_index": attempt_index, "query_plan": plan,
                    "http_requests": http_requests,
                    "source_snapshots": actual["source_snapshots"] if actual else [],
                    "located_evidence": actual["verified_evidence"] if actual else [],
                    "semantic_verifications": semantic_results,
                    "terminal_status": "ERROR", "error_detail": str(exc),
                }
                failed_sha = _write_immutable(attempt_path, failed_attempt)
                attempts.append({
                    "artifact": {
                        "path": attempt_path.relative_to(project).as_posix(),
                        "sha256": failed_sha,
                    },
                })
                raise _typed_attempt_error(exc, attempts) from exc
            discovery_batches.extend(prepared["discovery_batches"])
            source_snapshots.extend(actual["source_snapshots"])
            paper_failures.extend(actual["paper_failures"])
            reserve_promotions.extend(actual["reserve_promotions"])
            for paper in actual["acquired_papers"]:
                if paper["paper_id"] not in seen_papers:
                    seen_papers.add(paper["paper_id"])
                    acquired_papers.append(paper)
            for evidence in actual["verified_evidence"]:
                key = evidence["evidence_id"]
                if key in seen_evidence:
                    if seen_evidence[key] != evidence:
                        raise CurieAcquisitionError("CONTRACT_ERROR", f"evidence ID collision: {key}")
                    continue
                seen_evidence[key] = evidence
                verified_evidence.append(evidence)
            for verification in actual["admitted_semantic_verifications"]:
                key = verification["evidence_id"]
                if key in seen_semantics:
                    if seen_semantics[key] != verification:
                        raise CurieAcquisitionError("CONTRACT_ERROR", f"semantic verification collision: {key}")
                    continue
                seen_semantics[key] = verification
                semantic_verifications.append(verification)
            coverage = _coverage_for(source_snapshots, verified_evidence, round_index=1)
            current_evidence_ids = {
                item["evidence_id"] for item in actual["verified_evidence"]
            }
            if coverage["verdict"] == "PASS":
                next_reason = None
            elif attempt_index == 3:
                next_reason = "budget_exhausted"
            elif explicit_queries is not None:
                next_reason = "no_admissible_replan"
            else:
                next_reason = "coverage_insufficient_replan"
            attempt = {
                "attempt_index": attempt_index,
                "query_plan": plan,
                "http_requests": http_requests,
                "transport_handshake": prepared["transport_handshake"],
                "discovery_batches": prepared["discovery_batches"],
                "discovery_outcome": {
                    "record_count": len(prepared["discovery"]["records"]),
                    "source_qualified_record_count": len(prepared["selection"]["selected"]),
                },
                "selection": prepared["selection"],
                "acquired_papers": actual["acquired_papers"],
                "source_snapshots": actual["source_snapshots"],
                "located_evidence": actual["located_evidence"],
                "semantic_verifications": actual["semantic_verifications"],
                **({"semantic_host_receipts": actual["semantic_host_receipts"]}
                   if isinstance(_host_context, dict) else {}),
                "paper_failures": actual["paper_failures"],
                "reserve_promotions": actual["reserve_promotions"],
                "verified_evidence_ids": [item["evidence_id"] for item in actual["verified_evidence"]],
                "verified_evidence": actual["verified_evidence"],
                "cumulative_verified_evidence_ids": [
                    item["evidence_id"] for item in verified_evidence
                ],
                "reused_evidence_ids": [
                    item["evidence_id"] for item in verified_evidence
                    if item["evidence_id"] not in current_evidence_ids
                ],
                "coverage_facts": coverage,
                "next_reason": next_reason,
            }
            feedback = {
                "previous_plan": plan.get("planning"),
                "previous_plan_id": plan["plan_id"],
                "executed_plans": [
                    {"plan_id": previous["plan_id"],
                     "plan_content_hash": (previous.get("planning") or {}).get("plan_content_hash"),
                     "attempt_index": index}
                    for index, previous in enumerate(plans, 1)
                ],
                "executed_queries": [
                    {"query_id": item["query_id"],
                     "query_content_hash": item.get("query_content_hash"),
                     "query": item["query"]}
                    for previous in plans for item in previous["queries"]
                ],
                "attempt_outcome": {
                    **attempt["discovery_outcome"],
                    "located_count": len(actual["located_evidence"]),
                    "semantic_admitted_count": len(actual["verified_evidence"]),
                    "semantic_rejected_count": len(actual["located_evidence"]) - len(actual["verified_evidence"]),
                    "type": (
                        "ZERO_DISCOVERY" if not prepared["discovery"]["records"] else
                        "NO_SOURCE_QUALIFIED_FULLTEXT" if not prepared["selection"]["selected"] else
                        "NO_LOCATED_EVIDENCE" if not actual["located_evidence"] else
                        "COVERAGE_GAP"
                    ),
                },
                "cumulative_admitted_evidence_ids": [item["evidence_id"] for item in verified_evidence],
                "validated_coverage_gaps": coverage["gaps"],
                "semantic_rejections": [
                    {"evidence_id": item["evidence_id"],
                     "entailment": item["entailment"], "reason": item["reason"],
                     "verification_id": item["verification_id"]}
                    for item in actual["semantic_verifications"]
                    if item["evidence_id"] not in current_evidence_ids
                ],
            }
            attempt["planner_feedback"] = feedback
            attempt_sha = _write_attempt_immutable(attempt_path, attempt)
            attempt["artifact"] = {
                "path": attempt_path.relative_to(project).as_posix(),
                "sha256": attempt_sha,
            }
            attempts.append(attempt)
            if coverage["verdict"] == "PASS":
                break
            if attempt_index == 3:
                terminal_reason = "budget_exhausted"
                break
        if coverage is None:
            raise CurieAcquisitionError("CONTRACT_ERROR", "planner produced no initial plan")
        frozen = coverage["verdict"] == "PASS"
        evidence_pack = None
        if frozen:
            pack = build_evidence_pack(
                candidate_id=candidate_id, round_id=round_id,
                seed_sha256=seed_digest, version=1, query_plans=plans,
                discovery_receipts=discovery_batches,
                selected_papers=acquired_papers, evidence=verified_evidence,
                coverage=coverage, gaps=coverage["gaps"],
                source_run_id=acquisition_run_id,
                semantic_verifications=semantic_verifications,
            )
            evidence_pack = preview_frozen_evidence_pack(project, pack)
        manifest = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "candidate_id": candidate_id, "round_id": round_id,
            "seed_sha256": seed_digest,
            "acquisition_run_id": acquisition_run_id,
            "run_id": acquisition_run_id,
            "target_pack_version": 1, "max_attempts": 3,
            "attempts": attempts,
            **({"planner_terminal": planner_terminal} if planner_terminal else {}),
            "query_plans": plans, "discovery_batches": discovery_batches,
            "selection": attempts[-1]["selection"],
            "source_snapshots": source_snapshots,
            "paper_failures": paper_failures,
            "reserve_promotions": reserve_promotions,
            "verified_evidence_ids": [item["evidence_id"] for item in verified_evidence],
            "coverage": coverage, "evidence_pack": evidence_pack,
            "terminal_status": "FROZEN" if frozen else "INSUFFICIENT_STOP",
            "terminal_reason": None if frozen else terminal_reason,
            "status": "FROZEN" if frozen else "INSUFFICIENT_STOP",
        }
        if frozen:
            checkpoint = {
                "schema_version": "L05EuropePmcFreezeInput/v1",
                "candidate_id": candidate_id, "round_id": round_id,
                "seed_sha256": seed_digest, "acquisition_run_id": acquisition_run_id,
                "ready_pack": pack, "expected_evidence_pack": evidence_pack,
                "manifest": manifest,
            }
            checkpoint_sha = _write_immutable(checkpoint_path, checkpoint)
            try:
                actual_manifest = freeze_evidence_pack(project, pack)
            except (CurieContractError, OSError) as exc:
                raise CurieAcquisitionError("PERSISTENCE_ERROR", str(exc)) from exc
            if actual_manifest != evidence_pack:
                raise CurieAcquisitionError("PERSISTENCE_ERROR", "frozen pack differs from pre-freeze checkpoint")
            manifest["checkpoint"] = {
                "path": checkpoint_path.relative_to(project).as_posix(),
                "sha256": checkpoint_sha,
            }
        _validate_acquisition_manifest(
            project, manifest, candidate_id=candidate_id, round_id=round_id,
            seed_sha256=seed_digest, run_id=acquisition_run_id,
            seed=seed,
        )
        try:
            relative, digest = _write_audit_manifest(
                project, candidate_id=candidate_id,
                run_id=acquisition_run_id, payload=manifest,
            )
        except (CurieContractError, OSError) as exc:
            raise CurieAcquisitionError("PERSISTENCE_ERROR", str(exc)) from exc
        return _result_from_manifest(manifest, relative, digest)


def _host_request(project: Path, *, candidate_id: str, round_id: str,
                  attempt_index: int, stage: str, persona: str,
                  inputs: dict, output_contract: dict) -> dict:
    from research_loop import host_handoff
    from research_loop.commands.ledger import _ledger_for

    ledger = _ledger_for(project)
    binding = ledger.require_activated_project(project)
    profile_id = ledger.project_profile(project)
    identity = {
        "project_id": str(binding["project_id"]),
        "candidate_id": candidate_id,
        "round_id": round_id,
        "node": "L0.5",
        "stage": stage,
        "attempt": attempt_index,
        "cursor": ledger.snapshot_candidate(project, candidate_id, round_id),
        "persona": persona,
        "profile_id": profile_id,
    }
    return host_handoff.prepare_request(
        project,
        kind=f"l05_{stage}",
        identity=identity,
        inputs=inputs,
        tools_policy=(
            _ACQUISITION_HOST_TOOLS_POLICY if stage == "planner"
            else _SEMANTIC_HOST_TOOLS_POLICY
        ),
        output_contract=output_contract,
    )


def _request_ref(request: dict, *, attempt_index: int, stage: str) -> dict:
    return {
        "request_id": request["request_id"],
        "request_path": request["request_path"],
        "request_sha256": request["request_sha256"],
        "attempt_index": attempt_index,
        "stage": stage,
    }


def _semantic_checkpoint_key(attempt_index: int, evidence_id: str) -> str:
    return f"{attempt_index}:{evidence_id}"


def _host_checkpoint(project: Path, candidate_id: str, round_id: str,
                     run_id: str, seed: dict) -> tuple[dict, Path]:
    paths = _acquisition_paths(project, candidate_id, round_id, run_id)
    _bind_acquisition_mode(project, candidate_id, round_id, run_id, "agent_native")
    seed_digest = research_seed.seed_sha256(seed)
    owner = {
        "schema_version": "L05FirstAcquisitionOwner/v1",
        "candidate_id": candidate_id, "round_id": round_id,
        "seed_sha256": seed_digest, "acquisition_run_id": run_id,
    }
    with _first_acquisition_writer(project, candidate_id, round_id):
        if paths["owner"].exists():
            if _read_object(paths["owner"]) != owner:
                raise CurieAcquisitionError("RECOVERY_ERROR", "first acquisition owner identity changed")
        else:
            if initial_evidence_pack_path(project, candidate_id, round_id).exists():
                raise CurieAcquisitionError("RECOVERY_ERROR", "legacy frozen first pack lacks a host checkpoint")
            _write_immutable(paths["owner"], owner)
        paths["run"].mkdir(parents=True, exist_ok=True)
        checkpoint_path = paths["checkpoint"]
        if checkpoint_path.exists():
            checkpoint = _load_acquisition_checkpoint(
                checkpoint_path, project=project, candidate_id=candidate_id,
                round_id=round_id, run_id=run_id, seed_sha256=seed_digest,
            )
            return checkpoint, checkpoint_path
        if any(paths["run"].iterdir()):
            raise CurieAcquisitionError(
                "RECOVERY_ERROR", "incomplete legacy acquisition artifacts lack a valid versioned checkpoint"
            )
        checkpoint = {
            "schema_version": ACQUISITION_CHECKPOINT_SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "round_id": round_id,
            "acquisition_run_id": run_id,
            "seed_sha256": seed_digest,
            "feedback_sha256": None,
            "source_sha256": None,
            "attempt_index": 1,
            "execution_mode": "agent_native",
            "phase": "REQUEST_PREPARED",
            "planner_requests": {},
            "planner_responses": {},
            "planner_reproposals": {},
            "semantic_requests": {},
            "semantic_responses": {},
            "semantic_verifications": {},
            "semantic_host_receipts": {},
            "http_responses": [],
            "external_state": None,
            "current_request_id": None,
            "committed_result": None,
        }
        _save_acquisition_checkpoint(checkpoint_path, checkpoint)
    return checkpoint, checkpoint_path


def _planner_request_for(project: Path, seed: dict, checkpoint: dict,
                         checkpoint_path: Path, *, attempt_index: int,
                         feedback: dict | None) -> dict:
    from research_loop import host_handoff

    key = str(attempt_index)
    expected_planner_request = prepare_scientific_query_plan_request(
        seed, reformulation_index=attempt_index - 1, feedback=feedback,
    )
    expected_feedback_hash = expected_planner_request["feedback_sha256"]
    existing = checkpoint["planner_requests"].get(key)
    if existing:
        request = host_handoff.load_request(project, existing["request_id"])
        request_inputs = request.get("inputs") or {}
        planner_request = request_inputs.get("planner_request")
        if (planner_request != expected_planner_request
                or request_inputs.get("feedback") != feedback
                or request_inputs.get("feedback_sha256") != expected_feedback_hash
                or (checkpoint.get("attempt_index") == attempt_index
                    and checkpoint.get("feedback_sha256") != expected_feedback_hash)):
            raise CurieAcquisitionError("RECOVERY_ERROR", "planner feedback differs from checkpoint")
        return request
    planner_request = expected_planner_request
    request = _host_request(
        project, candidate_id=str(seed["candidate_id"]),
        round_id=str(seed["round_id"]), attempt_index=attempt_index,
        stage="planner", persona="L05 Scientific Query Planner",
        inputs={
            "seed": seed,
            "seed_sha256": research_seed.seed_sha256(seed),
            "feedback": feedback,
            "feedback_sha256": expected_feedback_hash,
            "planner_request": planner_request,
        },
        output_contract={"type": "object", "schema": planner_request["schema"]},
    )
    checkpoint["planner_requests"][key] = _request_ref(
        request, attempt_index=attempt_index, stage="planner",
    )
    checkpoint["current_request_id"] = request["request_id"]
    checkpoint["attempt_index"] = attempt_index
    checkpoint["feedback_sha256"] = expected_feedback_hash
    checkpoint["phase"] = "REQUEST_PREPARED"
    _save_acquisition_checkpoint(checkpoint_path, checkpoint)
    return request


def _planner_reproposal_for(
    project: Path, seed: dict, checkpoint: dict, checkpoint_path: Path, *,
    attempt_index: int, base_request: dict, base_receipt: dict, decision: dict,
) -> tuple[dict, dict]:
    if (decision.get("status") != "REPROPOSAL_REQUIRED"
            or not isinstance(decision.get("candidates"), list)
            or not decision["candidates"]
            or not isinstance(decision.get("next_request"), dict)):
        raise CurieAcquisitionError("RECOVERY_ERROR", "planner reproposal decision is invalid")
    original_planner_request = (base_request.get("inputs") or {}).get("planner_request")
    if not isinstance(original_planner_request, dict):
        raise CurieAcquisitionError("RECOVERY_ERROR", "planner reproposal source request is missing")
    followup_planner_request = decision["next_request"]
    followup_attempt = attempt_index * 10 + 1
    inputs = dict(base_request["inputs"])
    inputs["planner_request"] = followup_planner_request
    request = _host_request(
        project, candidate_id=str(seed["candidate_id"]),
        round_id=str(seed["round_id"]), attempt_index=followup_attempt,
        stage="planner", persona="L05 Scientific Query Planner", inputs=inputs,
        output_contract={"type": "object", "schema": followup_planner_request["schema"]},
    )
    ref = _request_ref(request, attempt_index=followup_attempt, stage="planner")
    record = {
        "schema_version": PLANNER_REPROPOSAL_SCHEMA_VERSION,
        "acquisition_attempt_index": attempt_index,
        "proposal_index": 2,
        "source_request_id": base_request["request_id"],
        "source_request": {
            "request_id": base_request["request_id"],
            "request_path": base_request["request_path"],
            "request_sha256": base_request["request_sha256"],
        },
        "source_planner_request_sha256": original_planner_request["request_sha256"],
        "source_response_receipt": base_receipt,
        "source_proposal_sha256": decision["proposal_sha256"],
        "candidate_set_sha256": hashlib.sha256(
            _canonical_bytes(decision["candidates"])
        ).hexdigest(),
        "followup_request": ref,
        "followup_prompt_sha256": hashlib.sha256(
            followup_planner_request["prompt"].encode("utf-8")
        ).hexdigest(),
    }
    key = str(attempt_index)
    reproposals = checkpoint.setdefault("planner_reproposals", {})
    existing_record = reproposals.get(key)
    existing_ref = checkpoint["planner_requests"].get(f"{key}:reproposal")
    if ((existing_record is not None and existing_record != record)
            or (existing_ref is not None and existing_ref != ref)):
        raise CurieAcquisitionError("RECOVERY_ERROR", "planner reproposal changed on replay")
    checkpoint["planner_requests"][f"{key}:reproposal"] = ref
    reproposals[key] = record
    checkpoint["current_request_id"] = request["request_id"]
    checkpoint["attempt_index"] = attempt_index
    checkpoint["phase"] = "REQUEST_PREPARED"
    checkpoint["proposal_index"] = 2
    _save_acquisition_checkpoint(checkpoint_path, checkpoint)
    return request, ref


def _host_pending(project: Path, checkpoint: dict, checkpoint_path: Path) -> dict:
    from research_loop import host_handoff

    request_id = checkpoint.get("current_request_id")
    if not request_id:
        raise CurieAcquisitionError("RECOVERY_ERROR", "checkpoint has no active host request")
    request = host_handoff.load_request(project, str(request_id))
    relative = checkpoint_path.relative_to(project).as_posix()
    stage = str((request.get("identity") or {}).get("stage") or "")
    return {
        "kind": "needs_host",
        "request_id": request["request_id"],
        "request": request,
        "receipt_version": (
            PLANNER_HOST_RECEIPT_SCHEMA_VERSION
            if stage == "planner" else SEMANTIC_HOST_RECEIPT_SCHEMA_VERSION
        ),
        "checkpoint": dict(checkpoint),
        "checkpoint_path": relative,
    }


def prepare_acquisition_host_step(
    project_dir: str | Path, cand_id: str, *, run_id: str | None = None,
) -> dict:
    """Persist or return the next planner/semantic host request for L0.5."""
    project = Path(project_dir).resolve(strict=True)
    candidate_id = str(cand_id)
    try:
        seed = research_seed.load_l1_research_seed(project, candidate_id)
    except research_seed.ResearchSeedError as exc:
        raise CurieAcquisitionError("CONTRACT_ERROR", f"canonical ResearchSeed is invalid: {exc}") from exc
    round_id = str(seed["round_id"])
    normalized_run_id = _safe_token(
        run_id or f"EPMC_{research_seed.seed_sha256(seed)[:24]}", "acquisition_run_id"
    )
    checkpoint, checkpoint_path = _host_checkpoint(
        project, candidate_id, round_id, normalized_run_id, seed,
    )
    if checkpoint.get("external_state") == "uncertain_external_result":
        return {"kind": "blocked", "reason": "uncertain_external_result", "checkpoint": checkpoint}
    if checkpoint.get("phase") == "COMMITTED":
        return {"kind": "deterministic", "result": checkpoint.get("committed_result"),
                "checkpoint": checkpoint}
    if not checkpoint.get("current_request_id"):
        request = _planner_request_for(
            project, seed, checkpoint, checkpoint_path,
            attempt_index=int(checkpoint.get("attempt_index") or 1), feedback=None,
        )
        checkpoint = _load_acquisition_checkpoint(
            checkpoint_path, project=project, candidate_id=candidate_id,
            round_id=round_id, run_id=normalized_run_id,
            seed_sha256=research_seed.seed_sha256(seed),
        )
        checkpoint["current_request_id"] = request["request_id"]
        return _host_pending(project, checkpoint, checkpoint_path)
    if checkpoint.get("current_request_id") in checkpoint.get("planner_responses", {}) or checkpoint.get(
        "current_request_id"
    ) in checkpoint.get("semantic_responses", {}):
        return {"kind": "deterministic", "checkpoint": checkpoint}
    return _host_pending(project, checkpoint, checkpoint_path)


def submit_acquisition_host_response(
    project_dir: str | Path, cand_id: str, request_id: str,
    response_path: str | Path,
) -> dict:
    """Record one immutable response against the active L0.5 host request."""
    from research_loop import host_handoff

    project = Path(project_dir).resolve(strict=True)
    candidate_id = str(cand_id)
    seed = research_seed.load_l1_research_seed(project, candidate_id)
    round_id = str(seed["round_id"])
    # Resolve the unique active owner by the request's persisted identity, not a directory scan.
    try:
        request = host_handoff.load_request(project, str(request_id))
    except (ValueError, OSError) as exc:
        raise CurieAcquisitionError("CONTRACT_ERROR", f"host request rejected: {exc}") from exc
    identity = request["identity"]
    if identity.get("candidate_id") != candidate_id or identity.get("round_id") != round_id:
        raise CurieAcquisitionError("CONTRACT_ERROR", "host response candidate/round does not match request")
    acquisition_run_id = None
    audit_candidate = project / "08_Audit" / "l05_acquisition" / _safe_token(candidate_id, "candidate_id")
    owner_path = audit_candidate / f"first_{_safe_token(round_id, 'round_id')}.json"
    if not owner_path.is_file():
        raise CurieAcquisitionError("RECOVERY_ERROR", "host response has no active acquisition owner")
    owner = _read_object(owner_path)
    acquisition_run_id = str(owner.get("acquisition_run_id") or "")
    if not acquisition_run_id:
        raise CurieAcquisitionError("RECOVERY_ERROR", "active acquisition owner has no run ID")
    checkpoint, checkpoint_path = _host_checkpoint(
        project, candidate_id, round_id, acquisition_run_id, seed,
    )
    if checkpoint.get("current_request_id") != str(request_id):
        known = (str(request_id) in checkpoint.get("planner_responses", {})
                 or str(request_id) in checkpoint.get("semantic_responses", {}))
        if not known:
            raise CurieAcquisitionError("CONTRACT_ERROR", "host response does not match current acquisition request")
    stage = str(request.get("identity", {}).get("stage") or "")
    if stage == "semantic":
        try:
            raw = Path(response_path).read_bytes()
            answer = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CurieAcquisitionError("MODEL_CONTRACT_ERROR", f"semantic response is invalid: {exc}") from exc
        allowed = {"entailment", "scope_match", "context_preserved", "qualification_preserved", "reason"}
        if not isinstance(answer, dict) or set(answer) != allowed:
            raise CurieAcquisitionError("MODEL_CONTRACT_ERROR", "semantic host response must contain only assessor fields")
    elif stage.startswith("semantic:"):
        inputs = request.get("inputs") or {}
        extract = inputs.get("extract")
        if (not isinstance(extract, dict)
                or stage != f"semantic:{extract.get('evidence_id')}"
                or inputs.get("extract_sha256") != evidence_extract_sha256(extract)
                or inputs.get("claim_sha256") != hashlib.sha256(
                    str(inputs.get("claim") or "").encode("utf-8")
                ).hexdigest()
                or inputs.get("source_sha256") != (extract.get("retrieval") or {}).get("source_sha256")):
            raise CurieAcquisitionError("CONTRACT_ERROR", "semantic host request input hashes are invalid")
        try:
            raw = Path(response_path).read_bytes()
            answer = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CurieAcquisitionError("MODEL_CONTRACT_ERROR", f"semantic response is invalid: {exc}") from exc
        allowed = {"entailment", "scope_match", "context_preserved", "qualification_preserved", "reason"}
        if not isinstance(answer, dict) or set(answer) != allowed:
            raise CurieAcquisitionError("MODEL_CONTRACT_ERROR", "semantic host response must contain only assessor fields")
    elif stage == "planner":
        try:
            raw = Path(response_path).read_bytes()
            validate_scientific_query_plan_response(
                seed,
                request=request["inputs"]["planner_request"],
                raw_response=raw,
            )
        except (OSError, CurieContractError) as exc:
            raise CurieAcquisitionError(
                "MODEL_CONTRACT_ERROR", f"planner host response rejected: {exc}"
            ) from exc
    try:
        receipt = host_handoff.submit_response(
            project, str(request_id), response_path,
            expected_cursor=request["identity"]["cursor"],
        )
    except (ValueError, OSError) as exc:
        raise CurieAcquisitionError("CONTRACT_ERROR", f"host response rejected: {exc}") from exc
    table = (
        "planner_responses" if stage == "planner"
        else "semantic_responses" if stage.startswith("semantic:") else None
    )
    if table is None:
        raise CurieAcquisitionError("CONTRACT_ERROR", "host response stage is not an L0.5 stage")
    existing = checkpoint[table].get(str(request_id))
    if existing is not None and existing != receipt:
        raise CurieAcquisitionError("RECOVERY_ERROR", "same L0.5 request has a conflicting response receipt")
    if existing is not None:
        return existing
    checkpoint[table][str(request_id)] = receipt
    checkpoint["response_sha256"] = receipt["raw_response_sha256"]
    checkpoint["phase"] = "RESPONSE_RECORDED"
    checkpoint["current_request_id"] = str(request_id)
    _save_acquisition_checkpoint(checkpoint_path, checkpoint)
    return receipt


def continue_acquisition(
    project_dir: str | Path, cand_id: str, *, run_id: str | None = None,
) -> dict:
    """Resume the persisted L0.5 owner at its exact host or deterministic boundary."""
    from research_loop import host_handoff

    project = Path(project_dir).resolve(strict=True)
    candidate_id = str(cand_id)
    try:
        seed = research_seed.load_l1_research_seed(project, candidate_id)
    except research_seed.ResearchSeedError as exc:
        raise CurieAcquisitionError("CONTRACT_ERROR", f"canonical ResearchSeed is invalid: {exc}") from exc
    round_id = str(seed["round_id"])
    normalized_run_id = _safe_token(
        run_id or f"EPMC_{research_seed.seed_sha256(seed)[:24]}", "acquisition_run_id"
    )
    paths = _acquisition_paths(project, candidate_id, round_id, normalized_run_id)
    if not paths["checkpoint"].is_file():
        if paths["owner"].exists() or paths["run"].exists():
            raise CurieAcquisitionError("RECOVERY_ERROR", "incomplete acquisition lacks a versioned checkpoint")
        return prepare_acquisition_host_step(project, candidate_id, run_id=normalized_run_id)
    checkpoint = _load_acquisition_checkpoint(
        paths["checkpoint"], project=project, candidate_id=candidate_id,
        round_id=round_id, run_id=normalized_run_id,
        seed_sha256=research_seed.seed_sha256(seed),
    )
    if checkpoint.get("external_state") == "uncertain_external_result":
        return {"kind": "blocked", "reason": "uncertain_external_result", "checkpoint": checkpoint}
    if checkpoint.get("phase") == "COMMITTED":
        result = checkpoint.get("committed_result")
        if not isinstance(result, dict):
            raise CurieAcquisitionError("RECOVERY_ERROR", "committed acquisition result is missing")
        return result
    request_id = checkpoint.get("current_request_id")
    if not request_id:
        return prepare_acquisition_host_step(project, candidate_id, run_id=normalized_run_id)
    response_receipt = checkpoint.get("planner_responses", {}).get(str(request_id)) or checkpoint.get(
        "semantic_responses", {}
    ).get(str(request_id))
    if response_receipt is None:
        return _host_pending(project, checkpoint, paths["checkpoint"])

    # The terminal result has priority if a crash occurred after manifest publication.
    final_path = paths["run"] / "acquisition_manifest.json"
    if final_path.is_file():
        validated = validate_europepmc_acquisition_result(project, candidate_id, _result_from_manifest(
            _read_object(final_path), final_path.relative_to(project).as_posix(),
            hashlib.sha256(final_path.read_bytes()).hexdigest(),
        ))
        checkpoint["phase"] = "COMMITTED"
        checkpoint["committed_result"] = {"kind": validated["status"], **validated}
        _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
        return checkpoint["committed_result"]

    def planner_builder(active_seed, *, seed_sha256, round_index, explicit_queries,
                        providers, reformulation_index, query_id_prefix, feedback=None):
        from research_loop import host_handoff

        attempt_index = reformulation_index + 1
        active_attempt["index"] = attempt_index
        base_request = _planner_request_for(
            project, active_seed, checkpoint, paths["checkpoint"],
            attempt_index=attempt_index, feedback=feedback,
        )
        base_ref = checkpoint["planner_requests"][str(attempt_index)]
        followup_key = f"{attempt_index}:reproposal"
        followup_ref = checkpoint["planner_requests"].get(followup_key)
        if followup_ref is not None:
            base_receipt = checkpoint["planner_responses"].get(base_ref["request_id"])
            if not isinstance(base_receipt, dict):
                raise CurieAcquisitionError("RECOVERY_ERROR", "planner reproposal lacks its original response receipt")
            base_raw_path = Path(base_receipt["raw_response_path"]).resolve()
            try:
                base_raw_path.relative_to(project)
            except ValueError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", "planner reproposal source response escapes project") from exc
            base_raw = base_raw_path.read_bytes()
            if hashlib.sha256(base_raw).hexdigest() != base_receipt.get("raw_response_sha256"):
                raise CurieAcquisitionError("RECOVERY_ERROR", "planner reproposal source response changed")
            base_decision = validate_scientific_query_plan_response(
                active_seed, request=base_request["inputs"]["planner_request"],
                raw_response=base_raw,
            )
            request, expected_ref = _planner_reproposal_for(
                project, active_seed, checkpoint, paths["checkpoint"],
                attempt_index=attempt_index, base_request=base_request,
                base_receipt=base_receipt, decision=base_decision,
            )
            if expected_ref != followup_ref:
                raise CurieAcquisitionError("RECOVERY_ERROR", "planner reproposal request reference changed")
            planner_ref = followup_ref
        else:
            request = base_request
            planner_ref = base_ref
        planner_receipt = checkpoint["planner_responses"].get(planner_ref["request_id"])
        checkpoint["current_request_id"] = planner_ref["request_id"]
        if planner_receipt is None:
            checkpoint["phase"] = "REQUEST_PREPARED"
            _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
            raise _AcquisitionHostPending(_host_pending(project, checkpoint, paths["checkpoint"]))
        response_raw_path = Path(planner_receipt["raw_response_path"]).resolve()
        try:
            response_raw_path.relative_to(project)
        except ValueError as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", "planner response escapes project") from exc
        raw = response_raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != planner_receipt["raw_response_sha256"]:
            raise CurieAcquisitionError("RECOVERY_ERROR", "planner response bytes/hash changed")
        planner_request = request["inputs"]["planner_request"]
        decision = validate_scientific_query_plan_response(
            active_seed, request=planner_request, raw_response=raw,
        )
        checkpoint["phase"] = "VALIDATED"
        checkpoint["planner_feedback_sha256"] = planner_request["feedback_sha256"]
        _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
        if decision["status"] == "REPROPOSAL_REQUIRED":
            if followup_ref is not None:
                raise CurieAcquisitionError(
                    "MODEL_CONTRACT_ERROR", "planner reproposal budget exhausted with candidates remaining"
                )
            request, _ref = _planner_reproposal_for(
                project, active_seed, checkpoint, paths["checkpoint"],
                attempt_index=attempt_index, base_request=request,
                base_receipt=planner_receipt, decision=decision,
            )
            raise _AcquisitionHostPending(_host_pending(project, checkpoint, paths["checkpoint"]))
        if decision["status"] != "PLAN":
            if decision["status"] == "NO_ADMISSIBLE_REPLAN":
                terminal_receipt = {
                    "schema_version": PLANNER_HOST_RECEIPT_SCHEMA_VERSION,
                    "host_response_receipt": planner_receipt,
                    "planner_request_sha256": planner_request["request_sha256"],
                    "proposal_sha256": decision["proposal_sha256"],
                }
                terminal = {
                    "schema_version": PLANNER_TERMINAL_SCHEMA_VERSION,
                    "status": decision["status"],
                    "reason": decision["reason"],
                    "proposal_sha256": decision["proposal_sha256"],
                    "receipt": terminal_receipt,
                }
                prior_terminal = checkpoint.get("planner_terminal")
                if prior_terminal is not None and prior_terminal != terminal:
                    raise CurieAcquisitionError(
                        "RECOVERY_ERROR", "host planner terminal proposal changed on replay"
                    )
                checkpoint["planner_terminal"] = terminal
                _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
            elif decision["status"] != "PLAN":
                raise CurieAcquisitionError("MODEL_CONTRACT_ERROR", "host planner response is not admissible")
            return None
        host_planner_receipt = {
            "schema_version": PLANNER_HOST_RECEIPT_SCHEMA_VERSION,
            "host_response_receipt": planner_receipt,
            "planner_request_sha256": planner_request["request_sha256"],
            "proposal_sha256": decision["proposal_sha256"],
        }
        reproposal = checkpoint.get("planner_reproposals", {}).get(str(attempt_index))
        if reproposal is not None:
            host_planner_receipt["reproposal"] = reproposal
        return build_multisource_query_plan(
            active_seed, seed_sha256=seed_sha256, round_index=round_index,
            explicit_queries=explicit_queries, providers=providers,
            reformulation_index=reformulation_index, query_id_prefix=query_id_prefix,
            scientific_plan=decision["plan"],
            planning_provenance={
                "proposal_sha256": decision["proposal_sha256"],
                "receipt": host_planner_receipt,
                "reason": decision["reason"],
            },
        )

    active_attempt = {"index": 1}
    def semantic_assessor(*, extract, claim):
        extract_sha = evidence_extract_sha256(extract)
        claim_sha = hashlib.sha256(claim.encode("utf-8")).hexdigest()
        source_sha = str((extract.get("retrieval") or {}).get("source_sha256") or "")
        if not source_sha:
            raise CurieAcquisitionError("RECOVERY_ERROR", "LOCATED extract lacks a source snapshot hash")
        inputs = {
            "extract": extract, "extract_sha256": extract_sha,
            "claim": claim, "claim_sha256": claim_sha,
            "source_sha256": source_sha,
            "source_snapshot_path": (extract.get("retrieval") or {}).get("snapshot_path"),
        }
        semantic_stage = f"semantic:{extract['evidence_id']}"
        request = _host_request(
            project, candidate_id=candidate_id, round_id=round_id,
            attempt_index=int(active_attempt["index"]), stage=semantic_stage,
            persona="L05 Semantic Evidence Assessor", inputs=inputs,
            output_contract={"type": "object", "schema": {
                "entailment": "SUPPORTED | CONTRADICTED | AMBIGUOUS | UNRELATED",
                "scope_match": "boolean", "context_preserved": "boolean",
                "qualification_preserved": "boolean", "reason": "string",
            }},
        )
        ref = checkpoint["semantic_requests"].get(request["request_id"])
        if ref is None:
            ref = _request_ref(
                request, attempt_index=int(active_attempt["index"]), stage="semantic",
            )
            checkpoint["semantic_requests"][request["request_id"]] = ref
        checkpoint["source_sha256"] = source_sha
        checkpoint["current_request_id"] = request["request_id"]
        receipt = checkpoint["semantic_responses"].get(request["request_id"])
        if receipt is None:
            checkpoint["phase"] = "REQUEST_PREPARED"
            _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
            raise _AcquisitionHostPending(_host_pending(project, checkpoint, paths["checkpoint"]))
        request_ref = checkpoint["semantic_requests"][request["request_id"]]
        checkpoint.setdefault("semantic_host_receipts", {})[
            _semantic_checkpoint_key(int(active_attempt["index"]), extract["evidence_id"])
        ] = {
            "evidence_id": extract["evidence_id"],
            "host_request": {
                "request_id": request_ref["request_id"],
                "request_path": request_ref["request_path"],
                "request_sha256": request_ref["request_sha256"],
            },
            "host_response_receipt": receipt,
            "extract_sha256": extract_sha,
            "claim_sha256": claim_sha,
            "source_sha256": source_sha,
        }
        checkpoint["phase"] = "RESPONSE_RECORDED"
        _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
        raw_path = Path(receipt["raw_response_path"]).resolve()
        try:
            raw_path.relative_to(project)
        except ValueError as exc:
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic response escapes project") from exc
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt["raw_response_sha256"]:
            raise CurieAcquisitionError("RECOVERY_ERROR", "semantic response bytes/hash changed")
        try:
            answer = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CurieAcquisitionError("MODEL_CONTRACT_ERROR", f"semantic response is invalid: {exc}") from exc
        return answer

    http_cursor = {"index": 0}
    def replayable_http_get(url: str, timeout: int) -> bytes:
        index = http_cursor["index"]
        http_cursor["index"] += 1
        cached = checkpoint["http_responses"]
        if index < len(cached):
            item = cached[index]
            if item.get("url") != url or item.get("timeout") != timeout:
                raise CurieAcquisitionError("RECOVERY_ERROR", "replayed HTTP request differs from checkpoint")
            raw_path = Path(item["path"]).resolve()
            try:
                raw_path.relative_to(project)
            except ValueError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", "HTTP response path escapes project") from exc
            raw = raw_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
                raise CurieAcquisitionError("RECOVERY_ERROR", "HTTP response bytes/hash changed")
            return raw
        checkpoint["external_state"] = "HTTP_IN_FLIGHT"
        checkpoint["phase"] = "HTTP_IN_FLIGHT"
        _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
        try:
            raw = _default_http_get(url, timeout)
        except Exception as exc:
            checkpoint["external_state"] = "uncertain_external_result"
            checkpoint["phase"] = "uncertain_external_result"
            checkpoint["external_error"] = type(exc).__name__
            _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
            raise CurieAcquisitionError("SERVICE_ERROR", "uncertain_external_result") from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise CurieAcquisitionError("CONTRACT_ERROR", "Europe PMC HTTP response must be bytes")
        raw = bytes(raw)
        response_path = paths["run"] / "host_http" / f"response_{index + 1:04d}.raw"
        digest = hashlib.sha256(raw).hexdigest()
        _atomic_json(response_path.with_suffix(".json"), {
            "url": url, "timeout": timeout, "response_sha256": digest,
        }, immutable=True)
        if response_path.exists():
            if response_path.read_bytes() != raw:
                raise CurieAcquisitionError("RECOVERY_ERROR", "HTTP response artifact conflicts")
        else:
            response_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = response_path.with_suffix(".tmp")
            with temp_path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, response_path)
        checkpoint["http_responses"].append({
            "url": url, "timeout": timeout,
            "path": str(response_path), "sha256": digest,
        })
        checkpoint["external_state"] = None
        _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
        return raw

    try:
        result = run_europepmc_acquisition(
            project, candidate_id, run_id=normalized_run_id,
            plan_builder=planner_builder,
            semantic_assessor=semantic_assessor,
            semantic_assessor_id="l05-agent-native-host-assessor/v1",
            http_get=replayable_http_get,
            execution_mode="agent_native",
            _host_context={"checkpoint": checkpoint},
        )
    except _AcquisitionHostPending as pending:
        return pending.result
    except CurieAcquisitionError as exc:
        if "uncertain_external_result" in str(exc):
            checkpoint["external_state"] = "uncertain_external_result"
            checkpoint["phase"] = "uncertain_external_result"
            _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
            return {"kind": "blocked", "reason": "uncertain_external_result", "checkpoint": checkpoint}
        raise
    checkpoint["phase"] = "COMMITTED"
    checkpoint["current_request_id"] = None
    checkpoint["committed_result"] = {"kind": result["status"], **result}
    _save_acquisition_checkpoint(paths["checkpoint"], checkpoint)
    return checkpoint["committed_result"]


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
            paperqa_question = _paperqa2_retrieval_query(
                selected, seed, prepared["query_plan"]
            )
            result = paperqa_runtime.retrieve_and_verify(
                paper=paper,
                question=paperqa_question,
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
                "retrieval_query": paperqa_question,
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
