"""Preserve L4 navigation evidence without treating it as a method anchor."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path


_REVIEW_TYPES = {"review", "systematic_review", "meta_analysis"}
_ANCHOR_FIELDS = {"anchor_id", "method_component_ids", "method_ids", "source_kind"}


def _paper_type(paper: dict) -> str:
    return str(paper.get("paper_type") or "").strip().lower()


def _is_review(paper: dict) -> bool:
    return _paper_type(paper) in _REVIEW_TYPES


def _canonical_paper_type(paper: dict) -> str:
    value = _paper_type(paper)
    if value not in _REVIEW_TYPES:
        return value or "primary"
    if "systematic" in value:
        return "systematic_review"
    if "meta" in value:
        return "meta_analysis"
    return "review"


def _has_anchor_fields(extract: dict) -> bool:
    return any(
        bool(extract.get(field))
        and not (field == "source_kind" and extract.get(field) == "navigation_only")
        for field in _ANCHOR_FIELDS
    )


def _split(payload: dict) -> tuple[dict, list[dict]]:
    """Split anchored extracts from navigation-only extracts at extract level."""
    method_payload = copy.deepcopy(payload)
    method_papers = []
    navigation_papers = []
    for original in payload.get("papers", []):
        anchored = []
        navigation = []
        for extract in original.get("extracts", []):
            (anchored if _has_anchor_fields(extract) else navigation).append(
                copy.deepcopy(extract)
            )
        if anchored:
            paper = copy.deepcopy(original)
            paper["extracts"] = anchored
            method_papers.append(paper)
        if navigation or not original.get("extracts"):
            paper = copy.deepcopy(original)
            paper["extracts"] = navigation
            navigation_papers.append(paper)
    method_payload["papers"] = method_papers
    return method_payload, navigation_papers


def _validate_navigation(dr, navigation_papers: list[dict]) -> None:
    for paper in navigation_papers:
        if not any(str(paper.get(key) or "").strip() for key in ("doi", "pmid", "url")):
            raise dr.DeepResearchError(
                "each L4 navigation paper needs DOI, PMID, or stable URL"
            )
        if not str(paper.get("title") or "").strip():
            raise dr.DeepResearchError("each L4 navigation paper needs a title")
        if not str(paper.get("source_database") or "").strip():
            raise dr.DeepResearchError(
                "each L4 navigation paper needs source_database"
            )
        if not isinstance(paper.get("source_metadata_response"), (dict, list)):
            raise dr.DeepResearchError(
                "each L4 navigation paper needs source_metadata_response"
            )
        extracts = paper.get("extracts")
        if not isinstance(extracts, list):
            raise dr.DeepResearchError("L4 navigation extracts must be a list")
        for extract in extracts:
            if not isinstance(extract, dict) or not all(
                str(extract.get(field) or "").strip()
                for field in ("section", "text", "locator")
            ):
                raise dr.DeepResearchError(
                    "each L4 navigation extract needs section, text, and locator"
                )
            if _has_anchor_fields(extract):
                raise dr.DeepResearchError(
                    "navigation extracts must not claim method-anchor fields"
                )


def _reject_review_anchor_claims(dr, payload: dict) -> None:
    for paper in payload.get("papers", []):
        if not _is_review(paper):
            continue
        if any(_has_anchor_fields(extract) for extract in paper.get("extracts", [])):
            raise dr.DeepResearchError(
                "review extracts are navigation only and cannot claim method-anchor fields"
            )


def _persist_navigation(
    dr, project: Path, artifact: dict, navigation_papers: list[dict]
) -> None:
    if not navigation_papers:
        return
    _, papers_dir, sources_dir = dr._run_paths(project)
    for paper in navigation_papers:
        paper = copy.deepcopy(paper)
        paper["paper_type"] = _canonical_paper_type(paper)
        paper_id = dr._paper_id(paper)
        source_payload = str(paper.get("source_payload") or "")
        source_path = ""
        if source_payload:
            ext = (
                ".html"
                if "html" in str(paper.get("content_type") or "").lower()
                else ".txt"
            )
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
                "extraction_method": extract.get(
                    "extraction_method", "source-located"
                ),
                "verification_status": extract.get(
                    "verification_status", "located"
                ),
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
            "paper_type": paper["paper_type"],
            "retrieved_at": dr._now(),
            "source_metadata_response": paper["source_metadata_response"],
            "metadata_response_hash": dr._sha(json.dumps(
                paper["source_metadata_response"],
                ensure_ascii=False,
                sort_keys=True,
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
            "doi": record["doi"],
            "pmid": record["pmid"],
            "url": record["url"],
            "user_source_id": "",
            "evidence_ids": [item["evidence_id"] for item in extracts],
        })


def _navigation_markdown(project_dir: str | Path, artifact: dict) -> str:
    project = Path(project_dir)
    lines = ["", "## Navigation evidence"]
    found = False
    review_found = False
    for ref in artifact.get("papers", []):
        try:
            record = json.loads(
                (project / ref["path"]).read_text(encoding="utf-8")
            )
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        extracts = record.get("evidence_extracts", [])
        if any(extract.get("anchor_id") for extract in extracts):
            continue
        found = True
        is_review = str(record.get("paper_type") or "").lower() in {
            "review", "systematic_review", "meta_analysis"
        }
        review_found = review_found or is_review
        role = "review navigation" if is_review else "context navigation"
        lines.append(f"- {record['title']} ({record['paper_type']}; {role}):")
        for extract in extracts:
            lines.append(
                f"  - {extract['section']} @ {extract['locator']} "
                f"(`{extract['evidence_id']}`; navigation only, not a method anchor)"
            )
    if not found:
        lines.append("- No navigation-only evidence was retained.")
    if not review_found:
        lines.append(
            "- No relevant review was retained; see the review-search receipt."
        )
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
            extract = schema["properties"]["papers"]["items"]["properties"][
                "extracts"
            ]["items"]
            extract["required"] = [
                field
                for field in extract["required"]
                if field not in _ANCHOR_FIELDS
            ]
        return schema

    def validate_payload(
        payload, *, node=None, project_dir=None, candidate_id=""
    ):
        if node != "L4" or not payload.get("method_components"):
            return original_validate(
                payload,
                node=node,
                project_dir=project_dir,
                candidate_id=candidate_id,
            )
        _reject_review_anchor_claims(dr, payload)
        method_payload, navigation = _split(payload)
        original_validate(
            method_payload,
            node=node,
            project_dir=project_dir,
            candidate_id=candidate_id,
        )
        _validate_navigation(dr, navigation)

    def persist_run(
        project_dir,
        candidate_id,
        node,
        payload,
        receipt,
        result_context="",
        *,
        project_id="",
        round_id="",
        profile_id="",
        research_persona="Curie",
    ):
        if node != "L4" or not payload.get("method_components"):
            return original_persist(
                project_dir,
                candidate_id,
                node,
                payload,
                receipt,
                result_context,
                project_id=project_id,
                round_id=round_id,
                profile_id=profile_id,
                research_persona=research_persona,
            )
        validate_payload(
            payload,
            node=node,
            project_dir=project_dir,
            candidate_id=candidate_id,
        )
        method_payload, navigation = _split(payload)
        artifact = original_persist(
            project_dir,
            candidate_id,
            node,
            method_payload,
            receipt,
            result_context,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            research_persona=research_persona,
        )
        project = Path(project_dir)
        _persist_navigation(dr, project, artifact, navigation)
        run_path = project / artifact["path"]
        run_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        summary_path = project / artifact["summary_path"]
        summary_path.write_text(
            original_render(artifact).rstrip()
            + "\n"
            + _navigation_markdown(project, artifact),
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
        return text.rstrip() + "\n" + _navigation_markdown(
            project_hint, artifact
        )

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
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        schema_path = work_dir / "deep_research_output.schema.json"
        schema = runtime_schema(node)
        if node == "L4":
            # The compatibility schema permits navigation-only extracts, but
            # the provider-facing OpenAI strict schema must require every
            # declared property.
            extract = schema["properties"]["papers"]["items"]["properties"][
                "extracts"
            ]["items"]
            extract["required"] = list(extract["properties"])
        schema_path.write_text(
            json.dumps(schema, indent=2), encoding="utf-8"
        )
        local_sources = (
            dr.registered_sources(project_dir, candidate_id)
            if node == "L4" and hasattr(dr, "registered_sources")
            else []
        )
        if node == "L4":
            command, prompt = dr.build_invocation(
                spec,
                node,
                question,
                claim,
                work_dir,
                result_context,
                user_sources=local_sources,
            )
        else:
            command, prompt = dr.build_invocation(
                spec, node, question, claim, work_dir, result_context
            )
        command[0] = dr.resolve_subprocess_executable(command[0])
        execution_command, invocation_kwargs = dr.subprocess_invocation(
            command, prompt
        )
        try:
            completed = subprocess.run(
                execution_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=spec.timeout,
                check=False,
                **invocation_kwargs,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise dr.DeepResearchError(
                f"Academic Research CLI invocation failed: {exc}"
            ) from exc
        receipt = dr.skill_receipt(
            spec.backend,
            command,
            prompt,
            skill_version,
            exit_code=completed.returncode,
            stdout_hash=dr._sha(completed.stdout),
            model=spec.model,
        )
        if completed.returncode != 0:
            raise dr.DeepResearchError(
                f"Academic Research CLI exited {completed.returncode}: "
                f"{completed.stderr.strip()}"
            )
        artifact = persist_run(
            project_dir,
            candidate_id,
            node,
            dr._parse_cli_output(completed.stdout),
            receipt,
            result_context,
            project_id=project_id,
            round_id=round_id,
            profile_id=profile_id,
            research_persona=research_persona,
        )
        target = (
            Path(project_dir)
            / "02_Agent_Notes"
            / "_pre_research"
            / f"{node}_research.md"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_pre_research_markdown(artifact), encoding="utf-8"
        )
        return artifact

    dr._runtime_schema = runtime_schema
    dr.validate_payload = validate_payload
    dr.persist_run = persist_run
    dr.render_pre_research_markdown = render_pre_research_markdown
    dr.run_and_persist = run_and_persist
    dr._METHOD_REVIEW_NAVIGATION_INSTALLED = True
