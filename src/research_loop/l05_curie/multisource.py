"""Provider-neutral multi-source discovery for L0.5 Curie.

Adapters are deterministic infrastructure. They may discover bibliographic
metadata, but they do not select papers, retrieve evidence, or certify claims.
Every provider record is normalized into one canonical identity graph before it
can reach downstream Curie stages.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
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
    validate_discovery_batch,
    validate_query_plan,
    validate_transport_handshake,
)
from .europepmc import normalize_doi, normalize_pmcid, normalize_pmid


HttpGet = Callable[[str, int], bytes]
_PROVIDERS = ("europe-pmc", "pubmed", "openalex", "crossref", "semantic-scholar")
_STABLE_NAMESPACES = (
    "doi",
    "pmid",
    "pmcid",
    "openalex_id",
    "semantic_scholar_paper_id",
    "semantic_scholar_corpus_id",
)
_AUDIT_ROOT = Path("08_Audit") / "l05_acquisition"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_TAGS = re.compile(r"<[^>]+>")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CurieContractError(f"{name} must be a non-empty string")
    return text


def _safe(value: object, name: str) -> str:
    text = _SAFE.sub("_", _require_text(value, name)).strip("._")
    if not text:
        raise CurieContractError(f"{name} cannot be normalized to a safe token")
    return text


def _first(value: object) -> str:
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def _year(value: object) -> str:
    match = _YEAR.search(str(value or ""))
    return match.group(0) if match else ""


def _metadata_fingerprint(title: str, year: str = "", authors: str = "") -> str:
    return _sha({
        "title": " ".join(title.casefold().split()),
        "year": year,
        "first_author": authors.split(",", 1)[0].casefold().strip(),
    })


def _paper_id(identifiers: dict, *, title: str, year: str = "", authors: str = "") -> str:
    for key in _STABLE_NAMESPACES:
        value = str(identifiers.get(key) or "").strip()
        if value:
            return "P_" + _sha((key, value))[:20]
    return "P_" + _sha(("metadata", _metadata_fingerprint(title, year, authors)))[:20]


def _record(provider: str, raw: dict, *, title: str, identifiers: dict,
            authors: str = "", year: str = "", journal: str = "",
            abstract: str = "", publication_types: list[str] | None = None,
            is_open_access: bool = False) -> dict:
    title = _require_text(title, f"{provider} result title")
    identifiers = {key: str(value) for key, value in identifiers.items() if str(value or "").strip()}
    return {
        "paper_id": _paper_id(identifiers, title=title, year=year, authors=authors),
        "title": title,
        "identifiers": identifiers,
        "metadata": {
            "authors": authors,
            "year": year,
            "journal": journal,
            "abstract": abstract,
            "publication_types": list(publication_types or []),
            "is_open_access": bool(is_open_access),
        },
        "provenance": {
            "provider": provider,
            "raw_record_sha256": hashlib.sha256(_canonical_bytes(raw)).hexdigest(),
        },
    }


def canonicalize_pubmed_record(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise CurieContractError("PubMed result must be an object")
    uid = normalize_pmid(raw.get("uid"))
    identifiers = {"pmid": uid} if uid else {}
    article_ids = raw.get("articleids") or []
    if isinstance(article_ids, list):
        for item in article_ids:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("idtype") or "").casefold()
            value = item.get("value")
            if kind in {"pubmed", "pmid"}:
                normalized = normalize_pmid(value)
                if normalized:
                    identifiers["pmid"] = normalized
            elif kind == "doi":
                normalized = normalize_doi(value)
                if normalized:
                    identifiers["doi"] = normalized
            elif kind in {"pmc", "pmcid"}:
                normalized = normalize_pmcid(value)
                if normalized:
                    identifiers["pmcid"] = normalized
    authors_raw = raw.get("authors") or []
    authors = ", ".join(
        str(item.get("name") or "").strip()
        for item in authors_raw
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ) if isinstance(authors_raw, list) else ""
    pub_types = raw.get("pubtype") or []
    if isinstance(pub_types, str):
        pub_types = [pub_types]
    return _record(
        "pubmed",
        raw,
        title=str(raw.get("title") or ""),
        identifiers=identifiers,
        authors=authors,
        year=_year(raw.get("pubdate") or raw.get("sortpubdate") or raw.get("epubdate")),
        journal=str(raw.get("fulljournalname") or raw.get("source") or "").strip(),
        publication_types=[str(item) for item in pub_types if str(item).strip()]
        if isinstance(pub_types, list) else [],
        is_open_access=bool(identifiers.get("pmcid")),
    )


def _openalex_id(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    token = text.rsplit("/", 1)[-1]
    return token if re.fullmatch(r"W\d+", token, re.IGNORECASE) else ""


def _url_pmid(value: object) -> str:
    match = re.search(r"(?:pubmed(?:\.ncbi\.nlm\.nih\.gov)?/|PMID:)?(\d+)(?:/)?$", str(value or ""), re.IGNORECASE)
    return normalize_pmid(match.group(1)) if match else ""


def _url_pmcid(value: object) -> str:
    match = re.search(r"(PMC\d+)", str(value or ""), re.IGNORECASE)
    return normalize_pmcid(match.group(1)) if match else ""


def _openalex_abstract(raw: dict) -> str:
    inverted = raw.get("abstract_inverted_index")
    if not isinstance(inverted, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for token, values in inverted.items():
        if isinstance(values, list):
            for position in values:
                if isinstance(position, int):
                    positions.append((position, str(token)))
    return " ".join(token for _position, token in sorted(positions))


def canonicalize_openalex_record(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise CurieContractError("OpenAlex result must be an object")
    ids = raw.get("ids") if isinstance(raw.get("ids"), dict) else {}
    identifiers = {}
    doi = normalize_doi(raw.get("doi") or ids.get("doi"))
    if doi:
        identifiers["doi"] = doi
    pmid = _url_pmid(ids.get("pmid"))
    if pmid:
        identifiers["pmid"] = pmid
    pmcid = _url_pmcid(ids.get("pmcid"))
    if pmcid:
        identifiers["pmcid"] = pmcid
    openalex_id = _openalex_id(raw.get("id") or ids.get("openalex"))
    if openalex_id:
        identifiers["openalex_id"] = openalex_id
    authorships = raw.get("authorships") or []
    authors = ", ".join(
        str((item.get("author") or {}).get("display_name") or "").strip()
        for item in authorships
        if isinstance(item, dict) and isinstance(item.get("author"), dict)
        and str(item["author"].get("display_name") or "").strip()
    ) if isinstance(authorships, list) else ""
    primary = raw.get("primary_location") if isinstance(raw.get("primary_location"), dict) else {}
    source = primary.get("source") if isinstance(primary.get("source"), dict) else {}
    oa = raw.get("open_access") if isinstance(raw.get("open_access"), dict) else {}
    return _record(
        "openalex",
        raw,
        title=str(raw.get("title") or raw.get("display_name") or ""),
        identifiers=identifiers,
        authors=authors,
        year=str(raw.get("publication_year") or ""),
        journal=str(source.get("display_name") or "").strip(),
        abstract=_openalex_abstract(raw),
        publication_types=[str(raw.get("type"))] if str(raw.get("type") or "").strip() else [],
        is_open_access=bool(oa.get("is_oa") or primary.get("is_oa")),
    )


def canonicalize_crossref_record(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise CurieContractError("Crossref result must be an object")
    identifiers = {}
    doi = normalize_doi(raw.get("DOI"))
    if doi:
        identifiers["doi"] = doi
    authors_raw = raw.get("author") or []
    authors = ", ".join(
        " ".join(filter(None, (
            str(item.get("given") or "").strip(),
            str(item.get("family") or "").strip(),
        )))
        for item in authors_raw if isinstance(item, dict)
    ) if isinstance(authors_raw, list) else ""
    date_parts = ((raw.get("published") or {}).get("date-parts")
                  if isinstance(raw.get("published"), dict) else None)
    year = ""
    if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
        year = str(date_parts[0][0])
    links = raw.get("link") or []
    is_oa = any(
        isinstance(item, dict) and str(item.get("URL") or "").startswith("http")
        for item in links
    ) if isinstance(links, list) else False
    abstract = _TAGS.sub(" ", str(raw.get("abstract") or ""))
    abstract = " ".join(abstract.split())
    return _record(
        "crossref",
        raw,
        title=_first(raw.get("title")),
        identifiers=identifiers,
        authors=authors,
        year=year,
        journal=_first(raw.get("container-title")),
        abstract=abstract,
        publication_types=[str(raw.get("type"))] if str(raw.get("type") or "").strip() else [],
        is_open_access=is_oa,
    )


def canonicalize_semantic_scholar_record(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise CurieContractError("Semantic Scholar result must be an object")
    external = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
    identifiers = {}
    doi = normalize_doi(external.get("DOI"))
    if doi:
        identifiers["doi"] = doi
    pmid = normalize_pmid(external.get("PubMed") or external.get("PMID"))
    if pmid:
        identifiers["pmid"] = pmid
    pmcid = normalize_pmcid(external.get("PubMedCentral") or external.get("PMCID"))
    if pmcid:
        identifiers["pmcid"] = pmcid
    paper_id = str(raw.get("paperId") or "").strip()
    if paper_id:
        identifiers["semantic_scholar_paper_id"] = paper_id
    corpus_id = str(raw.get("corpusId") or "").strip()
    if corpus_id:
        identifiers["semantic_scholar_corpus_id"] = corpus_id
    authors_raw = raw.get("authors") or []
    authors = ", ".join(
        str(item.get("name") or "").strip()
        for item in authors_raw
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ) if isinstance(authors_raw, list) else ""
    return _record(
        "semantic-scholar",
        raw,
        title=str(raw.get("title") or ""),
        identifiers=identifiers,
        authors=authors,
        year=str(raw.get("year") or ""),
        journal=str(raw.get("venue") or "").strip(),
        abstract=str(raw.get("abstract") or "").strip(),
        is_open_access=isinstance(raw.get("openAccessPdf"), dict)
        and bool(raw.get("openAccessPdf")),
    )


def _stable_ids(record: dict) -> set[tuple[str, str]]:
    identifiers = record.get("identifiers")
    if not isinstance(identifiers, dict):
        return set()
    return {
        (key, str(identifiers.get(key)))
        for key in _STABLE_NAMESPACES
        if str(identifiers.get(key) or "").strip()
    }


def _source_record(record: dict) -> dict:
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    return {
        key: provenance[key]
        for key in ("provider", "raw_record_sha256")
        if provenance.get(key) is not None
    }


def _copy_record(record: dict) -> dict:
    copied = {
        **record,
        "identifiers": dict(record.get("identifiers") or {}),
        "metadata": {
            **(record.get("metadata") or {}),
            "publication_types": list((record.get("metadata") or {}).get("publication_types") or []),
        },
        "provenance": dict(record.get("provenance") or {}),
    }
    copied["provenance"]["source_records"] = list(
        copied["provenance"].get("source_records") or [_source_record(record)]
    )
    return copied


def _merge(primary: dict, duplicate: dict) -> None:
    left_ids = primary["identifiers"]
    right_ids = duplicate.get("identifiers") or {}
    for key in _STABLE_NAMESPACES:
        left = str(left_ids.get(key) or "")
        right = str(right_ids.get(key) or "")
        if left and right and left != right:
            raise CurieContractError(
                f"cross-provider identity conflict on {key}: {left} != {right}"
            )
    for key, value in right_ids.items():
        if value and not left_ids.get(key):
            left_ids[key] = value
    left_meta = primary["metadata"]
    right_meta = duplicate.get("metadata") if isinstance(duplicate.get("metadata"), dict) else {}
    for key in ("authors", "year", "journal", "abstract"):
        if not left_meta.get(key) and right_meta.get(key):
            left_meta[key] = right_meta[key]
    left_meta["is_open_access"] = bool(
        left_meta.get("is_open_access") or right_meta.get("is_open_access")
    )
    types = list(left_meta.get("publication_types") or [])
    for value in right_meta.get("publication_types") or []:
        if value not in types:
            types.append(value)
    left_meta["publication_types"] = types
    sources = primary["provenance"].setdefault("source_records", [])
    incoming = duplicate.get("provenance") if isinstance(duplicate.get("provenance"), dict) else {}
    for item in incoming.get("source_records") or [_source_record(duplicate)]:
        if item not in sources:
            sources.append(item)


def deduplicate_provider_records(records: list[dict]) -> tuple[list[dict], list[str]]:
    if not isinstance(records, list):
        raise CurieContractError("provider discovery records must be a list")
    unique: list[dict] = []
    duplicates: list[str] = []
    paper_owner: dict[str, int] = {}
    id_owner: dict[tuple[str, str], int] = {}
    for record in records:
        if not isinstance(record, dict):
            raise CurieContractError("provider discovery record must be an object")
        paper_id = _require_text(record.get("paper_id"), "provider discovery paper_id")
        identities = _stable_ids(record)
        owners = {
            owner for identity in identities
            if (owner := id_owner.get(identity)) is not None
        }
        if paper_id in paper_owner:
            owners.add(paper_owner[paper_id])
        if len(owners) > 1:
            raise CurieContractError(
                "provider record bridges multiple canonical identity clusters"
            )
        if owners:
            owner = next(iter(owners))
            _merge(unique[owner], record)
            duplicates.append(paper_id)
            paper_owner[paper_id] = owner
            for identity in _stable_ids(unique[owner]):
                id_owner[identity] = owner
            continue
        owner = len(unique)
        canonical = _copy_record(record)
        unique.append(canonical)
        paper_owner[paper_id] = owner
        for identity in identities:
            id_owner[identity] = owner
    return unique, duplicates


def build_multisource_query_plan(
    seed: dict,
    *,
    seed_sha256: str,
    round_index: int = 1,
    explicit_queries: list[str] | None = None,
    providers: list[str] | None = None,
) -> dict:
    if not isinstance(seed, dict):
        raise CurieContractError("ResearchSeed must be an object")
    candidate_id = _require_text(seed.get("candidate_id"), "ResearchSeed candidate_id")
    round_id = _require_text(seed.get("round_id"), "ResearchSeed round_id")
    provider_list = list(providers or _PROVIDERS)
    if not provider_list or len(provider_list) != len(set(provider_list)):
        raise CurieContractError("multisource providers must be a non-empty unique list")
    unknown = [item for item in provider_list if item not in _PROVIDERS]
    if unknown:
        raise CurieContractError(f"unsupported discovery providers: {unknown}")
    if explicit_queries is None:
        queries = [
            " ".join((
                _require_text(seed.get("scientific_question"), "ResearchSeed scientific_question"),
                _require_text(seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed"),
            ))
        ]
        intent = "seed_question_hypothesis"
    else:
        if not isinstance(explicit_queries, list) or not explicit_queries:
            raise CurieContractError("explicit_queries must be a non-empty list")
        queries = [_require_text(item, "explicit query") for item in explicit_queries]
        intent = "operator_reproducible_query"
    query_items = [
        {
            "query_id": f"Q{index:03d}",
            "intent": intent,
            "query": query,
            "providers": list(provider_list),
        }
        for index, query in enumerate(queries, 1)
    ]
    identity = {
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": str(seed_sha256).lower(),
        "round_index": round_index,
        "queries": query_items,
    }
    plan = {
        "schema_version": QUERY_PLAN_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "round_id": round_id,
        "seed_sha256": str(seed_sha256).lower(),
        "plan_id": "QP_MULTI_" + _sha(identity)[:16],
        "round_index": round_index,
        "queries": query_items,
        "coverage_targets": ["cross_provider_discovery", "canonical_identity"],
        "planner": "curie-multisource-seed-planner/v1",
    }
    validate_query_plan(plan, seed_sha256=str(seed_sha256))
    return plan


def _default_http_get(url: str, timeout: int) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "RLR-L0.5-Curie/1.0 (+https://github.com/hk20013106/RLR)",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - adapter URLs are fixed HTTPS bases
        return response.read()


class _BaseTransport:
    provider = ""
    capabilities: tuple[str, ...] = ()

    def __init__(self, project_dir: str | Path, *, candidate_id: str,
                 run_id: str, http_get: HttpGet | None = None,
                 timeout: int = 20) -> None:
        self.project_dir = Path(project_dir)
        self.candidate_id = _safe(candidate_id, "candidate_id")
        self.run_id = _safe(run_id, "run_id")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise CurieContractError(f"{self.provider} timeout must be a positive integer")
        self.timeout = timeout
        self.http_get = http_get or _default_http_get

    def handshake(self) -> dict:
        return {
            "schema_version": DISCOVERY_TRANSPORT_SCHEMA_VERSION,
            "provider": self.provider,
            "capabilities": list(self.capabilities),
        }

    def _get(self, url: str) -> bytes:
        try:
            raw = self.http_get(url, self.timeout)
        except Exception as exc:
            raise CurieContractError(f"{self.provider} search request failed: {exc}") from exc
        if not isinstance(raw, (bytes, bytearray)):
            raise CurieContractError(f"{self.provider} http_get must return bytes")
        return bytes(raw)

    def _json(self, raw: bytes) -> dict:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CurieContractError(
                f"{self.provider} search response is not valid UTF-8 JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CurieContractError(f"{self.provider} search response must be a JSON object")
        return payload

    def _receipt(self, query_id: str, urls: list[str], responses: list[bytes]) -> dict:
        manifest = {
            "provider": self.provider,
            "query_id": query_id,
            "requests": list(urls),
            "responses_base64": [base64.b64encode(item).decode("ascii") for item in responses],
        }
        relative = (
            _AUDIT_ROOT / self.candidate_id / self.run_id
            / f"search_{_safe(self.provider, 'provider')}_{_safe(query_id, 'query_id')}.json"
        )
        path = self.project_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw_manifest = _canonical_bytes(manifest) + b"\n"
        if path.exists() and path.read_bytes() != raw_manifest:
            raise CurieContractError(
                f"{self.provider} discovery receipt already exists with different bytes"
            )
        if not path.exists():
            path.write_bytes(raw_manifest)
        return {
            "request_sha256": hashlib.sha256(_canonical_bytes(urls)).hexdigest(),
            "response_sha256": hashlib.sha256(b"\0".join(responses)).hexdigest(),
            "response_path": relative.as_posix(),
        }

    @staticmethod
    def _request(request: dict) -> tuple[str, str, int]:
        if not isinstance(request, dict):
            raise CurieContractError("discovery search request must be an object")
        query_id = _require_text(request.get("query_id"), "discovery query_id")
        query = _require_text(request.get("query"), "discovery query")
        page_size = request.get("page_size", 25)
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 1000:
            raise CurieContractError("discovery page_size must be an integer from 1 to 1000")
        return query_id, query, page_size


class PubMedTransport(_BaseTransport):
    provider = "pubmed"
    capabilities = ("search:esearch", "metadata:esummary")
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def search(self, request: dict) -> dict:
        query_id, query, page_size = self._request(request)
        esearch_url = self.base + "/esearch.fcgi?" + urlencode({
            "db": "pubmed", "term": query, "retmode": "json", "retmax": str(page_size),
        })
        search_raw = self._get(esearch_url)
        search_payload = self._json(search_raw)
        ids = ((search_payload.get("esearchresult") or {}).get("idlist")
               if isinstance(search_payload.get("esearchresult"), dict) else [])
        if not isinstance(ids, list):
            raise CurieContractError("PubMed ESearch idlist must be a list")
        urls = [esearch_url]
        responses = [search_raw]
        records = []
        if ids:
            esummary_url = self.base + "/esummary.fcgi?" + urlencode({
                "db": "pubmed", "id": ",".join(str(item) for item in ids), "retmode": "json",
            })
            summary_raw = self._get(esummary_url)
            summary_payload = self._json(summary_raw)
            urls.append(esummary_url)
            responses.append(summary_raw)
            result = summary_payload.get("result")
            if not isinstance(result, dict):
                raise CurieContractError("PubMed ESummary result must be an object")
            uids = result.get("uids") or ids
            if not isinstance(uids, list):
                raise CurieContractError("PubMed ESummary uids must be a list")
            for uid in uids:
                raw = result.get(str(uid))
                if isinstance(raw, dict):
                    records.append(canonicalize_pubmed_record(raw))
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": self.provider,
            "query_id": query_id,
            "receipt": self._receipt(query_id, urls, responses),
            "records": records,
            "hit_count": len(ids),
        }


class OpenAlexTransport(_BaseTransport):
    provider = "openalex"
    capabilities = ("search:works",)
    base = "https://api.openalex.org/works"

    def search(self, request: dict) -> dict:
        query_id, query, page_size = self._request(request)
        params = {"search": query, "per-page": str(page_size)}
        api_key = str(os.environ.get("OPENALEX_API_KEY") or "").strip()
        if api_key:
            params["api_key"] = api_key
        url = self.base + "?" + urlencode(params)
        raw = self._get(url)
        payload = self._json(raw)
        results = payload.get("results") or []
        if not isinstance(results, list):
            raise CurieContractError("OpenAlex results must be a list")
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": self.provider,
            "query_id": query_id,
            "receipt": self._receipt(query_id, [url], [raw]),
            "records": [canonicalize_openalex_record(item) for item in results],
            "hit_count": int((payload.get("meta") or {}).get("count") or len(results))
            if isinstance(payload.get("meta"), dict) else len(results),
        }


class CrossrefTransport(_BaseTransport):
    provider = "crossref"
    capabilities = ("search:works",)
    base = "https://api.crossref.org/works"

    def search(self, request: dict) -> dict:
        query_id, query, page_size = self._request(request)
        params = {"query.bibliographic": query, "rows": str(page_size)}
        mailto = str(os.environ.get("CROSSREF_MAILTO") or "").strip()
        if mailto:
            params["mailto"] = mailto
        url = self.base + "?" + urlencode(params)
        raw = self._get(url)
        payload = self._json(raw)
        message = payload.get("message")
        if not isinstance(message, dict):
            raise CurieContractError("Crossref response message must be an object")
        items = message.get("items") or []
        if not isinstance(items, list):
            raise CurieContractError("Crossref message.items must be a list")
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": self.provider,
            "query_id": query_id,
            "receipt": self._receipt(query_id, [url], [raw]),
            "records": [canonicalize_crossref_record(item) for item in items],
            "hit_count": int(message.get("total-results") or len(items)),
        }


class SemanticScholarTransport(_BaseTransport):
    provider = "semantic-scholar"
    capabilities = ("search:paper-relevance",)
    base = "https://api.semanticscholar.org/graph/v1/paper/search"

    def search(self, request: dict) -> dict:
        query_id, query, page_size = self._request(request)
        url = self.base + "?" + urlencode({
            "query": query,
            "limit": str(page_size),
            "fields": "title,year,authors,venue,abstract,externalIds,corpusId,openAccessPdf",
        })
        raw = self._get(url)
        payload = self._json(raw)
        items = payload.get("data") or []
        if not isinstance(items, list):
            raise CurieContractError("Semantic Scholar data must be a list")
        return {
            "schema_version": DISCOVERY_BATCH_SCHEMA_VERSION,
            "provider": self.provider,
            "query_id": query_id,
            "receipt": self._receipt(query_id, [url], [raw]),
            "records": [canonicalize_semantic_scholar_record(item) for item in items],
            "hit_count": int(payload.get("total") or len(items)),
        }


def run_multisource_discovery(plan: dict, transports: dict[str, object], *,
                              page_size: int = 25,
                              allow_partial: bool = False) -> dict:
    validate_query_plan(plan, seed_sha256=str(plan.get("seed_sha256") or ""))
    query_ids = {str(item["query_id"]) for item in plan["queries"]}
    batches = []
    records = []
    failures = []
    for query in plan["queries"]:
        for provider in query["providers"]:
            transport = transports.get(provider)
            if transport is None:
                error = f"no discovery transport supplied for declared provider {provider}"
                if not allow_partial:
                    raise CurieContractError(error)
                failures.append({"provider": provider, "query_id": query["query_id"], "error": error})
                continue
            try:
                handshake = validate_transport_handshake(transport.handshake())
                if handshake["provider"] != provider:
                    raise CurieContractError(
                        f"transport provider {handshake['provider']} does not match QueryPlan provider {provider}"
                    )
                batch = transport.search({
                    "query_id": query["query_id"],
                    "query": query["query"],
                    "page_size": page_size,
                })
                validate_discovery_batch(batch, query_ids=query_ids)
            except Exception as exc:
                if not allow_partial:
                    if isinstance(exc, CurieContractError):
                        raise
                    raise CurieContractError(
                        f"discovery provider {provider} failed: {exc}"
                    ) from exc
                failures.append({
                    "provider": provider,
                    "query_id": query["query_id"],
                    "error": str(exc),
                })
                continue
            batches.append(batch)
            records.extend(batch["records"])
    canonical, duplicates = deduplicate_provider_records(records)
    return {
        "schema_version": "L05MultiSourceDiscovery/v1",
        "query_plan_id": str(plan["plan_id"]),
        "batches": batches,
        "records": canonical,
        "duplicate_paper_ids": duplicates,
        "failures": failures,
    }
