"""Component-level L4 method evidence extension.

The extension is installed by :mod:`research_loop.__init__` after the base
``deep_research`` module loads.  Keeping the method-catalog responsibility in a
focused module avoids further enlarging the runtime/provider implementation.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

from research_loop.user_sources import registered_sources, verify_registered_source


_ACCEPTED_SOURCE_KINDS = {
    "primary_study", "method_paper", "protocol", "supplementary_methods",
    "official_documentation", "versioned_code", "user_supplied_pdf",
}
_NAVIGATION_SOURCE_KIND = "navigation_only"
_METHODS_HEADING_KINDS = {
    "primary_study", "supplementary_methods", "user_supplied_pdf",
}
_PLACEHOLDER_PATTERNS = (
    "open-access full text was retrieved",
    "full text was retrieved; the located",
    "the located methods extract is retained below",
)
_MIN_SOURCE_BYTES = 500


def _string_array_schema(*, min_items=0):
    return {
        "type": "array", "minItems": min_items,
        "items": {"type": "string", "minLength": 1},
    }


def _method_component_schema():
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "component_id": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1},
            "required": {"type": "boolean"},
            "rationale": {"type": "string", "minLength": 1},
        },
        "required": ["component_id", "name", "required", "rationale"],
    }


def _method_candidate_schema():
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "method_id": {"type": "string", "minLength": 1},
            "component_id": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1},
            "status": {"enum": ["eligible", "ineligible", "needs_user_source"]},
            "purpose": {"type": "string", "minLength": 1},
            "applicable_to": _string_array_schema(min_items=1),
            "implementation_steps": _string_array_schema(min_items=1),
            "assumptions": _string_array_schema(),
            "expected_outputs": _string_array_schema(min_items=1),
            "strengths": _string_array_schema(),
            "limitations": _string_array_schema(),
            "alternatives": _string_array_schema(),
            "rejection_reasons": _string_array_schema(),
            "method_anchor_ids": _string_array_schema(),
            "missing_source": {"type": "string"},
        },
        "required": [
            "method_id", "component_id", "name", "status", "purpose",
            "applicable_to", "implementation_steps", "assumptions",
            "expected_outputs", "strengths", "limitations", "alternatives",
            "rejection_reasons", "method_anchor_ids", "missing_source",
        ],
    }


def _extend_l4_schema(schema: dict) -> dict:
    schema["properties"]["review_search"]["properties"]["status"] = {
        "enum": ["completed", "none_found", "not_retained"],
    }
    extract = schema["properties"]["papers"]["items"]["properties"]["extracts"]["items"]
    extract["properties"].update({
        "anchor_id": {"type": "string"},
        "method_component_ids": _string_array_schema(),
        "method_ids": _string_array_schema(),
        "source_kind": {
            "enum": sorted(_ACCEPTED_SOURCE_KINDS | {_NAVIGATION_SOURCE_KIND, ""})
        },
    })
    extract["required"].extend([
        "anchor_id", "method_component_ids", "method_ids", "source_kind",
    ])
    paper = schema["properties"]["papers"]["items"]
    paper["properties"].update({
        "user_source_id": {"type": "string"},
        "user_source_sha256": {"type": "string"},
    })
    paper["required"].extend(["user_source_id", "user_source_sha256"])
    schema["properties"].update({
        "method_components": {
            "type": "array", "minItems": 1, "items": _method_component_schema(),
        },
        "method_candidates": {
            "type": "array", "minItems": 1, "items": _method_candidate_schema(),
        },
    })
    schema["required"].extend(["method_components", "method_candidates"])
    return schema


def _normalize_source_text(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.translate(str.maketrans({
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
        "―": "-", "−": "-",
    }))
    return re.sub(r"\s+", " ", value).strip().casefold()


def _validate_payload_source(dr, paper: dict, extract: dict,
                             project_dir: str | Path | None,
                             candidate_id: str) -> None:
    payload = str(paper.get("source_payload") or "")
    if len(payload.encode("utf-8")) < _MIN_SOURCE_BYTES:
        raise dr.DeepResearchError(
            f"L4 source payload must contain at least {_MIN_SOURCE_BYTES} bytes of real source text"
        )
    normalized_payload = _normalize_source_text(payload)
    if any(pattern in normalized_payload for pattern in _PLACEHOLDER_PATTERNS):
        raise dr.DeepResearchError("L4 source payload is a retrieval placeholder, not source text")
    normalized_extract = _normalize_source_text(extract.get("text", ""))
    if not normalized_extract or normalized_extract not in normalized_payload:
        raise dr.DeepResearchError("L4 located extract is not present in the retained source payload")
    source_kind = str(extract.get("source_kind") or "")
    if source_kind not in _ACCEPTED_SOURCE_KINDS:
        raise dr.DeepResearchError(f"unsupported L4 method source kind: {source_kind}")
    if source_kind in _METHODS_HEADING_KINDS and not dr._is_methods_section(extract.get("section")):
        raise dr.DeepResearchError(
            f"{source_kind} anchor must be located in Methods or a Methods subsection"
        )
    if source_kind == "user_supplied_pdf":
        if project_dir is None or not candidate_id:
            raise dr.DeepResearchError("user-supplied PDF evidence requires project and candidate binding")
        ok, reason = verify_registered_source(
            project_dir, candidate_id,
            str(paper.get("user_source_id") or ""),
            str(paper.get("user_source_sha256") or ""),
        )
        if not ok:
            raise dr.DeepResearchError(reason)


def _validate_l4_payload(dr, payload: dict, project_dir=None, candidate_id="") -> None:
    components = payload.get("method_components")
    candidates = payload.get("method_candidates")
    if not isinstance(components, list) or not components:
        raise dr.DeepResearchError("L4 payload requires method_components")
    if not isinstance(candidates, list) or not candidates:
        raise dr.DeepResearchError("L4 payload requires method_candidates")

    component_ids = []
    for component in components:
        if not isinstance(component, dict):
            raise dr.DeepResearchError("L4 method components must be objects")
        component_id = str(component.get("component_id") or "").strip()
        if not component_id or not str(component.get("name") or "").strip():
            raise dr.DeepResearchError("each L4 method component needs component_id and name")
        if not str(component.get("rationale") or "").strip():
            raise dr.DeepResearchError("each L4 method component needs a rationale")
        component_ids.append(component_id)
    if len(component_ids) != len(set(component_ids)):
        raise dr.DeepResearchError("L4 method component IDs must be unique")
    if not any(bool(component.get("required")) for component in components):
        raise dr.DeepResearchError("L4 requires at least one required method component")

    method_ids = []
    candidate_by_id = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise dr.DeepResearchError("L4 method candidates must be objects")
        method_id = str(candidate.get("method_id") or "").strip()
        component_id = str(candidate.get("component_id") or "").strip()
        if not method_id or component_id not in component_ids:
            raise dr.DeepResearchError("L4 method candidate references an unknown component")
        status = candidate.get("status")
        if status not in {"eligible", "ineligible", "needs_user_source"}:
            raise dr.DeepResearchError("L4 method candidate status is invalid")
        for field in ("name", "purpose"):
            if not str(candidate.get(field) or "").strip():
                raise dr.DeepResearchError(f"L4 method candidate requires {field}")
        for field in (
            "applicable_to", "implementation_steps", "assumptions",
            "expected_outputs", "strengths", "limitations", "alternatives",
            "rejection_reasons", "method_anchor_ids",
        ):
            if not isinstance(candidate.get(field), list):
                raise dr.DeepResearchError(f"L4 method candidate {field} must be a list")
        if status == "eligible" and not candidate["method_anchor_ids"]:
            raise dr.DeepResearchError("eligible L4 method candidate requires method_anchor_ids")
        if status == "ineligible" and not candidate["rejection_reasons"]:
            raise dr.DeepResearchError("ineligible L4 method candidate requires rejection_reasons")
        if status == "needs_user_source" and not str(candidate.get("missing_source") or "").strip():
            raise dr.DeepResearchError("source-blocked L4 candidate requires missing_source")
        method_ids.append(method_id)
        candidate_by_id[method_id] = candidate
    if len(method_ids) != len(set(method_ids)):
        raise dr.DeepResearchError("L4 method IDs must be unique")

    anchor_ids = set()
    for paper in payload.get("papers", []):
        for extract in paper.get("extracts", []):
            anchor_id = str(extract.get("anchor_id") or "").strip()
            if not anchor_id or anchor_id in anchor_ids:
                raise dr.DeepResearchError("L4 anchor IDs must be non-empty and unique")
            anchor_ids.add(anchor_id)
            component_refs = extract.get("method_component_ids")
            method_refs = extract.get("method_ids")
            if (not isinstance(component_refs, list) or not component_refs
                    or any(value not in component_ids for value in component_refs)):
                raise dr.DeepResearchError("L4 anchor references an unknown method component")
            if (not isinstance(method_refs, list) or not method_refs
                    or any(value not in method_ids for value in method_refs)):
                raise dr.DeepResearchError("L4 anchor references an unknown method candidate")
            if any(candidate_by_id[value]["component_id"] not in component_refs
                   for value in method_refs):
                raise dr.DeepResearchError("L4 anchor method/component references are inconsistent")
            _validate_payload_source(dr, paper, extract, project_dir, candidate_id)

    for candidate in candidates:
        if any(anchor_id not in anchor_ids for anchor_id in candidate["method_anchor_ids"]):
            raise dr.DeepResearchError("L4 method candidate references an unknown anchor ID")


def _registered_source_prompt(records: list[dict]) -> str:
    if not records:
        return "\nRegistered user-supplied PDFs: none.\n"
    lines = ["", "Registered user-supplied PDFs (registration alone is not evidence):"]
    for record in records:
        identifier = record.get("doi") or record.get("pmid") or record.get("url") or "no external identifier"
        lines.append(
            f"- user_source_id={record['user_source_id']} sha256={record['sha256']} "
            f"path={record['stored_path']} identifier={identifier}"
        )
    lines.append("Read only relevant registered PDFs, return extracted source text, and bind the exact ID and SHA256.")
    return "\n".join(lines) + "\n"


def _render_list(values) -> str:
    values = [str(value) for value in (values or [])]
    return "; ".join(values) if values else "_none_"


def _render_l4_markdown(artifact: dict) -> str:
    receipt = artifact["skill_receipt"]
    lines = [
        "# Pre-Research: L4",
        "",
        "## Runtime digest",
        f"Verified Academic Research evidence pack `{artifact['run_id']}`.",
        "",
        "## Method Candidate Catalog",
        "L4 constructs the comparison pool. L5 critiques every eligible candidate; L6 selects the executable method.",
    ]
    components = {item["component_id"]: item for item in artifact.get("method_components", [])}
    anchors = {item["anchor_id"]: item for item in artifact.get("method_anchors", [])}
    project_hint = artifact.get("project_dir_hint") or "<project_dir>"
    for component_id, component in components.items():
        lines.extend([
            "", f"### Component `{component_id}` — {component['name']}",
            f"- Required: {bool(component.get('required'))}",
            f"- Rationale: {component.get('rationale', '')}",
        ])
        for candidate in artifact.get("method_candidates", []):
            if candidate.get("component_id") != component_id:
                continue
            lines.extend([
                "", f"#### `{candidate['method_id']}` — {candidate['name']}",
                f"- Status: `{candidate['status']}`",
                f"- Purpose: {candidate['purpose']}",
                f"- Applicable input: {_render_list(candidate['applicable_to'])}",
                f"- Implementation steps: {_render_list(candidate['implementation_steps'])}",
                f"- Assumptions: {_render_list(candidate['assumptions'])}",
                f"- Expected outputs: {_render_list(candidate['expected_outputs'])}",
                f"- Strengths: {_render_list(candidate['strengths'])}",
                f"- Limitations: {_render_list(candidate['limitations'])}",
                f"- Alternatives: {_render_list(candidate['alternatives'])}",
                f"- Rejection reasons: {_render_list(candidate['rejection_reasons'])}",
                "- Evidence anchors:",
            ])
            for anchor_id in candidate.get("method_anchor_ids", []):
                anchor = anchors.get(anchor_id)
                if anchor:
                    lines.append(
                        f"  - `{anchor_id}`: {anchor['title']} [{anchor['source_kind']}] "
                        f"@ {anchor['locator']} (`{anchor['evidence_id']}`)"
                    )
                else:
                    lines.append(f"  - `{anchor_id}`: unresolved")
            if candidate.get("status") == "needs_user_source":
                lines.extend([
                    f"- Missing source: {candidate.get('missing_source', '')}",
                    "- Register a legally obtained PDF:",
                    f"  `python scripts/import_literature_pdf.py \"{project_hint}\" "
                    f"{artifact['candidate_id']} --file \"<path-to.pdf>\"`",
                    "- Registration alone does not satisfy L4; ARS must extract and RLR must verify located Methods text.",
                ])
    queries = "\n".join(f"- {query}" for query in artifact.get("queries", []))
    lines.extend([
        "", "## Evidence pack", f"- {artifact['path']}",
        "", "## Query log", queries,
        "", "## Tool receipt",
        f"- {receipt['backend']} / {receipt['skill']} {receipt.get('skill_version', '')}; "
        f"command_hash={receipt['command_hash']}; prompt_hash={receipt['prompt_hash']}",
        "", "## Source count", str(len(artifact.get("papers", []))), "",
    ])
    return "\n".join(lines)


def install(deep_research_module) -> None:
    """Install L4-specific behavior while preserving legacy evidence readers."""
    dr = deep_research_module
    if getattr(dr, "_METHOD_EVIDENCE_INSTALLED", False):
        return

    original_runtime_schema = dr._runtime_schema
    original_build_invocation = dr.build_invocation
    original_validate_payload = dr.validate_payload
    original_persist_run = dr.persist_run
    original_audit = dr.audit_evidence_pack
    original_render = dr.render_pre_research_markdown

    def runtime_schema(node: str | None = None) -> dict:
        schema = original_runtime_schema()
        return _extend_l4_schema(schema) if node == "L4" else schema

    def build_invocation(spec, node, question, claim, work_dir, result_context="",
                         user_sources=None):
        command, prompt = original_build_invocation(
            spec, node, question, claim, work_dir, result_context
        )
        if node == "L4":
            prompt += """
Identify the critical method components implied by this study. For each component,
construct comparable method candidates with purpose, applicable inputs,
implementation steps, assumptions, expected outputs, strengths, limitations,
alternatives, and evidence-anchor IDs. A relevant biological paper and the
implementation anchor may be different sources. Prefer PMC/Europe PMC JATS XML,
OA HTML/XML, Supplementary Methods, method/protocol papers, official software
documentation, versioned code, and preprints. Abstract labels, table mentions,
reviews, and retrieval placeholders do not count as method anchors.
For review or navigation-only extracts, set `anchor_id` to an empty string,
`method_component_ids` and `method_ids` to empty arrays, and `source_kind` to
`navigation_only`; do not claim method anchors for those extracts.
For every retained method anchor, `source_payload` must contain at least 500
bytes of the actual retrieved source text and the exact extract text must be
present in that payload. If that evidence cannot be retrieved, do not retain
a method anchor; mark the candidate as source-blocked or use navigation-only
fields instead.
The extract text must be copied verbatim as one contiguous substring from the
retained source payload; do not paraphrase, normalize, or reconstruct it.
For `source_kind` `primary_study` or `supplementary_methods`, the extract
section must be `Methods` or a Methods subsection; Results and Discussion text
from those papers is not a method anchor.
MUST NOT use a primary-study Results, Discussion, abstract, table, or review
extract as a method anchor; assign those extracts `navigation_only` fields.
Do not perform online literature or review searches in L4B. The output MUST
include a `review_search` object with a truthful receipt. If the frozen L4A
catalog has no selected asset with `role=review`, set `status` to
`not_retained`, explain that no selected review was retained, and emit no
review paper. A selected review may be used only as navigation evidence.
The `method_components` array MUST contain at least one component with
`required: true`; every required component must have an eligible candidate
with a real accepted method anchor, or a truthful source-blocked candidate.
"""
            prompt += _registered_source_prompt(list(user_sources or []))
        return command, prompt

    def validate_payload(payload, *, node=None, project_dir=None, candidate_id=""):
        original_validate_payload(payload)
        if node == "L4" and payload.get("method_components") is not None:
            _validate_l4_payload(dr, payload, project_dir, candidate_id)

    def persist_run(project_dir, candidate_id, node, payload, receipt,
                    result_context="", *, project_id="", round_id="",
                    profile_id="", research_persona="Curie"):
        if node != "L4" or payload.get("method_components") is None:
            return original_persist_run(
                project_dir, candidate_id, node, payload, receipt, result_context,
                project_id=project_id, round_id=round_id, profile_id=profile_id,
                research_persona=research_persona,
            )
        validate_payload(
            payload, node=node, project_dir=project_dir, candidate_id=candidate_id
        )
        if receipt.get("exit_code") != 0 or not receipt.get("command_hash") or not receipt.get("prompt_hash"):
            raise dr.DeepResearchError("skill receipt is incomplete or records a failed invocation")
        project = Path(project_dir)
        runs_dir, papers_dir, sources_dir = dr._run_paths(project)
        for directory in (runs_dir, papers_dir, sources_dir):
            directory.mkdir(parents=True, exist_ok=True)
        run_seed = json.dumps({
            "candidate_id": candidate_id, "node": node, "payload": payload,
            "receipt": receipt,
        }, ensure_ascii=False, sort_keys=True)
        run_id = f"{dr._safe_id(candidate_id)}_L4_{dr._sha(run_seed)[:12]}"
        records = []
        method_anchors = []
        for paper in payload["papers"]:
            identity = str(paper.get("doi") or paper.get("pmid") or paper.get("url")
                           or paper.get("user_source_id"))
            paper_snapshot = json.dumps({
                "identity": identity,
                "source_metadata_response": paper.get("source_metadata_response"),
                "source_payload": paper.get("source_payload"),
                "extracts": paper.get("extracts", []),
            }, ensure_ascii=False, sort_keys=True)
            paper_id = dr._safe_id(dr._sha(paper_snapshot)[:16])
            source_payload = str(paper.get("source_payload") or "")
            source_path = ""
            if source_payload:
                ext = ".html" if "html" in str(paper.get("content_type", "")).lower() else ".txt"
                source_file = sources_dir / f"{paper_id}{ext}"
                source_file.write_text(source_payload, encoding="utf-8")
                source_path = source_file.relative_to(project).as_posix()
            extracts = []
            for index, extract in enumerate(paper.get("extracts", []), 1):
                evidence_id = (
                    f"{paper_id}:{dr._safe_id(str(extract['section']))}:{index}:"
                    f"{dr._sha(extract['text'])[:10]}"
                )
                saved = {
                    "evidence_id": evidence_id,
                    "anchor_id": extract["anchor_id"],
                    "section": extract["section"],
                    "text": extract["text"],
                    "locator": extract["locator"],
                    "extraction_method": extract.get("extraction_method", "source-located"),
                    "verification_status": extract.get("verification_status", "located"),
                    "source_hash": dr._sha(source_payload),
                    "method_component_ids": list(extract["method_component_ids"]),
                    "method_ids": list(extract["method_ids"]),
                    "source_kind": extract["source_kind"],
                }
                extracts.append(saved)
                method_anchors.append({
                    "anchor_id": extract["anchor_id"],
                    "evidence_id": evidence_id,
                    "paper_id": paper_id,
                    "title": paper["title"],
                    "source_kind": extract["source_kind"],
                    "locator": extract["locator"],
                    "method_component_ids": list(extract["method_component_ids"]),
                    "method_ids": list(extract["method_ids"]),
                })
            record = {
                "schema_version": dr.SCHEMA_VERSION,
                "paper_id": paper_id,
                "doi": paper.get("doi", ""),
                "pmid": paper.get("pmid", ""),
                "url": paper.get("url", ""),
                "user_source_id": paper.get("user_source_id", ""),
                "user_source_sha256": paper.get("user_source_sha256", ""),
                "title": paper["title"],
                "source_database": paper["source_database"],
                "metadata": paper.get("metadata", {}),
                "paper_type": str(paper.get("paper_type", "primary")),
                "retrieved_at": dr._now(),
                "source_metadata_response": paper["source_metadata_response"],
                "metadata_response_hash": dr._sha(json.dumps(
                    paper["source_metadata_response"], ensure_ascii=False, sort_keys=True
                )),
                "open_access": bool(paper.get("open_access")),
                "content_hash": dr._sha(source_payload),
                "source_payload_path": source_path,
                "evidence_extracts": extracts,
            }
            paper_file = papers_dir / f"{paper_id}.json"
            paper_file.write_text(
                json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            records.append({
                "paper_id": paper_id,
                "path": paper_file.relative_to(project).as_posix(),
                "doi": record["doi"], "pmid": record["pmid"], "url": record["url"],
                "user_source_id": record["user_source_id"],
                "evidence_ids": [item["evidence_id"] for item in extracts],
            })
        artifact = {
            "schema_version": dr.SCHEMA_VERSION,
            "evidence_receipt_schema": "EvidenceRunReceipt/v1.2",
            "kind": "deep_research_run",
            "research_phase": "pre_research",
            "research_persona": research_persona,
            "run_id": run_id,
            "project_id": project_id,
            "project_dir_hint": str(project),
            "round_id": str(round_id),
            "profile_id": profile_id,
            "status": "completed",
            "candidate_id": candidate_id,
            "node": node,
            "created_at": dr._now(),
            "queries": payload["queries"],
            "skill_receipt": receipt,
            "papers": records,
            "rejected_papers": [],
            "review_search": payload.get("review_search", {}),
            "verification": payload.get("verification", []),
            "method_components": payload["method_components"],
            "method_candidates": payload["method_candidates"],
            "method_anchors": method_anchors,
            "result_context_hash": dr._sha(result_context) if result_context else "",
        }
        run_file = runs_dir / f"{run_id}.json"
        summary_file = runs_dir / f"{run_id}.md"
        artifact["path"] = run_file.relative_to(project).as_posix()
        artifact["summary_path"] = summary_file.relative_to(project).as_posix()
        run_file.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        summary_file.write_text(_render_l4_markdown(artifact), encoding="utf-8")
        return artifact

    def audit_evidence_pack(project_dir, candidate_id, node, *, run_id=None):
        artifact = dr._artifact(project_dir, candidate_id, node, run_id=run_id)
        if node != "L4" or not artifact or not artifact.get("method_components"):
            return original_audit(project_dir, candidate_id, node, run_id=run_id)
        receipt = artifact.get("skill_receipt") or {}
        if artifact.get("status") != "completed" or receipt.get("exit_code") != 0:
            return False, "evidence pack has no successful skill receipt"
        review = artifact.get("review_search") or {}
        if review.get("status") not in {"completed", "none_found", "not_retained"} or not review.get("receipt"):
            return False, "L4 requires a review search receipt or documented zero-result search"
        root = Path(project_dir)
        accepted_anchors = set()
        records = []
        for ref in artifact.get("papers", []):
            try:
                record = json.loads((root / ref["path"]).read_text(encoding="utf-8"))
            except (KeyError, OSError, json.JSONDecodeError):
                return False, "evidence pack references an unreadable paper record"
            records.append(record)
            source_path = str(record.get("source_payload_path") or "")
            if not source_path or not (root / source_path).is_file():
                continue
            payload = (root / source_path).read_text(encoding="utf-8")
            paper = dict(record)
            paper["source_payload"] = payload
            for extract in record.get("evidence_extracts", []):
                try:
                    _validate_payload_source(dr, paper, extract, root, candidate_id)
                except dr.DeepResearchError:
                    continue
                accepted_anchors.add(str(extract.get("anchor_id") or ""))
        if review.get("status") == "completed":
            review_extracts = [
                extract
                for record in records
                if str(record.get("paper_type", "")).lower() in {
                    "review", "systematic_review", "meta_analysis"
                }
                for extract in record.get("evidence_extracts", [])
                if extract.get("verification_status") == "located" and extract.get("locator")
            ]
            if (not any(dr._is_results_section(extract.get("section"))
                        for extract in review_extracts)
                    or not any(dr._is_conclusion_section(extract.get("section"))
                               for extract in review_extracts)):
                return False, "L4 completed review search lacks located review Results and Conclusion extracts"
        candidates = artifact.get("method_candidates", [])
        for component in artifact.get("method_components", []):
            if not component.get("required"):
                continue
            component_id = component["component_id"]
            eligible = [
                candidate for candidate in candidates
                if candidate.get("component_id") == component_id
                and candidate.get("status") == "eligible"
                and any(anchor in accepted_anchors
                        for anchor in candidate.get("method_anchor_ids", []))
            ]
            if eligible:
                continue
            blocked = [
                candidate for candidate in candidates
                if candidate.get("component_id") == component_id
                and candidate.get("status") == "needs_user_source"
            ]
            if blocked:
                return False, (
                    f"L4 required component {component_id} needs a user-supplied source: "
                    f"{blocked[0].get('missing_source', '')}"
                )
            return False, f"L4 required component {component_id} lacks an eligible accepted method anchor"
        return True, ""

    def render_pre_research_markdown(artifact):
        return _render_l4_markdown(artifact) if artifact.get("method_components") else original_render(artifact)

    def run_and_persist(project_dir, candidate_id, node, question, claim, spec,
                        work_dir, skill_version="unknown", result_context="", *,
                        project_id="", round_id="", profile_id="",
                        research_persona="Curie"):
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        schema_path = work_dir / "deep_research_output.schema.json"
        schema = runtime_schema(node)
        if node == "L4":
            # OpenAI strict response schemas require every declared property
            # to appear in `required`. Navigation-only L4 parsing keeps these
            # fields optional at the compatibility API boundary, so make the
            # provider-facing copy strict without changing that reader path.
            extract = schema["properties"]["papers"]["items"]["properties"][
                "extracts"
            ]["items"]
            extract["required"] = list(extract["properties"])
        schema_path.write_text(
            json.dumps(schema, indent=2), encoding="utf-8"
        )
        local_sources = registered_sources(project_dir, candidate_id) if node == "L4" else []
        command, prompt = build_invocation(
            spec, node, question, claim, work_dir, result_context,
            user_sources=local_sources,
        )
        command[0] = dr.resolve_subprocess_executable(command[0])
        execution_command, invocation_kwargs = dr.subprocess_invocation(command, prompt)
        try:
            completed = subprocess.run(
                execution_command, capture_output=True, text=True,
                encoding="utf-8", errors="strict", timeout=spec.timeout,
                check=False, **invocation_kwargs,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise dr.DeepResearchError(f"Academic Research CLI invocation failed: {exc}") from exc
        receipt = dr.skill_receipt(
            spec.backend, command, prompt, skill_version,
            exit_code=completed.returncode, stdout_hash=dr._sha(completed.stdout),
            model=spec.model,
        )
        if completed.returncode != 0:
            raise dr.DeepResearchError(
                f"Academic Research CLI exited {completed.returncode}: {completed.stderr.strip()}"
            )
        artifact = persist_run(
            project_dir, candidate_id, node, dr._parse_cli_output(completed.stdout),
            receipt, result_context, project_id=project_id, round_id=round_id,
            profile_id=profile_id, research_persona=research_persona,
        )
        target = Path(project_dir) / "02_Agent_Notes" / "_pre_research" / f"{node}_research.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_pre_research_markdown(artifact), encoding="utf-8")
        return artifact

    dr._runtime_schema = runtime_schema
    dr.build_invocation = build_invocation
    dr.validate_payload = validate_payload
    dr.persist_run = persist_run
    dr.audit_evidence_pack = audit_evidence_pack
    dr.render_pre_research_markdown = render_pre_research_markdown
    dr.run_and_persist = run_and_persist
    dr._normalize_source_text = _normalize_source_text
    dr._METHOD_EVIDENCE_INSTALLED = True
