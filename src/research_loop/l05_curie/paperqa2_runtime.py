"""Explicit external PaperQA2 runtime and source-candidate alignment.

The PaperQA2 process is retrieval-only. It returns ranked chunks and immutable
runtime provenance. Alignment to an independently acquired source paragraph is
still an UNVERIFIED candidate operation; only the source verifier may emit a
LOCATED EvidenceExtract.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from research_loop.process_runner import DEFAULT_PROCESS_RUNNER, ProcessRunner

from .contracts import CurieContractError
from .paperqa2 import (
    PAPERQA2_DOCUMENT_RUNTIME_SCHEMA_VERSION,
    PAPERQA2_RUNTIME_SCHEMA_VERSION,
    PaperQA2Retriever,
    PAPERQA2_CORPUS_TASK_SCHEMA_VERSION, canonical_corpus_bytes,
    _corpus_task_id, _validate_evidence_focus, validate_paperqa2_corpus_task,
    validate_paperqa2_corpus_result,
)
from .contracts import _require_dict, _require_exact_keys, _require_int, _require_text

_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_RUNTIME = (
    "package", "version", "upstream_repo", "upstream_tag", "upstream_commit",
    "fork_repo",
)
PAPERQA2_PACKAGE = "paper-qa"
PAPERQA2_VERSION = "2026.8.12"
PAPERQA2_UPSTREAM_REPO = "https://github.com/Future-House/paper-qa"
PAPERQA2_UPSTREAM_TAG = "v2026.08.12"
PAPERQA2_UPSTREAM_COMMIT = "57e89f7223b0960d5ee5ea048c69e3c47e088572"
PAPERQA2_FORK_REPO = "https://github.com/hk20013106/paper-qa"
PAPERQA2_BACKEND_ID = "paperqa2-fork-v2026.08.12/sparse-docs-v1"
PAPERQA2_QUERY_GENERATION_MODE = "paperqa2-keyword-proposals-v1"
SOURCE_ALIGNMENT_METHOD = "token-coverage-multimatch/v2"
MIN_SOURCE_TOKEN_COVERAGE = 0.5
_PINNED_RUNTIME = {
    "package": PAPERQA2_PACKAGE,
    "version": PAPERQA2_VERSION,
    "upstream_repo": PAPERQA2_UPSTREAM_REPO,
    "upstream_tag": PAPERQA2_UPSTREAM_TAG,
    "upstream_commit": PAPERQA2_UPSTREAM_COMMIT,
    "fork_repo": PAPERQA2_FORK_REPO,
}


def materialize_corpus_question(seed: dict, *, evidence_focus: dict | None) -> str:
    _require_dict(seed, "ResearchSeed")
    question = _require_text(seed.get("scientific_question"), "ResearchSeed scientific_question")
    hypothesis = _require_text(seed.get("hypothesis_seed"), "ResearchSeed hypothesis_seed")
    base = f"Scientific question:\n{question}\n\nHypothesis to evaluate:\n{hypothesis}"
    focus = _validate_evidence_focus(evidence_focus)
    if focus is not None:
        base += "\n\nEvidence focus:\n" + canonical_corpus_bytes(focus["gaps"])[:-1].decode("utf-8")
    try:
        base.encode("utf-8")
    except UnicodeError as exc:
        raise CurieContractError("corpus question must be strict UTF-8") from exc
    return base


def build_corpus_task(*, acquisition_run_id: str, attempt_index: int, seed: dict,
                      settings_sha256: str, corpus: list[dict], evidence_k: int,
                      evidence_focus: dict | None) -> dict:
    from research_loop.research_seed import seed_sha256

    task = {"schema_version": PAPERQA2_CORPUS_TASK_SCHEMA_VERSION,
            "research_seed_sha256": seed_sha256(seed),
            "question": materialize_corpus_question(seed, evidence_focus=evidence_focus),
            "evidence_focus": copy.deepcopy(evidence_focus), "parser_profile": "jats-paragraphs/v2",
            "settings_sha256": settings_sha256, "corpus": copy.deepcopy(corpus),
            "budget": {"evidence_k": evidence_k}}
    task["task_id"] = _corpus_task_id(task, acquisition_run_id=acquisition_run_id, attempt_index=attempt_index)
    return validate_paperqa2_corpus_task(task, acquisition_run_id=acquisition_run_id, attempt_index=attempt_index)


def validate_corpus_worker_config(config: dict) -> dict:
    """Freeze non-sensitive native Settings and bounded acquisition configuration."""
    config = copy.deepcopy(_require_dict(config, "corpus worker config"))
    canonical_corpus_bytes(config)
    if config.get("worker_mode") != "corpus-evidence-v1":
        raise CurieContractError("corpus worker_mode must be explicit")
    if ("query_generation" in config
            and config["query_generation"] != PAPERQA2_QUERY_GENERATION_MODE):
        raise CurieContractError("corpus query_generation selector is unsupported")
    for key in ("python_executable", "bridge_script", "paperqa_repo", "pqa_home"):
        _require_text(config.get(key), f"corpus config {key}")
    _require_int(config.get("timeout_seconds"), "timeout_seconds")
    config["settings"] = _validate_corpus_settings(config.get("settings"))
    budget = config.setdefault("acquisition_budget", {})
    _require_dict(budget, "acquisition_budget")
    defaults = {"max_acquisition_attempts": 3, "new_papers_per_attempt": 30, "cumulative_paper_limit": 90}
    if set(budget) - set(defaults):
        raise CurieContractError("unknown acquisition_budget fields")
    for key, maximum in defaults.items():
        budget.setdefault(key, maximum)
        _require_int(budget[key], key, maximum=maximum)
    return config


def _validate_corpus_settings(settings: dict) -> dict:
    """One Settings boundary shared by configuration and result validation."""
    settings = copy.deepcopy(_require_dict(settings, "corpus Settings"))
    canonical_corpus_bytes(settings)
    for key in ("embedding", "summary_llm"):
        _require_text(settings.get(key), f"Settings {key}")
    # Credentials belong to the environment; reject them before any artifact can be frozen.
    def reject_credentials(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and key.casefold() in {"api_key", "apikey", "access_token", "authorization", "password", "secret", "client_secret"}:
                    raise CurieContractError("credentials are not permitted in frozen Settings")
                reject_credentials(item)
        elif isinstance(value, list):
            for item in value:
                reject_credentials(item)
    reject_credentials(settings)
    for key in ("embedding_config", "summary_llm_config"):
        if key not in settings or not isinstance(settings[key], dict):
            raise CurieContractError(f"Settings {key} must explicitly contain non-sensitive configuration")
    answer = _require_dict(settings.get("answer"), "Settings answer")
    answer.setdefault("evidence_k", 60)
    answer.setdefault("max_concurrent_requests", 4)
    _require_int(answer["evidence_k"], "evidence_k")
    _require_int(answer["max_concurrent_requests"], "max_concurrent_requests", maximum=4)
    for key, required in {"evidence_retrieval": True, "evidence_skip_summary": False, "evidence_text_only_fallback": False}.items():
        if answer.get(key) is not required:
            raise CurieContractError(f"Settings answer.{key} must be {required}")
    parsing = _require_dict(settings.get("parsing"), "Settings parsing")
    for key in ("use_doc_details", "multimodal"):
        if parsing.get(key) is not False:
            raise CurieContractError(f"Settings parsing.{key} must be false")
    if parsing.get("doc_filters") not in ([], None) or "doc_filters" not in parsing:
        raise CurieContractError("Settings parsing.doc_filters must be explicitly empty")
    if type(parsing.get("defer_embedding")) is not bool:
        raise CurieContractError("Settings parsing.defer_embedding must be explicit boolean")
    if type(settings.get("texts_index_mmr_lambda")) not in (int, float) or settings["texts_index_mmr_lambda"] != 1.0:
        raise CurieContractError("Settings texts_index_mmr_lambda must be 1.0")
    return settings


def _decode_corpus_json(raw: bytes) -> dict:
    """Strict transport decode before dict validation or canonical hashing."""
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise CurieContractError(f"duplicate JSON key: {key}")
            value[key] = item
        return value
    def constant(value):
        raise CurieContractError("non-finite JSON number")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        raise CurieContractError("corpus transport is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CurieContractError("corpus transport must be a JSON object")
    return value


class _CorpusOutputObserver:
    def __init__(self, worker_dir: Path):
        self.handles = {}
        try:
            for name in ("stdout", "stderr"):
                self.handles[name] = (worker_dir / f"{name}.log").open("xb")
        except OSError:
            self.close()
            raise

    def on_stdout(self, chunk: bytes):
        self.handles["stdout"].write(chunk)

    def on_stderr(self, chunk: bytes):
        self.handles["stderr"].write(chunk)

    def finish(self):
        for handle in self.handles.values():
            handle.flush()
            os.fsync(handle.fileno())

    def close(self):
        for handle in self.handles.values():
            handle.close()


def _corpus_log_facts(project: Path, worker: Path, process=None) -> dict:
    facts = {}
    for name in ("stdout", "stderr"):
        path = worker / f"{name}.log"
        raw = path.read_bytes()
        facts[name] = {"path": path.relative_to(project).as_posix(),
                       "sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw),
                       "truncated": getattr(process, f"{name}_truncated", False)}
        if process is not None and len(raw) != getattr(process, f"{name}_bytes"):
            raise PaperQA2ExecutionError("PERSISTENCE_ERROR: incomplete corpus process log")
    frames = []
    for line in (worker / "stderr.log").read_bytes().splitlines():
        if line.lstrip().startswith(b'{"paperqa2_corpus_diagnostic"'):
            try:
                frame = _decode_corpus_json(line)
                _require_exact_keys(frame, {"paperqa2_corpus_diagnostic"}, "corpus diagnostic frame")
                frames.append(frame["paperqa2_corpus_diagnostic"])
            except CurieContractError as exc:
                facts["diagnostic_error"] = str(exc)
    facts["diagnostics"] = frames
    return facts


def validate_corpus_completion(completion: dict, *, task: dict, result: dict | None, process_logs: dict) -> dict:
    fields = {"worker_mode", "task_id", "task_sha256", "settings_sha256", "result_sha256",
              "process_terminal_state", "returncode", "stdout", "stderr",
              "terminal_context_error_count", "process_tree_cleanup"}
    _require_exact_keys(completion, fields | ({"error"} if "error" in completion else set()), "corpus completion")
    if (completion["worker_mode"] != "corpus-evidence-v1" or completion["task_id"] != task["task_id"]
            or completion["task_sha256"] != hashlib.sha256(canonical_corpus_bytes(task)).hexdigest()
            or completion["settings_sha256"] != task["settings_sha256"]):
        raise PaperQA2IntegrityError("corpus completion task/Settings binding mismatch")
    for name in ("stdout", "stderr"):
        _require_exact_keys(completion[name], {"path", "sha256", "byte_count", "truncated"}, f"completion {name}")
        if completion[name] != process_logs[name]:
            raise PaperQA2IntegrityError("corpus completion full log mismatch")
    if "error" in completion:
        if result is not None or completion["result_sha256"] is not None:
            raise PaperQA2IntegrityError("failed execution cannot bind successful result")
        return copy.deepcopy(completion)
    frames = process_logs["diagnostics"]
    if process_logs.get("diagnostic_error"):
        raise PaperQA2ExecutionError(process_logs["diagnostic_error"])
    if len(frames) != 1:
        raise PaperQA2ExecutionError("corpus completion requires one terminal diagnostic frame")
    frame = _require_exact_keys(frames[0], {"task_id", "capture_established", "capture_failed", "terminal_context_error_count"}, "corpus diagnostic")
    _require_int(frame["terminal_context_error_count"], "terminal_context_error_count", minimum=0)
    if (frame["task_id"] != task["task_id"] or frame["capture_established"] is not True
            or frame["capture_failed"] is not False or frame["terminal_context_error_count"] != 0):
        raise PaperQA2ExecutionError("native corpus terminal diagnostic failure")
    if (completion["process_terminal_state"] != "completed" or type(completion["returncode"]) is not int
            or completion["returncode"] != 0 or completion["terminal_context_error_count"] != 0
            or result is None or completion["result_sha256"] != hashlib.sha256(canonical_corpus_bytes(result)).hexdigest()):
        raise PaperQA2ExecutionError("corpus completion is not successful")
    if not isinstance(completion["process_tree_cleanup"], dict) or completion["process_tree_cleanup"].get("alive_after_cleanup") is not False:
        raise PaperQA2ExecutionError("corpus process cleanup is unresolved")
    return copy.deepcopy(completion)


class PaperQA2ExecutionError(CurieContractError):
    """PaperQA2 did not produce a trustworthy successful process response."""


class PaperQA2IntegrityError(CurieContractError):
    """PaperQA2 runtime or document provenance failed an integrity check."""


class PaperQA2SourceError(CurieContractError):
    """A valid PaperQA2 result could not yield evidence for this source."""


def _text(value: object, name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise CurieContractError(f"{name} must be a non-empty string")
    return value


def _integrity_text(value: object, name: str) -> str:
    try:
        return _text(value, name)
    except CurieContractError as exc:
        raise PaperQA2IntegrityError(str(exc)) from exc


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PaperQA2IntegrityError(f"PaperQA2 PDF is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tokens(value: object) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.findall(r"[\w]+", normalized, flags=re.UNICODE)


def validate_pinned_paperqa2_runtime(
    runtime: object,
    *,
    pdf_sha256: str = "",
    document_sha256: str = "",
    media_type: str = "",
) -> dict:
    """Validate immutable PaperQA2 integration provenance at every use boundary."""
    if not isinstance(runtime, dict):
        raise PaperQA2IntegrityError("PaperQA2 bridge runtime provenance must be an object")
    schema_version = runtime.get("schema_version")
    if schema_version == PAPERQA2_RUNTIME_SCHEMA_VERSION:
        required_runtime = _REQUIRED_RUNTIME + ("pdf_sha256",)
    elif schema_version == PAPERQA2_DOCUMENT_RUNTIME_SCHEMA_VERSION:
        required_runtime = _REQUIRED_RUNTIME + ("document_sha256", "media_type")
    else:
        raise PaperQA2IntegrityError("PaperQA2 bridge runtime schema_version is invalid")
    for field in required_runtime:
        _integrity_text(runtime.get(field), f"PaperQA2 bridge runtime {field}")
    commit = str(runtime["upstream_commit"]).lower()
    if not _GIT_COMMIT.fullmatch(commit):
        raise PaperQA2IntegrityError(
            "PaperQA2 bridge upstream_commit must be a 40-character git SHA"
        )
    for field, expected in _PINNED_RUNTIME.items():
        observed = commit if field == "upstream_commit" else str(runtime[field])
        if observed != expected:
            raise PaperQA2IntegrityError(
                f"PaperQA2 runtime {field} does not match the pinned integration"
            )
    if schema_version == PAPERQA2_RUNTIME_SCHEMA_VERSION:
        expected_hash = _integrity_text(
            pdf_sha256, "requested PaperQA2 PDF hash"
        ).lower()
        if str(runtime["pdf_sha256"]).lower() != expected_hash:
            raise PaperQA2IntegrityError(
                "PaperQA2 runtime PDF hash does not match the requested PDF"
            )
    else:
        expected_hash = _integrity_text(
            document_sha256, "requested PaperQA2 document hash"
        ).lower()
        expected_media_type = _integrity_text(
            media_type, "requested PaperQA2 media_type"
        )
        if str(runtime["document_sha256"]).lower() != expected_hash:
            raise PaperQA2IntegrityError(
                "PaperQA2 runtime document hash does not match the requested document"
            )
        if str(runtime["media_type"]) != expected_media_type:
            raise PaperQA2IntegrityError(
                "PaperQA2 runtime media_type does not match the requested document"
            )
    return copy.deepcopy(runtime)


class PaperQA2SubprocessBackend:
    """Call the pinned PaperQA2 checkout through an explicit JSON bridge."""

    def __init__(
        self,
        *,
        python_executable: str | Path,
        bridge_script: str | Path,
        paperqa_repo: str | Path,
        pqa_home: str | Path,
        timeout_seconds: int = 300,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.python_executable = Path(python_executable).resolve()
        self.bridge_script = Path(bridge_script).resolve()
        self.paperqa_repo = Path(paperqa_repo).resolve()
        self.pqa_home = Path(pqa_home).resolve()
        self.backend_id = PAPERQA2_BACKEND_ID
        self.runner = runner or DEFAULT_PROCESS_RUNNER
        if not self.python_executable.is_file():
            raise CurieContractError(f"PaperQA2 Python executable is missing: {self.python_executable}")
        if not self.bridge_script.is_file():
            raise CurieContractError(f"PaperQA2 bridge script is missing: {self.bridge_script}")
        if not self.paperqa_repo.is_dir():
            raise CurieContractError(f"PaperQA2 repository is missing: {self.paperqa_repo}")
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise CurieContractError("PaperQA2 timeout_seconds must be a positive integer")
        self.timeout_seconds = timeout_seconds
        self.pqa_home.mkdir(parents=True, exist_ok=True)

    def execute_search_queries(
        self, *, question: str, count: int, settings: dict, expected_runtime: dict,
    ):
        """Run the pinned PaperQA2 keyword helper without creating worker artifacts."""
        if not isinstance(question, str) or not question.strip():
            raise CurieContractError("PaperQA2 keyword question must be non-empty text")
        if type(count) is not int or count != 3:
            raise CurieContractError("PaperQA2 keyword request count must be exactly 3")
        settings = _validate_corpus_settings(settings)
        fields = {
            "package", "version", "upstream_tag", "upstream_commit",
            "module_path", "clean_checkout", "llm_model",
        }
        if (not isinstance(expected_runtime, dict) or set(expected_runtime) != fields
                or expected_runtime.get("package") != PAPERQA2_PACKAGE
                or expected_runtime.get("version") != PAPERQA2_VERSION
                or expected_runtime.get("upstream_tag") != PAPERQA2_UPSTREAM_TAG
                or expected_runtime.get("upstream_commit") != PAPERQA2_UPSTREAM_COMMIT
                or expected_runtime.get("module_path") != str(
                    self.paperqa_repo / "src" / "paperqa" / "agents" / "helpers.py"
                )
                or expected_runtime.get("clean_checkout") is not True
                or expected_runtime.get("llm_model") != settings["summary_llm"]):
            raise PaperQA2IntegrityError("PaperQA2 keyword runtime/model binding is invalid")
        request = {
            "worker_mode": "search-query-v1",
            "question": question,
            "count": count,
            "settings": settings,
            "paperqa_repo": str(self.paperqa_repo),
            "pqa_home": str(self.pqa_home),
            "expected_runtime": copy.deepcopy(expected_runtime),
        }
        environment = os.environ.copy()
        environment["PQA_HOME"] = str(self.pqa_home)
        try:
            process = self.runner.run(
                [str(self.python_executable), str(self.bridge_script)],
                cwd=str(self.paperqa_repo),
                env=environment,
                input_text=canonical_corpus_bytes(request).decode("utf-8"),
                timeout=self.timeout_seconds,
                encoding="utf-8",
                errors="strict",
            )
        except OSError as exc:
            raise PaperQA2ExecutionError("PaperQA2 keyword subprocess could not start") from exc
        try:
            payload = _decode_corpus_json(process.stdout.encode("utf-8"))
        except CurieContractError:
            payload = None
        return process, payload

    def execute_corpus(self, *, project_dir: str | Path, task: dict, settings: dict,
                       worker_dir: str | Path, acquisition_run_id: str, attempt_index: int) -> dict:
        from .europepmc import parse_jats_paragraphs
        from .europepmc_runtime import _atomic_json

        project = Path(project_dir).resolve(strict=True)
        worker = Path(worker_dir).resolve()
        try:
            worker.relative_to(project)
        except ValueError as exc:
            raise PaperQA2IntegrityError("corpus worker path escapes project") from exc
        task = validate_paperqa2_corpus_task(task, acquisition_run_id=acquisition_run_id, attempt_index=attempt_index)
        settings = _validate_corpus_settings(settings)
        if hashlib.sha256(canonical_corpus_bytes(settings)).hexdigest() != task["settings_sha256"]:
            raise PaperQA2IntegrityError("corpus frozen Settings hash mismatch")
        for paper in task["corpus"]:
            path = (project / paper["document_path"]).resolve(strict=True)
            try:
                path.relative_to(project)
            except ValueError as exc:
                raise PaperQA2IntegrityError("corpus source path escapes project") from exc
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != paper["document_sha256"]:
                raise PaperQA2IntegrityError("corpus snapshot SHA-256 mismatch before dispatch")
            units = [{"source_locator": u["locator"], "section": u["section"], "source_text": u["text"]}
                     for u in parse_jats_paragraphs(raw, parser_profile=task["parser_profile"])]
            if units != paper["source_units"]:
                raise PaperQA2IntegrityError("corpus source_units mismatch independently read XML")
        worker.mkdir(parents=True, exist_ok=True)
        _atomic_json(worker / "task.json", task, immutable=True)
        _atomic_json(worker / "settings.json", settings, immutable=True)
        observer = _CorpusOutputObserver(worker)
        process = None
        result = None
        failure = None
        try:
            process = self.runner.run(
                [str(self.python_executable), str(self.bridge_script)], cwd=self.paperqa_repo,
                env={**os.environ, "PQA_HOME": str(self.pqa_home)}, timeout=self.timeout_seconds,
                input_text=canonical_corpus_bytes({"worker_mode": "corpus-evidence-v1", "task": task,
                    "settings": settings, "project_root": str(project), "paperqa_repo": str(self.paperqa_repo),
                    "pqa_home": str(self.pqa_home)}).decode("utf-8"), observer=observer,
                encoding="utf-8", errors="strict")
            observer.finish()
        except Exception as exc:
            failure = PaperQA2ExecutionError(f"PERSISTENCE_ERROR: corpus capture failed: {exc}")
        finally:
            observer.close()
        logs = _corpus_log_facts(project, worker, process)
        completion = {"worker_mode": "corpus-evidence-v1", "task_id": task["task_id"],
            "task_sha256": hashlib.sha256(canonical_corpus_bytes(task)).hexdigest(),
            "settings_sha256": task["settings_sha256"], "result_sha256": None,
            "process_terminal_state": process.terminal_state if process else "unknown",
            "returncode": process.returncode if process else None, "stdout": logs["stdout"], "stderr": logs["stderr"],
            "terminal_context_error_count": None,
            "process_tree_cleanup": dict(process.process_tree_cleanup) if process else None}
        try:
            if failure is not None:
                raise failure
            if process.terminal_state != "completed" or process.returncode != 0:
                raise PaperQA2ExecutionError(f"corpus process {process.terminal_state}, returncode={process.returncode}")
            expected = {key: _PINNED_RUNTIME[key] for key in ("package", "version", "upstream_commit", "upstream_tag")}
            expected.update(embedding_model=settings["embedding"], summary_llm_model=settings["summary_llm"])
            result = validate_paperqa2_corpus_result(_decode_corpus_json((worker / "stdout.log").read_bytes()),
                task=task, settings=settings, expected_runtime=expected)
            completion["result_sha256"] = hashlib.sha256(canonical_corpus_bytes(result)).hexdigest()
            if len(logs["diagnostics"]) == 1:
                completion["terminal_context_error_count"] = logs["diagnostics"][0].get("terminal_context_error_count")
            validate_corpus_completion(completion, task=task, result=result, process_logs=logs)
        except CurieContractError as exc:
            failure = exc if isinstance(exc, PaperQA2ExecutionError) else PaperQA2ExecutionError(str(exc))
            completion["result_sha256"] = None
            completion["error"] = {"type": type(exc).__name__, "message": str(exc)}
            _atomic_json(worker / "completion.json", completion, immutable=True)
            failure.completion = completion
            if failure is exc:
                raise
            raise failure from exc
        result_hash = _atomic_json(worker / "result.json", result, immutable=True)
        completion_hash = _atomic_json(worker / "completion.json", completion, immutable=True)
        return {"result": result, "completion": completion,
                "result_ref": {"path": (worker / "result.json").relative_to(project).as_posix(), "sha256": result_hash},
                "completion_ref": {"path": (worker / "completion.json").relative_to(project).as_posix(), "sha256": completion_hash}}

    def __call__(self, *, paper: dict, question: str) -> list[dict]:
        if not isinstance(paper, dict):
            raise CurieContractError("PaperQA2 subprocess paper must be an object")
        document_value = str(paper.get("document_path") or "").strip()
        if document_value:
            document_path = Path(document_value).resolve()
            document_sha256 = _sha256_file(document_path)
            media_type = _text(paper.get("media_type"), "PaperQA2 paper media_type")
            pdf_path = None
            pdf_sha256 = ""
        else:
            pdf_path = Path(
                _text(paper.get("pdf_path"), "PaperQA2 paper pdf_path")
            ).resolve()
            pdf_sha256 = _sha256_file(pdf_path)
            document_path = None
            document_sha256 = ""
            media_type = "application/pdf"
        request = {
            "paper_id": _text(paper.get("paper_id"), "PaperQA2 paper_id"),
            "title": _text(paper.get("title"), "PaperQA2 paper title"),
            "doi": str((paper.get("identifiers") or {}).get("doi") or "").strip(),
            "question": _text(question, "PaperQA2 question"),
            "pqa_home": str(self.pqa_home),
            "paperqa_repo": str(self.paperqa_repo),
            "k": 5,
        }
        if document_path is not None:
            request.update({
                "document_path": str(document_path),
                "media_type": media_type,
            })
        else:
            request["pdf_path"] = str(pdf_path)
        environment = os.environ.copy()
        environment["PQA_HOME"] = str(self.pqa_home)
        try:
            completed = self.runner.run(
                [str(self.python_executable), str(self.bridge_script)],
                cwd=str(self.paperqa_repo),
                env=environment,
                input_text=json.dumps(request, ensure_ascii=False),
                timeout=self.timeout_seconds,
                encoding="utf-8",
                errors="strict",
            )
        except OSError as exc:
            raise PaperQA2ExecutionError(
                f"PaperQA2 subprocess could not start: {exc}"
            ) from exc
        if completed.terminal_state == "timed_out":
            raise PaperQA2ExecutionError("PaperQA2 subprocess timed out")
        if completed.returncode != 0:
            raise PaperQA2ExecutionError(
                f"PaperQA2 subprocess failed with exit code {completed.returncode}"
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PaperQA2ExecutionError("PaperQA2 bridge did not return JSON") from exc
        if not isinstance(payload, dict) or payload.get("engine") != "paperqa2":
            raise CurieContractError("PaperQA2 bridge engine identity is invalid")
        if document_path is not None:
            runtime = validate_pinned_paperqa2_runtime(
                payload.get("runtime"),
                document_sha256=document_sha256,
                media_type=media_type,
            )
            runtime.update({
                "python_executable": str(self.python_executable),
                "paperqa_repo": str(self.paperqa_repo),
                "pqa_home": str(self.pqa_home),
                "document_path": str(document_path),
            })
        else:
            runtime = validate_pinned_paperqa2_runtime(
                payload.get("runtime"),
                pdf_sha256=pdf_sha256,
            )
            runtime.update({
                "python_executable": str(self.python_executable),
                "paperqa_repo": str(self.paperqa_repo),
                "pqa_home": str(self.pqa_home),
                "pdf_path": str(pdf_path),
            })
        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise CurieContractError("PaperQA2 bridge hits must be a list")
        results = []
        for hit in hits:
            if not isinstance(hit, dict):
                raise CurieContractError("PaperQA2 bridge hit must be an object")
            text = _text(hit.get("text"), "PaperQA2 bridge hit text")
            locator = _text(hit.get("locator"), "PaperQA2 bridge hit locator")
            section = _text(hit.get("section"), "PaperQA2 bridge hit section")
            score = hit.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise CurieContractError("PaperQA2 bridge hit score must be numeric")
            results.append({
                "text": text,
                "locator": locator,
                "section": section,
                "score": float(score),
                "runtime": runtime,
                "paperqa2": {
                    "chunk_locator": locator,
                    "chunk_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "context_score": hit.get("context_score"),
                },
            })
        return results


class PaperQA2CurieRuntime:
    """Run retrieval, retain UNVERIFIED candidates, then call a verifier."""

    def __init__(self, *, backend, backend_id: str) -> None:
        if not callable(backend):
            raise CurieContractError("PaperQA2 Curie backend must be callable")
        self.backend = backend
        self.backend_id = _text(backend_id, "PaperQA2 Curie backend_id")

    def retrieve_and_verify(
        self,
        *,
        paper: dict,
        question: str,
        source_candidates: list[dict],
        verify,
    ) -> dict:
        if not callable(verify):
            raise CurieContractError("PaperQA2 Curie source verifier must be callable")
        chunks = self.backend(paper=paper, question=question)
        if not isinstance(chunks, list):
            raise CurieContractError("PaperQA2 Curie backend must return a list")
        aligned = align_paperqa2_chunks(
            chunks=chunks,
            source_candidates=source_candidates,
        )
        unverified = PaperQA2Retriever(
            backend=lambda **_kwargs: aligned,
            backend_id=self.backend_id,
        ).retrieve(paper=paper, question=question)
        located = verify(unverified)
        if not isinstance(located, list):
            raise CurieContractError("PaperQA2 Curie source verifier must return a list")
        return {
            "chunks": copy.deepcopy(chunks),
            "unverified": unverified,
            "located": copy.deepcopy(located),
        }


def corpus_backend_from_config(config: dict) -> PaperQA2SubprocessBackend:
    """Adapt the explicit corpus capability to the existing subprocess owner."""
    bound = validate_corpus_worker_config(config)
    return PaperQA2SubprocessBackend(**{key: bound[key] for key in (
        "python_executable", "bridge_script", "paperqa_repo", "pqa_home", "timeout_seconds")})


def runtime_from_config(config: object) -> PaperQA2CurieRuntime:
    """Build the one pinned PaperQA2 runtime from an explicit bound config."""

    if not isinstance(config, dict) or not config:
        raise CurieContractError("PaperQA2 runtime is not configured")
    required = ("python_executable", "bridge_script", "paperqa_repo", "pqa_home")
    missing = [
        field for field in required if not str(config.get(field) or "").strip()
    ]
    if missing:
        raise CurieContractError(
            "PaperQA2 runtime config is incomplete: " + ", ".join(missing)
        )
    backend = PaperQA2SubprocessBackend(
        python_executable=config["python_executable"],
        bridge_script=config["bridge_script"],
        paperqa_repo=config["paperqa_repo"],
        pqa_home=config["pqa_home"],
        timeout_seconds=int(config.get("timeout_seconds") or 300),
    )
    return PaperQA2CurieRuntime(backend=backend, backend_id=backend.backend_id)


def align_paperqa2_chunks(*, chunks: list[dict], source_candidates: list[dict]) -> list[dict]:
    """Map retrieved chunks to exact source paragraphs without certifying them.

    Every independently sourced paragraph that clears the lexical coverage
    threshold may be proposed, but each source locator retains only its
    strongest PaperQA2 alignment across all chunks. Equal-coverage ties are
    resolved deterministically by chunk index and then source-candidate index.
    """
    if not isinstance(chunks, list) or not isinstance(source_candidates, list):
        raise CurieContractError("PaperQA2 source alignment requires candidate lists")
    if not source_candidates:
        raise CurieContractError("PaperQA2 source alignment has no independent source candidates")

    best_by_locator: dict[str, tuple[float, int, int, dict, str]] = {}
    for chunk_index, chunk in enumerate(chunks):
        chunk_text = _text(chunk.get("text"), "PaperQA2 chunk text")
        chunk_tokens = set(_tokens(chunk_text))
        if not chunk_tokens:
            continue
        for source_index, source in enumerate(source_candidates):
            source_text = _text(source.get("text"), "source candidate text")
            locator = _text(source.get("locator"), "source candidate locator")
            source_tokens = set(_tokens(source_text))
            if not source_tokens:
                continue
            coverage = len(chunk_tokens & source_tokens) / len(source_tokens)
            if coverage < MIN_SOURCE_TOKEN_COVERAGE:
                continue
            candidate = (coverage, chunk_index, source_index, source, chunk_text)
            existing = best_by_locator.get(locator)
            if existing is None or (
                coverage > existing[0]
                or (
                    coverage == existing[0]
                    and (chunk_index, source_index) < (existing[1], existing[2])
                )
            ):
                best_by_locator[locator] = candidate

    if not best_by_locator:
        raise PaperQA2SourceError(
            "PaperQA2 retrieved chunks could not align to source candidates"
        )

    aligned: list[dict] = []
    winners = sorted(
        best_by_locator.items(),
        key=lambda item: (item[1][1], item[1][2], item[0]),
    )
    for locator, (coverage, chunk_index, source_index, source, chunk_text) in winners:
        chunk = chunks[chunk_index]
        aligned_item = {
            "text": _text(source.get("text"), "source candidate text"),
            "locator": locator,
            "section": _text(source.get("section"), "source candidate section"),
            "score": float(chunk.get("score", 0.0)),
            "paperqa2": copy.deepcopy(chunk.get("paperqa2", {
                "chunk_locator": _text(chunk.get("locator"), "PaperQA2 chunk locator"),
                "chunk_sha256": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
            })),
            "source_alignment": {
                "method": SOURCE_ALIGNMENT_METHOD,
                "chunk_index": chunk_index,
                "source_candidate_index": source_index,
                "source_token_coverage": coverage,
            },
        }
        if chunk.get("runtime") is not None:
            aligned_item["runtime"] = copy.deepcopy(chunk["runtime"])
        aligned.append(aligned_item)
    return aligned
