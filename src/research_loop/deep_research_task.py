"""Minimal detached wrapper around the existing synchronous research command."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


TASK_SCHEMA_VERSION = "DeepResearchDetachedTask/v1"
_HANDLER_ARGUMENTS = (
    "project_dir", "cand_id", "node", "backend", "allow_host_mismatch",
    "executable", "plugin_dir", "skill_path", "skill_version", "model",
    "timeout",
)


class DetachedTaskError(RuntimeError):
    """Raised when a detached research task cannot be started or collected."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _task_root(project_dir: str | Path) -> Path:
    return (Path(project_dir).resolve() / "08_Audit" / "deep_research_runtime" /
            "tasks")


def _task_dir(project_dir: str | Path, task_id: str) -> Path:
    if not task_id or Path(task_id).name != task_id or task_id in {".", ".."}:
        raise DetachedTaskError(f"invalid detached Deep Research task ID: {task_id!r}")
    return _task_root(project_dir) / task_id


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DetachedTaskError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise DetachedTaskError(f"invalid {label}: expected a JSON object")
    return value


def _validate_request(request: dict, project_dir: str | Path, task_id: str) -> dict:
    handler_args = request.get("handler_args")
    if (request.get("schema_version") != TASK_SCHEMA_VERSION or
            request.get("task_id") != task_id or
            not isinstance(handler_args, dict)):
        raise DetachedTaskError(f"task {task_id} request identity is invalid")
    requested_project = handler_args.get("project_dir")
    if (not requested_project or
            Path(requested_project).resolve() != Path(project_dir).resolve()):
        raise DetachedTaskError(f"task {task_id} request project does not match")
    candidate_id = handler_args.get("cand_id")
    if (not isinstance(candidate_id, str) or not candidate_id or
            "/" in candidate_id or "\\" in candidate_id or
            candidate_id in {".", ".."} or not handler_args.get("node")):
        raise DetachedTaskError(f"task {task_id} request target is incomplete")
    return handler_args


def _validate_status(status: dict, task_id: str) -> None:
    if (status.get("schema_version") != TASK_SCHEMA_VERSION or
            status.get("task_id") != task_id or
            status.get("state") not in {"running", "succeeded", "failed"}):
        raise DetachedTaskError(f"task {task_id} status identity is invalid")


def _status(task_id: str, state: str, *, error: str = "", run_id: str = "") -> dict:
    value = {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "state": state,
        "updated_at": _now(),
    }
    if run_id:
        value["run_id"] = run_id
    if error:
        value["error"] = error
    return value


def _public_cli_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "research_loop_v04.py"
    if not path.is_file():
        raise DetachedTaskError(f"public Research Loop entry point not found: {path}")
    return path


def start_task(args: argparse.Namespace) -> dict:
    """Start the existing synchronous handler in a detached CLI worker."""
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.is_dir():
        raise DetachedTaskError(f"project directory not found: {project_dir}")
    task_id = f"dr-{uuid.uuid4().hex}"
    task_dir = _task_dir(project_dir, task_id)
    task_dir.mkdir(parents=True, exist_ok=False)
    request = {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "created_at": _now(),
        "working_directory": str(Path.cwd().resolve()),
        "handler_args": {
            name: getattr(args, name, None) for name in _HANDLER_ARGUMENTS
        },
    }
    request["handler_args"]["project_dir"] = str(project_dir)
    _write_json(task_dir / "request.json", request)
    _write_json(task_dir / "status.json", _status(task_id, "running"))

    stdout_log = None
    stderr_log = None
    try:
        command = [
            sys.executable,
            str(_public_cli_path().resolve()),
            "_deep-research-worker",
            str(project_dir),
            task_id,
        ]
        stdout_log = (task_dir / "stdout.log").open("w", encoding="utf-8")
        stderr_log = (task_dir / "worker_stderr.log").open("w", encoding="utf-8")
        popen_kwargs = {
            "cwd": request["working_directory"],
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_log,
            "stderr": stderr_log,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen(command, **popen_kwargs)
    except (OSError, DetachedTaskError) as exc:
        _write_json(
            task_dir / "status.json",
            _status(task_id, "failed", error=f"worker launch failed: {exc}"),
        )
        raise DetachedTaskError(f"worker launch failed: {exc}") from exc
    finally:
        if stdout_log is not None:
            stdout_log.close()
        if stderr_log is not None:
            stderr_log.close()
    return get_status(project_dir, task_id)


def get_status(project_dir: str | Path, task_id: str) -> dict:
    task_dir = _task_dir(project_dir, task_id)
    status = _read_json(task_dir / "status.json", f"task {task_id} status")
    _validate_status(status, task_id)
    return status


def run_worker(
        project_dir: str | Path,
        task_id: str,
        synchronous_handler: Callable[[argparse.Namespace], int]) -> int:
    """Run the existing handler unchanged and record its complete CLI output."""
    task_dir = _task_dir(project_dir, task_id)
    stdout_path = task_dir / "stdout.log"
    stderr_path = task_dir / "worker_stderr.log"
    returncode = 3
    try:
        request = _read_json(task_dir / "request.json", f"task {task_id} request")
        handler_args = _validate_request(request, project_dir, task_id)
        with stdout_path.open("a", encoding="utf-8") as stdout, \
                stderr_path.open("a", encoding="utf-8") as stderr:
            old_stdout, old_stderr = sys.stdout, sys.stderr
            try:
                sys.stdout, sys.stderr = stdout, stderr
                returncode = synchronous_handler(argparse.Namespace(**handler_args))
            except Exception:
                traceback.print_exc(file=stderr)
                returncode = 3
            finally:
                stdout.flush()
                stderr.flush()
                sys.stdout, sys.stderr = old_stdout, old_stderr

        if returncode != 0:
            error = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            _write_json(
                task_dir / "status.json",
                _status(task_id, "failed", error=error or f"command exited {returncode}"),
            )
            return returncode

        result = _read_json(stdout_path, f"task {task_id} stdout")
        run_id = result.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise DetachedTaskError("successful Deep Research output has no run_id")
        _write_json(task_dir / "result.json", result)
        _write_json(
            task_dir / "status.json",
            _status(task_id, "succeeded", run_id=run_id),
        )
        return 0
    except Exception as exc:
        with stderr_path.open("a", encoding="utf-8") as stderr:
            stderr.write(f"Detached worker failed: {exc}\n")
        _write_json(
            task_dir / "status.json",
            _status(task_id, "failed", error=str(exc)),
        )
        return 3


def collect_task(project_dir: str | Path, task_id: str, audit: Callable) -> dict:
    """Return a completed result after repeating the existing exact-run audit."""
    task_dir = _task_dir(project_dir, task_id)
    status = get_status(project_dir, task_id)
    if status.get("state") != "succeeded":
        raise DetachedTaskError(
            f"task {task_id} is {status.get('state', 'unknown')}; only succeeded tasks can be collected"
        )
    request = _read_json(task_dir / "request.json", f"task {task_id} request")
    result = _read_json(task_dir / "result.json", f"task {task_id} result")
    handler_args = _validate_request(request, project_dir, task_id)
    run_id = result.get("run_id")
    if (not isinstance(run_id, str) or not run_id or
            Path(run_id).name != run_id or "/" in run_id or "\\" in run_id or
            status.get("run_id") != run_id or
            result.get("candidate_id") != handler_args.get("cand_id") or
            result.get("node") != handler_args.get("node")):
        raise DetachedTaskError(f"task {task_id} result identity is invalid")
    expected_relative_path = (
        Path("09_Literature_Database") / "evidence_packs" / "runs" /
        f"{run_id}.json"
    )
    relative_path = Path(str(result.get("path") or ""))
    if relative_path.as_posix() != expected_relative_path.as_posix():
        raise DetachedTaskError(f"task {task_id} result path is invalid")
    project_root = Path(project_dir).resolve()
    artifact_path = project_root / expected_relative_path
    persisted_result = _read_json(artifact_path, f"task {task_id} persisted evidence run")
    if persisted_result != result:
        raise DetachedTaskError(
            f"task {task_id} result differs from the persisted evidence run"
        )
    ok, reason = audit(
        project_dir,
        handler_args.get("cand_id"),
        handler_args.get("node"),
        run_id=run_id,
    )
    if not ok:
        raise DetachedTaskError(f"Deep Research evidence gate failed: {reason}")
    return result
