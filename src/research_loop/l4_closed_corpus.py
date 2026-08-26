"""Deterministic full-text resolution inside the L4B boundary."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import html
import json
import ipaddress
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

POLICY = "closed_corpus_exact_asset_only"
RECEIPT_SCHEMA = "L4BFullTextRetrievalReceipt/v1"
MIN_BYTES = 500
MAX_BYTES = 5 * 1024 * 1024
_STATE = {}
_SEARCH_HOSTS = {"google.com", "www.google.com", "bing.com", "www.bing.com", "duckduckgo.com"}
_SECRET_KEYS = ("token", "secret", "password", "authorization", "cookie", "credential", "api_key")


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _sha(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _safe(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_.") or "asset"


def _key(project, candidate):
    return str(Path(project).resolve()), str(candidate)


def _doi(value):
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", str(value or "").strip().lower()).rstrip("/")


def _url(value):
    text = str(value or "").strip()
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        return text
    host = (parsed.hostname or "").lower()
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _unique(values):
    result, seen = [], set()
    for value in values:
        marker = _url(value)
        if marker and marker not in seen:
            seen.add(marker)
            result.append(str(value).strip())
    return result


def _pmcid(asset):
    text = json.dumps(asset.get("source_metadata_response") or {}, ensure_ascii=False)
    text += " " + " ".join(asset.get("full_text_locations") or [])
    text += " " + str(asset.get("url") or "")
    match = re.search(r"\bPMC\d+\b", text, re.I)
    return match.group(0).upper() if match else ""


def build_retrieval_contract(asset):
    return {
        "paper_id": str(asset.get("asset_id") or ""),
        "doi": _doi(asset.get("doi")),
        "pmid": str(asset.get("pmid") or ""),
        "pmcid": _pmcid(asset),
        "registered_locations": _unique(
            list(asset.get("full_text_locations") or [])
            + ([asset["url"]] if asset.get("url") else [])
        ),
        "full_text_status": str(asset.get("full_text_status") or "metadata_only"),
        "retrieval_policy": POLICY,
    }


def _internal_contract(asset):
    contract = build_retrieval_contract(asset)
    contract["_asset"] = copy.deepcopy(asset)
    return contract


def _public(contract):
    return {key: copy.deepcopy(value) for key, value in contract.items() if not key.startswith("_")}


def _identifier(contract):
    for key in ("doi", "pmid", "pmcid", "paper_id"):
        if contract.get(key):
            return f"{key}:{contract[key]}"
    return "unidentified"


def _redact_url(value):
    parsed = urllib.parse.urlsplit(str(value or ""))
    if parsed.scheme.lower() not in {"http", "https"}:
        return str(value or "")
    query = urllib.parse.urlencode([
        (key, "<redacted>")
        for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    ])
    host = parsed.hostname or ""
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def _redact(value, key=""):
    if any(word in key.lower() for word in _SECRET_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return _redact_url(value)
    return value


def _search_url(value):
    parsed = urllib.parse.urlsplit(str(value or ""))
    keys = {key.lower() for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
    return (
        (parsed.hostname or "").lower() in _SEARCH_HOSTS
        or bool(re.search(r"(^|/)(search|query)(/|$)", parsed.path.lower()))
        or bool(keys & {"q", "query", "search", "keywords"})
    )


def _aliases(contract):
    values = []
    if contract.get("pmcid"):
        values += [
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{contract['pmcid']}/fullTextXML",
            f"https://pmc.ncbi.nlm.nih.gov/articles/{contract['pmcid']}/",
        ]
    if contract.get("doi"):
        values.append(f"https://doi.org/{contract['doi']}")
    if contract.get("pmid"):
        values.append(f"https://pubmed.ncbi.nlm.nih.gov/{contract['pmid']}/")
    return _unique(values)


def _validate_public_http_url(value):
    parsed = urllib.parse.urlsplit(str(value or ""))
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("closed-corpus resolver requires an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("closed-corpus resolver rejects credential-bearing URLs")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("closed-corpus resolver rejects local network URLs")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("closed-corpus resolver rejects non-public network URLs")


def validate_request_url(contract, value):
    _validate_public_http_url(value)
    if _search_url(value):
        raise ValueError(f"closed-corpus resolver rejected search URL: {_redact_url(value)}")
    allowed = {
        _url(item)
        for item in list(contract.get("registered_locations") or []) + _aliases(contract)
    }
    if _url(value) not in allowed:
        raise ValueError(f"URL is not registered for selected asset {_identifier(contract)}")


def _local(value):
    return urllib.parse.urlsplit(str(value)).scheme.lower() in {"", "file"}


def _local_path(project, value):
    parsed = urllib.parse.urlsplit(value)
    path = Path(urllib.request.url2pathname(parsed.path)) if parsed.scheme == "file" else Path(value)
    resolved = path.resolve() if path.is_absolute() else (Path(project) / path).resolve()
    try:
        resolved.relative_to(Path(project).resolve())
    except ValueError as exc:
        raise ValueError("registered local full-text path escapes the project") from exc
    return resolved


def _plan(contract):
    plan = []
    for item in contract.get("registered_locations", []):
        if _local(item):
            plan.append((item, "registered_local_payload"))
    if contract.get("pmcid"):
        plan += [
            (
                f"https://www.ebi.ac.uk/europepmc/webservices/rest/{contract['pmcid']}/fullTextXML",
                "europe_pmc_fulltext_xml",
            ),
            (f"https://pmc.ncbi.nlm.nih.gov/articles/{contract['pmcid']}/", "pmc_html"),
        ]
    for item in contract.get("registered_locations", []):
        host = (urllib.parse.urlsplit(item).hostname or "").lower()
        if not _local(item) and host not in {
            "pmc.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "www.ebi.ac.uk"
        }:
            plan.append((item, "registered_publisher_or_doi"))
    if contract.get("doi"):
        plan.append((f"https://doi.org/{contract['doi']}", "doi_alias"))
    for item in contract.get("registered_locations", []):
        host = (urllib.parse.urlsplit(item).hostname or "").lower()
        if not _local(item) and host in {
            "pmc.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "www.ebi.ac.uk"
        }:
            plan.append((item, "registered_identifier_alias"))
    if contract.get("pmid"):
        plan.append((f"https://pubmed.ncbi.nlm.nih.gov/{contract['pmid']}/", "pubmed_alias"))
    result, seen = [], set()
    for location, method in plan:
        marker = (_local(location), _url(location))
        if marker not in seen:
            seen.add(marker)
            result.append((location, method))
    return result


class _RedirectRecorder(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append(str(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(value):
    request = urllib.request.Request(value, headers={
        "User-Agent": "RLR-L4B-Closed-Corpus/1.0",
        "Accept": "application/xml,text/xml,text/html,text/plain",
    })
    redirects = _RedirectRecorder()
    opener = urllib.request.build_opener(redirects)
    with opener.open(request, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
        return {
            "resolved_url": response.geturl(),
            "redirect_chain": redirects.chain,
            "http_status": int(getattr(response, "status", 200)),
            "content_type": str(
                response.headers.get("Content-Type") or "application/octet-stream"
            ),
            "body": body,
        }


def normalized_source_text(value):
    value = html.unescape(str(value or ""))
    # Scientific inequalities such as ``FDR < 0.01`` are common in source
    # text. JATS payloads often encode them as ``&lt;``; after unescaping,
    # a broad ``<...>`` pattern would otherwise discard real evidence.
    value = re.sub(r"</?[A-Za-z][^>]*>|<\?[^>]*>|<![^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def extract_is_contiguous(payload, extract):
    text = normalized_source_text(extract)
    return bool(text) and text in normalized_source_text(payload)


def _score(title):
    title = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    if title in {
        "methods", "method", "materials and methods", "methods and materials",
        "experimental methods", "statistical methods", "methodology",
    }:
        return 100
    if any(word in title for word in ("result", "discussion", "abstract", "reference")):
        return 0
    return 50 if re.search(r"\bmethods?\b|\bmethodology\b", title) else 0


def _methods_xml(payload):
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    best = None
    for section in root.iter():
        if str(section.tag).rsplit("}", 1)[-1].lower() != "sec":
            continue
        title_node = next(
            (
                child for child in list(section)
                if str(child.tag).rsplit("}", 1)[-1].lower() == "title"
            ),
            None,
        )
        title = " ".join(title_node.itertext()).strip() if title_node is not None else ""
        score = _score(title)
        if score and (best is None or score > best[0]):
            text = re.sub(r"\s+", " ", " ".join(section.itertext())).strip()
            best = (
                score,
                {
                    "section": title or "Methods",
                    "text": text,
                    "locator": (
                        f"JATS sec[id={section.attrib.get('id', '')}] title={title}"
                    ),
                    "parser": "jats-xml",
                },
            )
    return best[1] if best else None


def _strip(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _methods_html(payload):
    headings = list(re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", payload, re.I | re.S))
    for index, heading in enumerate(headings):
        title = _strip(heading.group(2))
        if not _score(title):
            continue
        level, end = int(heading.group(1)), len(payload)
        for later in headings[index + 1:]:
            if int(later.group(1)) <= level:
                end = later.start()
                break
        text = f"{title} {_strip(payload[heading.end():end])}".strip()
        return {
            "section": title,
            "text": text,
            "locator": f"HTML h{level} title={title}",
            "parser": "html-heading",
        }
    return None


def extract_methods_section(payload, content_type=""):
    if "xml" in content_type.lower() or "<article" in payload[:1000].lower():
        found = _methods_xml(payload)
        if found:
            return found
    if "html" in content_type.lower() or re.search(r"<h[1-6]\b", payload[:3000], re.I):
        return _methods_html(payload)
    return None


def _identity_ok(contract, requested, response, payload):
    if _local(requested):
        return True
    resolved = str(response.get("resolved_url") or requested)
    try:
        for item in list(response.get("redirect_chain") or []) + [resolved]:
            _validate_public_http_url(item)
            if _search_url(item):
                return False
    except ValueError:
        return False
    haystack = normalized_source_text(payload) + " " + resolved.casefold()
    tokens = [
        str(contract.get(key) or "").casefold()
        for key in ("doi", "pmcid", "pmid")
    ]
    return any(token and token in haystack for token in tokens)


def _attempt(contract, location, method):
    return {
        "requested_url": _redact_url(location),
        "resolved_url": "",
        "asset_identifier": _identifier(contract),
        "retrieval_method": method,
        "retrieved_at": _now(),
        "http_status": 0,
        "content_type": "",
        "byte_length": 0,
        "content_hash": "",
        "redirect_chain": [],
        "parser": "",
        "section_locator": "",
        "failure_reason": "",
    }


def resolve_contract(project, contract, *, fetcher=None):
    fetcher = fetcher or _fetch
    attempts = []
    for location, method in _plan(contract):
        receipt = _attempt(contract, location, method)
        try:
            if _local(location):
                path = _local_path(project, location)
                body = path.read_bytes()
                content_type = (
                    "application/xml" if path.suffix.lower() == ".xml"
                    else "text/html" if path.suffix.lower() in {".html", ".htm"}
                    else "text/plain"
                )
                response = {
                    "resolved_url": location,
                    "redirect_chain": [],
                    "http_status": 200,
                    "content_type": content_type,
                    "body": body,
                }
            else:
                validate_request_url(contract, location)
                response = fetcher(location)
                body = bytes(response.get("body") or b"")
            if len(body) > MAX_BYTES:
                raise ValueError("retrieved source exceeds 5 MiB limit")
            payload = body.decode("utf-8", errors="replace")
            if len(payload.encode("utf-8")) < MIN_BYTES:
                raise ValueError("retrieved source payload must contain at least 500 bytes")
            if not _identity_ok(contract, location, response, payload):
                raise ValueError("redirected payload does not preserve selected asset identity")
            methods = extract_methods_section(
                payload, str(response.get("content_type") or "")
            )
            role = str((contract.get("_asset") or {}).get("role") or "method").lower()
            if role not in {"review", "navigation"} and not methods:
                raise ValueError("no explicit Methods section found")
            if methods and not extract_is_contiguous(payload, methods["text"]):
                raise ValueError("Methods extract is not contiguous in retained payload")
            receipt.update({
                "resolved_url": _redact_url(str(response.get("resolved_url") or location)),
                "http_status": int(response.get("http_status") or 0),
                "content_type": str(response.get("content_type") or ""),
                "byte_length": len(body),
                "content_hash": _sha(body),
                "redirect_chain": [
                    _redact_url(str(item))
                    for item in response.get("redirect_chain") or []
                ],
                "parser": str((methods or {}).get("parser") or "payload-only"),
                "section_locator": str((methods or {}).get("locator") or ""),
            })
            attempts.append(receipt)
            return {
                "status": "resolved",
                "contract": _public(contract),
                "source_payload": payload,
                "source_bytes": body,
                "content_type": receipt["content_type"],
                "methods_section": methods,
                "receipt": copy.deepcopy(receipt),
                "attempts": attempts,
                "local_path": "",
            }
        except (OSError, ValueError) as exc:
            receipt["failure_reason"] = str(exc)
            receipt["http_status"] = int(getattr(exc, "code", 0) or 0)
            attempts.append(receipt)
    return {
        "status": "failed",
        "contract": _public(contract),
        "source_payload": "",
        "source_bytes": b"",
        "content_type": "",
        "methods_section": None,
        "receipt": None,
        "attempts": attempts,
        "local_path": "",
    }


def _match(record, contract):
    return (
        (contract.get("doi") and _doi(record.get("doi")) == contract["doi"])
        or (contract.get("pmid") and str(record.get("pmid") or "") == contract["pmid"])
        or (
            _url(record.get("url"))
            in {_url(item) for item in contract.get("registered_locations", [])}
        )
    )


def _asset_for(result, state):
    paper_id = result["contract"].get("paper_id")
    return next(
        (
            copy.deepcopy(contract.get("_asset") or {})
            for contract in state.get("contracts", [])
            if contract.get("paper_id") == paper_id
        ),
        {},
    )


def enrich_provider_payload(payload, state):
    resolved = [
        result for result in state.get("resolutions", [])
        if result.get("status") == "resolved"
    ]
    for result in resolved:
        result["_asset"] = _asset_for(result, state)
        paper = next(
            (
                record for record in payload.get("papers", [])
                if _match(record, result["contract"])
            ),
            None,
        )
        if paper:
            paper.update({
                "source_payload": result["source_payload"],
                "content_type": result["content_type"],
                "open_access": True,
            })
    usable = [
        result for result in resolved
        if result.get("methods_section")
        and len(result["methods_section"]["text"].encode("utf-8")) >= MIN_BYTES
    ]
    components = {
        component.get("component_id"): component
        for component in payload.get("method_components", [])
    }
    blocked = [
        candidate for candidate in payload.get("method_candidates", [])
        if candidate.get("status") == "needs_user_source"
        and components.get(candidate.get("component_id"), {}).get("required")
    ]
    if len(usable) != 1 or len(blocked) != 1:
        return
    result, candidate = usable[0], blocked[0]
    paper = next(
        (
            record for record in payload.get("papers", [])
            if _match(record, result["contract"])
        ),
        None,
    )
    if not paper:
        return
    method_id = str(candidate["method_id"])
    component_id = str(candidate["component_id"])
    anchor_id = _safe(f"resolved-{result['contract']['paper_id']}-{method_id}")
    methods = result["methods_section"]
    role = str((result.get("_asset") or {}).get("role") or "method").lower()
    source_kind = {
        "primary": "primary_study",
        "protocol": "protocol",
        "method": "method_paper",
    }.get(role, "method_paper")
    paper.setdefault("extracts", []).append({
        "anchor_id": anchor_id,
        "section": methods["section"],
        "text": methods["text"],
        "locator": methods["locator"],
        "extraction_method": f"deterministic-{methods['parser']}",
        "verification_status": "located",
        "method_component_ids": [component_id],
        "method_ids": [method_id],
        "source_kind": source_kind,
    })
    candidate.update({
        "status": "eligible",
        "method_anchor_ids": [anchor_id],
        "missing_source": "",
        "rejection_reasons": [],
    })


def required_source_blocked(payload):
    components = {
        component.get("component_id"): component
        for component in payload.get("method_components", [])
    }
    return [
        candidate for candidate in payload.get("method_candidates", [])
        if candidate.get("status") == "needs_user_source"
        and components.get(candidate.get("component_id"), {}).get("required")
    ]


def render_provider_handoff(state):
    contracts = [_redact(_public(contract)) for contract in state.get("contracts", [])]
    resolved = [{
        "paper_id": result["contract"].get("paper_id"),
        "status": result.get("status"),
        "local_payload_path": result.get("local_path"),
        "content_type": result.get("content_type"),
        "section": (result.get("methods_section") or {}).get("section", ""),
        "section_locator": (result.get("methods_section") or {}).get("locator", ""),
        "content_hash": (result.get("receipt") or {}).get("content_hash", ""),
    } for result in state.get("resolutions", [])]
    return (
        "\n\n=== L4B CLOSED-CORPUS FULL-TEXT CONTRACT ===\n"
        "You must not search for additional literature or expand the frozen corpus.\n"
        "You are allowed and required to read the exact full-text assets already "
        "registered for the selected DOI/PMID/PMCID.\n"
        "Retrieving a registered selected asset is not literature search.\n"
        "Read only the resolved local payload paths below; do not browse, download, "
        "search, or substitute papers.\n"
        "Do not return needs_user_source merely because the selected full text is "
        "online. Return needs_user_source only after all permitted registered-asset "
        "retrieval paths have deterministically failed and those failures have been "
        "recorded.\n"
        f"Contracts: {json.dumps(contracts, ensure_ascii=False, sort_keys=True)}\n"
        f"Resolved assets: {json.dumps(_redact(resolved), ensure_ascii=False, sort_keys=True)}\n"
    )


def resolve_manifest(project, candidate, manifest, work_dir, *, selected_assets, fetcher=None):
    contracts = [_internal_contract(asset) for asset in selected_assets]
    results = [
        resolve_contract(project, contract, fetcher=fetcher)
        for contract in contracts
    ]
    directory = Path(work_dir) / "l4b_resolved_sources"
    directory.mkdir(parents=True, exist_ok=True)
    for result in results:
        if result["status"] == "resolved":
            suffix = (
                ".xml"
                if "xml" in str((result.get("methods_section") or {}).get("parser"))
                else ".html"
            )
            path = directory / f"{_safe(result['contract']['paper_id'])}{suffix}"
            source_bytes = result.get("source_bytes")
            path.write_bytes(
                bytes(source_bytes)
                if isinstance(source_bytes, (bytes, bytearray))
                else result["source_payload"].encode("utf-8")
            )
            result["local_path"] = str(path.resolve())
    state = {
        "manifest_path": manifest.get("path", ""),
        "manifest_sha256": manifest.get("manifest_sha256", ""),
        "contracts": contracts,
        "resolutions": results,
        "provider_payload": None,
    }
    _STATE[_key(project, candidate)] = state
    return state


def persist_debug_evidence(project, artifact, state, *, provider_error=""):
    project = Path(project)
    run_id = _safe(artifact.get("run_id") or "unbound")
    receipts = (
        project / "09_Literature_Database/evidence_packs/retrieval_receipts" / run_id
    )
    providers = project / "09_Literature_Database/evidence_packs/provider_responses"
    receipts.mkdir(parents=True, exist_ok=True)
    providers.mkdir(parents=True, exist_ok=True)
    refs = []
    for result in state.get("resolutions", []):
        data = {
            "schema_version": RECEIPT_SCHEMA,
            "contract": _redact(result["contract"]),
            "status": result["status"],
            "attempts": _redact(result["attempts"]),
            "selected_attempt": _redact(result["receipt"]),
        }
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        path = receipts / f"{_safe(result['contract'].get('paper_id'))}.json"
        path.write_text(raw, encoding="utf-8")
        ref = {
            "paper_id": result["contract"].get("paper_id"),
            "path": path.relative_to(project).as_posix(),
            "sha256": _sha(raw),
            "status": result["status"],
            "section_locator": str(
                (result.get("methods_section") or {}).get("locator") or ""
            ),
        }
        refs.append(ref)
        for paper_ref in artifact.get("papers", []):
            if not _match(paper_ref, result["contract"]):
                continue
            try:
                record_path = project / paper_ref["path"]
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (KeyError, OSError, json.JSONDecodeError):
                continue
            record["retrieval_receipt_path"] = ref["path"]
            record["retrieval_receipt_sha256"] = ref["sha256"]
            record["retrieval_section_locator"] = ref["section_locator"]
            record_path.write_text(
                json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
    provider = {
        "schema_version": "L4BProviderResponse/v1",
        "response_stage": "raw_structured_response_before_deterministic_enrichment",
        "payload": _redact(state.get("provider_payload")),
        "validated_enriched_payload_sha256": state.get("validated_payload_sha256", ""),
        "provider_error": _redact(str(provider_error or "")),
    }
    provider_raw = json.dumps(provider, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    provider_path = providers / f"{run_id}.json"
    provider_path.write_text(provider_raw, encoding="utf-8")
    artifact["full_text_retrieval"] = refs
    artifact["provider_response_path"] = provider_path.relative_to(project).as_posix()
    artifact["provider_response_sha256"] = _sha(provider_raw)
    if artifact.get("path"):
        path = project / artifact["path"]
        path.write_text(
            json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


def install(l4_pipeline_module, deep_research_module):
    dr = deep_research_module
    l4p = l4_pipeline_module
    if getattr(dr, "_l4_closed_corpus_installed", False):
        return
    original_discovery = l4p.run_l4a_discovery
    original_build = dr.build_invocation
    original_validate = dr.validate_payload
    original_run = dr.run_and_persist

    def discovery(*args, **kwargs):
        manifest = original_discovery(*args, **kwargs)
        project = args[0] if args else kwargs["project_dir"]
        candidate = args[1] if len(args) > 1 else kwargs["candidate_id"]
        work_dir = args[5] if len(args) > 5 else kwargs["work_dir"]
        resolve_manifest(
            project,
            candidate,
            manifest,
            work_dir,
            selected_assets=l4p.selected_l4a_assets(manifest, require=True),
            fetcher=getattr(dr, "_l4b_fulltext_fetcher", None),
        )
        return manifest

    def build(*args, **kwargs):
        command, prompt = original_build(*args, **kwargs)
        node = args[1] if len(args) > 1 else kwargs.get("node")
        context = getattr(dr, "_l4b_frozen_manifest_context", None)
        if node == "L4" and context:
            state = _STATE.get(_key(context[0], context[1]))
            if state:
                prompt += render_provider_handoff(state)
        return command, prompt

    def validate(payload, *args, **kwargs):
        context = getattr(dr, "_l4b_frozen_manifest_context", None)
        if context and payload.get("method_components") is not None:
            state = _STATE.get(_key(context[0], context[1]))
            if state:
                state["provider_payload"] = copy.deepcopy(payload)
                enrich_provider_payload(payload, state)
                state["validated_payload_sha256"] = _sha(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True)
                )
                usable = [
                    result for result in state.get("resolutions", [])
                    if result.get("status") == "resolved"
                    and result.get("methods_section")
                ]
                if usable and required_source_blocked(payload):
                    raise dr.DeepResearchError(
                        "L4B resolved registered Methods text but could not bind every "
                        "required source-blocked candidate unambiguously"
                    )
        return original_validate(payload, *args, **kwargs)

    def run(*args, **kwargs):
        project = args[0] if args else kwargs["project_dir"]
        candidate = args[1] if len(args) > 1 else kwargs["candidate_id"]
        node = args[2] if len(args) > 2 else kwargs["node"]
        key = _key(project, candidate)
        if node == "L4":
            _STATE.pop(key, None)
        try:
            artifact = original_run(*args, **kwargs)
            if node == "L4" and key in _STATE:
                persist_debug_evidence(project, artifact, _STATE[key])
            return artifact
        except Exception as exc:
            if node == "L4" and key in _STATE:
                state = _STATE[key]
                run_id = (
                    f"{_safe(candidate)}_L4_retrieval_"
                    f"{str(state.get('manifest_sha256') or 'unbound')[:12]}"
                )
                persist_debug_evidence(
                    project,
                    {"run_id": run_id, "papers": []},
                    state,
                    provider_error=str(exc),
                )
            raise
        finally:
            if node == "L4":
                _STATE.pop(key, None)

    l4p.run_l4a_discovery = discovery
    dr.build_invocation = build
    dr.validate_payload = validate
    dr.run_and_persist = run
    dr._l4_closed_corpus_installed = True
