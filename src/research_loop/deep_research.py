"""Versioned Deep Research runtime, evidence packs, and audit helpers.

The module deliberately has no dependency on the RLR engine.  A successful
research run is an external CLI invocation plus a validated, persisted source
record; a prose pre-research note alone is never evidence of execution.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os as _os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


SCHEMA_VERSION = "1.0"
_STAGES = {"L1", "L4", "L8.5"}

# Deep Research backends. Deliberately closed: every backend needs a verified
# invocation shape, a skill/plugin layout, and evidence-gate coverage, so a name
# is only added once those exist.
SUPPORTED_BACKENDS = ("codex", "claude")

# Environment markers that identify the agent host. Claude Code sets these and
# providers/headless.py already depends on them. No Codex marker is listed
# because none has been verified in this repository -- see detect_host_backend.
_HOST_MARKERS = {"claude": ("CLAUDECODE", "CLAUDE_CODE")}
_MAX_SOURCE_BYTES = 5 * 1024 * 1024


class DeepResearchError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeSpec:
    backend: str
    executable: str
    plugin_dir: str | None = None
    model: str | None = None
    timeout: int | None = None
    skill_path: str | None = None


def runtime_config_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / "00_Preflight" / "deep_research_runtime.json"


def detect_host_backend(env: dict | None = None) -> str | None:
    """Name the agent host running this process, or None when it is unknown.

    Only the Claude Code markers are verified (providers/headless.py relies on
    the same two variables). Codex exposes no marker this repository has
    confirmed, so an unmarked host is reported as unknown -- never assumed to be
    Codex. Guessing here is what let a Claude session spend Codex quota.
    """
    env = _os.environ if env is None else env
    for backend, markers in _HOST_MARKERS.items():
        if any(env.get(marker) for marker in markers):
            return backend
    return None


def default_runtime_config(backend: str | None = None,
                           env: dict | None = None) -> dict:
    """Runtime config for an explicit backend, or for the detected host.

    Fails loud when the host cannot be detected: silently defaulting to one
    backend is what sent Claude-hosted runs to the Codex CLI.
    """
    backend = backend or detect_host_backend(env)
    if backend is None:
        raise DeepResearchError(
            "cannot detect the current agent host; pass --backend "
            f"{'|'.join(SUPPORTED_BACKENDS)} to name the runtime explicitly")
    if backend not in SUPPORTED_BACKENDS:
        raise DeepResearchError(
            f"backend must be one of {', '.join(SUPPORTED_BACKENDS)}, got {backend!r}")
    config = {
        "schema_version": SCHEMA_VERSION,
        "backend": backend,
        "executable": backend,
        "skill_path": "",
        "plugin_dir": "",
        "skill_version": "unknown",
        "timeout": 900,
    }
    if backend == "codex":
        config["skill_path"] = str(
            Path.home() / ".codex" / "skills" / "academic-research-suite")
    # The Claude plugin directory is installation-specific and is left empty
    # rather than guessed; runtime_ready() reports it as missing.
    return config


def host_matches(spec: RuntimeSpec, env: dict | None = None) -> tuple[bool, str]:
    """Reject a configured backend that contradicts the detected host.

    An unknown host is permissive: a detection gap must not block every run.
    Only a positive mismatch stops one, because that is the case that spends the
    wrong provider's quota.
    """
    host = detect_host_backend(env)
    if host is None or host == spec.backend:
        return True, ""
    return False, (
        f"running inside the {host!r} host but the project runtime is configured "
        f"for backend {spec.backend!r}. This would spend {spec.backend!r} quota "
        f"from a {host!r} session. Either re-run with --backend {host} or, if the "
        f"cross-host run is intended, pass --allow-host-mismatch")


def load_runtime_spec(project_dir: str | Path, overrides: dict | None = None) -> tuple[RuntimeSpec, str]:
    path = runtime_config_path(project_dir)
    if not path.exists():
        raise DeepResearchError(f"runtime config missing: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepResearchError(f"runtime config is invalid: {exc}") from exc
    if not isinstance(config, dict):
        raise DeepResearchError("runtime config must be a JSON object")
    for key, value in (overrides or {}).items():
        if value not in (None, ""):
            config[key] = value
    backend = str(config.get("backend", ""))
    return RuntimeSpec(
        backend=backend, executable=str(config.get("executable") or backend),
        plugin_dir=config.get("plugin_dir") or None, model=config.get("model") or None,
        timeout=config.get("timeout"), skill_path=config.get("skill_path") or None,
    ), str(config.get("skill_version") or "unknown")


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return value or "record"


def _runtime_schema() -> dict:
    extract = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "section": {"type": "string"},
            "text": {"type": "string"},
            "locator": {"type": "string"},
            "extraction_method": {"type": "string"},
            "verification_status": {"type": "string"},
        },
        "required": ["section", "text", "locator", "extraction_method", "verification_status"],
    }
    paper = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "doi": {"type": "string"},
            "pmid": {"type": "string"},
            "url": {"type": "string"},
            "title": {"type": "string"},
            "source_database": {"type": "string"},
            "metadata": {
                "type": "object", "additionalProperties": False,
                "properties": {"year": {"type": "integer"}, "journal": {"type": "string"}},
                "required": ["year", "journal"],
            },
            "source_metadata_response": {
                "type": "object", "additionalProperties": False,
                "properties": {"id": {"type": "string"}, "title": {"type": "string"}},
                "required": ["id", "title"],
            },
            "open_access": {"type": "boolean"},
            "content_type": {"type": "string"},
            "source_payload": {"type": "string"},
            "paper_type": {"type": "string"},
            "extracts": {"type": "array", "items": extract},
        },
        "required": [
            "doi", "pmid", "url", "title", "source_database", "metadata",
            "source_metadata_response", "open_access", "content_type",
            "source_payload", "paper_type", "extracts",
        ],
    }
    review_search = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "query": {"type": "string"},
            "status": {"type": "string"},
            "receipt": {"type": "string"},
        },
        "required": ["query", "status", "receipt"],
    }
    verification = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "finding": {"type": "string"},
            "verdict": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["finding", "verdict", "evidence_ids"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "queries", "papers", "review_search", "verification"],
        "properties": {
            "schema_version": {"type": "string", "const": SCHEMA_VERSION},
            "queries": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "papers": {"type": "array", "minItems": 1, "items": paper},
            "review_search": review_search,
            "verification": {"type": "array", "items": verification},
        },
    }


def _stage_instruction(node: str) -> str:
    if node == "L1":
        return ("Run deep-research/literature discovery for hypothesis generation. "
                "For every claim, extract located Results, Discussion, and Conclusion evidence "
                "from primary research papers.")
    if node == "L4":
        return ("Run a method literature review. Extract located Methods from primary studies. "
                "Also execute a review query; capture Results and Conclusion from each relevant "
                "review, or record a zero-result review-search receipt.")
    if node == "L8.5":
        return ("Run post-result literature verification. For every L7/L8 finding, record a "
                "located paper-based confirmation, contradiction, or unresolved verdict.")
    raise DeepResearchError(f"unsupported Deep Research stage {node!r}")


def build_invocation(spec: RuntimeSpec, node: str, question: str, claim: str,
                     work_dir: str | Path, result_context: str = "") -> tuple[list[str], str]:
    """Build an explicit ARS command and a JSON-only evidence request.

    Codex uses the single-suite skill name. Claude receives a plugin directory
    and the installed ARS alias.  There is intentionally no generic command
    template or environment-variable fallback.
    """
    if node not in _STAGES:
        raise DeepResearchError(f"unsupported Deep Research stage {node!r}")
    if spec.backend not in SUPPORTED_BACKENDS:
        raise DeepResearchError(
            f"backend must be one of {', '.join(SUPPORTED_BACKENDS)}")
    if not spec.executable:
        raise DeepResearchError("executable is required")
    work_dir = Path(work_dir)
    schema_path = work_dir / "deep_research_output.schema.json"
    if spec.backend == "codex":
        command = [spec.executable, "exec", "--output-schema", str(schema_path)]
        if spec.model:
            command.extend(["--model", spec.model])
        invocation = "$academic-research-suite"
    else:
        if not spec.plugin_dir:
            raise DeepResearchError("Claude backend requires plugin_dir for academic-research-skills")
        command = [spec.executable, "-p", "--plugin-dir", str(spec.plugin_dir),
                   "--json-schema", str(schema_path), "--output-format", "json"]
        if spec.model:
            command.extend(["--model", spec.model])
        invocation = "/ars-lit-review" if node == "L4" else "/ars-full"
    result_block = ""
    if node == "L8.5":
        if not result_context.strip():
            raise DeepResearchError("L8.5 requires actual L7/L8 findings for verification")
        result_block = f"\nActual L7/L8 findings to verify:\n{result_context}\n"
    prompt = f"""Use {invocation}. {_stage_instruction(node)}

RLR stage: {node}
Scientific question: {question}
Current hypothesis/claim: {claim}
{result_block}

Return JSON only, matching the supplied schema. Each paper must include DOI,
PMID, or stable URL; source_database; metadata; open_access; and located
extracts with section, text, and locator. Include source_metadata_response as
the actual metadata record returned by the named database. Provide source_payload only for
open-access content that you actually retrieved. Never invent a citation,
extract, paper section, or retrieval receipt.
"""
    return command, prompt


def skill_receipt(backend: str, command: list[str], prompt: str,
                  skill_version: str, *, exit_code: int = 0,
                  stdout_hash: str = "", model: str | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "backend": backend,
        "provider": backend,
        "model": model or "default",
        "skill": "academic-research-suite" if backend == "codex" else "academic-research-skills",
        "upstream": ("https://github.com/Imbad0202/academic-research-skills-codex"
                     if backend == "codex"
                     else "https://github.com/imbad0202/academic-research-skills"),
        "skill_version": skill_version,
        "command_hash": _sha(json.dumps(command, ensure_ascii=False)),
        "prompt_hash": _sha(prompt),
        "executed_at": _now(),
        "exit_code": exit_code,
        "stdout_hash": stdout_hash,
    }


def _parse_cli_output(stdout: str) -> dict:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DeepResearchError(f"research CLI did not return JSON: {exc}") from exc
    # Claude --output-format json may place the model result in this envelope.
    if isinstance(value, dict) and isinstance(value.get("result"), str):
        try:
            value = json.loads(value["result"])
        except json.JSONDecodeError as exc:
            raise DeepResearchError("research CLI result is not JSON evidence") from exc
    if not isinstance(value, dict):
        raise DeepResearchError("research CLI result must be a JSON object")
    return value


def _filter_unidentifiable_papers(payload: dict) -> tuple[dict, list[dict]]:
    """Keep citable records and return an auditable list of rejected records."""
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if not isinstance(papers, list):
        return payload, []
    accepted, rejected = [], []
    for index, paper in enumerate(papers):
        if isinstance(paper, dict) and any(
                str(paper.get(key, "")).strip() for key in ("doi", "pmid", "url")):
            accepted.append(paper)
            continue
        rejected.append({
            "index": index,
            "title": str(paper.get("title", "")) if isinstance(paper, dict) else "",
            "doi": str(paper.get("doi", "")) if isinstance(paper, dict) else "",
            "pmid": str(paper.get("pmid", "")) if isinstance(paper, dict) else "",
            "url": str(paper.get("url", "")) if isinstance(paper, dict) else "",
            "reason": "missing DOI, PMID, or stable URL",
        })
    if not accepted:
        raise DeepResearchError("no retrievable papers remain after identifier filtering")
    if not rejected:
        return payload, []
    filtered = dict(payload)
    filtered["papers"] = accepted
    return filtered, rejected


def validate_payload(payload: dict) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise DeepResearchError("payload schema_version is missing or unsupported")
    if not isinstance(payload.get("queries"), list) or not all(isinstance(q, str) and q.strip()
                                                                 for q in payload["queries"]):
        raise DeepResearchError("payload queries must be a non-empty list of strings")
    if not isinstance(payload.get("papers"), list) or not payload["papers"]:
        raise DeepResearchError("payload must contain at least one retrieved paper")
    for paper in payload["papers"]:
        if not isinstance(paper, dict):
            raise DeepResearchError("paper records must be objects")
        if not any(str(paper.get(k, "")).strip() for k in ("doi", "pmid", "url")):
            raise DeepResearchError("each paper needs DOI, PMID, or stable URL")
        if not str(paper.get("title", "")).strip() or not str(paper.get("source_database", "")).strip():
            raise DeepResearchError("each paper needs title and source_database")
        if not isinstance(paper.get("source_metadata_response"), (dict, list)):
            raise DeepResearchError("each paper needs a source_metadata_response from its database")
        extracts = paper.get("extracts", [])
        if not isinstance(extracts, list):
            raise DeepResearchError("paper extracts must be a list")
        for extract in extracts:
            if not isinstance(extract, dict) or not all(str(extract.get(k, "")).strip()
                                                         for k in ("section", "text", "locator")):
                raise DeepResearchError("each evidence extract needs section, text, and locator")
        if paper.get("open_access") and paper.get("source_payload") and \
                len(str(paper["source_payload"]).encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise DeepResearchError("open-access source payload exceeds 5 MiB limit")


def _paper_id(paper: dict) -> str:
    identity = str(paper.get("doi") or paper.get("pmid") or paper.get("url"))
    snapshot = json.dumps({
        "source_metadata_response": paper.get("source_metadata_response"),
        "source_payload": paper.get("source_payload"),
        "extracts": paper.get("extracts", []),
    }, ensure_ascii=False, sort_keys=True)
    return _safe_id(hashlib.sha256(f"{identity}|{snapshot}".encode("utf-8")).hexdigest()[:16])


def _run_paths(project_dir: Path) -> tuple[Path, Path, Path]:
    base = project_dir / "09_Literature_Database" / "evidence_packs"
    return base / "runs", base / "papers", base / "sources"


def persist_run(
    project_dir: str | Path,
    candidate_id: str,
    node: str,
    payload: dict,
    receipt: dict,
    result_context: str = "",
    *,
    project_id: str = "",
    round_id: str = "",
    profile_id: str = "",
    research_persona: str = "Curie",
) -> dict:
    """Persist immutable paper records and a run artifact from a validated payload."""
    if node not in _STAGES:
        raise DeepResearchError(f"unsupported Deep Research stage {node!r}")
    payload, rejected_papers = _filter_unidentifiable_papers(payload)
    validate_payload(payload)
    if receipt.get("exit_code") != 0 or not receipt.get("command_hash") or not receipt.get("prompt_hash"):
        raise DeepResearchError("skill receipt is incomplete or records a failed invocation")
    project_dir = Path(project_dir)
    runs_dir, papers_dir, sources_dir = _run_paths(project_dir)
    for directory in (runs_dir, papers_dir, sources_dir):
        directory.mkdir(parents=True, exist_ok=True)
    run_seed = json.dumps({"candidate_id": candidate_id, "node": node, "payload": payload,
                           "receipt": receipt}, ensure_ascii=False, sort_keys=True)
    run_id = f"{_safe_id(candidate_id)}_{node.replace('.', '_')}_{_sha(run_seed)[:12]}"
    records = []
    for paper in payload["papers"]:
        paper_id = _paper_id(paper)
        source_path = ""
        source_payload = str(paper.get("source_payload") or "")
        if paper.get("open_access") and source_payload:
            ext = ".html" if "html" in str(paper.get("content_type", "")).lower() else ".txt"
            source_file = sources_dir / f"{paper_id}{ext}"
            source_file.write_text(source_payload, encoding="utf-8")
            source_path = str(source_file.relative_to(project_dir)).replace("\\", "/")
        extracts = []
        for index, extract in enumerate(paper.get("extracts", []), 1):
            evidence_id = f"{paper_id}:{_safe_id(str(extract['section']))}:{index}:{_sha(extract['text'])[:10]}"
            extracts.append({
                "evidence_id": evidence_id,
                "section": extract["section"], "text": extract["text"],
                "locator": extract["locator"],
                "extraction_method": extract.get("extraction_method", "source-located"),
                "verification_status": extract.get("verification_status", "located"),
                "source_hash": _sha(source_payload) if source_payload else "",
            })
        record = {
            "schema_version": SCHEMA_VERSION, "paper_id": paper_id,
            "doi": paper.get("doi", ""), "pmid": paper.get("pmid", ""), "url": paper.get("url", ""),
            "title": paper["title"], "source_database": paper["source_database"],
            "metadata": paper.get("metadata", {}),
            "paper_type": str(paper.get("paper_type", "primary")), "retrieved_at": _now(),
            "source_metadata_response": paper["source_metadata_response"],
            "metadata_response_hash": _sha(json.dumps(paper["source_metadata_response"],
                                                        ensure_ascii=False, sort_keys=True)),
            "open_access": bool(paper.get("open_access")), "content_hash": _sha(source_payload) if source_payload else "",
            "source_payload_path": source_path, "evidence_extracts": extracts,
        }
        paper_file = papers_dir / f"{paper_id}.json"
        paper_file.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        records.append({"paper_id": paper_id,
                        "path": str(paper_file.relative_to(project_dir)).replace("\\", "/"),
                        "doi": record["doi"], "pmid": record["pmid"], "url": record["url"],
                        "evidence_ids": [e["evidence_id"] for e in extracts]})
    artifact = {
        "schema_version": SCHEMA_VERSION, "evidence_receipt_schema": "EvidenceRunReceipt/v1.1",
        "kind": "deep_research_run", "research_phase": "pre_research",
        "research_persona": research_persona, "run_id": run_id,
        "project_id": project_id, "round_id": str(round_id),
        "profile_id": profile_id,
        "status": "completed", "candidate_id": candidate_id, "node": node, "created_at": _now(),
        "queries": payload["queries"], "skill_receipt": receipt, "papers": records,
        "rejected_papers": rejected_papers,
        "review_search": payload.get("review_search", {}), "verification": payload.get("verification", []),
        "result_context_hash": _sha(result_context) if result_context else "",
    }
    run_file = runs_dir / f"{run_id}.json"
    summary_file = runs_dir / f"{run_id}.md"
    artifact["path"] = str(run_file.relative_to(project_dir)).replace("\\", "/")
    artifact["summary_path"] = str(summary_file.relative_to(project_dir)).replace("\\", "/")
    run_file.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    summary_file.write_text(render_pre_research_markdown(artifact), encoding="utf-8")
    return artifact


def _artifact(project_dir: str | Path, candidate_id: str, node: str,
              *, run_id: str | None = None) -> dict | None:
    """Load an exact evidence run when requested; legacy callers use latest."""
    runs_dir, _, _ = _run_paths(Path(project_dir))
    if run_id:
        path = runs_dir / f"{_safe_id(run_id)}.json"
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if artifact.get("run_id") != run_id or artifact.get("candidate_id") != candidate_id or artifact.get("node") != node:
            return None
        return artifact
    matches = []
    for path in runs_dir.glob(f"{_safe_id(candidate_id)}_{node.replace('.', '_')}_*.json"):
        try:
            matches.append((path.stat().st_mtime_ns, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def _latest_artifact(project_dir: str | Path, candidate_id: str, node: str) -> dict | None:
    """Compatibility helper; new context assembly must supply an exact run ID."""
    return _artifact(project_dir, candidate_id, node)


def run_ids_for_stage(
    project_dir: str | Path, candidate_id: str, node: str
) -> list[str]:
    """Return stable evidence run IDs without consulting filesystem mtimes."""
    runs_dir, _, _ = _run_paths(Path(project_dir))
    found = []
    for path in sorted(
        runs_dir.glob(
            f"{_safe_id(candidate_id)}_{node.replace('.', '_')}_*.json"
        ),
        key=lambda item: item.name,
    ):
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if artifact.get("candidate_id") == candidate_id and artifact.get("node") == node:
            run_id = str(artifact.get("run_id") or "")
            if run_id:
                found.append(run_id)
    return found


def unique_run_id(project_dir: str | Path, candidate_id: str, node: str) -> str | None:
    """Return an unambiguous run ID without selecting by mtime.

    A native context may infer the ID only while there is exactly one valid run
    for the candidate/stage; once a retry creates multiple runs, callers must
    supply --evidence-run-id explicitly.
    """
    found = run_ids_for_stage(project_dir, candidate_id, node)
    return found[0] if len(found) == 1 else None


def evidence_artifact_manifest(
    project_dir: str | Path,
    candidate_id: str,
    node: str,
    run_id: str,
) -> dict:
    """Return the exact immutable evidence files consumed by one context."""
    root = Path(project_dir)
    artifact = _artifact(root, candidate_id, node, run_id=run_id)
    if artifact is None:
        raise DeepResearchError(
            f"evidence pack missing for {candidate_id} {node} run {run_id}"
        )
    root_resolved = root.resolve()

    def bound_path(value: str, label: str) -> Path:
        path = (root / value).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError as exc:
            raise DeepResearchError(
                f"evidence {label} path escapes the project"
            ) from exc
        return path

    run_path = bound_path(
        str((_run_paths(root)[0] / f"{_safe_id(run_id)}.json").relative_to(root)),
        "run",
    )
    summary_value = artifact.get("summary_path")
    summary_path = (
        bound_path(str(summary_value), "summary")
        if summary_value
        else bound_path(
            f"02_Agent_Notes/_pre_research/{node}_research.md", "summary"
        )
    )
    if not summary_path.is_file():
        raise DeepResearchError("exact evidence-run summary is missing")
    summary_text = summary_path.read_text(encoding="utf-8")
    if f"`{run_id}`" not in summary_text:
        raise DeepResearchError("pre-research summary does not match the selected evidence run")
    files = [{
        "kind": "run",
        "path": str(run_path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha(run_path.read_bytes()),
    }, {
        "kind": "summary",
        "path": str(summary_path.relative_to(root)).replace("\\", "/"),
        "sha256": _sha(summary_path.read_bytes()),
    }]
    for ref in artifact.get("papers", []):
        try:
            paper_path = bound_path(str(ref["path"]), "paper")
            paper = json.loads(paper_path.read_text(encoding="utf-8"))
        except (KeyError, OSError, json.JSONDecodeError) as exc:
            raise DeepResearchError("evidence run references an unreadable paper record") from exc
        files.append({
            "kind": "paper",
            "path": str(paper_path.relative_to(root)).replace("\\", "/"),
            "sha256": _sha(paper_path.read_bytes()),
        })
        source_value = paper.get("source_payload_path")
        if source_value:
            source_path = bound_path(str(source_value), "source")
            if not source_path.is_file():
                raise DeepResearchError("evidence paper source payload is missing")
            files.append({
                "kind": "source",
                "path": str(source_path.relative_to(root)).replace("\\", "/"),
                "sha256": _sha(source_path.read_bytes()),
            })
    return {
        "run_id": run_id,
        "project_id": str(artifact.get("project_id") or ""),
        "candidate_id": str(artifact.get("candidate_id") or ""),
        "round_id": str(artifact.get("round_id") or ""),
        "profile_id": str(artifact.get("profile_id") or ""),
        "target_node": str(artifact.get("node") or ""),
        "research_phase": str(artifact.get("research_phase") or ""),
        "research_persona": str(artifact.get("research_persona") or ""),
        "receipt_schema": str(artifact.get("evidence_receipt_schema") or ""),
        "files": sorted(files, key=lambda item: (item["kind"], item["path"])),
    }


def audit_evidence_pack(project_dir: str | Path, candidate_id: str, node: str,
                        *, run_id: str | None = None) -> tuple[bool, str]:
    artifact = _artifact(project_dir, candidate_id, node, run_id=run_id)
    if not artifact:
        return False, f"evidence pack missing for {candidate_id} {node}"
    receipt = artifact.get("skill_receipt") or {}
    if artifact.get("status") != "completed" or receipt.get("exit_code") != 0:
        return False, "evidence pack has no successful skill receipt"
    if receipt.get("skill") not in {"academic-research-suite", "academic-research-skills"}:
        return False, "evidence pack was not produced by Academic Research Skills"
    records = []
    root = Path(project_dir)
    for ref in artifact.get("papers", []):
        try:
            records.append(json.loads((root / ref["path"]).read_text(encoding="utf-8")))
        except (KeyError, OSError, json.JSONDecodeError):
            return False, "evidence pack references an unreadable paper record"
    sections = {str(e.get("section", "")).lower() for r in records for e in r.get("evidence_extracts", [])
                if e.get("verification_status") == "located" and e.get("locator")}
    if node == "L1":
        for required in ("results", "discussion", "conclusion"):
            if required not in sections:
                return False, f"L1 evidence lacks located {required.title()} extract"
    elif node == "L4":
        if "methods" not in sections:
            return False, "L4 evidence lacks located Methods extract"
        review = artifact.get("review_search") or {}
        if review.get("status") not in {"completed", "none_found"} or not review.get("receipt"):
            return False, "L4 requires a review search receipt or a documented zero-result search"
        if review.get("status") == "completed":
            review_sections = {
                str(e.get("section", "")).lower()
                for record in records
                if str(record.get("paper_type", "")).lower() in {"review", "systematic_review", "meta_analysis"}
                for e in record.get("evidence_extracts", [])
                if e.get("verification_status") == "located" and e.get("locator")
            }
            if not {"results", "conclusion"}.issubset(review_sections):
                return False, "L4 completed review search lacks located review Results and Conclusion extracts"
    elif node == "L8.5":
        verification = artifact.get("verification")
        if not artifact.get("result_context_hash"):
            return False, "L8.5 evidence pack lacks the audited L7/L8 result context hash"
        if not isinstance(verification, list) or not verification:
            return False, "L8.5 requires a paper-based verification verdict"
        known_ids = {e.get("evidence_id") for r in records for e in r.get("evidence_extracts", [])}
        for item in verification:
            if not isinstance(item, dict) or not str(item.get("finding", "")).strip():
                return False, "L8.5 verification entries require a finding"
            if item.get("verdict") not in {"supports", "contradicts", "unresolved"}:
                return False, "L8.5 verification verdict must be supports, contradicts, or unresolved"
            if not isinstance(item.get("evidence_ids"), list) or not item["evidence_ids"]:
                return False, "L8.5 verification entries require evidence_ids"
            if any(str(value) not in known_ids for value in item["evidence_ids"]):
                return False, "L8.5 verification references an unknown evidence ID"
    return True, ""


def render_evidence_digest(project_dir: str | Path, candidate_id: str, nodes: list[str],
                           *, run_ids: dict[str, str] | None = None) -> str:
    """Render compact, source-located evidence for a cognitive-node context."""
    root = Path(project_dir)
    lines = ["=== DEEP RESEARCH EVIDENCE ==="]
    for node in nodes:
        if run_ids is not None and node not in run_ids:
            continue
        artifact = _artifact(root, candidate_id, node, run_id=(run_ids or {}).get(node))
        if not artifact:
            continue
        lines.append(f"## {node} Evidence IDs")
        for ref in artifact.get("papers", []):
            try:
                paper = json.loads((root / ref["path"]).read_text(encoding="utf-8"))
            except (KeyError, OSError, json.JSONDecodeError):
                continue
            lines.append(f"- Paper {paper['paper_id']}: {paper['title']} ({paper.get('doi') or paper.get('pmid') or paper.get('url')})")
            for extract in paper.get("evidence_extracts", []):
                lines.append(f"  - [{extract['evidence_id']}] {extract['section']} @ {extract['locator']}: {extract['text']}")
    return "\n".join(lines) + "\n"


def evidence_ids(project_dir: str | Path, candidate_id: str, nodes: list[str],
                 *, run_ids: dict[str, str] | None = None) -> list[str]:
    """Return IDs present in persisted, source-located evidence records."""
    root = Path(project_dir)
    found = []
    for node in nodes:
        if run_ids is not None and node not in run_ids:
            continue
        artifact = _artifact(root, candidate_id, node, run_id=(run_ids or {}).get(node))
        if not artifact:
            continue
        for ref in artifact.get("papers", []):
            try:
                paper = json.loads((root / ref["path"]).read_text(encoding="utf-8"))
            except (KeyError, OSError, json.JSONDecodeError):
                continue
            found.extend(str(e["evidence_id"]) for e in paper.get("evidence_extracts", [])
                         if e.get("verification_status") == "located" and e.get("locator"))
    return found


def evidence_pack_details(project_dir: str | Path, candidate_id: str,
                          node: str = "L8.5", *, run_id: str | None = None) -> dict:
    """Return hash-bound, source-located records for ledger import."""
    ok, reason = audit_evidence_pack(project_dir, candidate_id, node, run_id=run_id)
    if not ok:
        raise DeepResearchError(reason)
    root = Path(project_dir)
    artifact = _artifact(root, candidate_id, node, run_id=run_id)
    if artifact is None:  # guarded by audit; keeps the return type explicit
        raise DeepResearchError("evidence pack missing")
    records = {}
    for paper_ref in artifact.get("papers", []):
        path = root / paper_ref["path"]
        paper = json.loads(path.read_text(encoding="utf-8"))
        file_hash = _sha(path.read_text(encoding="utf-8"))
        for index, extract in enumerate(paper.get("evidence_extracts", [])):
            if extract.get("verification_status") != "located" or not extract.get("locator"):
                continue
            records[str(extract["evidence_id"])] = {
                "summary": str(extract["text"]),
                "artifact_ref": {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "sha256": file_hash,
                    "json_pointer": f"/evidence_extracts/{index}",
                },
            }
    return {
        "run_id": artifact["run_id"],
        "receipt_hash": _sha(json.dumps(artifact["skill_receipt"],
                                         ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"))),
        "records": records,
    }


def render_pre_research_markdown(artifact: dict) -> str:
    identifiers = []
    for paper in artifact.get("papers", []):
        identifier = (f"doi:{paper['doi']}" if paper.get("doi")
                      else f"PMID:{paper['pmid']}" if paper.get("pmid")
                      else paper.get("url") or paper["paper_id"])
        identifiers.append(f"{paper['paper_id']} ({identifier})")
    receipt = artifact["skill_receipt"]
    queries = "\n".join(f"- {q}" for q in artifact.get("queries", []))
    return f"""# Pre-Research: {artifact['node']}\n\n## Runtime digest\nVerified Academic Research evidence pack `{artifact['run_id']}` with paper IDs: {', '.join(identifiers)}.\n\n## Evidence pack\n- {artifact['path']}\n\n## Query log\n{queries}\n\n## Tool receipt\n- {receipt['backend']} / {receipt['skill']} {receipt.get('skill_version', '')}; command_hash={receipt['command_hash']}; prompt_hash={receipt['prompt_hash']}\n\n## Source count\n{len(artifact.get('papers', []))}\n"""


def run_and_persist(
    project_dir: str | Path,
    candidate_id: str,
    node: str,
    question: str,
    claim: str,
    spec: RuntimeSpec,
    work_dir: str | Path,
    skill_version: str = "unknown",
    result_context: str = "",
    *,
    project_id: str = "",
    round_id: str = "",
    profile_id: str = "",
    research_persona: str = "Curie",
) -> dict:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    schema_path = work_dir / "deep_research_output.schema.json"
    schema_path.write_text(json.dumps(_runtime_schema(), indent=2), encoding="utf-8")
    command, prompt = build_invocation(spec, node, question, claim, work_dir, result_context)
    try:
        completed = subprocess.run(command + [prompt], capture_output=True, text=True,
                                   encoding="utf-8", errors="strict",
                                   timeout=spec.timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeepResearchError(f"Academic Research CLI invocation failed: {exc}") from exc
    receipt = skill_receipt(spec.backend, command, prompt, skill_version,
                            exit_code=completed.returncode, stdout_hash=_sha(completed.stdout),
                            model=spec.model)
    if completed.returncode != 0:
        raise DeepResearchError(f"Academic Research CLI exited {completed.returncode}: {completed.stderr.strip()}")
    artifact = persist_run(
        project_dir, candidate_id, node, _parse_cli_output(completed.stdout),
        receipt, result_context, project_id=project_id, round_id=round_id,
        profile_id=profile_id, research_persona=research_persona,
    )
    target = Path(project_dir) / "02_Agent_Notes" / "_pre_research" / f"{node}_research.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_pre_research_markdown(artifact), encoding="utf-8")
    return artifact


def runtime_ready(spec: RuntimeSpec) -> tuple[bool, str]:
    if spec.backend not in SUPPORTED_BACKENDS:
        return False, f"backend must be one of {', '.join(SUPPORTED_BACKENDS)}"
    if not shutil.which(spec.executable):
        return False, f"executable not found: {spec.executable}"
    if spec.backend == "claude":
        if not spec.plugin_dir or not Path(spec.plugin_dir).exists():
            return False, "Claude Academic Research plugin_dir is missing"
        manifests = [Path(spec.plugin_dir) / ".claude-plugin" / "plugin.json",
                     Path(spec.plugin_dir) / "plugin.json"]
        if not any(path.exists() for path in manifests):
            return False, "Claude Academic Research plugin manifest is missing"
    if spec.backend == "codex":
        if not spec.skill_path:
            return False, "Codex Academic Research skill_path is required"
        manifest = Path(spec.skill_path) / "manifest.json"
        if not manifest.exists():
            return False, "Codex Academic Research skill manifest is missing"
    return True, ""
