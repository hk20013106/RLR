"""Compatibility shims for provider observability integration boundaries."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from research_loop import provider_runtime_observability as _runtime


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_legacy_python_provider(args) -> bool:
    """Identify old test/provider shims that do not implement Codex JSONL."""
    if not args or len(args) < 2:
        return False
    executable = Path(str(args[0])).name.lower()
    return executable in {
        "python", "python.exe", "python3", "python3.exe",
    } and str(args[1]) == "exec"


def install(deep_research_module, detached_task_module, l4_pipeline_module) -> None:
    if getattr(deep_research_module, "_provider_observability_compat_installed", False):
        return

    proxy = deep_research_module.subprocess
    previous_proxy_run = proxy.run

    def provider_scoped_run(args, *positional, **kwargs):
        context = _runtime._CONTEXT.get()
        if context is not None and (
            context.get("backend") != "codex" or _is_legacy_python_provider(args)
        ):
            # Only the native Codex CLI JSONL/output-last-message contract is
            # observed. Claude and legacy Python shims retain their established
            # single-JSON stdout behavior instead of being misclassified as a
            # Codex event stream.
            return proxy._original.run(args, *positional, **kwargs)
        return previous_proxy_run(args, *positional, **kwargs)

    proxy.run = provider_scoped_run

    # Several installed scientific wrappers own a copied stdlib subprocess
    # module and reimplement the final provider boundary. Bind every loaded
    # provider owner to the same proxy; otherwise the active L1/L4 wrapper can
    # bypass observation even though deep_research itself is patched.
    provider_owner_modules = (
        "research_loop.method_evidence",
        "research_loop.method_review_navigation",
    )
    for module_name in provider_owner_modules:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "subprocess"):
            module.subprocess = proxy

    # L4A has its own provider subprocess boundary. Share the same proxy object
    # so Codex JSONL streaming and existing monkeypatch-based tests both reach it.
    l4_pipeline_module.subprocess = proxy

    previous_status = detached_task_module._status
    previous_validate = detached_task_module._validate_status
    detailed_failure_terminal = {
        "provider_failed", "validation_failed", "job_timed_out",
        "inactivity_timed_out", "cancelled", "provider_dead", "transport_lost",
    }

    def status(task_id: str, state: str, *, error: str = "", run_id: str = "") -> dict:
        task_dir_value = os.environ.get("RLR_DEEP_RESEARCH_TASK_DIR")
        before = _read(Path(task_dir_value) / "status.json") if task_dir_value else {}
        value = previous_status(task_id, state, error=error, run_id=run_id)
        if state == "failed":
            before_state = before.get("state")
            if before_state == "succeeded":
                # Provider execution/persistence succeeded, but the enclosing
                # synchronous command failed its evidence/audit gate afterwards.
                value["state"] = "validation_failed"
                value["legacy_state"] = "failed"
            elif before_state in detailed_failure_terminal:
                value["state"] = before_state
                value["legacy_state"] = "failed"
            else:
                # Preserve the v1 public contract for worker-launch, malformed
                # request, and malformed result failures. The more specific
                # classification is additive rather than a breaking rename.
                value["state"] = "failed"
                value["diagnostic_state"] = "provider_failed"
        return value

    def validate_status(value: dict, task_id: str) -> None:
        if (
            value.get("schema_version") == "DeepResearchDetachedTask/v2"
            and value.get("task_id") == task_id
            and value.get("state") == "failed"
        ):
            return
        return previous_validate(value, task_id)

    detached_task_module._status = status
    detached_task_module._validate_status = validate_status
    deep_research_module._provider_observability_compat_installed = True
