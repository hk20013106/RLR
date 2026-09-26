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

from research_loop import research_seed
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
from .semantic_verifier import SemanticEvidenceVerifier, admit_reasoning_evidence
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


def _typed_attempt_error(exc: CurieContractError, attempts: list[dict]) -> CurieAcquisitionError:
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


def _validate_acquisition_manifest(project: Path, manifest: dict, *,
                                   candidate_id: str, round_id: str,
                                   seed_sha256: str, run_id: str) -> None:
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
    all_evidence: dict[str, dict] = {}
    all_papers: dict[str, dict] = {}
    all_batches: list[dict] = []
    for index, attempt in enumerate(attempts, 1):
        if attempt.get("attempt_index") != index:
            raise CurieAcquisitionError("RECOVERY_ERROR", "v2 acquisition attempt indexes are not contiguous")
        plan = validate_query_plan(attempt.get("query_plan"), seed_sha256=seed_sha256)
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
        for paper in attempt.get("acquired_papers", []):
            all_papers.setdefault(paper["paper_id"], paper)
        for evidence in attempt.get("verified_evidence", []):
            evidence = validate_evidence_extract(evidence)
            previous = all_evidence.setdefault(evidence["evidence_id"], evidence)
            if previous != evidence:
                raise CurieAcquisitionError("RECOVERY_ERROR", "evidence ID collision across attempts")
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
    elif manifest.get("evidence_pack") is not None:
        raise CurieAcquisitionError("RECOVERY_ERROR", "insufficient acquisition carries a frozen pack")
    elif manifest.get("terminal_reason") not in {"budget_exhausted", "no_admissible_replan"}:
        raise CurieAcquisitionError("RECOVERY_ERROR", "insufficient acquisition reason is invalid")


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
        run_id=run_id,
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
    run_root = (project / "08_Audit" / "l05_acquisition"
                / _safe_token(candidate_id, "candidate_id") / acquisition_run_id)
    final_path = run_root / "acquisition_manifest.json"
    checkpoint_path = run_root / "freeze_input.json"
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
                )
            except CurieContractError as exc:
                raise CurieAcquisitionError("RECOVERY_ERROR", str(exc)) from exc
            relative, digest = _write_audit_manifest(
                project, candidate_id=candidate_id,
                run_id=acquisition_run_id, payload=manifest,
            )
            return _result_from_manifest(manifest, relative, digest)
        if not created_owner or run_root.exists() or initial_evidence_pack_path(
            project, candidate_id, round_id
        ).exists():
            raise CurieAcquisitionError(
                "RECOVERY_ERROR", "incomplete or conflicting first acquisition; preserved for inspection"
            )
        run_root.mkdir(parents=True)
        builder = plan_builder or build_multisource_query_plan
        attempts: list[dict] = []
        plans: list[dict] = []
        discovery_batches: list[dict] = []
        source_snapshots: list[dict] = []
        verified_evidence: list[dict] = []
        acquired_papers: list[dict] = []
        paper_failures: list[dict] = []
        reserve_promotions: list[dict] = []
        seen_evidence: dict[str, dict] = {}
        seen_papers: set[str] = set()
        coverage = None
        terminal_reason = None
        for attempt_index in range(1, 4):
            if attempt_index > 1 and (explicit_queries is not None or
                                      (plan_builder is None and attempt_index > 2)):
                terminal_reason = "no_admissible_replan"
                break
            prefix = f"{acquisition_run_id}_A{attempt_index}_Q"
            plan = builder(
                seed, seed_sha256=seed_digest, round_index=1,
                explicit_queries=explicit_queries, providers=["europe-pmc"],
                reformulation_index=attempt_index - 1, query_id_prefix=prefix,
            )
            if plan is None:
                terminal_reason = "no_admissible_replan"
                break
            plan = validate_query_plan(plan, seed_sha256=seed_digest)
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
            except CurieContractError as exc:
                failed_attempt = {
                    "attempt_index": attempt_index, "query_plan": plan,
                    "http_requests": http_requests,
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
            coverage = _coverage_for(source_snapshots, verified_evidence, round_index=1)
            current_evidence_ids = {
                item["evidence_id"] for item in actual["verified_evidence"]
            }
            if coverage["verdict"] == "PASS":
                next_reason = None
            elif attempt_index == 3:
                next_reason = "budget_exhausted"
            elif explicit_queries is not None or (plan_builder is None and attempt_index == 2):
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
            attempt_sha = _write_immutable(attempt_path, attempt)
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
        )
        try:
            relative, digest = _write_audit_manifest(
                project, candidate_id=candidate_id,
                run_id=acquisition_run_id, payload=manifest,
            )
        except (CurieContractError, OSError) as exc:
            raise CurieAcquisitionError("PERSISTENCE_ERROR", str(exc)) from exc
        return _result_from_manifest(manifest, relative, digest)


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
