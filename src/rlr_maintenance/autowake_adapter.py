"""Outer runtime adapters that wake Meta-RLR after classified RLR failures.

The scientific ``research_loop`` package must never depend on this module.
Repository-root entry points install these adapters after RLR has initialized
its own validators/observability.
"""
from __future__ import annotations

import os
import subprocess
import sys
from functools import wraps
from pathlib import Path
from typing import Callable, Sequence

from .autowake import (
    AUTOWAKE_CONFIG_ENV,
    AUTOWAKE_RETRY_GUARD_ENV,
    RepairHandoff,
    maybe_wake_first_mile_failure,
    maybe_wake_meta_rlr,
)


def _resume_verified_worker(
    *,
    project_dir: str | Path,
    task_id: str,
    request: dict,
    handoff: RepairHandoff,
    runner=subprocess.Popen,
) -> int | None:
    """Launch the same immutable detached request from verified code.

    This boundary owns only launch/handshake. It must not wait for the entire
    resumed scientific task; the fresh worker continues under RLR's normal
    detached provider/runtime supervision.
    """
    cli = handoff.worktree_path / "research_loop_v04.py"
    if not cli.is_file():
        return None
    working_directory = request.get("working_directory")
    cwd = Path(str(working_directory)) if working_directory else None
    if cwd is not None and not cwd.is_dir():
        return None
    environment = dict(os.environ)
    environment.pop(AUTOWAKE_RETRY_GUARD_ENV, None)
    popen_kwargs = {
        "cwd": cwd,
        "env": environment,
        "shell": False,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_kwargs["start_new_session"] = True
    completed = runner(
        [
            sys.executable,
            str(cli),
            "_deep-research-worker",
            str(Path(project_dir).resolve()),
            task_id,
        ],
        **popen_kwargs,
    )
    if hasattr(completed, "pid"):
        return 0 if completed.pid else None
    return int(getattr(completed, "returncode", 3))


def _resume_verified_cli(
    *,
    handoff: RepairHandoff,
    entrypoint_name: str,
    argv: Sequence[str],
    runner=subprocess.run,
) -> int | None:
    """Replay one failed root CLI operation from independently verified code."""
    entrypoint = handoff.worktree_path / entrypoint_name
    if not entrypoint.is_file():
        return None
    environment = dict(os.environ)
    environment.pop(AUTOWAKE_RETRY_GUARD_ENV, None)
    completed = runner(
        [sys.executable, str(entrypoint), *[str(token) for token in argv]],
        env=environment,
        shell=False,
    )
    return int(getattr(completed, "returncode", 3))


def _first_mile_target(
    argv: Sequence[str], *, entrypoint_name: str
) -> tuple[str, Path] | None:
    tokens = [str(token) for token in argv]
    if len(tokens) < 2:
        return None
    command = tokens[0]
    if entrypoint_name == "research_loop_v04.py" and command == "preflight":
        return command, Path(tokens[1])
    if entrypoint_name == "run_loop.py" and command == "run":
        return command, Path(tokens[1])
    return None


def _first_mile_failure(
    *,
    project_dir: str | Path,
    operation: str,
) -> dict | None:
    """Ask the canonical PROJECT_READY validator; never infer readiness here."""
    from research_loop import l0_preflight

    result = l0_preflight.validate_project_ready(project_dir)
    if result.get("status") == "PASS":
        return None
    return {
        "code": str(result.get("code") or "PROJECT_NOT_READY"),
        "reason": str(result.get("reason") or f"{operation} readiness failed"),
    }


def wrap_first_mile_main(
    core_main: Callable[[list[str] | None], int],
    *,
    entrypoint_name: str,
) -> Callable[[list[str] | None], int]:
    """Wrap a repository-root CLI without changing the scientific core."""

    @wraps(core_main)
    def wrapped(argv: list[str] | None = None) -> int:
        effective_argv = list(sys.argv[1:] if argv is None else argv)
        result = int(core_main(argv))
        if (
            result == 0
            or os.environ.get(AUTOWAKE_RETRY_GUARD_ENV)
            or not os.environ.get(AUTOWAKE_CONFIG_ENV)
        ):
            return result
        target = _first_mile_target(effective_argv, entrypoint_name=entrypoint_name)
        if target is None:
            return result
        operation, project_dir = target
        try:
            failure = _first_mile_failure(
                project_dir=project_dir,
                operation=operation,
            )
            if failure is None:
                return result
            handoff = maybe_wake_first_mile_failure(
                project_dir=project_dir,
                operation=operation,
                failure=failure,
            )
            if handoff is None:
                return result
            replayed = _resume_verified_cli(
                handoff=handoff,
                entrypoint_name=entrypoint_name,
                argv=effective_argv,
            )
            return result if replayed is None else replayed
        except Exception:
            return result

    return wrapped


def install(detached_task_module) -> None:
    """Install exactly one post-failure reconcile hook on the detached worker."""
    if getattr(detached_task_module, "_maintenance_autowake_installed", False):
        return
    original_run_worker = detached_task_module.run_worker

    def run_worker(project_dir, task_id, synchronous_handler):
        returncode = original_run_worker(project_dir, task_id, synchronous_handler)
        if (
            returncode == 0
            or os.environ.get(AUTOWAKE_RETRY_GUARD_ENV)
            or not os.environ.get(AUTOWAKE_CONFIG_ENV)
        ):
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
            return returncode

    detached_task_module.run_worker = run_worker
    detached_task_module._maintenance_autowake_installed = True
