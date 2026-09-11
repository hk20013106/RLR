"""Generic schema-constrained model execution for native RLR stages.

This module is deliberately smaller than the historical literature runner. It
only builds and executes a structured provider command. It has no literature
search skill, source identity, paper selection, retrieval, or evidence-pack
authority. Those contracts remain owned by the canonical Curie modules.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "StructuredModelExecutionReceipt/v1"
SUPPORTED_BACKENDS = ("codex", "claude")


class StructuredExecutionError(ValueError):
    """Raised when a generic structured provider cannot be used."""


def _sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def build_invocation(spec: Any, schema_path: str | Path) -> list[str]:
    """Build one provider command for a schema-constrained model response.

    The command intentionally contains no plugin directory, skill path, slash
    command, or literature-specific alias. schema_path is the controller-owned
    wire contract; the prompt remains the caller's responsibility.
    """
    backend = str(getattr(spec, "backend", "") or "").strip()
    executable = str(getattr(spec, "executable", "") or "").strip()
    if backend not in SUPPORTED_BACKENDS:
        raise StructuredExecutionError(
            f"backend must be one of {', '.join(SUPPORTED_BACKENDS)}"
        )
    if not executable:
        raise StructuredExecutionError("executable is required")
    schema = str(Path(schema_path))
    if not schema:
        raise StructuredExecutionError("schema_path is required")

    if backend == "codex":
        command = [
            executable,
            "exec",
            "--ephemeral",
            "-c",
            "mcp_servers={}",
            "--output-schema",
            schema,
        ]
    else:
        command = [
            executable,
            "-p",
            "--json-schema",
            schema,
            "--output-format",
            "json",
        ]
    model = str(getattr(spec, "model", "") or "").strip()
    if model:
        command.extend(["--model", model])
    return command


def runtime_ready(spec: Any) -> tuple[bool, str]:
    """Check only the generic provider runtime, never an optional skill."""
    backend = str(getattr(spec, "backend", "") or "").strip()
    executable = str(getattr(spec, "executable", "") or "").strip()
    if backend not in SUPPORTED_BACKENDS:
        return False, f"backend must be one of {', '.join(SUPPORTED_BACKENDS)}"
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
    """Create a provider receipt without pretending a skill produced it."""
    return {
        "schema_version": SCHEMA_VERSION,
        "backend": str(backend),
        "provider": str(backend),
        "model": model or "default",
        "execution_kind": str(purpose),
        "command_hash": _sha(json.dumps(command, ensure_ascii=False)),
        "prompt_hash": _sha(prompt),
        "executed_at": _now(),
        "exit_code": int(exit_code),
        "stdout_hash": str(stdout_hash or ""),
    }


__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_BACKENDS",
    "StructuredExecutionError",
    "build_invocation",
    "runtime_ready",
    "execution_receipt",
]
