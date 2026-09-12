"""Generic schema-constrained model invocation for native RLR stages.

It has no literature, skill, retrieval, identity, verification, or evidence
pack authority; Curie and L4 retain those responsibilities.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


SUPPORTED_BACKENDS = ("codex", "claude")


class StructuredExecutionError(ValueError):
    pass


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
