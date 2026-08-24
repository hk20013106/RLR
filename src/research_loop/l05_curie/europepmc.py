"""Europe PMC acquisition primitives for the L0.5 Curie runtime.

Discovery, selection, source retrieval, and verification are deliberately
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
    QUERY_PLAN_SCHEMA_VERSION,
    CurieContractError,
    validate_evidence_extract,
)

PROVIDER = "europe-pmc"
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
SOURCE_SNAPSHOT_SCHEMA_VERSION = "L05SourceSnapshot/v1"
EVIDENCE_CANDIDATE_SCHEMA_VERSION = "L05EvidenceCandidate/v1"
HttpGet = Callable[[str, int], bytes]

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")
_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "about", "after", "also", "among", "because", "before", "between",
    "could", "from", "have", "into", "more", "most", "other", "than",
    "that", "their", "there", "these", "this", "through", "under", "using",
    "what", "when", "where", "which", "with", "would", "does", "how", "why",
    "the", "and", "are", "for", "not", "can", "its", "our", "they", "them",
}
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


def normalize_doi(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = _DOI_PREFIX.sub("", text).strip().rstrip(".")
    return text.lower()


def normalize_pmid(value: object) -> str:
    text = str(value or "").strip()
    return text if text.isdigit() else ""


def normalize_pmcid(value: object) -> str:
    text = str(value or "").strip().upper().replace("_", "")
    if not text:
        return ""
    if text.isdigit():
        text = "PMC" + text
    if re.fullmatch(r"PMC\d+", text):
        return text
    return ""


def _metadata_fingerprint(raw: dict) -> str:
    title = " ".join(str(raw.get("title") or "").casefold().split())
    year = str(raw.get("pubYear") or "").strip()
    author = str(raw.get("authorString") or "").split(",", 1)[0].casefold().strip()
    return _sha({"title": title, "year": year, "first_author": author})


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

    if doi:
        identity = ("doi", doi)
    elif pmid:
        identity = ("pmid", pmid)
    elif pmcid:
        identity = ("pmcid", pmcid)
    elif source and ext_id:
        identity = ("source", f"{source}:{ext_id}")
    else:
        identity = ("metadata", _metadata_fingerprint(raw))
    paper_id = "P_" + _sha(identity)[:20]

    identifiers = {}
    for key, value in (
        ("doi", doi),
        ("pmid", pmid),
        ("pmcid", pmcid),
        ("europepmc_source", source),
        ("europepmc_id", ext_id),
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

    return {
        "paper_id": paper_id,
        "title": title,
        "identifiers": identifiers,
        "metadata": {
            "authors": str(raw.get("authorString") or "").strip(),
            "year": str(raw.get("pubYear") or "").strip(),
            "journal": str(raw.get("journalTitle") or "").strip(),
            "abstract": str(raw.get("abstractText") or "").strip(),
            "publication_types": [str(item) for item in pub_types if str(item).strip()],
            "is_open_access": str(raw.get("isOpenAccess") or "").upper() == "Y",
            "in_europe_pmc": str(raw.get("inEPMC") or "").upper() == "Y",
        },
        "provenance": {
            "provider": PROVIDER,
            "source": source,
            "ext_id": ext_id,
            "raw_record_sha256": hashlib.sha256(_canonical_bytes(raw)).hexdigest(),
        },
    }


def _copy_record(record: dict) -> dict:
    return {
        **record,
        "identifiers": dict(record.get("identifiers") or {}),
        "metadata": {
            **(record.get("metadata") or {}),
            "publication_types": list(
                (record.get("metadata") or {}).get("publication_types") or []
            ),
        },
        "provenance": dict(record.get("provenance") or {}),
    }


def _stable_identifiers(record: dict) -> set[tuple[str, str]]:
    identifiers = record.get("identifiers")
    if not isinstance(identifiers, dict):
        return set()
    return {
        (key, str(identifiers[key]))
        for key in ("doi", "pmid", "pmcid")
        if str(identifiers.get(key) or "").strip()
    }


def _merge_discovery_record(primary: dict, duplicate: dict) -> None:
    primary_ids = primary["identifiers"]
    duplicate_ids = duplicate.get("identifiers") or {}
    for key in ("doi", "pmid", "pmcid"):
        left = str(primary_ids.get(key) or "")
        right = str(duplicate_ids.get(key) or "")
        if left and right and left != right:
            raise CurieContractError(
                f"Europe PMC duplicate records conflict on canonical {key}: {left} != {right}"
            )
    for key, value in duplicate_ids.items():
        if value and not primary_ids.get(key):
            primary_ids[key] = value

    primary_meta = primary["metadata"]
    duplicate_meta = duplicate.get("metadata") or {}
    for key in ("authors", "year", "journal", "abstract"):
        if not primary_meta.get(key) and duplicate_meta.get(key):
            primary_meta[key] = duplicate_meta[key]
    for key in ("is_open_access", "in_europe_pmc"):
        primary_meta[key] = bool(primary_meta.get(key) or duplicate_meta.get(key))
    publication_types = list(primary_meta.get("publication_types") or [])
    for value in duplicate_meta.get("publication_types") or []:
        if value not in publication_types:
            publication_types.append(value)
    primary_meta["publication_types"] = publication_types

    provenance = primary["provenance"]
    source_records = provenance.get("source_records")
    if not isinstance(source_records, list):
        source_records = [{
            key: provenance.get(key)
            for key in ("provider", "source", "ext_id", "raw_record_sha256")
            if provenance.get(key) is not None
        }]
    duplicate_provenance = duplicate.get("provenance") or {}
    source_records.append({
        key: duplicate_provenance.get(key)
        for key in ("provider", "source", "ext_id", "raw_record_sha256")
        if duplicate_provenance.get(key) is not None
    })
    provenance["source_records"] = source_records


def deduplicate_discovery_records(records: list[dict]) -> tuple[list[dict], list[str]]:
    """Deduplicate by stable identifier overlap and merge richer source metadata."""
    if not isinstance(records, list):
        raise CurieContractError("discovery records must be a list")
    unique: list[dict] = []
    duplicates: list[str] = []
    paper_owner: dict[str, int] = {}
    identifier_owner: dict[tuple[str, str], int] = {}

    for record in records:
        if not isinstance(record, dict):
            raise CurieContractError("discovery record must be an object")
        paper_id = _require_text(record.get("paper_id"), "discovery record paper_id")
        stable_ids = _stable_identifiers(record)
        owners = {
            owner for identity in stable_ids
            if (owner := identifier_owner.get(identity)) is not None
        }
        if paper_id in paper_owner:
            owners.add(paper_owner[paper_id])
        if len(owners) > 1:
            raise CurieContractError(
                "Europe PMC record bridges multiple canonical papers with conflicting identity clusters"
            )
        if owners:
            owner = next(iter(owners))
            _merge_discovery_record(unique[owner], record)
            duplicates.append(paper_id)
            paper_owner[paper_id] = owner
            for identity in _stable_identifiers(unique[owner]):
                identifier_owner[identity] = owner
            continue

        owner = len(unique)
        canonical = _copy_record(record)
        unique.append(canonical)
        paper_owner[paper_id] = owner
        for identity in stable_ids:
            identifier_owner[identity] = owner
    return unique, duplicates


def _keywords(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(text):
        lowered = token.casefold()
        if lowered in _STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        values.append(token)
    return values


def build_europepmc_query_plan(
    seed: dict,
    *,
    seed_sha256: str,
    round_index: int = 1,
    explicit_queries: list[str] | None = None,
) -> dict:
    """Project one canonical ResearchSeed into an auditable Europe PMC QueryPlan."""
    if not isinstance(seed, dict):
        raise CurieContractError("ResearchSeed must be an object")
    candidate_id = _require_text(seed.get("candidate_id"), "ResearchSeed candidate_id")
    round_id = _require_text(seed.get("round_id"), "ResearchSeed round_id")
    question = _require_text(seed.get("scientific_question"), "ResearchSeed scientific_question")
    hypothesis = _require_text(seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed")
    if not isinstance(round_index, int) or isinstance(round_index, bool) or not 1 <= round_index <= 3:
        raise CurieContractError("round_index must be an integer from 1 to 3")

    queries: list[tuple[str, str]] = []
    if explicit_queries is not None:
        if not isinstance(explicit_queries, list) or not explicit_queries:
            raise CurieContractError("explicit_queries must be a non-empty list")
        for query in explicit_queries:
            queries.append(("operator_reproducible_query", _require_text(query, "explicit query")))
    else:
        question_terms = _keywords(question)[:10]
        hypothesis_terms = _keywords(hypothesis)[:10]
        combined = list(dict.fromkeys(question_terms + hypothesis_terms))[:14]
        if not combined:
            raise CurieContractError("ResearchSeed produced no searchable Europe PMC terms")
        queries.append(("seed_question_hypothesis", f"({' '.join(combined)}) AND (OPEN_ACCESS:y)"))

    query_items = [
        {
            "query_id": f"Q{index:03d}",
            "intent": intent,
            "query": query,
            "providers": [PROVIDER],
        }
        for index, (intent, query) in enumerate(queries, 1)
    ]
    identity = {
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": str(seed_sha256).lower(),
        "round_index": round_index,
        "queries": query_items,
    }
    return {
        "schema_version": QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": str(seed_sha256).lower(),
        "plan_id": "QP_EPMC_" + _sha(identity)[:16],
        "round_index": round_index,
        "queries": query_items,
        "coverage_targets": [
            "verified_full_text_source",
            "located_results_or_interpretation",
        ],
        "planner": "curie-europepmc-seed-planner/v1",
    }


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


def _relevance_score(record: dict, seed: dict) -> int:
    seed_text = " ".join((
        _require_text(seed.get("scientific_question"), "seed scientific_question"),
        _require_text(seed.get("hypothesis_seed"), "seed hypothesis_seed"),
    ))
    terms = {item.casefold() for item in _keywords(seed_text)}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    haystack = " ".join((
        str(record.get("title") or ""),
        str(metadata.get("abstract") or ""),
    )).casefold()
    matched = sum(1 for term in terms if term in haystack)
    return matched


def select_europepmc_candidates(
    records: list[dict], *, seed: dict, max_papers: int = 3
) -> dict:
    """Rank candidates while preserving INCLUDE/EXCLUDE/RESERVE decisions."""
    if not isinstance(max_papers, int) or isinstance(max_papers, bool) or max_papers < 1:
        raise CurieContractError("max_papers must be a positive integer")
    unique, duplicates = deduplicate_discovery_records(records)
    eligible: list[tuple[int, int, dict]] = []
    decisions: list[dict] = []

    for index, record in enumerate(unique):
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        identifiers = record.get("identifiers") if isinstance(record.get("identifiers"), dict) else {}
        score = _relevance_score(record, seed)
        has_full_text = bool(
            identifiers.get("pmcid")
            and metadata.get("is_open_access") is True
            and metadata.get("in_europe_pmc") is True
        )
        if not has_full_text:
            decisions.append({
                "paper_id": record["paper_id"],
                "decision": "EXCLUDE",
                "reason_code": "NO_OPEN_FULL_TEXT",
                "reason": "Europe PMC does not expose an OA PMCID full-text source for this record.",
                "score": score,
            })
            continue
        eligible.append((score, -index, record))

    eligible.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected_ids = {item[2]["paper_id"] for item in eligible[:max_papers]}
    for score, _neg_index, record in eligible:
        included = record["paper_id"] in selected_ids
        decision = "INCLUDE" if included else "RESERVE"
        decisions.append({
            "paper_id": record["paper_id"],
            "decision": decision,
            "reason_code": "SELECTED_FOR_FULL_TEXT" if included else "CAPACITY_RESERVE",
            "reason": (
                "Selected for Europe PMC full-text retrieval."
                if included else
                "Eligible OA full text retained as reserve after the retrieval cap."
            ),
            "score": score,
        })

    selected: list[dict] = []
    decisions_by_id = {item["paper_id"]: item for item in decisions}
    for _score, _neg_index, record in eligible[:max_papers]:
        decision = decisions_by_id[record["paper_id"]]
        selected.append({
            "paper_id": record["paper_id"],
            "title": record["title"],
            "identifiers": dict(record.get("identifiers") or {}),
            "metadata": dict(record.get("metadata") or {}),
            "provenance": dict(record.get("provenance") or {}),
            "selection": {
                "decision": "INCLUDE",
                "reason": decision["reason"],
                "reason_code": decision["reason_code"],
                "score": decision["score"],
            },
        })

    return {
        "provider": PROVIDER,
        "selected": selected,
        "decisions": decisions,
        "duplicate_paper_ids": duplicates,
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
            if candidate.get("schema_version") != EVIDENCE_CANDIDATE_SCHEMA_VERSION:
                raise CurieContractError("Europe PMC evidence candidate schema_version is invalid")
            if candidate.get("verification_status") != "UNVERIFIED":
                raise CurieContractError("Europe PMC evidence candidate must be UNVERIFIED")
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
            role = _require_text(candidate.get("role"), "evidence candidate role")
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
            verified.append(validate_evidence_extract(extract))
        return verified
