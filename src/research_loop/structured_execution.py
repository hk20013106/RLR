"""Generic schema-constrained model invocation for native RLR stages.

It has no literature, skill, retrieval, identity, verification, or evidence
pack authority; Curie and L4 retain those responsibilities.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from research_loop.external_resilience import run_provider_with_retry
from research_loop.providers.executor import DEFAULT_EXECUTOR, ProviderExecutionError


SUPPORTED_BACKENDS = ("codex", "claude")
SCHEMA_VERSION = "StructuredModelExecutionReceipt/v1"


class StructuredExecutionError(ValueError):
    def __init__(self, message: str, *, category: str = "MODEL_CONTRACT_ERROR", receipt: dict | None = None):
        super().__init__(message)
        self.category = category
        self.receipt = receipt


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def build_invocation(spec: Any, schema_path: str | Path) -> list[str]:
    backend = str(getattr(spec, "backend", "") or "").strip()
    executable = str(getattr(spec, "executable", "") or "").strip()
    if backend not in SUPPORTED_BACKENDS:
        raise StructuredExecutionError(f"unsupported backend: {backend!r}")
    if not executable:
        raise StructuredExecutionError("executable is required")
    schema = str(Path(schema_path))
    if backend == "codex":
        command = [executable, "exec", "--ephemeral", "--cd", str(Path(schema).parent),
                   "--sandbox", "read-only", "-c", "mcp_servers={}",
                   "--output-schema", schema]
    else:
        command = [executable, "-p", "--tools", "", "--no-session-persistence",
                   "--json-schema", schema, "--output-format", "json"]
    model = str(getattr(spec, "model", "") or "").strip()
    if model:
        command.extend(["--model", model])
    return command


def runtime_ready(spec: Any) -> tuple[bool, str]:
    backend = str(getattr(spec, "backend", "") or "").strip()
    executable = str(getattr(spec, "executable", "") or "").strip()
    if backend not in SUPPORTED_BACKENDS:
        return False, f"unsupported backend: {backend!r}"
    if not executable:
        return False, "provider executable is missing"
    if shutil.which(executable) is None:
        return False, f"provider executable not found: {executable}"
    return True, ""


def execution_receipt(
    backend: str,
    command: list[str],
    prompt: str,
    *,
    exit_code: int = 0,
    stdout_hash: str = "",
    model: str | None = None,
    purpose: str = "structured_model",
) -> dict:
    """Create a provider receipt without claiming a skill produced it."""
    return {
        "schema_version": SCHEMA_VERSION,
        "backend": str(backend),
        "provider": str(backend),
        "model": model or "default",
        "execution_kind": str(purpose),
        "command_hash": _sha(json.dumps(command, ensure_ascii=False)),
        "prompt_hash": _sha(prompt),
        "executed_at": _dt.datetime.now(_dt.timezone.utc).replace(
            microsecond=0
        ).isoformat(),
        "exit_code": int(exit_code),
        "stdout_hash": str(stdout_hash or ""),
    }


def run_structured_model(
    spec: Any, *, prompt: str, schema: dict, work_dir: str | Path,
    purpose: str = "structured_model",
) -> dict:
    """Use the existing runtime spec and provider executor for one isolated JSON result."""
    from research_loop import deep_research as runtime

    if not isinstance(prompt, str) or not prompt.strip():
        raise StructuredExecutionError("structured model prompt is empty")
    if not isinstance(schema, dict):
        raise StructuredExecutionError("structured model schema must be an object")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise StructuredExecutionError(f"structured model schema is invalid: {exc}") from exc
    work = Path(work_dir)
    schema_bytes = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    schema_path = work / "structured_model_output.schema.json"
    prompt_path = work / "structured_model_prompt.txt"
    try:
        work.mkdir(parents=True, exist_ok=True)
        schema_path.write_bytes(schema_bytes)
        prompt_path.write_bytes(prompt.encode("utf-8"))
    except OSError as exc:
        receipt = {
            "schema_version": SCHEMA_VERSION, "prompt_hash": _sha(prompt),
            "schema_sha256": _sha(schema_bytes), "work_dir": str(work),
            "validation_status": "PERSISTENCE_ERROR", "error_category": "PERSISTENCE_ERROR",
        }
        raise StructuredExecutionError(
            f"structured model inputs could not be persisted: {exc}",
            category="PERSISTENCE_ERROR", receipt=receipt,
        ) from exc
    command = build_invocation(spec, schema_path)
    try:
        command[0] = runtime.resolve_subprocess_executable(command[0])
        invocation, kwargs = runtime.subprocess_invocation(command, prompt)
        completed = run_provider_with_retry(
            lambda: DEFAULT_EXECUTOR.run(
                invocation, timeout=getattr(spec, "timeout", None),
                input_text=kwargs.get("input"), cwd=work, check=False,
                encoding="utf-8", errors="strict",
            )
        )
    except (OSError, runtime.DeepResearchError, ProviderExecutionError) as exc:
        receipt = execution_receipt(
            str(getattr(spec, "backend", "")), command, prompt,
            exit_code=1, model=getattr(spec, "model", None), purpose=purpose,
        )
        receipt.update(schema_sha256=_sha(schema_bytes), schema_path=str(schema_path),
                       prompt_path=str(prompt_path),
                       validation_status="EXECUTION_ERROR",
                       error_category="MODEL_EXECUTION_ERROR")
        raise StructuredExecutionError(
            f"structured model execution failed: {exc}",
            category="MODEL_EXECUTION_ERROR", receipt=receipt,
        ) from exc
    raw = completed.stdout
    if not isinstance(raw, str):
        raise StructuredExecutionError("structured model output must be UTF-8 text",
                                       category="MODEL_CONTRACT_ERROR")
    output_path = work / "structured_model_stdout.txt"
    receipt = execution_receipt(
        str(getattr(spec, "backend", "")), command, prompt,
        exit_code=completed.returncode, stdout_hash=_sha(raw),
        model=getattr(spec, "model", None), purpose=purpose,
    )
    receipt.update(schema_sha256=_sha(schema_bytes), schema_path=str(schema_path),
                   prompt_path=str(prompt_path),
                   output_path=str(output_path),
                   validation_status="PENDING")
    try:
        output_path.write_bytes(raw.encode("utf-8"))
    except OSError as exc:
        receipt.update(validation_status="PERSISTENCE_ERROR", error_category="PERSISTENCE_ERROR")
        raise StructuredExecutionError(
            f"structured model output could not be persisted: {exc}",
            category="PERSISTENCE_ERROR", receipt=receipt,
        ) from exc
    if getattr(completed, "stdout_truncated", False):
        receipt.update(validation_status="SCHEMA_ERROR", error_category="MODEL_CONTRACT_ERROR")
        raise StructuredExecutionError("structured model output was truncated",
                                       category="MODEL_CONTRACT_ERROR", receipt=receipt)
    if completed.returncode != 0:
        receipt.update(validation_status="EXECUTION_ERROR", error_category="MODEL_EXECUTION_ERROR")
        raise StructuredExecutionError(
            "structured model command returned nonzero exit", category="MODEL_EXECUTION_ERROR",
            receipt=receipt,
        )
    try:
        payload = runtime._parse_cli_output(raw)
        errors = sorted(Draft202012Validator(schema).iter_errors(payload),
                        key=lambda error: (list(error.absolute_path), error.message))
        if errors:
            location = ".".join(str(part) for part in errors[0].absolute_path) or "payload"
            raise StructuredExecutionError(f"structured model schema {location}: {errors[0].message}")
    except (runtime.DeepResearchError, StructuredExecutionError) as exc:
        receipt.update(validation_status="SCHEMA_ERROR", error_category="MODEL_CONTRACT_ERROR")
        raise StructuredExecutionError(
            f"structured model schema validation failed: {exc}",
            category="MODEL_CONTRACT_ERROR", receipt=receipt,
        ) from exc
    receipt["validation_status"] = "PASS"
    return {"payload": payload, "receipt": receipt, "raw_output": raw}
