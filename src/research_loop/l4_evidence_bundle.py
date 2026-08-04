"""Deterministic staged-L4B evidence bundles and required-path audit.

New staged runs use L4A for an identifier-bearing method inventory, L4B for
exact-source retrieval and Methods extraction, and L4C for Fisher's method
components/candidates. L4B records truthful evidence gaps but never creates its
own `required` obligations.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from research_loop import l4_closed_corpus as cc
from research_loop import l4_inventory


EVIDENCE_BUNDLE_SCHEMA = "L4BEvidenceBundle/v2"
DETERMINISTIC_RECEIPT_SCHEMA = "DeterministicResolverReceipt/v2"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _safe(dr, value: Any) -> str:
    return dr._safe_id(str(value or ""))


def _bound_path(project: Path, value: Any, label: str) -> Path:
    """Resolve a project-relative artifact path without permitting escape."""
    relative = Path(str(value or ""))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} must be a non-empty project-relative path")
    root = project.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the project") from exc
    return resolved


def _source_kind(asset: dict) -> str:
    role = str(asset.get("role") or "method").strip().casefold()
    return {
        "primary": "primary_study",
        "method": "method_paper",
        "protocol": "protocol",
    }.get(role, "method_paper")


def _paper_id(dr, asset: dict, result: dict) -> str:
    seed = {
        "asset_id": asset.get("asset_id"),
        "doi": asset.get("doi"),
        "pmid": asset.get("pmid"),
        "url": asset.get("url"),
        "content_hash": (result.get("receipt") or {}).get("content_hash", ""),
    }
    return _safe(dr, _sha(_canonical_json(seed))[:16])


def _receipt_payload(result: dict) -> dict:
    return {
        "schema_version": cc.RECEIPT_SCHEMA,
        "contract": result.get("contract") or {},
        "status": result.get("status") or "failed",
        "attempts": result.get("attempts") or [],
        "selected_attempt": result.get("receipt"),
    }


def _failure_reason(result: dict) -> str:
    attempts = result.get("attempts") or []
    reasons = [
        str(item.get("failure_reason") or "").strip()
        for item in attempts
        if str(item.get("failure_reason") or "").strip()
    ]
    if reasons:
        return reasons[-1]
    if result.get("status") == "resolved" and not result.get("methods_section"):
        return "resolved source has no explicit Methods section"
    return "exact source could not produce a substantive located Methods payload"


def _render_summary(artifact: dict) -> str:
    lines = [
        "# Pre-Research: L4",
        "",
        "## Runtime digest",
        f"Deterministic L4B evidence bundle `{artifact['run_id']}`.",
        "",
        "## Responsibility boundary",
        "L4B retrieves exact registered sources and extracts evidence. It does not define method components, candidates, eligibility, required flags, or the final plan.",
        "",
        "## Accepted evidence cards",
    ]
    cards = artifact.get("evidence_cards") or []
    if cards:
        for card in cards:
            lines.append(
                f"- `{card['evidence_card_id']}` method=`{card['method_id']}` "
                f"source=`{card['source_ref_id']}` @ {card['locator']}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Evidence gaps"])
    gaps = artifact.get("evidence_gaps") or []
    if gaps:
        for gap in gaps:
            lines.append(
                f"- `{gap['evidence_gap_id']}` method=`{gap['method_id']}`: "
                f"{gap['failure_reason']}"
            )
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Evidence pack",
        f"- {artifact['path']}",
        "",
        "## Source count",
        str(len(artifact.get("papers") or [])),
        "",
    ])
    return "\n".join(lines)


def run_l4b_evidence(
    l4p,
    dr,
    project_dir: str | Path,
    candidate_id: str,
    manifest: dict,
    work_dir: str | Path,
    *,
    project_id: str = "",
    round_id: str = "",
    profile_id: str = "",
    research_persona: str = "Curie",
    fetcher=None,
) -> dict:
    """Resolve inventory sources and persist a deterministic L4B bundle."""
    project = Path(project_dir)
    sources, no_source_methods = l4_inventory.inventory_sources(manifest)
    contracts = [cc._internal_contract(asset) for asset in sources]
    results = [
        cc.resolve_contract(project, contract, fetcher=fetcher)
        for contract in contracts
    ]
    result_seed = [{
        "contract": result.get("contract"),
        "status": result.get("status"),
        "content_hash": (result.get("receipt") or {}).get("content_hash", ""),
        "failure_reason": _failure_reason(result),
    } for result in results]
    run_seed = {
        "candidate_id": candidate_id,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "results": result_seed,
        "no_source_methods": [item.get("method_id") for item in no_source_methods],
    }
    run_id = f"{_safe(dr, candidate_id)}_L4_{_sha(_canonical_json(run_seed))[:12]}"

    runs_dir, papers_dir, sources_dir = dr._run_paths(project)
    receipts_dir = (
        project
        / "09_Literature_Database"
        / "evidence_packs"
        / "retrieval_receipts"
        / run_id
    )
    for directory in (runs_dir, papers_dir, sources_dir, receipts_dir):
        directory.mkdir(parents=True, exist_ok=True)

    paper_refs = []
    evidence_cards = []
    evidence_gaps = []
    retrieval_refs = []

    assets_by_id = {str(asset.get("asset_id") or ""): asset for asset in sources}
    for result in results:
        contract = result.get("contract") or {}
        asset_id = str(contract.get("paper_id") or "")
        asset = assets_by_id.get(asset_id, {})
        method_ids = list(asset.get("inventory_method_ids") or [])
        source_ref_ids = list(asset.get("inventory_source_ref_ids") or [])
        source_ref_id = source_ref_ids[0] if source_ref_ids else f"asset:{asset_id}"

        receipt_data = _receipt_payload(result)
        receipt_raw = json.dumps(
            receipt_data, ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"
        receipt_path = receipts_dir / f"{_safe(dr, asset_id)}.json"
        receipt_path.write_text(receipt_raw, encoding="utf-8")
        receipt_ref = {
            "paper_id": asset_id,
            "path": receipt_path.relative_to(project).as_posix(),
            "sha256": _sha(receipt_raw),
            "status": str(result.get("status") or "failed"),
            "section_locator": str(
                (result.get("methods_section") or {}).get("locator") or ""
            ),
        }
        retrieval_refs.append(receipt_ref)

        payload = str(result.get("source_payload") or "")
        methods = result.get("methods_section") or None
        accepted = bool(
            result.get("status") == "resolved"
            and methods
            and len(str(methods.get("text") or "").encode("utf-8")) >= cc.MIN_BYTES
            and cc.extract_is_contiguous(payload, str(methods.get("text") or ""))
        )

        paper_id = _paper_id(dr, asset, result)
        source_path = ""
        extracts = []
        if payload:
            content_type = str(result.get("content_type") or "")
            suffix = ".xml" if "xml" in content_type.casefold() else ".html" if "html" in content_type.casefold() else ".txt"
            source_file = sources_dir / f"{paper_id}{suffix}"
            source_file.write_text(payload, encoding="utf-8")
            source_path = source_file.relative_to(project).as_posix()

        anchor_id = ""
        evidence_id = ""
        if accepted:
            anchor_id = _safe(dr, f"anchor-{asset_id}-{_sha(methods['text'])[:10]}")
            evidence_id = (
                f"{paper_id}:{_safe(dr, methods.get('section') or 'Methods')}:1:"
                f"{_sha(methods['text'])[:10]}"
            )
            extracts.append({
                "evidence_id": evidence_id,
                "anchor_id": anchor_id,
                "section": str(methods.get("section") or "Methods"),
                "text": str(methods.get("text") or ""),
                "locator": str(methods.get("locator") or ""),
                "extraction_method": f"deterministic-{methods.get('parser') or 'source'}",
                "verification_status": "located",
                "source_hash": _sha(payload),
                "method_ids": method_ids,
                "source_ref_ids": source_ref_ids,
                "source_kind": _source_kind(asset),
            })

        if payload:
            record = {
                "schema_version": dr.SCHEMA_VERSION,
                "paper_id": paper_id,
                "asset_id": asset_id,
                "doi": str(asset.get("doi") or ""),
                "pmid": str(asset.get("pmid") or ""),
                "url": str(asset.get("url") or ""),
                "title": str(asset.get("title") or asset_id),
                "source_database": str(asset.get("source_database") or "method_inventory"),
                "metadata": {"year": asset.get("year", 0), "role": asset.get("role", "method")},
                "paper_type": str(asset.get("role") or "method"),
                "retrieved_at": dr._now(),
                "source_metadata_response": asset.get("source_metadata_response") or {},
                "metadata_response_hash": _sha(_canonical_json(asset.get("source_metadata_response") or {})),
                "open_access": True,
                "content_hash": _sha(payload),
                "source_payload_path": source_path,
                "retrieval_receipt_path": receipt_ref["path"],
                "retrieval_receipt_sha256": receipt_ref["sha256"],
                "retrieval_section_locator": receipt_ref["section_locator"],
                "evidence_extracts": extracts,
            }
            paper_path = papers_dir / f"{paper_id}.json"
            paper_path.write_text(
                json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            paper_refs.append({
                "paper_id": paper_id,
                "asset_id": asset_id,
                "path": paper_path.relative_to(project).as_posix(),
                "doi": record["doi"],
                "pmid": record["pmid"],
                "url": record["url"],
                "evidence_ids": [item["evidence_id"] for item in extracts],
            })

        for method_id in method_ids:
            if accepted:
                card_id = _safe(dr, f"card-{method_id}-{asset_id}")
                evidence_cards.append({
                    "evidence_card_id": card_id,
                    "method_id": method_id,
                    "source_ref_id": source_ref_id,
                    "asset_id": asset_id,
                    "paper_id": paper_id,
                    "evidence_id": evidence_id,
                    "anchor_id": anchor_id,
                    "source_kind": _source_kind(asset),
                    "section": str(methods.get("section") or "Methods"),
                    "locator": str(methods.get("locator") or ""),
                    "content_hash": _sha(payload),
                    "status": "accepted",
                })
            else:
                evidence_gaps.append({
                    "evidence_gap_id": _safe(dr, f"gap-{method_id}-{asset_id}"),
                    "method_id": method_id,
                    "source_ref_id": source_ref_id,
                    "asset_id": asset_id,
                    "identifiers": {
                        "doi": str(contract.get("doi") or ""),
                        "pmid": str(contract.get("pmid") or ""),
                        "pmcid": str(contract.get("pmcid") or ""),
                        "registered_locations": list(contract.get("registered_locations") or []),
                    },
                    "attempts": copy.deepcopy(result.get("attempts") or []),
                    "failure_reason": _failure_reason(result),
                    "status": "unresolved",
                })

    for method in no_source_methods:
        method_id = str(method.get("method_id") or "")
        evidence_gaps.append({
            "evidence_gap_id": _safe(dr, f"gap-{method_id}-no-source"),
            "method_id": method_id,
            "source_ref_id": "",
            "asset_id": "",
            "identifiers": {
                "doi": "", "pmid": "", "pmcid": "", "registered_locations": [],
            },
            "attempts": [],
            "failure_reason": "method inventory contains no exact source identifier",
            "status": "unresolved",
        })

    output_hash = _sha(_canonical_json({
        "cards": evidence_cards,
        "gaps": evidence_gaps,
        "retrieval": retrieval_refs,
    }))
    skill_receipt = {
        "schema_version": DETERMINISTIC_RECEIPT_SCHEMA,
        "backend": "deterministic",
        "skill": "closed-corpus-exact-source-resolver",
        "skill_version": "2",
        "command_hash": _sha(_canonical_json([item.get("contract") for item in results])),
        "prompt_hash": str(manifest.get("manifest_sha256") or ""),
        "stdout_hash": output_hash,
        "exit_code": 0,
        "model": "none",
    }
    queries = [
        str(item.get("query") or "").strip()
        for item in manifest.get("queries") or []
        if str(item.get("query") or "").strip()
    ] or ["deterministic exact-source resolution"]
    artifact = {
        "schema_version": dr.SCHEMA_VERSION,
        "evidence_receipt_schema": "EvidenceRunReceipt/v2",
        "evidence_bundle_schema": EVIDENCE_BUNDLE_SCHEMA,
        "kind": "deep_research_run",
        "research_phase": "pre_research",
        "research_persona": research_persona,
        "run_id": run_id,
        "project_id": project_id,
        "round_id": str(round_id),
        "profile_id": profile_id,
        "status": "completed",
        "candidate_id": str(candidate_id),
        "node": "L4",
        "created_at": dr._now(),
        "queries": queries,
        "skill_receipt": skill_receipt,
        "papers": paper_refs,
        "rejected_papers": [],
        "review_search": {
            "query": "none; deterministic exact-source resolution only",
            "status": "not_retained",
            "receipt": "L4B performed no literature or review search.",
        },
        "verification": [],
        "method_inventory": copy.deepcopy(manifest.get("method_inventory") or []),
        "evidence_cards": evidence_cards,
        "evidence_gaps": evidence_gaps,
        "full_text_retrieval": retrieval_refs,
        "pipeline_schema": l4p.PIPELINE_SCHEMA_VERSION,
        "pipeline_stage": "L4B",
        "l4a_manifest_path": manifest["path"],
        "l4a_manifest_sha256": manifest["manifest_sha256"],
        "l4a_run_id": manifest["run_id"],
    }
    run_path = runs_dir / f"{run_id}.json"
    summary_path = runs_dir / f"{run_id}.md"
    artifact["path"] = run_path.relative_to(project).as_posix()
    artifact["summary_path"] = summary_path.relative_to(project).as_posix()
    run_path.write_text(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = _render_summary(artifact)
    summary_path.write_text(summary, encoding="utf-8")
    pre_research = project / "02_Agent_Notes" / "_pre_research" / "L4_research.md"
    pre_research.parent.mkdir(parents=True, exist_ok=True)
    pre_research.write_text(summary, encoding="utf-8")
    l4p._persist_l4b_linkage(project, artifact)
    return artifact


def audit_bundle(l4p, dr, project_dir, candidate_id, artifact: dict) -> tuple[bool, str]:
    project = Path(project_dir).resolve()
    if artifact.get("evidence_bundle_schema") != EVIDENCE_BUNDLE_SCHEMA:
        return False, "unexpected L4B evidence bundle schema"
    if artifact.get("pipeline_stage") != "L4B":
        return False, "evidence bundle is not an L4B artifact"
    if str(artifact.get("candidate_id") or "") != str(candidate_id):
        return False, "L4B evidence candidate mismatch"
    if artifact.get("method_components") or artifact.get("method_candidates"):
        return False, "L4B v2 must not define method components or candidates"
    receipt = artifact.get("skill_receipt") or {}
    if receipt.get("backend") != "deterministic" or receipt.get("exit_code") != 0:
        return False, "L4B deterministic resolver receipt is invalid"

    try:
        manifest_path = _bound_path(
            project, artifact.get("l4a_manifest_path"), "L4A manifest path"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return False, "L4B linked L4A manifest is unreadable or unsafe"
    ok, reason = l4p.validate_l4a_manifest(project, manifest)
    if not ok:
        return False, f"L4A manifest validation failed: {reason}"
    if manifest.get("manifest_sha256") != artifact.get("l4a_manifest_sha256"):
        return False, "L4A manifest SHA256 does not match L4B linkage"

    records = {}
    for ref in artifact.get("papers") or []:
        try:
            path = _bound_path(project, ref["path"], "L4B paper-record path")
            record = json.loads(path.read_text(encoding="utf-8"))
        except (KeyError, ValueError, OSError, json.JSONDecodeError):
            return False, "L4B evidence bundle references an unreadable or unsafe paper record"
        records[str(record.get("paper_id") or "")] = record

    cards = artifact.get("evidence_cards") or []
    card_ids = []
    for card in cards:
        card_id = str(card.get("evidence_card_id") or "")
        if not card_id or card.get("status") != "accepted":
            return False, "L4B accepted evidence card is malformed"
        card_ids.append(card_id)
        record = records.get(str(card.get("paper_id") or ""))
        if not record:
            return False, f"L4B evidence card {card_id} references an unknown paper"
        try:
            source_path = _bound_path(
                project, record.get("source_payload_path"), "L4B source-payload path"
            )
        except ValueError:
            return False, f"L4B evidence card {card_id} source payload path is unsafe"
        if not source_path.is_file():
            return False, f"L4B evidence card {card_id} source payload is missing"
        payload = source_path.read_text(encoding="utf-8")
        if _sha(payload) != str(card.get("content_hash") or ""):
            return False, f"L4B evidence card {card_id} content hash mismatch"
        extracts = {
            str(item.get("evidence_id") or ""): item
            for item in record.get("evidence_extracts") or []
        }
        extract = extracts.get(str(card.get("evidence_id") or ""))
        if not extract:
            return False, f"L4B evidence card {card_id} extract is missing"
        text = str(extract.get("text") or "")
        if len(text.encode("utf-8")) < cc.MIN_BYTES:
            return False, f"L4B evidence card {card_id} extract is below 500 bytes"
        if not str(extract.get("locator") or ""):
            return False, f"L4B evidence card {card_id} locator is missing"
        if not cc.extract_is_contiguous(payload, text):
            return False, f"L4B evidence card {card_id} extract is not contiguous"
        try:
            receipt_path = _bound_path(
                project, record.get("retrieval_receipt_path"), "L4B retrieval-receipt path"
            )
        except ValueError:
            return False, f"L4B evidence card {card_id} retrieval receipt path is unsafe"
        if not receipt_path.is_file():
            return False, f"L4B evidence card {card_id} retrieval receipt is missing"
        if _sha(receipt_path.read_bytes()) != str(record.get("retrieval_receipt_sha256") or ""):
            return False, f"L4B evidence card {card_id} retrieval receipt hash mismatch"
    if len(card_ids) != len(set(card_ids)):
        return False, "L4B evidence_card_id values must be unique"

    gaps = artifact.get("evidence_gaps") or []
    gap_ids = []
    for gap in gaps:
        gap_id = str(gap.get("evidence_gap_id") or "")
        if not gap_id or gap.get("status") != "unresolved":
            return False, "L4B evidence gap is malformed"
        if not str(gap.get("method_id") or "") or not str(gap.get("failure_reason") or ""):
            return False, f"L4B evidence gap {gap_id} lacks method or failure reason"
        gap_ids.append(gap_id)
    if len(gap_ids) != len(set(gap_ids)):
        return False, "L4B evidence_gap_id values must be unique"

    covered = {
        str(item.get("method_id") or "") for item in cards + gaps
    }
    expected = {
        str(item.get("method_id") or "") for item in artifact.get("method_inventory") or []
    }
    if not expected or expected - covered:
        return False, "L4B evidence bundle does not account for every inventory method"
    return True, ""


def _delta_payload(path: Path, dr) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise dr.DeepResearchError(f"L4C delta is unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise dr.DeepResearchError("L4C delta must be a JSON object")
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    return payload


def _validate_required_paths(dr, evidence_artifact: dict, delta: dict) -> tuple[list[dict], list[dict]]:
    if str(delta.get("deep_research_run_id") or "") != str(evidence_artifact.get("run_id") or ""):
        raise dr.DeepResearchError("L4C deep_research_run_id does not match the L4B evidence bundle")
    components = delta.get("method_components") or []
    candidates = delta.get("method_candidates") or []
    if not isinstance(components, list) or not components:
        raise dr.DeepResearchError("L4C requires method_components for staged L4B v2")
    if not isinstance(candidates, list) or not candidates:
        raise dr.DeepResearchError("L4C requires method_candidates for staged L4B v2")

    accepted_cards = {
        str(card.get("evidence_card_id") or "")
        for card in evidence_artifact.get("evidence_cards") or []
        if card.get("status") == "accepted"
    }
    accepted_anchors = {
        str(card.get("anchor_id") or "")
        for card in evidence_artifact.get("evidence_cards") or []
        if card.get("status") == "accepted"
    }
    gap_ids = {
        str(gap.get("evidence_gap_id") or "")
        for gap in evidence_artifact.get("evidence_gaps") or []
    }

    for component in components:
        if not component.get("required"):
            continue
        component_id = str(component.get("component_id") or "")
        required_candidates = [
            candidate for candidate in candidates
            if str(candidate.get("component_id") or "") == component_id
            and candidate.get("status") == "eligible"
            and bool(candidate.get("execution_required"))
        ]
        if not required_candidates:
            raise dr.DeepResearchError(
                f"L4.5 required component {component_id} lacks an eligible execution-required candidate"
            )
        if not any(
            set(candidate.get("evidence_card_ids") or []) <= accepted_cards
            and bool(candidate.get("evidence_card_ids") or [])
            for candidate in required_candidates
        ):
            raise dr.DeepResearchError(
                f"L4.5 required component {component_id} lacks an accepted evidence card"
            )

    for candidate in candidates:
        card_refs = set(candidate.get("evidence_card_ids") or [])
        anchor_refs = set(candidate.get("method_anchor_ids") or [])
        gap_refs = set(candidate.get("evidence_gap_ids") or [])
        if card_refs - accepted_cards:
            raise dr.DeepResearchError(
                f"L4C method {candidate.get('method_id')} references an unknown evidence card"
            )
        if anchor_refs and anchor_refs - accepted_anchors:
            raise dr.DeepResearchError(
                f"L4C method {candidate.get('method_id')} references an unknown method anchor"
            )
        if gap_refs - gap_ids:
            raise dr.DeepResearchError(
                f"L4C method {candidate.get('method_id')} references an unknown evidence gap"
            )
        if (
            candidate.get("status") == "eligible"
            and bool(candidate.get("execution_required"))
            and not card_refs
        ):
            raise dr.DeepResearchError(
                f"L4C execution-required method {candidate.get('method_id')} lacks evidence_card_ids"
            )
    return components, candidates


def install(l4p, dr) -> None:
    """Install staged-v2 production, integrity audit, and L4.5 path gate."""
    if getattr(dr, "_l4_evidence_bundle_installed", False):
        return
    original_run = dr.run_and_persist
    original_audit = dr.audit_evidence_pack
    original_commit = l4p.commit_l45_method_projection

    def run_and_persist(
        project_dir,
        candidate_id,
        node,
        question,
        claim,
        spec,
        work_dir,
        skill_version="unknown",
        result_context="",
        *,
        project_id="",
        round_id="",
        profile_id="",
        research_persona="Curie",
    ):
        if node != "L4":
            return original_run(
                project_dir,
                candidate_id,
                node,
                question,
                claim,
                spec,
                work_dir,
                skill_version,
                result_context,
                project_id=project_id,
                round_id=round_id,
                profile_id=profile_id,
                research_persona=research_persona,
            )
        manifest = l4_inventory.run_discovery(
            l4p,
            dr,
            project_dir,
            candidate_id,
            question,
            claim,
            spec,
            work_dir,
            skill_version,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
        )
        return run_l4b_evidence(
            l4p,
            dr,
            project_dir,
            candidate_id,
            manifest,
            work_dir,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            research_persona=research_persona,
            fetcher=getattr(dr, "_l4b_fulltext_fetcher", None),
        )

    def audit_evidence_pack(project_dir, candidate_id, node, *, run_id=None):
        artifact = dr._artifact(project_dir, candidate_id, node, run_id=run_id)
        if node == "L4" and artifact and artifact.get("evidence_bundle_schema") == EVIDENCE_BUNDLE_SCHEMA:
            return audit_bundle(l4p, dr, project_dir, candidate_id, artifact)
        return original_audit(project_dir, candidate_id, node, run_id=run_id)

    def commit_l45_method_projection(
        project_dir,
        candidate_id,
        evidence_artifact,
        l4c_delta_path,
        *args,
        **kwargs,
    ):
        if evidence_artifact.get("evidence_bundle_schema") != EVIDENCE_BUNDLE_SCHEMA:
            return original_commit(
                project_dir,
                candidate_id,
                evidence_artifact,
                l4c_delta_path,
                *args,
                **kwargs,
            )
        delta_path = Path(l4c_delta_path)
        if not delta_path.is_absolute():
            delta_path = Path(project_dir) / delta_path
        delta = _delta_payload(delta_path, dr)
        components, candidates = _validate_required_paths(dr, evidence_artifact, delta)
        projected = dict(evidence_artifact)
        projected["method_components"] = copy.deepcopy(components)
        projected["method_candidates"] = copy.deepcopy(candidates)
        projected["method_anchors"] = [
            {
                "anchor_id": str(card.get("anchor_id") or ""),
                "evidence_id": str(card.get("evidence_id") or ""),
                "method_component_ids": [],
                "method_ids": [str(card.get("method_id") or "")],
            }
            for card in evidence_artifact.get("evidence_cards") or []
            if card.get("status") == "accepted"
        ]
        return original_commit(
            project_dir,
            candidate_id,
            projected,
            l4c_delta_path,
            *args,
            **kwargs,
        )

    dr.run_and_persist = run_and_persist
    dr.audit_evidence_pack = audit_evidence_pack
    l4p.commit_l45_method_projection = commit_l45_method_projection
    dr._l4_evidence_bundle_original_run = original_run
    dr._l4_evidence_bundle_original_audit = original_audit
    l4p._l4_evidence_bundle_original_commit = original_commit
    dr._l4_evidence_bundle_installed = True
