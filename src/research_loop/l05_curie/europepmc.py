"""Europe PMC provider-specific acquisition primitives for L0.5 Curie.

Discovery transport, source retrieval, and verification are deliberately
separated. A retriever may propose candidate extracts, but only the independent
verifier may emit `L05EvidenceExtract/v1` records with `LOCATED` status.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from .contracts import (
    DISCOVERY_BATCH_SCHEMA_VERSION,
    DISCOVERY_TRANSPORT_SCHEMA_VERSION,
    EVIDENCE_EXTRACT_SCHEMA_VERSION,
    CurieContractError,
    validate_evidence_extract,
)
from .multisource import canonicalize_provider_record, normalize_doi, normalize_pmcid, normalize_pmid

PROVIDER = "europe-pmc"
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
SOURCE_SNAPSHOT_SCHEMA_VERSION = "L05SourceSnapshot/v1"
EVIDENCE_CANDIDATE_SCHEMA_VERSION = "L05EvidenceCandidate/v1"
HttpGet = Callable[[str, int], bytes]

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")
_TARGET_SECTION_WORDS = ("result", "discussion", "conclusion")
_SOURCE_ROOT = Path("09_Literature_Database") / "source_snapshots" / "l05"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_token(value: str) -> str:
    token = _SAFE_TOKEN.sub("_", str(value)).strip("_.")
    if not token:
        raise CurieContractError("artifact identity cannot be normalized to a safe token")
    return token


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurieContractError(f"{name} must be a non-empty string")
    return value.strip()


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _element_text(element: ET.Element) -> str:
    return _normalize_text(" ".join(element.itertext()))


def canonicalize_europepmc_record(raw: dict) -> dict:
    """Normalize one Europe PMC core result to a provider-neutral paper record."""
    if not isinstance(raw, dict):
        raise CurieContractError("Europe PMC result must be an object")
    title = _require_text(raw.get("title"), "Europe PMC result title")
    source = str(raw.get("source") or "").strip().upper()
    ext_id = str(raw.get("id") or "").strip()
    doi = normalize_doi(raw.get("doi"))
    pmid = normalize_pmid(raw.get("pmid"))
    if not pmid and source == "MED":
        pmid = normalize_pmid(ext_id)
    pmcid = normalize_pmcid(raw.get("pmcid"))
    if not pmcid and source == "PMC":
        pmcid = normalize_pmcid(ext_id)

    identifiers = {}
    for key, value in (
        ("doi", doi),
        ("pmid", pmid),
        ("pmcid", pmcid),
    ):
        if value:
            identifiers[key] = value

    pub_types = raw.get("pubTypeList", {}).get("pubType", []) if isinstance(
        raw.get("pubTypeList"), dict
    ) else []
    if isinstance(pub_types, str):
        pub_types = [pub_types]
    if not isinstance(pub_types, list):
        pub_types = []

    return canonicalize_provider_record(
        PROVIDER, raw, title=title, identifiers=identifiers,
        authors=str(raw.get("authorString") or "").strip(), year=str(raw.get("pubYear") or "").strip(),
        journal=str(raw.get("journalTitle") or "").strip(), abstract=str(raw.get("abstractText") or "").strip(),
        publication_types=[str(item) for item in pub_types if str(item).strip()],
        is_open_access=str(raw.get("isOpenAccess") or "").upper() == "Y",
        extra_metadata={"in_europe_pmc": str(raw.get("inEPMC") or "").upper() == "Y"},
        extra_provenance={"source": source, "ext_id": ext_id},
    )


def _default_http_get(url: str, timeout: int) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json, application/xml;q=0.9, */*;q=0.1",
            "User-Agent": "RLR-L0.5-Curie/1.0 (+https://github.com/hk20013106/RLR)",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed HTTPS base
        return response.read()


class EuropePmcTransport:
    """Deterministic Europe PMC `search` adapter with persisted raw receipts."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        candidate_id: str,
        run_id: str,
        http_get: HttpGet | None = None,
        timeout: int = 20,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.candidate_id = _safe_token(candidate_id)
        self.run_id = _safe_token(run_id)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise CurieContractError("Europe PMC timeout must be a positive integer")
        self.timeout = timeout
        self.http_get = http_get or _default_http_get

    def handshake(self) -> dict:
        return {
            "schema_version": DISCOVERY_TRANSPORT_SCHEMA_VERSION,
            "provider": PROVIDER,
            "capabilities": ["search:core", "fulltext:xml", "cursor-pagination"],
        }

    def _write_raw_response(self, query_id: str, raw: bytes) -> str:
        relative = (
            Path("08_Audit")
            / "l05_acquisition"
            / self.candidate_id
            / self.run_id
            / f"search_{_safe_token(query_id)}.json"
        )
        path = self.project_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_bytes()
            if existing != raw:
                raise CurieContractError(
                    f"Europe PMC discovery receipt already exists with different bytes: {relative.as_posix()}"
                )
        else:
            path.write_bytes(raw)
        return relative.as_posix()

    def search(self, request: dict) -> dict:
        if not isinstance(request, dict):
            raise CurieContractError("Europe PMC search request must be an object")
        query_id = _require_text(request.get("query_id"), "Europe PMC query_id")
        query = _require_text(request.get("query"), "Europe PMC query")
        page_size = request.get("page_size", 25)
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 1000:
            raise CurieContractError("Europe PMC page_size must be an integer from 1 to 1000")
        cursor_mark = str(request.get("cursor_mark") or "").strip()

        normalized_request = {
            "provider": PROVIDER,
            "query_id": query_id,
            "query": query,
            "result_type": "core",
            "format": "json",
            "page_size": page_size,
            "cursor_mark": cursor_mark or None,
        }
        params = {
            "query": query,
            "resultType": "core",
            "format": "json",
            "pageSize": str(page_size),
        }
        if cursor_mark:
            params["cursorMark"] = cursor_mark
        url = BASE_URL + "/search?" + urlencode(params)
        try:
            raw = self.http_get(url, self.timeout)
        except Exception as exc:
            raise CurieContractError(f"Europe PMC search request failed: {exc}") from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise CurieContractError("Europe PMC http_get must return bytes")
        raw = bytes(raw)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CurieContractError(f"Europe PMC search response is not valid UTF-8 JSON: {exc}") from exc
        results = payload.get("resultList", {}).get("result", []) if isinstance(payload, dict) else []
        if not isinstance(results, list):
            raise CurieContractError("Europe PMC search response resultList.result must be a list")
        records = [canonicalize_europepmc_record(item) for item in results]
        response_path = self._write_raw_response(query_id, raw)
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": PROVIDER,
            "query_id": query_id,
            "receipt": {
                "request_sha256": hashlib.sha256(_canonical_bytes(normalized_request)).hexdigest(),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "response_path": response_path,
                "endpoint": "search",
            },
            "records": records,
            "hit_count": int(payload.get("hitCount") or 0) if isinstance(payload, dict) else 0,
            "next_cursor_mark": str(payload.get("nextCursorMark") or "") if isinstance(payload, dict) else "",
        }


def _parse_target_paragraphs(raw: bytes) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise CurieContractError(f"Europe PMC fullTextXML is invalid XML: {exc}") from exc
    extracted: list[dict] = []
    section_index = 0
    for element in root.iter():
        if _local_name(element.tag) != "sec":
            continue
        section_index += 1
        title_element = next(
            (child for child in list(element) if _local_name(child.tag) == "title"),
            None,
        )
        title = _element_text(title_element) if title_element is not None else ""
        normalized_title = title.casefold()
        if not any(word in normalized_title for word in _TARGET_SECTION_WORDS):
            continue
        paragraphs = [child for child in element.iter() if _local_name(child.tag) == "p"]
        for paragraph_index, paragraph in enumerate(paragraphs, 1):
            text = _element_text(paragraph)
            if not text:
                continue
            extracted.append({
                "section": title or "Untitled section",
                "text": text,
                "locator": f"sec:{section_index}/p:{paragraph_index}",
            })
    return extracted


def _paragraph_locator_map(raw: bytes) -> dict[str, dict]:
    return {item["locator"]: item for item in _parse_target_paragraphs(raw)}


class EuropePmcEvidenceRetriever:
    """Persist exact OA XML and propose unverified evidence candidates."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        candidate_id: str,
        run_id: str,
        http_get: HttpGet | None = None,
        timeout: int = 20,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.candidate_id = _safe_token(candidate_id)
        self.run_id = _safe_token(run_id)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise CurieContractError("Europe PMC timeout must be a positive integer")
        self.timeout = timeout
        self.http_get = http_get or _default_http_get

    def _snapshot_path(self, paper_id: str) -> tuple[Path, Path]:
        relative = (
            _SOURCE_ROOT
            / self.candidate_id
            / self.run_id
            / f"{_safe_token(paper_id)}.xml"
        )
        return relative, self.project_dir / relative

    def retrieve(self, paper: dict, *, seed: dict) -> dict:
        if not isinstance(paper, dict):
            raise CurieContractError("selected Europe PMC paper must be an object")
        paper_id = _require_text(paper.get("paper_id"), "selected paper paper_id")
        identifiers = paper.get("identifiers")
        if not isinstance(identifiers, dict):
            raise CurieContractError("selected paper identifiers must be an object")
        pmcid = normalize_pmcid(identifiers.get("pmcid"))
        if not pmcid:
            raise CurieContractError("Europe PMC full-text retrieval requires a PMCID")
        _require_text(seed.get("scientific_question") if isinstance(seed, dict) else None,
                      "seed scientific_question")
        _require_text(seed.get("hypothesis_seed") if isinstance(seed, dict) else None,
                      "seed hypothesis_seed")

        url = f"{BASE_URL}/{pmcid}/fullTextXML"
        try:
            raw = self.http_get(url, self.timeout)
        except Exception as exc:
            raise CurieContractError(f"Europe PMC fullTextXML request failed: {exc}") from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise CurieContractError("Europe PMC http_get must return bytes")
        raw = bytes(raw)
        paragraphs = _parse_target_paragraphs(raw)
        if not paragraphs:
            raise CurieContractError(
                "Europe PMC fullTextXML contains no Results/Discussion/Conclusion paragraphs"
            )

        relative, path = self._snapshot_path(paper_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw:
                raise CurieContractError(
                    f"Europe PMC source snapshot already exists with different bytes: {relative.as_posix()}"
                )
        else:
            path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        snapshot = {
            "schema_version": SOURCE_SNAPSHOT_SCHEMA_VERSION,
            "provider": PROVIDER,
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "paper_id": paper_id,
            "pmcid": pmcid,
            "artifact_path": relative.as_posix(),
            "artifact_sha256": digest,
            "content_type": "application/xml",
            "source_endpoint": f"/{pmcid}/fullTextXML",
        }
        candidates = [
            {
                "schema_version": EVIDENCE_CANDIDATE_SCHEMA_VERSION,
                "candidate_extract_id": "EC_" + _sha({
                    "paper_id": paper_id,
                    "locator": item["locator"],
                    "text": item["text"],
                    "source_sha256": digest,
                })[:20],
                "paper_id": paper_id,
                "section": item["section"],
                "text": item["text"],
                "locator": item["locator"],
                "role": "CONTEXT",
                "verification_status": "UNVERIFIED",
                "retrieval": {
                    "engine": "europe-pmc-fulltext-xml/v1",
                    "source_sha256": digest,
                    "snapshot_path": relative.as_posix(),
                    "pmcid": pmcid,
                },
            }
            for item in paragraphs
        ]
        return {"snapshot": snapshot, "candidates": candidates}


class EuropePmcEvidenceVerifier:
    """Independently re-open source XML and certify exact located extracts."""

    def __init__(self, project_dir: str | Path, *, candidate_id: str) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.candidate_id = _safe_token(candidate_id)

    def _load_snapshot(self, snapshot: dict) -> bytes:
        if not isinstance(snapshot, dict):
            raise CurieContractError("Europe PMC source snapshot must be an object")
        if snapshot.get("schema_version") != SOURCE_SNAPSHOT_SCHEMA_VERSION:
            raise CurieContractError("Europe PMC source snapshot schema_version is invalid")
        if snapshot.get("provider") != PROVIDER:
            raise CurieContractError("Europe PMC source snapshot provider is invalid")
        if snapshot.get("candidate_id") != self.candidate_id:
            raise CurieContractError("Europe PMC source snapshot candidate_id mismatch")
        paper_id = _require_text(snapshot.get("paper_id"), "source snapshot paper_id")
        _require_text(snapshot.get("run_id"), "source snapshot run_id")
        _require_text(snapshot.get("pmcid"), "source snapshot pmcid")
        expected_sha = _require_text(snapshot.get("artifact_sha256"),
                                     "source snapshot artifact_sha256").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise CurieContractError("Europe PMC source snapshot SHA-256 is invalid")
        relative = Path(_require_text(snapshot.get("artifact_path"),
                                      "source snapshot artifact_path"))
        if relative.is_absolute():
            raise CurieContractError("Europe PMC source snapshot artifact_path must be relative")
        expected_root = (self.project_dir / _SOURCE_ROOT / self.candidate_id).resolve()
        path = (self.project_dir / relative).resolve()
        try:
            path.relative_to(expected_root)
        except ValueError as exc:
            raise CurieContractError(
                "Europe PMC source snapshot path escapes the candidate source root"
            ) from exc
        if not path.is_file():
            raise CurieContractError("Europe PMC source snapshot file is missing")
        raw = path.read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != expected_sha:
            raise CurieContractError(
                "Europe PMC source snapshot SHA-256 does not match the frozen source bytes"
            )
        _require_text(paper_id, "source snapshot paper_id")
        return raw

    def verify(self, snapshot: dict, candidates: list[dict]) -> list[dict]:
        raw = self._load_snapshot(snapshot)
        if not isinstance(candidates, list) or not candidates:
            raise CurieContractError("Europe PMC evidence candidates must be a non-empty list")
        locator_map = _paragraph_locator_map(raw)
        verified: list[dict] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise CurieContractError("Europe PMC evidence candidate must be an object")
            is_paperqa2_candidate = candidate.get("schema_version") == "L05PaperQA2Candidate/v1"
            if (
                candidate.get("schema_version") != EVIDENCE_CANDIDATE_SCHEMA_VERSION
                and not is_paperqa2_candidate
            ):
                raise CurieContractError("Europe PMC evidence candidate schema_version is invalid")
            if candidate.get("verification_status") != "UNVERIFIED":
                raise CurieContractError("Europe PMC evidence candidate must be UNVERIFIED")
            if is_paperqa2_candidate:
                from .paperqa2 import validate_paperqa2_candidate

                candidate = validate_paperqa2_candidate(candidate)
            if candidate.get("paper_id") != snapshot.get("paper_id"):
                raise CurieContractError("Europe PMC evidence candidate paper_id mismatch")
            locator = _require_text(candidate.get("locator"), "evidence candidate locator")
            located = locator_map.get(locator)
            if located is None:
                raise CurieContractError(
                    f"Europe PMC evidence locator cannot be resolved: {locator}"
                )
            text = _normalize_text(candidate.get("text"))
            if text != located["text"]:
                raise CurieContractError(
                    f"Europe PMC evidence text does not match source at locator {locator}"
                )
            section = _require_text(candidate.get("section"), "evidence candidate section")
            if _normalize_text(section) != located["section"]:
                raise CurieContractError(
                    f"Europe PMC evidence section does not match source at locator {locator}"
                )
            role = _require_text(candidate.get("role") or "CONTEXT", "evidence candidate role")
            upstream_retrieval = candidate.get("retrieval")
            if not isinstance(upstream_retrieval, dict):
                raise CurieContractError("Europe PMC evidence candidate retrieval is missing")
            extract = {
                "schema_version": EVIDENCE_EXTRACT_SCHEMA_VERSION,
                "evidence_id": "E_" + _sha({
                    "paper_id": snapshot["paper_id"],
                    "locator": locator,
                    "text": text,
                    "source_sha256": snapshot["artifact_sha256"],
                })[:20],
                "paper_id": snapshot["paper_id"],
                "section": located["section"],
                "text": text,
                "locator": locator,
                "role": role,
                "verification_status": "LOCATED",
                "retrieval": {
                    "engine": "europe-pmc-fulltext-xml/v1",
                    "source_sha256": snapshot["artifact_sha256"],
                    "snapshot_path": snapshot["artifact_path"],
                    "pmcid": snapshot["pmcid"],
                    "verifier": "europe-pmc-source-relocator/v1",
                },
            }
            if is_paperqa2_candidate:
                extract["retrieval"]["upstream_engine"] = "paperqa2"
                if upstream_retrieval.get("backend_id"):
                    extract["retrieval"]["upstream_backend_id"] = str(
                        upstream_retrieval["backend_id"]
                    )
                for provenance_key in ("runtime", "paperqa2", "source_alignment"):
                    if provenance_key in upstream_retrieval:
                        if not isinstance(upstream_retrieval[provenance_key], dict):
                            raise CurieContractError(
                                f"Europe PMC PaperQA2 {provenance_key} provenance must be an object"
                            )
                        extract["retrieval"][provenance_key] = json.loads(
                            json.dumps(upstream_retrieval[provenance_key])
                        )
            verified.append(validate_evidence_extract(extract))
        return verified
