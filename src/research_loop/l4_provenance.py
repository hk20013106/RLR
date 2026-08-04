"""Fail-closed provenance constraints for the staged L4 pipeline."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from jsonschema import Draft202012Validator

from research_loop.user_sources import verify_registered_source


_IDENTITY_FIELDS = ("project_id", "round_id", "profile_id")
_REVIEW_TYPES = {
    "review", "systematic_review", "systematic review", "meta_analysis",
    "meta analysis", "meta-analysis", "review/meta-analysis",
}
_REVIEW_ROLES = {"review", "systematic_review", "meta_analysis"}
_REVIEW_STATUS_ALIASES = {
    "relevant_review_found": "completed",
    "relevant_review_located": "completed",
    "review_located": "completed",
    "no_relevant_review_found": "none_found",
    "zero_results": "none_found",
}


def _raise(dr, message: str) -> None:
    raise dr.DeepResearchError(message)


def _json_path(error) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    return path or "payload"


def _require_unique(dr, records: list[dict], key: str) -> None:
    values = [str(record.get(key) or "").strip() for record in records]
    if any(not value for value in values):
        _raise(dr, f"L4A {key} values must be non-empty")
    if len(values) != len(set(values)):
        _raise(dr, f"L4A {key} values must be unique")


def _validate_provider_payload(l4p, dr, payload: Any) -> None:
    """Validate a payload after the shared L4A adapter has run."""
    if not isinstance(payload, dict):
        _raise(dr, "L4A payload must be a JSON object")
    validator = Draft202012Validator(l4p.l4a_discovery_schema())
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        _raise(dr, f"L4A payload {_json_path(error)}: {error.message}")
    _require_unique(dr, list(payload.get("queries") or []), "query_id")
    _require_unique(dr, list(payload.get("assets") or []), "asset_id")


def _provider_payload_from_manifest(l4p, dr, manifest: dict) -> dict:
    assets = []
    for raw in manifest.get("assets") or []:
        if not isinstance(raw, dict):
            _raise(dr, "L4A manifest assets must be objects")
        asset = dict(raw)
        metadata = asset.get("source_metadata_response")
        if not isinstance(metadata, dict):
            _raise(dr, "L4A manifest source_metadata_response must be a JSON object")
        asset["source_metadata_response"] = metadata
        assets.append(asset)
    return l4p._canonicalize_l4a_provider_payload({
        "schema_version": manifest.get("schema_version"),
        "queries": manifest.get("queries"),
        "assets": assets,
    })


def _validate_manifest_semantics(l4p, dr, manifest: dict) -> None:
    _validate_provider_payload(
        l4p, dr, _provider_payload_from_manifest(l4p, dr, manifest)
    )
    selected = manifest.get("selected_asset_ids")
    if not isinstance(selected, list) or not all(
        isinstance(value, str) and value.strip() for value in selected
    ):
        _raise(dr, "L4A manifest selected_asset_ids must be a string array")
    if len(selected) != len(set(selected)):
        _raise(dr, "L4A manifest selected_asset_ids must be unique")
    expected = [
        str(asset["asset_id"])
        for asset in manifest.get("assets") or []
        if asset.get("selection_status") == "selected"
    ]
    if selected != expected:
        _raise(
            dr,
            "L4A manifest selected_asset_ids do not match selected assets",
        )
    if not str(manifest.get("candidate_id") or "").strip():
        _raise(dr, "L4A manifest candidate_id must be non-empty")
    if not str(manifest.get("run_id") or "").strip():
        _raise(dr, "L4A manifest run_id must be non-empty")


def _safe_project_path(dr, project: Path, value: str, label: str) -> Path:
    relative = Path(str(value or ""))
    if relative.is_absolute() or ".." in relative.parts or not str(relative):
        _raise(dr, f"{label} path must be project-relative")
    path = (project / relative).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError:
        _raise(dr, f"{label} path escapes the project")
    return path


def _identity_reason(
    manifest: dict,
    artifact: dict,
    *,
    expected_candidate_id: str = "",
) -> str:
    artifact_candidate = str(artifact.get("candidate_id") or "")
    expected_candidate = str(expected_candidate_id or artifact_candidate)
    manifest_candidate = str(manifest.get("candidate_id") or "")
    if not expected_candidate or artifact_candidate != expected_candidate:
        return "L4B candidate_id does not match the requested candidate"
    if manifest_candidate != expected_candidate:
        return "L4A manifest candidate_id does not match L4B candidate_id"

    manifest_run = str(manifest.get("run_id") or "")
    linked_run = str(artifact.get("l4a_run_id") or "")
    if not linked_run or manifest_run != linked_run:
        return "L4A manifest run_id does not match L4B l4a_run_id"

    linked_path = str(artifact.get("l4a_manifest_path") or "")
    if str(manifest.get("path") or "") != linked_path:
        return "L4A manifest path does not match L4B linkage"

    for field in _IDENTITY_FIELDS:
        left = str(manifest.get(field) or "")
        right = str(artifact.get(field) or "")
        if left and right and left != right:
            return f"L4A manifest {field} does not match L4B {field}"
    return ""


def _load_linked_manifest(
    l4p,
    dr,
    project_dir: str | Path,
    artifact: dict,
    *,
    expected_candidate_id: str = "",
) -> dict:
    project = Path(project_dir)
    path = _safe_project_path(
        dr,
        project,
        str(artifact.get("l4a_manifest_path") or ""),
        "L4A manifest",
    )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _raise(dr, f"L4A manifest is unreadable: {exc}")
    if not isinstance(manifest, dict):
        _raise(dr, "L4A manifest must be a JSON object")
    ok, reason = l4p.validate_l4a_manifest(project, manifest)
    if not ok:
        _raise(dr, f"L4A manifest validation failed: {reason}")
    if manifest.get("manifest_sha256") != artifact.get("l4a_manifest_sha256"):
        _raise(dr, "L4A manifest SHA256 does not match L4B linkage")
    identity_error = _identity_reason(
        manifest,
        artifact,
        expected_candidate_id=expected_candidate_id,
    )
    if identity_error:
        _raise(dr, identity_error)
    return manifest


def _normalized_doi(value: Any) -> str:
    return re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        str(value or "").strip().casefold(),
    )


def _normalized_pmid(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalized_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), path, parts.query, "")
    )


def _normalized_role(value: Any) -> str:
    return str(value or "").strip().casefold().replace("-", "_")


def _is_review_record(record: dict) -> bool:
    return _normalized_role(record.get("paper_type")) in _REVIEW_TYPES


def _normalized_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _title_year(record: dict) -> tuple[str, str]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    year = record.get("year") or metadata.get("year") or ""
    return _normalized_title(record.get("title")), str(year).strip()


def _read_paper_record(dr, project: Path, reference: dict) -> dict:
    value = str(reference.get("path") or "")
    if not value:
        return {}
    path = _safe_project_path(dr, project, value, "L4B paper record")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _raise(dr, f"L4B paper record is unreadable: {exc}")
    if not isinstance(record, dict):
        _raise(dr, "L4B paper record must be a JSON object")
    return record


def _coalesced_identifier(
    dr,
    label: str,
    reference: dict,
    record: dict,
    normalizer: Callable[[Any], str],
) -> str:
    left = normalizer(reference.get(label.lower()))
    right = normalizer(record.get(label.lower()))
    if left and right and left != right:
        _raise(dr, f"L4B paper reference has conflicting {label}")
    return left or right


def _selected_identities(l4p, manifest: dict) -> list[dict]:
    selected = l4p.selected_l4a_assets(manifest, require=True)
    return [
        {
            "asset_id": str(item.get("asset_id") or ""),
            "doi": _normalized_doi(item.get("doi")),
            "pmid": _normalized_pmid(item.get("pmid")),
            "url": _normalized_url(item.get("url")),
            "role": _normalized_role(item.get("role")) or "unspecified",
            "title_year": (
                _normalized_title(item.get("title")),
                str(item.get("year") or "").strip(),
            ),
        }
        for item in selected
    ]


def _matching_selected_asset_ids(
    selected: list[dict],
    *,
    doi: str,
    pmid: str,
    url: str,
    title_year: tuple[str, str],
) -> list[str]:
    for key, value in (("doi", doi), ("pmid", pmid), ("url", url)):
        if value:
            owners = _identifier_owners(selected, key, value)
            if owners:
                return sorted(owners)
    if title_year[0]:
        return sorted(
            str(item.get("asset_id") or "")
            for item in selected
            if item.get("title_year") == title_year
        )
    return []


def _identifier_owners(selected: list[dict], key: str, value: str) -> list[str]:
    return [
        str(item.get("asset_id") or "")
        for item in selected
        if value and item.get(key) == value
    ]


def _matches_one_selected_asset(
    selected: list[dict],
    *,
    doi: str,
    pmid: str,
    url: str,
    title_year: tuple[str, str],
) -> tuple[bool, dict]:
    supplied = {"doi": doi, "pmid": pmid, "url": url}
    strong_owners = {
        key: _identifier_owners(selected, key, value)
        for key, value in (("doi", doi), ("pmid", pmid))
        if value and _identifier_owners(selected, key, value)
    }
    strong_asset_ids = {
        asset_id for owners in strong_owners.values() for asset_id in owners
    }
    if len(strong_asset_ids) > 1:
        return False, {
            "asset_ids": sorted(strong_asset_ids),
            "fields": {
                key.upper(): {"supplied": value, "asset_ids": owners}
                for key, owners in strong_owners.items()
                for value in (supplied[key],)
            },
        }

    if len(strong_asset_ids) == 1:
        asset_id = next(iter(strong_asset_ids))
        item = next(item for item in selected if item.get("asset_id") == asset_id)
        conflicts = {}
        for key, value in supplied.items():
            frozen = str(item.get(key) or "")
            if value and frozen and frozen != value:
                conflicts[key.upper()] = {
                    "supplied": value,
                    "frozen": frozen,
                    "asset_ids": _identifier_owners(selected, key, value),
                }
        hard_conflicts = {
            key: value
            for key, value in conflicts.items()
            if key in {"DOI", "PMID"} or value["asset_ids"]
        }
        if hard_conflicts:
            return False, {
                "asset_ids": sorted(
                    {asset_id}
                    | {
                        other_id
                        for value in hard_conflicts.values()
                        for other_id in value["asset_ids"]
                    }
                ),
                "fields": hard_conflicts,
            }
        # DOI/PMID uniquely identify this frozen asset. A different URL is
        # accepted only when no other frozen asset owns it (for example, the
        # real L4B PMC full-text URL for the PubMed-selected A1 record).
        return True, {}

    if doi:
        primary_key, primary_value = "doi", doi
    elif pmid:
        primary_key, primary_value = "pmid", pmid
    elif url:
        primary_key, primary_value = "url", url
    else:
        primary_key, primary_value = "title_year", title_year

    primary_matches = [
        item for item in selected if item.get(primary_key) == primary_value
    ]
    if not primary_matches:
        return False, {}
    return True, {}


def _paper_identity(
    record: dict,
    reference: dict,
    *,
    doi: str,
    pmid: str,
    url: str,
    title_year: tuple[str, str],
) -> str:
    title = str(record.get("title") or reference.get("title") or "").strip()
    year = str(
        record.get("year")
        or (record.get("metadata") or {}).get("year")
        or reference.get("year")
        or title_year[1]
        or ""
    ).strip()
    return (
        f"doi={doi or '<none>'}; pmid={pmid or '<none>'}; "
        f"url={url or '<none>'}; title={title or '<none>'!r}; "
        f"year={year or '<none>'}"
    )


def _format_identifier_conflict(identity: str, details: dict) -> str:
    fields = []
    for label, values in sorted((details.get("fields") or {}).items()):
        supplied = values.get("supplied") or "<none>"
        frozen = values.get("frozen")
        frozen_text = f"; frozen={frozen!r}" if frozen else ""
        owners = ",".join(values.get("asset_ids") or []) or "<none>"
        fields.append(
            f"{label}: supplied={supplied!r}{frozen_text}; "
            f"matching_assets={owners}"
        )
    asset_ids = ",".join(details.get("asset_ids") or []) or "<none>"
    return (
        f"L4B paper {identity} has conflicting identifiers across frozen "
        f"L4A assets [{asset_ids}]: "
        f"{'; '.join(fields) or '<no field details>'}"
    )


def _validate_review_search_contract(
    dr,
    manifest: dict,
    artifact: dict,
    selected: list[dict],
) -> None:
    review = artifact.get("review_search")
    if not isinstance(review, dict) or not str(review.get("receipt") or "").strip():
        _raise(
            dr,
            "L4B review_search must include a truthful receipt for the frozen corpus",
        )
    status = str(review.get("status") or "").strip().casefold()
    status = _REVIEW_STATUS_ALIASES.get(status, status)
    if status not in {"completed", "none_found", "not_retained"}:
        _raise(dr, f"L4B review_search status is invalid for frozen corpus: {status or '<empty>'}")
    selected_reviews = [
        item for item in selected if item.get("role") in _REVIEW_ROLES
    ]
    if not selected_reviews and status != "not_retained":
        _raise(
            dr,
            "L4B frozen L4A catalog has no selected review; review_search "
            "must use status=not_retained and must not search online",
        )


def _validate_frozen_paper(
    l4p,
    dr,
    project: Path,
    candidate_id: str,
    selected: list[dict],
    reference: dict,
    record: dict,
) -> None:
    reference_source = str(reference.get("user_source_id") or "").strip()
    record_source = str(record.get("user_source_id") or "").strip()
    if reference_source and record_source and reference_source != record_source:
        _raise(dr, "L4B paper reference has conflicting user_source_id")
    user_source_id = reference_source or record_source

    doi = _coalesced_identifier(
        dr, "DOI", reference, record, _normalized_doi
    )
    pmid = _coalesced_identifier(
        dr, "PMID", reference, record, _normalized_pmid
    )
    url = _coalesced_identifier(
        dr, "URL", reference, record, _normalized_url
    )
    title_year = _title_year(record or reference)
    matching_ids = _matching_selected_asset_ids(
        selected,
        doi=doi,
        pmid=pmid,
        url=url,
        title_year=title_year,
    )

    if user_source_id:
        sha256 = str(record.get("user_source_sha256") or "").strip()
        ok, reason = verify_registered_source(
            project, candidate_id, user_source_id, sha256
        )
        if not ok:
            _raise(dr, reason)
        if _is_review_record(record) and not any(
            item.get("asset_id") in matching_ids and item.get("role") in _REVIEW_ROLES
            for item in selected
        ):
            _raise(
                dr,
                f"L4B review {record.get('title') or '<untitled>'!r} is not a "
                "selected review in the frozen L4A catalog",
            )
        return

    accepted, conflict_details = _matches_one_selected_asset(
        selected,
        doi=doi,
        pmid=pmid,
        url=url,
        title_year=title_year,
    )
    if conflict_details:
        _raise(
            dr,
            _format_identifier_conflict(
                _paper_identity(
                    record,
                    reference,
                    doi=doi,
                    pmid=pmid,
                    url=url,
                    title_year=title_year,
                ),
                conflict_details,
            ),
        )
    if _is_review_record(record) and not any(
        item.get("asset_id") in matching_ids and item.get("role") in _REVIEW_ROLES
        for item in selected
    ):
        _raise(
            dr,
            f"L4B review {record.get('title') or '<untitled>'!r} is not a "
            "selected review in the frozen L4A catalog",
        )
    if not accepted:
        identity = doi or pmid or url or f"{title_year[0]}|{title_year[1]}"
        _raise(
            dr,
            f"L4B paper {identity or '<unidentified>'} is outside the frozen L4A corpus",
        )


def _validate_frozen_payload(
    l4p,
    dr,
    project_dir: str | Path,
    candidate_id: str,
    payload: dict,
    manifest: dict,
) -> None:
    project = Path(project_dir)
    selected = _selected_identities(l4p, manifest)
    if payload.get("method_components"):
        _validate_review_search_contract(dr, manifest, payload, selected)
    for paper in payload.get("papers") or []:
        if not isinstance(paper, dict):
            _raise(dr, "L4B paper records must be objects")
        reference = {
            key: paper.get(key, "")
            for key in ("doi", "pmid", "url", "user_source_id")
        }
        _validate_frozen_paper(
            l4p, dr, project, candidate_id, selected, reference, paper
        )


def _validate_frozen_corpus(
    l4p,
    dr,
    project_dir: str | Path,
    artifact: dict,
    manifest: dict,
) -> None:
    project = Path(project_dir)
    candidate_id = str(artifact.get("candidate_id") or "")
    selected = _selected_identities(l4p, manifest)
    if artifact.get("method_components"):
        _validate_review_search_contract(dr, manifest, artifact, selected)
    for reference in artifact.get("papers") or []:
        if not isinstance(reference, dict):
            _raise(dr, "L4B paper references must be objects")
        record = _read_paper_record(dr, project, reference)
        _validate_frozen_paper(
            l4p, dr, project, candidate_id, selected, reference, record
        )


def install(l4p, dr, lineage_module) -> None:
    """Install validation before lineage and ledger consumers capture references."""
    if getattr(l4p, "_l4_provenance_installed", False):
        return

    original_validate_manifest = l4p.validate_l4a_manifest

    def validate_l4a_manifest(project_dir, manifest):
        ok, reason = original_validate_manifest(project_dir, manifest)
        if not ok:
            return ok, reason
        try:
            _validate_manifest_semantics(l4p, dr, manifest)
        except dr.DeepResearchError as exc:
            return False, str(exc)
        return True, ""

    l4p.validate_l4a_manifest = validate_l4a_manifest
    lineage_module.validate_l4a_manifest = validate_l4a_manifest

    original_persist_discovery = l4p.persist_l4a_discovery

    def persist_l4a_discovery(
        project_dir,
        candidate_id,
        payload,
        runtime_receipt,
        *,
        question,
        claim,
        project_id="",
        round_id="",
        profile_id="",
    ):
        if not str(candidate_id or "").strip():
            _raise(dr, "L4A candidate_id must be non-empty")
        canonical_payload = l4p._canonicalize_l4a_provider_payload(payload)
        _validate_provider_payload(l4p, dr, canonical_payload)
        artifact = original_persist_discovery(
            project_dir,
            candidate_id,
            canonical_payload,
            runtime_receipt,
            question=question,
            claim=claim,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
        )
        ok, reason = l4p.validate_l4a_manifest(project_dir, artifact)
        if not ok:
            try:
                (Path(project_dir) / str(artifact.get("path") or "")).unlink(
                    missing_ok=True
                )
            except OSError:
                pass
            _raise(dr, f"persisted L4A manifest validation failed: {reason}")
        return artifact

    l4p.persist_l4a_discovery = persist_l4a_discovery

    original_persist_linkage = l4p._persist_l4b_linkage

    def persist_l4b_linkage(project_dir, artifact):
        if (
            artifact.get("pipeline_schema") == l4p.PIPELINE_SCHEMA_VERSION
            and artifact.get("pipeline_stage") == "L4B"
        ):
            manifest = _load_linked_manifest(l4p, dr, project_dir, artifact)
            _validate_frozen_corpus(l4p, dr, project_dir, artifact, manifest)
        return original_persist_linkage(project_dir, artifact)

    l4p._persist_l4b_linkage = persist_l4b_linkage

    def validate_l4b_payload_before_persistence(project_dir, candidate_id, payload):
        context = getattr(dr, "_l4b_frozen_manifest_context", None)
        if not context:
            return
        context_project, context_candidate, manifest = context
        if (
            Path(project_dir).resolve() != Path(context_project).resolve()
            or str(candidate_id) != str(context_candidate)
        ):
            _raise(dr, "L4B frozen manifest context does not match the payload project or candidate")
        _validate_frozen_payload(
            l4p, dr, project_dir, str(candidate_id), payload, manifest
        )

    dr._l4b_pre_persist_validator = validate_l4b_payload_before_persistence

    original_commit = l4p.commit_l45_method_projection

    def commit_l45_method_projection(
        project_dir,
        candidate_id,
        evidence_artifact,
        l4c_delta_path,
    ):
        if (
            evidence_artifact.get("pipeline_schema") == l4p.PIPELINE_SCHEMA_VERSION
            and evidence_artifact.get("pipeline_stage") == "L4B"
        ):
            manifest = _load_linked_manifest(
                l4p,
                dr,
                project_dir,
                evidence_artifact,
                expected_candidate_id=str(candidate_id),
            )
            _validate_frozen_corpus(
                l4p, dr, project_dir, evidence_artifact, manifest
            )
        return original_commit(
            project_dir,
            candidate_id,
            evidence_artifact,
            l4c_delta_path,
        )

    l4p.commit_l45_method_projection = commit_l45_method_projection

    original_lineage_validate = lineage_module._validate_link

    def validate_lineage_link(module, project_dir, artifact):
        ok, reason, path = original_lineage_validate(
            module, project_dir, artifact
        )
        if not ok or path is None:
            return ok, reason, path
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"L4A manifest is unreadable: {exc}", None
        identity_error = _identity_reason(manifest, artifact)
        if identity_error:
            return False, identity_error, None
        try:
            _validate_frozen_corpus(
                l4p, dr, project_dir, artifact, manifest
            )
        except dr.DeepResearchError as exc:
            return False, str(exc), None
        return True, "", path

    lineage_module._validate_link = validate_lineage_link

    l4p._l4_provenance_original_validate_manifest = original_validate_manifest
    l4p._l4_provenance_original_persist_discovery = original_persist_discovery
    l4p._l4_provenance_original_persist_linkage = original_persist_linkage
    l4p._l4_provenance_original_commit = original_commit
    l4p._l4_provenance_installed = True
