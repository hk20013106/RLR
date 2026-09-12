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


SUPPORTED_BACKENDS = ("codex", "claude")
SCHEMA_VERSION = "StructuredModelExecutionReceipt/v1"


class StructuredExecutionError(ValueError):
    pass


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
        command = [executable, "exec", "--ephemeral", "-c", "mcp_servers={}", "--output-schema", schema]
    else:
        command = [executable, "-p", "--json-schema", schema, "--output-format", "json"]
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
