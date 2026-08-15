"""Thin RLR-side adapter that wakes Meta-RLR after an observed runtime failure."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rlr_maintenance.autowake import (
    AUTOWAKE_RETRY_GUARD_ENV,
    RepairHandoff,
    maybe_wake_meta_rlr,
)


def _resume_verified_worker(
    *,
    project_dir: str | Path,
    task_id: str,
    request: dict,
    handoff: RepairHandoff,
    runner=subprocess.run,
) -> int | None:
    """Run the same immutable detached request from the verified code worktree."""
    cli = handoff.worktree_path / "research_loop_v04.py"
    if not cli.is_file():
        return None
    working_directory = request.get("working_directory")
    cwd = Path(str(working_directory)) if working_directory else None
    if cwd is not None and not cwd.is_dir():
        return None
    environment = dict(os.environ)
    environment[AUTOWAKE_RETRY_GUARD_ENV] = "1"
    completed = runner(
        [
            sys.executable,
            str(cli),
            "_deep-research-worker",
            str(Path(project_dir).resolve()),
            task_id,
        ],
        cwd=cwd,
        env=environment,
        shell=False,
    )
    return int(getattr(completed, "returncode", 3))


def install(detached_task_module) -> None:
    """Install exactly one post-failure reconcile hook on the detached worker."""
    if getattr(detached_task_module, "_maintenance_autowake_installed", False):
        return
    original_run_worker = detached_task_module.run_worker

    def run_worker(project_dir, task_id, synchronous_handler):
        returncode = original_run_worker(project_dir, task_id, synchronous_handler)
        if returncode == 0 or os.environ.get(AUTOWAKE_RETRY_GUARD_ENV):
            return returncode
        try:
            task_dir = detached_task_module._task_dir(project_dir, task_id)
            request = detached_task_module._read_json(
                task_dir / "request.json", f"task {task_id} request"
            )
            handler_args = detached_task_module._validate_request(
                request, project_dir, task_id
            )
            status = detached_task_module._read_json(
                task_dir / "status.json", f"task {task_id} status"
            )
            handoff = maybe_wake_meta_rlr(
                project_dir=project_dir,
                task_id=task_id,
                handler_args=handler_args,
                returncode=returncode,
                status=status,
            )
            if handoff is None:
                return returncode
            resumed = _resume_verified_worker(
                project_dir=project_dir,
                task_id=task_id,
                request=request,
                handoff=handoff,
            )
            return returncode if resumed is None else resumed
        except Exception:
            # Maintenance is fail-safe: never hide or transform the original RLR
            # failure when the optional repair bridge itself is unavailable.
            return returncode

    detached_task_module.run_worker = run_worker
    detached_task_module._maintenance_autowake_installed = True
