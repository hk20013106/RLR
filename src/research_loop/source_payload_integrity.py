"""Persist retained source payloads as exact UTF-8 bytes.

Installed before the higher-level Deep Research extensions so every evidence
path hashes the same bytes that are retained on disk. This avoids Windows text
newline conversion and preserves a content-appropriate source suffix.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _source_suffix(content_type: str) -> str:
    value = str(content_type or "").casefold()
    if "xml" in value or "jats" in value:
        return ".xml"
    if "html" in value:
        return ".html"
    return ".txt"


def install(deep_research_module) -> None:
    if getattr(deep_research_module, "_source_payload_integrity_installed", False):
        return
    original = deep_research_module.persist_run

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
        dr = deep_research_module
        if node not in dr._STAGES:
            raise dr.DeepResearchError(f"unsupported Deep Research stage {node!r}")
        payload, rejected_papers = dr._filter_unidentifiable_papers(payload)
        dr.validate_payload(payload)
        if (
            receipt.get("exit_code") != 0
            or not receipt.get("command_hash")
            or not receipt.get("prompt_hash")
        ):
            raise dr.DeepResearchError(
                "skill receipt is incomplete or records a failed invocation"
            )

        project_dir = Path(project_dir)
        runs_dir, papers_dir, sources_dir = dr._run_paths(project_dir)
        for directory in (runs_dir, papers_dir, sources_dir):
            directory.mkdir(parents=True, exist_ok=True)

        run_seed = json.dumps(
            {
                "candidate_id": candidate_id,
                "node": node,
                "payload": payload,
                "receipt": receipt,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        run_id = (
            f"{dr._safe_id(candidate_id)}_{node.replace('.', '_')}_"
            f"{dr._sha(run_seed)[:12]}"
        )
        records = []

        for paper in payload["papers"]:
            paper_id = dr._paper_id(paper)
            source_path = ""
            source_hash = ""
            source_payload = str(paper.get("source_payload") or "")
            if paper.get("open_access") and source_payload:
                source_file = sources_dir / (
                    f"{paper_id}{_source_suffix(paper.get('content_type', ''))}"
                )
                source_bytes = source_payload.encode("utf-8")
                source_hash = hashlib.sha256(source_bytes).hexdigest()
                source_file.write_bytes(source_bytes)
                source_path = str(source_file.relative_to(project_dir)).replace(
                    "\\", "/"
                )

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
                    "source_hash": source_hash,
                })

            record = {
                "schema_version": dr.SCHEMA_VERSION,
                "paper_id": paper_id,
                "doi": paper.get("doi", ""),
                "pmid": paper.get("pmid", ""),
                "url": paper.get("url", ""),
                "title": paper["title"],
                "source_database": paper["source_database"],
                "metadata": paper.get("metadata", {}),
                "paper_type": str(paper.get("paper_type", "primary")),
                "retrieved_at": dr._now(),
                "source_metadata_response": paper["source_metadata_response"],
                "metadata_response_hash": dr._sha(json.dumps(
                    paper["source_metadata_response"],
                    ensure_ascii=False,
                    sort_keys=True,
                )),
                "open_access": bool(paper.get("open_access")),
                "content_hash": source_hash,
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
                "path": str(paper_file.relative_to(project_dir)).replace("\\", "/"),
                "doi": record["doi"],
                "pmid": record["pmid"],
                "url": record["url"],
                "evidence_ids": [item["evidence_id"] for item in extracts],
            })

        artifact = {
            "schema_version": dr.SCHEMA_VERSION,
            "evidence_receipt_schema": "EvidenceRunReceipt/v1.1",
            "kind": "deep_research_run",
            "research_phase": "pre_research",
            "research_persona": research_persona,
            "run_id": run_id,
            "project_id": project_id,
            "round_id": str(round_id),
            "profile_id": profile_id,
            "status": "completed",
            "candidate_id": candidate_id,
            "node": node,
            "created_at": dr._now(),
            "queries": payload["queries"],
            "skill_receipt": receipt,
            "papers": records,
            "rejected_papers": rejected_papers,
            "review_search": payload.get("review_search", {}),
            "verification": payload.get("verification", []),
            "result_context_hash": dr._sha(result_context) if result_context else "",
        }
        run_file = runs_dir / f"{run_id}.json"
        summary_file = runs_dir / f"{run_id}.md"
        artifact["path"] = str(run_file.relative_to(project_dir)).replace("\\", "/")
        artifact["summary_path"] = str(
            summary_file.relative_to(project_dir)
        ).replace("\\", "/")
        run_file.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        summary_file.write_text(
            dr.render_pre_research_markdown(artifact), encoding="utf-8"
        )
        return artifact

    deep_research_module.persist_run = persist_run
    deep_research_module._source_payload_integrity_original = original
    deep_research_module._source_payload_integrity_installed = True
