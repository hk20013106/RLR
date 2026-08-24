"""Europe PMC discovery primitives for the L0.5 Curie acquisition runtime.

This module deliberately stops at discovery/canonical metadata. Full-text
retrieval and verification are added in the next TDD slice.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import (
    DISCOVERY_BATCH_SCHEMA_VERSION,
    DISCOVERY_TRANSPORT_SCHEMA_VERSION,
    QUERY_PLAN_SCHEMA_VERSION,
    CurieContractError,
)

PROVIDER = "europe-pmc"
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
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


def deduplicate_discovery_records(records: list[dict]) -> tuple[list[dict], list[str]]:
    """Preserve first-seen canonical records and report duplicate paper IDs."""
    if not isinstance(records, list):
        raise CurieContractError("discovery records must be a list")
    unique: list[dict] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise CurieContractError("discovery record must be an object")
        paper_id = _require_text(record.get("paper_id"), "discovery record paper_id")
        if paper_id in seen:
            duplicates.append(paper_id)
            continue
        seen.add(paper_id)
        unique.append(record)
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
        except Exception as exc:  # provider/network boundary: normalize as contract error
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
