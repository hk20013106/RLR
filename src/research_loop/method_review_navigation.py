"""Preserve L4 review evidence without treating it as a method anchor."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path


_REVIEW_TYPES = {"review", "systematic_review", "meta_analysis"}
_ANCHOR_FIELDS = {"anchor_id", "method_component_ids", "method_ids", "source_kind"}


def _is_review(paper: dict) -> bool:
    return str(paper.get("paper_type") or "").strip().lower() in _REVIEW_TYPES


def _split(payload: dict) -> tuple[dict, list[dict]]:
    method_payload = copy.deepcopy(payload)
    reviews = [copy.deepcopy(paper) for paper in payload.get("papers", []) if _is_review(paper)]
    method_payload["papers"] = [
        copy.deepcopy(paper) for paper in payload.get("papers", []) if not _is_review(paper)
    ]
    return method_payload, reviews


def _validate_reviews(dr, reviews: list[dict]) -> None:
    for paper in reviews:
        if not any(str(paper.get(key) or "").strip() for key in ("doi", "pmid", "url")):
            raise dr.DeepResearchError("each review needs DOI, PMID, or stable URL")
        if not str(paper.get("title") or "").strip():
            raise dr.DeepResearchError("each review needs a title")
        if not str(paper.get("source_database") or "").strip():
            raise dr.DeepResearchError("each review needs source_database")
        if not isinstance(paper.get("source_metadata_response"), (dict, list)):
            raise dr.DeepResearchError("each review needs source_metadata_response")
        extracts = paper.get("extracts")
        if not isinstance(extracts, list):
            raise dr.DeepResearchError("review extracts must be a list")
        for extract in extracts:
            if not isinstance(extract, dict) or not all(
                str(extract.get(field) or "").strip()
                for field in ("section", "text", "locator")
            ):
                raise dr.DeepResearchError(
                    "each review navigation extract needs section, text, and locator"
                )
            if any(str(extract.get(field) or "").strip() for field in _ANCHOR_FIELDS):
                raise dr.DeepResearchError(
                    "review navigation extracts must not claim method-anchor fields"
                )


def _persist_reviews(dr, project: Path, artifact: dict, reviews: list[dict]) -> None:
    if not reviews:
        return
    _, papers_dir, sources_dir = dr._run_paths(project)
    for paper in reviews:
        paper_id = dr._paper_id(paper)
        source_payload = str(paper.get("source_payload") or "")
        source_path = ""
        if source_payload:
            ext = ".html" if "html" in str(paper.get("content_type") or "").lower() else ".txt"
            source_file = sources_dir / f"{paper_id}{ext}"
            source_file.write_text(source_payload, encoding="utf-8")
            source_path = source_file.relative_to(project).as_posix()
        extracts = []
        for index, extract in enumerate(paper.get("extracts", []), 1):
            evidence_id = (
                f"{paper_id}:{dr._safe_id(str(extract['section']))}:{index}:"
                f"{dr._sha(extract['text'])[:10]}"
            )
            extracts.append({
                "evidence_id": evidence_id,
                "section": extract["section"],
                "text": extract["text"],
                "locator": extract["locator"],
                "extraction_method": extract.get("extraction_method", "source-located"),
                "verification_status": extract.get("verification_status", "located"),
                "source_hash": dr._sha(source_payload) if source_payload else "",
            })
        record = {
            "schema_version": dr.SCHEMA_VERSION,
            "paper_id": paper_id,
            "doi": paper.get("doi", ""),
            "pmid": paper.get("pmid", ""),
            "url": paper.get("url", ""),
            "user_source_id": "",
            "user_source_sha256": "",
            "title": paper["title"],
            "source_database": paper["source_database"],
            "metadata": paper.get("metadata", {}),
            "paper_type": str(paper.get("paper_type") or "review"),
            "retrieved_at": dr._now(),
            "source_metadata_response": paper["source_metadata_response"],
            "metadata_response_hash": dr._sha(json.dumps(
                paper["source_metadata_response"], ensure_ascii=False, sort_keys=True
            )),
            "open_access": bool(paper.get("open_access")),
            "content_hash": dr._sha(source_payload) if source_payload else "",
            "source_payload_path": source_path,
            "evidence_extracts": extracts,
        }
        paper_file = papers_dir / f"{paper_id}.json"
        paper_file.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        artifact["papers"].append({
            "paper_id": paper_id,
            "path": paper_file.relative_to(project).as_posix(),
            "doi": record["doi"], "pmid": record["pmid"], "url": record["url"],
            "user_source_id": "",
            "evidence_ids": [item["evidence_id"] for item in extracts],
        })


def _review_markdown(project_dir: str | Path, artifact: dict) -> str:
    project = Path(project_dir)
    lines = ["", "## Review navigation"]
    found = False
    for ref in artifact.get("papers", []):
        try:
            record = json.loads((project / ref["path"]).read_text(encoding="utf-8"))
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        if str(record.get("paper_type") or "").lower() not in _REVIEW_TYPES:
            continue
        found = True
        lines.append(f"- {record['title']} ({record['paper_type']}):")
        for extract in record.get("evidence_extracts", []):
            lines.append(
                f"  - {extract['section']} @ {extract['locator']} "
                f"(`{extract['evidence_id']}`; navigation only, not a method anchor)"
            )
    if not found:
        lines.append("- No relevant review was located; see the review-search receipt.")
    return "\n".join(lines) + "\n"


def install(deep_research_module) -> None:
    dr = deep_research_module
    if getattr(dr, "_METHOD_REVIEW_NAVIGATION_INSTALLED", False):
        return
    original_schema = dr._runtime_schema
    original_validate = dr.validate_payload
    original_persist = dr.persist_run
    original_render = dr.render_pre_research_markdown

    def runtime_schema(node=None):
        schema = original_schema(node)
        if node == "L4":
            extract = schema["properties"]["papers"]["items"]["properties"]["extracts"]["items"]
            extract["required"] = [
                field for field in extract["required"] if field not in _ANCHOR_FIELDS
            ]
        return schema

    def validate_payload(payload, *, node=None, project_dir=None, candidate_id=""):
        if node != "L4" or not payload.get("method_components"):
            return original_validate(
                payload, node=node, project_dir=project_dir, candidate_id=candidate_id
            )
        method_payload, reviews = _split(payload)
        original_validate(
            method_payload, node=node, project_dir=project_dir,
            candidate_id=candidate_id,
        )
        _validate_reviews(dr, reviews)

    def persist_run(project_dir, candidate_id, node, payload, receipt,
                    result_context="", *, project_id="", round_id="",
                    profile_id="", research_persona="Curie"):
        if node != "L4" or not payload.get("method_components"):
            return original_persist(
                project_dir, candidate_id, node, payload, receipt, result_context,
                project_id=project_id, round_id=round_id, profile_id=profile_id,
                research_persona=research_persona,
            )
        validate_payload(
            payload, node=node, project_dir=project_dir, candidate_id=candidate_id
        )
        method_payload, reviews = _split(payload)
        artifact = original_persist(
            project_dir, candidate_id, node, method_payload, receipt, result_context,
            project_id=project_id, round_id=round_id, profile_id=profile_id,
            research_persona=research_persona,
        )
        project = Path(project_dir)
        _persist_reviews(dr, project, artifact, reviews)
        run_path = project / artifact["path"]
        run_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        summary_path = project / artifact["summary_path"]
        summary_path.write_text(
            original_render(artifact).rstrip() + "\n" + _review_markdown(project, artifact),
            encoding="utf-8",
        )
        return artifact

    def render_pre_research_markdown(artifact):
        text = original_render(artifact)
        if artifact.get("node") != "L4" or not artifact.get("method_components"):
            return text
        project_hint = artifact.get("project_dir_hint")
        if not project_hint:
            return text
        return text.rstrip() + "\n" + _review_markdown(project_hint, artifact)

    def run_and_persist(project_dir, candidate_id, node, question, claim, spec,
                        work_dir, skill_version="unknown", result_context="", *,
                        project_id="", round_id="", profile_id="",
                        research_persona="Curie"):
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        schema_path = work_dir / "deep_research_output.schema.json"
        schema_path.write_text(
            json.dumps(runtime_schema(node), indent=2), encoding="utf-8"
        )
        local_sources = dr.registered_sources(project_dir, candidate_id) if (
            node == "L4" and hasattr(dr, "registered_sources")
        ) else []
        # method_evidence.build_invocation accepts user_sources; legacy nodes ignore it.
        if node == "L4":
            command, prompt = dr.build_invocation(
                spec, node, question, claim, work_dir, result_context,
                user_sources=local_sources,
            )
        else:
            command, prompt = dr.build_invocation(
                spec, node, question, claim, work_dir, result_context
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
    dr.validate_payload = validate_payload
    dr.persist_run = persist_run
    dr.render_pre_research_markdown = render_pre_research_markdown
    dr.run_and_persist = run_and_persist
    dr._METHOD_REVIEW_NAVIGATION_INSTALLED = True
