"""Canonical full-text retrieval for selected literature records.

Europe PMC remains the preferred exact JATS source when a PMCID is available.
The fetchpdf Python API is the DOI/PMID fallback: it first performs a strict
XML-only pass, then uses the existing structured/PDF strategy if no XML is
available. Retrieval and evidence admission remain separate: fetched PDF/HTML
artifacts are preserved and hash-bound, but only JATS XML is currently
converted into LOCATED evidence.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Callable

from research_loop.l05_curie import europepmc, multisource
from research_loop.l05_curie.contracts import CurieContractError


FETCHPDF_SNAPSHOT_SCHEMA_VERSION = "FullTextSourceSnapshot/v1"
_FETCHPDF_ENGINE = "fetchpdf-python-api/v1"
_FETCHPDF_VERIFIER = "fetchpdf-jats-source-relocator/v1"
_TARGET_SECTION_WORDS = ("result", "discussion", "conclusion")
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")
_STAGE_ROOTS = {
    "l05": Path("09_Literature_Database") / "source_snapshots" / "l05",
    "l85": Path("09_Literature_Database") / "source_snapshots" / "l85",
}


class _FetchPdfPassUnavailable(CurieContractError):
    """A retrieval pass found no usable artifact and may safely fall back."""


def _safe_token(value: object, name: str) -> str:
    token = _SAFE_TOKEN.sub("_", str(value or "")).strip("_.")
    if not token:
        raise CurieContractError(f"{name} cannot be normalized to a safe token")
    return token


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_type(path: Path) -> str:
    name = path.name.casefold()
    if name.endswith((".xml", ".nxml")):
        return "application/xml"
    if name.endswith((".fulltext.html", ".html", ".htm")):
        return "text/html"
    if name.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


def _artifact_kind(path: Path) -> str:
    content_type = _content_type(path)
    if content_type == "application/xml":
        return "xml"
    if content_type == "text/html":
        return "html"
    if content_type == "application/pdf":
        return "pdf"
    return "other"


def _normalized_identifiers(paper: dict) -> dict:
    identifiers = paper.get("identifiers")
    identifiers = identifiers if isinstance(identifiers, dict) else {}
    normalized = {}
    for key, normalizer in (
        ("doi", multisource.normalize_doi),
        ("pmid", multisource.normalize_pmid),
        ("pmcid", multisource.normalize_pmcid),
    ):
        value = normalizer(identifiers.get(key))
        if value:
            normalized[key] = value
    return normalized


def has_retrievable_identifier(paper: dict) -> tuple[bool, str]:
    """Admit only identities supported by Europe PMC or fetchpdf."""
    identifiers = _normalized_identifiers(paper if isinstance(paper, dict) else {})
    if any(identifiers.get(key) for key in ("pmcid", "doi", "pmid")):
        return True, "RETRIEVABLE_IDENTIFIER"
    return False, "NO_RETRIEVABLE_IDENTIFIER"


def _fetchpdf_callable(fetch_pdf_fn: Callable | None) -> tuple[Callable, str]:
    if fetch_pdf_fn is not None:
        if not callable(fetch_pdf_fn):
            raise CurieContractError("fetchpdf override must be callable")
        return fetch_pdf_fn, "injected"
    try:
        # fetchpdf prints configuration guidance at import time. Redirect it so
        # a Windows GBK console cannot turn an optional warning into an import
        # failure; retrieval errors still propagate through the API call below.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import fetchpdf
    except Exception as exc:
        raise CurieContractError(f"fetchpdf Python API is unavailable: {exc}") from exc
    fetch_pdf = getattr(fetchpdf, "fetch_pdf", None)
    if not callable(fetch_pdf):
        raise CurieContractError("fetchpdf package does not export callable fetch_pdf")
    return fetch_pdf, str(getattr(fetchpdf, "__version__", "unknown"))


def _fetchpdf_artifacts(stem: Path, returned: object) -> list[Path]:
    candidates = [
        stem.with_suffix(".xml"),
        stem.with_suffix(".nxml"),
        Path(str(stem) + ".fulltext.html"),
        stem.with_suffix(".html"),
        stem.with_suffix(".pdf"),
    ]
    if returned:
        candidates.append(Path(str(returned)))
    found = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        marker = str(resolved).casefold()
        if marker in seen or not resolved.is_file():
            continue
        if _artifact_kind(resolved) == "other" or resolved.stat().st_size <= 0:
            continue
        seen.add(marker)
        found.append(resolved)
    order = {"xml": 0, "html": 1, "pdf": 2}
    return sorted(found, key=lambda path: (order.get(_artifact_kind(path), 9), path.name))


def _run_fetchpdf_pass(
    *,
    paper_root: Path,
    paper_id: str,
    identifier: str,
    phase: str,
    fetch_pdf: Callable,
    fetch_kwargs: dict,
) -> tuple[list[Path], Path]:
    phase_dir = (paper_root / phase).resolve()
    try:
        phase_dir.relative_to(paper_root)
    except ValueError as exc:
        raise CurieContractError(
            "fetchpdf output directory escapes the project"
        ) from exc
    phase_dir.mkdir(parents=True, exist_ok=True)
    stem = phase_dir / paper_id
    save_path = stem.with_suffix(".pdf")
    try:
        returned = fetch_pdf(identifier, str(save_path), **fetch_kwargs)
    except Exception as exc:
        raise _FetchPdfPassUnavailable(
            f"fetchpdf {phase} retrieval failed: {exc}"
        ) from exc

    artifacts = _fetchpdf_artifacts(stem, returned)
    if not artifacts:
        raise _FetchPdfPassUnavailable(
            f"fetchpdf {phase} retrieval returned no validated PDF/XML/HTML artifact"
        )
    for artifact in artifacts:
        try:
            artifact.relative_to(phase_dir)
        except ValueError as exc:
            raise CurieContractError(
                "fetchpdf artifact escaped its candidate/run directory"
            ) from exc
    provenance = stem.with_suffix(".provenance.json")
    if not provenance.is_file():
        raise CurieContractError("fetchpdf did not write the required provenance sidecar")
    return artifacts, provenance


def _validate_fetchpdf_pass(
    project: Path,
    *,
    artifacts: list[Path],
    provenance: Path,
    identifier: str,
) -> list[dict]:
    try:
        provenance_value = json.loads(provenance.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurieContractError("fetchpdf provenance sidecar is unreadable") from exc
    if not isinstance(provenance_value, dict):
        raise CurieContractError("fetchpdf provenance sidecar must contain an object")
    resolved_identifiers = provenance_value.get("identifiers_resolved")
    resolved_identifiers = (
        resolved_identifiers if isinstance(resolved_identifiers, dict) else {}
    )
    provenance_identifier = str(provenance_value.get("identifier") or "").strip()
    normalized_provenance_ids = {
        value
        for value in (
            multisource.normalize_doi(provenance_identifier),
            multisource.normalize_pmid(provenance_identifier),
            multisource.normalize_doi(resolved_identifiers.get("doi")),
            multisource.normalize_pmid(resolved_identifiers.get("pmid")),
        )
        if value
    }
    if identifier not in normalized_provenance_ids:
        raise CurieContractError(
            "fetchpdf provenance does not bind the requested DOI or PMID"
        )
    accepted = provenance_value.get("artifacts")
    if not isinstance(accepted, list) or not accepted:
        raise CurieContractError("fetchpdf provenance sidecar records no accepted artifact")
    accepted_by_path = {
        str(item.get("path") or ""): item
        for item in accepted
        if isinstance(item, dict) and str(item.get("path") or "")
    }

    artifact_records = [
        {
            "artifact_path": path.relative_to(project).as_posix(),
            "artifact_sha256": _sha256(path),
            "content_type": _content_type(path),
            "artifact_kind": _artifact_kind(path),
            "byte_length": path.stat().st_size,
        }
        for path in artifacts
    ]
    for record in artifact_records:
        provenance_artifact = accepted_by_path.get(Path(record["artifact_path"]).name)
        if provenance_artifact is None:
            raise CurieContractError(
                "fetchpdf provenance does not bind every retained artifact"
            )
        recorded_hash = str(provenance_artifact.get("content_hash") or "")
        if recorded_hash.removeprefix("sha256:") != record["artifact_sha256"]:
            raise CurieContractError("fetchpdf provenance artifact hash does not match its bytes")
    return artifact_records


def _fetchpdf_snapshot(
    project: Path,
    *,
    candidate_id: str,
    run_id: str,
    paper: dict,
    stage: str,
    fetch_pdf_fn: Callable | None,
) -> tuple[dict, bytes, str]:
    identifiers = _normalized_identifiers(paper)
    if not identifiers.get("doi") and not identifiers.get("pmid"):
        raise CurieContractError("fetchpdf full-text retrieval requires a DOI or PMID")
    if stage not in _STAGE_ROOTS:
        raise CurieContractError(f"unsupported full-text retrieval stage {stage!r}")

    paper_id = _safe_token(paper.get("paper_id"), "paper_id")
    relative_dir = (
        _STAGE_ROOTS[stage]
        / _safe_token(candidate_id, "candidate_id")
        / _safe_token(run_id, "run_id")
        / paper_id
    )
    output_dir = (project / relative_dir).resolve()
    try:
        output_dir.relative_to(project.resolve())
    except ValueError as exc:
        raise CurieContractError(
            "fetchpdf output directory escapes the project"
        ) from exc
    output_dir.mkdir(parents=True, exist_ok=True)

    fetch_pdf, version = _fetchpdf_callable(fetch_pdf_fn)
    passes = (
        (
            "xml",
            identifiers.get("pmid") or identifiers.get("doi"),
            {
                "allow_xml_fallback": False,
                "xml_only": True,
                "get_xml_or_html": False,
                "target_task": "extraction",
                "want_provenance": True,
                "verbose": False,
            },
        ),
        (
            "fallback",
            identifiers.get("doi") or identifiers.get("pmid"),
            {
                "allow_xml_fallback": True,
                "xml_only": False,
                "get_xml_or_html": True,
                "target_task": "extraction",
                "want_provenance": True,
                "verbose": False,
            },
        ),
    )
    failures = []
    for phase, identifier, fetch_kwargs in passes:
        try:
            artifacts, provenance = _run_fetchpdf_pass(
                paper_root=output_dir,
                paper_id=paper_id,
                identifier=str(identifier),
                phase=phase,
                fetch_pdf=fetch_pdf,
                fetch_kwargs=fetch_kwargs,
            )
            if phase == "xml" and any(
                _artifact_kind(artifact) != "xml" for artifact in artifacts
            ):
                raise CurieContractError(
                    "fetchpdf strict XML retrieval returned a non-XML artifact"
                )
            artifact_records = _validate_fetchpdf_pass(
                project,
                artifacts=artifacts,
                provenance=provenance,
                identifier=str(identifier),
            )
        except _FetchPdfPassUnavailable as exc:
            failures.append(f"{phase}: {exc}")
            continue

        primary = artifacts[0]
        snapshot = {
            "schema_version": FETCHPDF_SNAPSHOT_SCHEMA_VERSION,
            "provider": "fetchpdf",
            "retrieval_engine": _FETCHPDF_ENGINE,
            "retrieval_version": version,
            "candidate_id": _safe_token(candidate_id, "candidate_id"),
            "run_id": _safe_token(run_id, "run_id"),
            "stage": stage,
            "paper_id": paper_id,
            "identifiers": identifiers,
            "artifact_path": primary.relative_to(project).as_posix(),
            "artifact_sha256": _sha256(primary),
            "content_type": _content_type(primary),
            "artifact_kind": _artifact_kind(primary),
            "artifacts": artifact_records,
            "provenance_path": provenance.relative_to(project).as_posix(),
            "provenance_sha256": _sha256(provenance),
        }
        return snapshot, primary.read_bytes(), str(identifier)

    raise CurieContractError(
        "fetchpdf full-text retrieval failed across strict XML and fallback passes: "
        + "; ".join(failures)
    )


def _fetchpdf_candidates(snapshot: dict, raw: bytes, identifier: str) -> list[dict]:
    if snapshot.get("artifact_kind") != "xml":
        return []
    try:
        paragraphs = europepmc.parse_jats_paragraphs(raw)
    except CurieContractError:
        return []
    targets = [
        item
        for item in paragraphs
        if any(word in str(item.get("section") or "").casefold()
               for word in _TARGET_SECTION_WORDS)
    ]
    digest = str(snapshot["artifact_sha256"])
    candidates = []
    for item in targets:
        identity = json.dumps(
            {
                "paper_id": snapshot["paper_id"],
                "locator": item["locator"],
                "text": item["text"],
                "source_sha256": digest,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        candidates.append({
            "schema_version": europepmc.EVIDENCE_CANDIDATE_SCHEMA_VERSION,
            "candidate_extract_id": "EC_" + hashlib.sha256(identity).hexdigest()[:20],
            "paper_id": snapshot["paper_id"],
            "section": item["section"],
            "text": item["text"],
            "locator": item["locator"],
            "role": "CONTEXT",
            "verification_status": "UNVERIFIED",
            "retrieval": {
                "engine": _FETCHPDF_ENGINE,
                "source_sha256": digest,
                "snapshot_path": snapshot["artifact_path"],
                "identifier": identifier,
            },
        })
    return candidates


def _verify_fetchpdf_jats(
    project: Path,
    *,
    candidate_id: str,
    snapshot: dict,
    candidates: list[dict],
) -> list[dict]:
    if snapshot.get("schema_version") != FETCHPDF_SNAPSHOT_SCHEMA_VERSION:
        raise CurieContractError("fetchpdf source snapshot schema_version is invalid")
    if snapshot.get("provider") != "fetchpdf":
        raise CurieContractError("fetchpdf source snapshot provider is invalid")
    if snapshot.get("candidate_id") != _safe_token(candidate_id, "candidate_id"):
        raise CurieContractError("fetchpdf source snapshot candidate_id mismatch")
    relative = Path(str(snapshot.get("artifact_path") or ""))
    if relative.is_absolute():
        raise CurieContractError("fetchpdf source snapshot path must be relative")
    source = (project / relative).resolve()
    stage = str(snapshot.get("stage") or "")
    if stage not in _STAGE_ROOTS:
        raise CurieContractError("fetchpdf source snapshot stage is invalid")
    expected_root = (
        project
        / _STAGE_ROOTS[stage]
        / _safe_token(candidate_id, "candidate_id")
        / _safe_token(snapshot.get("run_id"), "run_id")
        / _safe_token(snapshot.get("paper_id"), "paper_id")
    ).resolve()
    try:
        source.relative_to(expected_root)
    except ValueError as exc:
        raise CurieContractError(
            "fetchpdf source snapshot path escapes its candidate/run/paper root"
        ) from exc
    if not source.is_file():
        raise CurieContractError("fetchpdf source snapshot file is missing")
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != snapshot.get("artifact_sha256"):
        raise CurieContractError("fetchpdf source snapshot SHA-256 does not match its bytes")
    return europepmc.verify_jats_candidates(
        raw,
        candidates,
        paper_id=str(snapshot.get("paper_id") or ""),
        retrieval_base={
            "engine": _FETCHPDF_VERIFIER,
            "source_sha256": digest,
            "snapshot_path": relative.as_posix(),
            "provider": "fetchpdf",
            "verifier": _FETCHPDF_VERIFIER,
        },
    )


def retrieve_selected_fulltext(
    project_dir: str | Path,
    *,
    candidate_id: str,
    run_id: str,
    paper: dict,
    seed: dict,
    stage: str,
    timeout: int = 20,
    http_get: Callable[[str, int], bytes] | None = None,
    fetch_pdf_fn: Callable | None = None,
) -> dict:
    """Retrieve one selected paper, preferring Europe PMC and falling back to fetchpdf."""
    project = Path(project_dir).resolve()
    if not isinstance(paper, dict):
        raise CurieContractError("selected full-text paper must be an object")
    paper_id = _safe_token(paper.get("paper_id"), "paper_id")
    identifiers = _normalized_identifiers(paper)
    attempts = []
    snapshots = []

    pmcid = identifiers.get("pmcid")
    europepmc_result = None
    if pmcid:
        try:
            retrieval = europepmc.EuropePmcEvidenceRetriever(
                project,
                candidate_id=candidate_id,
                run_id=run_id,
                http_get=http_get,
                timeout=timeout,
            ).retrieve(
                {**paper, "identifiers": {**(paper.get("identifiers") or {}), "pmcid": pmcid}},
                seed=seed,
            )
            failure = retrieval.get("paper_failure")
            snapshots.append(retrieval["snapshot"])
            attempts.append({
                "paper_id": paper_id,
                "provider": "europe-pmc",
                "status": "retrieved_no_target_sections" if failure else "retrieved",
                "artifact_path": retrieval["snapshot"]["artifact_path"],
                "artifact_sha256": retrieval["snapshot"]["artifact_sha256"],
            })
            if failure is None:
                located = europepmc.EuropePmcEvidenceVerifier(
                    project, candidate_id=candidate_id
                ).verify(retrieval["snapshot"], retrieval["candidates"])
                return {
                    "snapshot": retrieval["snapshot"],
                    "candidates": retrieval["candidates"],
                    "located": located,
                    "paper_failure": None,
                    "attempts": attempts,
                    "snapshots": snapshots,
                }
            europepmc_result = retrieval
        except CurieContractError as exc:
            attempts.append({
                "paper_id": paper_id,
                "provider": "europe-pmc",
                "status": "failed",
                "reason": str(exc),
            })

    if identifiers.get("doi") or identifiers.get("pmid"):
        try:
            snapshot, raw, identifier = _fetchpdf_snapshot(
                project,
                candidate_id=candidate_id,
                run_id=run_id,
                paper=paper,
                stage=stage,
                fetch_pdf_fn=fetch_pdf_fn,
            )
            snapshots.append(snapshot)
            candidates = _fetchpdf_candidates(snapshot, raw, identifier)
            located = (
                _verify_fetchpdf_jats(
                    project,
                    candidate_id=candidate_id,
                    snapshot=snapshot,
                    candidates=candidates,
                )
                if candidates else []
            )
            attempts.append({
                "paper_id": paper_id,
                "provider": "fetchpdf",
                "status": "retrieved",
                "artifact_path": snapshot["artifact_path"],
                "artifact_sha256": snapshot["artifact_sha256"],
                "artifact_kind": snapshot["artifact_kind"],
            })
            failure = None
            if not located:
                failure = {
                    "paper_id": paper_id,
                    "provider": "fetchpdf",
                    "reason_code": (
                        "NO_TARGET_SECTIONS"
                        if snapshot["artifact_kind"] == "xml"
                        else "NO_LOCATABLE_EVIDENCE"
                    ),
                    "reason": (
                        "retrieved XML has no Results, Discussion, or Conclusion paragraphs"
                        if snapshot["artifact_kind"] == "xml"
                        else f"retrieved {snapshot['artifact_kind']} full text has no canonical locator adapter"
                    ),
                }
            return {
                "snapshot": snapshot,
                "candidates": candidates,
                "located": located,
                "paper_failure": failure,
                "attempts": attempts,
                "snapshots": snapshots,
            }
        except CurieContractError as exc:
            attempts.append({
                "paper_id": paper_id,
                "provider": "fetchpdf",
                "status": "failed",
                "reason": str(exc),
            })

    if europepmc_result is not None:
        return {
            "snapshot": europepmc_result["snapshot"],
            "candidates": europepmc_result["candidates"],
            "located": [],
            "paper_failure": europepmc_result["paper_failure"],
            "attempts": attempts,
            "snapshots": snapshots,
        }
    reason = (
        "no DOI or PMID is available for fetchpdf fallback"
        if not identifiers.get("doi") and not identifiers.get("pmid")
        else "all configured full-text providers failed"
    )
    return {
        "snapshot": None,
        "candidates": [],
        "located": [],
        "paper_failure": {
            "paper_id": paper_id,
            "provider": "fulltext-retrieval",
            "reason_code": "FULLTEXT_UNAVAILABLE",
            "reason": reason,
        },
        "attempts": attempts,
        "snapshots": snapshots,
    }
