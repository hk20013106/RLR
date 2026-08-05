"""Compatibility shims for provider observability integration boundaries."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def install(deep_research_module, detached_task_module, l4_pipeline_module) -> None:
    if getattr(deep_research_module, "_provider_observability_compat_installed", False):
        return

    # L4A has its own provider subprocess boundary. Share the same proxy object
    # so Codex JSONL streaming and existing monkeypatch-based tests both reach it.
    l4_pipeline_module.subprocess = deep_research_module.subprocess

    previous_status = detached_task_module._status
    previous_validate = detached_task_module._validate_status
    detailed_terminal = {
        "succeeded", "provider_failed", "validation_failed", "job_timed_out",
        "inactivity_timed_out", "cancelled", "provider_dead", "transport_lost",
    }

    def status(task_id: str, state: str, *, error: str = "", run_id: str = "") -> dict:
        task_dir_value = os.environ.get("RLR_DEEP_RESEARCH_TASK_DIR")
        before = _read(Path(task_dir_value) / "status.json") if task_dir_value else {}
        value = previous_status(task_id, state, error=error, run_id=run_id)
        if state == "failed":
            if before.get("state") in detailed_terminal:
                value["state"] = before["state"]
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
