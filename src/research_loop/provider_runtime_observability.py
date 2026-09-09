"""Real-time provider supervision over the canonical ProviderExecutor boundary.

ProcessRunner owns process mechanics, hard timeouts, and process-tree cleanup.
This module is deliberately non-owning: it interprets provider JSONL, publishes
runtime status, applies semantic inactivity policy, and persists replayable
runtime receipts. Detached-task compatibility is installed here so there is no
second execution/proxy owner.
"""
from __future__ import annotations

import codecs
import contextvars
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from research_loop.process_runner import DEFAULT_PROCESS_RUNNER
from research_loop.providers.executor import (
    ProviderExecutionError,
    ProviderExecutionResult,
    ProviderExecutor,
)

try:  # Optional at import time; requirements install it in supported runtime.
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - fallback is exercised only in minimal installs
    psutil = None


STATUS_SCHEMA = "ProviderRuntimeStatus/v1"
RECEIPT_SCHEMA = "ProviderRuntimeReceipt/v1"
_TASK_SCHEMA_V1 = "DeepResearchDetachedTask/v1"
_TASK_SCHEMA_V2 = "DeepResearchDetachedTask/v2"
_CONTEXT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "rlr_provider_runtime_context", default=None
)
_TERMINAL_STATES = {
    "succeeded", "provider_failed", "validation_failed", "job_timed_out",
    "inactivity_timed_out", "cancelled", "provider_dead", "transport_lost",
}
_ALLOWED_STATES = _TERMINAL_STATES | {
    "starting", "running", "waiting_external", "validating", "persisting",
    "failed",
}


@dataclass(frozen=True)
class ProviderExecution:
    args: list[str]
    returncode: int
    final_output: str
    stderr: str
    final_status: str
    runtime_dir: Path
    runtime_receipt_path: Path
    runtime_receipt_sha256: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 4:
                raise
            time.sleep(0.01 * (attempt + 1))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_event(event: dict) -> dict:
    projected = {"type": str(event.get("type") or "unknown")}
    if event.get("thread_id"):
        projected["thread_id"] = str(event["thread_id"])
    item = event.get("item")
    if isinstance(item, dict):
        projected["item_id"] = str(item.get("id") or "")
        projected["item_type"] = str(item.get("type") or "")
        projected["item_status"] = str(item.get("status") or "")
    if projected["type"] in {"error", "turn.failed"}:
        message = event.get("message")
        if not message and isinstance(event.get("error"), dict):
            message = event["error"].get("message")
        if message:
            projected["message"] = str(message)[:1000]
    return projected


def _safe_item(item: dict) -> dict:
    value = {
        "id": str(item.get("id") or ""),
        "type": str(item.get("type") or "unknown"),
        "status": str(item.get("status") or "in_progress"),
    }
    item_type = value["type"]
    if item_type == "mcp_tool_call":
        value["server"] = str(item.get("server") or "")
        value["tool"] = str(item.get("tool") or "")
    elif item_type == "command_execution":
        value["command"] = str(item.get("command") or "")[:4000]
    elif item_type == "web_search":
        value["query"] = str(item.get("query") or "")[:2000]
    # Deliberately omit reasoning/agent-message text from mutable status.
    return value


def _state_for_item(item: dict) -> str:
    if str(item.get("type") or "") in {"mcp_tool_call", "web_search"}:
        return "waiting_external"
    return "running"


def _file_record(path: Path) -> dict:
    if not path.is_file():
        return {"path": path.name, "sha256": "", "bytes": 0}
    content = path.read_bytes()
    return {"path": path.name, "sha256": _sha_bytes(content), "bytes": len(content)}


def _process_snapshot(pid: int) -> dict:
    if psutil is None:
        try:
            os.kill(pid, 0)
            alive = True
        except OSError:
            alive = False
        return {
            "alive": alive,
            "cpu_seconds": None,
            "io_bytes": None,
            "children": [],
            "process_tree_pids": [pid] if alive else [],
        }
    try:
        process = psutil.Process(pid)
        children = [child.pid for child in process.children(recursive=True) if child.is_running()]
        tree = [process, *(psutil.Process(child_pid) for child_pid in children)]
        cpu_values: list[float] = []
        io_values: list[int] = []
        for member in tree:
            try:
                cpu = member.cpu_times()
                cpu_values.append(float(cpu.user + cpu.system))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            try:
                io = member.io_counters()
                io_values.append(int(io.read_bytes + io.write_bytes))
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, NotImplementedError):
                pass
        return {
            "alive": process.is_running() and process.status() != psutil.STATUS_ZOMBIE,
            "cpu_seconds": sum(cpu_values) if cpu_values else None,
            "io_bytes": sum(io_values) if io_values else None,
            "children": children,
            "process_tree_pids": [member.pid for member in tree],
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return {
            "alive": False,
            "cpu_seconds": None,
            "io_bytes": None,
            "children": [],
            "process_tree_pids": [],
        }


def _version_for(command: Sequence[str]) -> str:
    if not command:
        return "unknown"
    try:
        completed = ProviderExecutor().run(
            [str(command[0]), "--version"],
            timeout=10,
            check=False,
            max_output_bytes=500,
        )
    except (OSError, ProviderExecutionError):
        return "unknown"
    text = (completed.stdout or completed.stderr or "").strip()
    return text[:500] or "unknown"


def _prepare_command(command: list[str], backend: str, final_output: Path) -> list[str]:
    prepared = list(command)
    if backend != "codex":
        return prepared
    if "--json" not in prepared and "--experimental-json" not in prepared:
        prepared.insert(2 if len(prepared) >= 2 else len(prepared), "--json")
    for flag in ("--output-last-message", "-o"):
        if flag in prepared:
            index = prepared.index(flag)
            if index + 1 >= len(prepared):
                raise ValueError(f"{flag} requires a file")
            prepared[index + 1] = str(final_output)
            break
    else:
        # Canonical Codex execution writes the final structured response to a
        # separate file while stdout remains the observable JSONL event stream.
        prepared.extend(["--output-last-message", str(final_output)])
    return prepared


class _RuntimeObserver:
    """Non-owning observer consumed by providers.executor.run_bounded_process."""

    def __init__(
        self,
        *,
        runtime_dir: Path,
        backend: str,
        task_id: str,
        candidate_id: str,
        node: str,
        inactivity_timeout: float | None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.backend = backend
        self.task_id = task_id
        self.candidate_id = candidate_id
        self.node = node
        self.inactivity_timeout = inactivity_timeout
        self.status_path = runtime_dir / "status.json"
        self.events_path = runtime_dir / "events.jsonl"
        self.stderr_path = runtime_dir / "stderr.log"
        self.final_output_path = runtime_dir / "final_output.json"
        self.started_at = _now()
        self.started_monotonic = time.monotonic()
        self.last_activity_monotonic = self.started_monotonic
        self.lock = threading.RLock()
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.line_buffer = ""
        self.last_snapshot: dict[str, Any] = {}
        self.shared: dict[str, Any] = {
            "revision": 0,
            "state": "starting",
            "thread_id": "",
            "provider_pid": None,
            "provider_alive": False,
            "observer_heartbeat_at": self.started_at,
            "last_provider_event_at": "",
            "last_provider_event": {},
            "last_successful_event": {},
            "current_item": {},
            "event_bytes": 0,
            "stderr_bytes": 0,
            "final_output_bytes": 0,
            "event_parse_errors": 0,
            "last_process_activity_at": "",
            "last_activity_at": self.started_at,
            "cpu_seconds": None,
            "io_bytes": None,
            "child_pids": [],
            "process_tree_pids": [],
            "termination_reason": "",
        }
        self.events_path.touch(exist_ok=True)
        self.stderr_path.touch(exist_ok=True)
        self.publish()

    def publish(self, **changes: Any) -> None:
        with self.lock:
            self.shared.update(changes)
            self.shared["revision"] = int(self.shared.get("revision", 0)) + 1
            value = {
                "schema_version": STATUS_SCHEMA,
                "task_schema_version": _TASK_SCHEMA_V2,
                "task_id": self.task_id,
                "attempt_id": os.environ.get("RLR_DEEP_RESEARCH_ATTEMPT_ID", ""),
                "candidate_id": self.candidate_id,
                "node": self.node,
                "backend": self.backend,
                "state": self.shared["state"],
                "revision": self.shared["revision"],
                "started_at": self.started_at,
                "updated_at": _now(),
                "provider_pid": self.shared["provider_pid"],
                "provider_alive": self.shared["provider_alive"],
                "observer_heartbeat_at": self.shared["observer_heartbeat_at"],
                "last_provider_event_at": self.shared["last_provider_event_at"],
                "last_provider_event": self.shared["last_provider_event"],
                "last_successful_event": self.shared["last_successful_event"],
                "current_item": self.shared["current_item"],
                "event_bytes": self.shared["event_bytes"],
                "stderr_bytes": self.shared["stderr_bytes"],
                "final_output_bytes": self.shared["final_output_bytes"],
                "event_parse_errors": self.shared["event_parse_errors"],
                "last_process_activity_at": self.shared["last_process_activity_at"],
                "last_activity_at": self.shared["last_activity_at"],
                "process_activity": {
                    "cpu_seconds": self.shared["cpu_seconds"],
                    "io_bytes": self.shared["io_bytes"],
                    "child_pids": self.shared["child_pids"],
                    "process_tree_pids": self.shared["process_tree_pids"],
                },
                "termination_reason": self.shared["termination_reason"],
                "elapsed_seconds": round(time.monotonic() - self.started_monotonic, 3),
            }
            _write_json_atomic(self.status_path, value)

    def on_start(self, pid: int) -> None:
        snapshot = _process_snapshot(pid)
        self.last_snapshot = snapshot
        now = _now()
        changes: dict[str, Any] = {
            "state": "running",
            "provider_pid": pid,
            "provider_alive": bool(snapshot.get("alive", True)),
            "last_process_activity_at": now,
            "last_activity_at": now,
            "child_pids": snapshot.get("children", []),
            "process_tree_pids": snapshot.get("process_tree_pids", [pid]),
        }
        if snapshot.get("cpu_seconds") is not None:
            changes["cpu_seconds"] = snapshot["cpu_seconds"]
        if snapshot.get("io_bytes") is not None:
            changes["io_bytes"] = snapshot["io_bytes"]
        self.publish(**changes)

    def _handle_event_line(self, line: str) -> None:
        if not line.strip():
            return
        at = _now()
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("event is not an object")
        except (json.JSONDecodeError, ValueError):
            self.publish(
                event_parse_errors=int(self.shared["event_parse_errors"]) + 1,
                last_activity_at=at,
            )
            return

        event_type = str(event.get("type") or "unknown")
        changes: dict[str, Any] = {
            "last_provider_event_at": at,
            "last_provider_event": _safe_event(event),
            "last_activity_at": at,
        }
        if event_type not in {"error", "turn.failed"}:
            changes["last_successful_event"] = _safe_event(event)
        if event_type == "thread.started":
            changes["thread_id"] = str(event.get("thread_id") or "")
        item = event.get("item")
        if event_type in {"item.started", "item.updated"} and isinstance(item, dict):
            safe = _safe_item(item)
            changes["current_item"] = safe
            changes["state"] = _state_for_item(safe)
        elif event_type == "item.completed" and isinstance(item, dict):
            if self.shared.get("current_item", {}).get("id") == str(item.get("id") or ""):
                changes["current_item"] = {}
            changes["state"] = "running"
        elif event_type == "turn.completed":
            changes["state"] = "validating"
        elif event_type == "turn.failed":
            changes["state"] = "provider_failed"
        # A recoverable `error` event is evidence, not terminal authority.
        self.last_activity_monotonic = time.monotonic()
        self.publish(**changes)

    def on_stdout(self, chunk: bytes) -> None:
        with self.lock:
            with self.events_path.open("ab") as stream:
                stream.write(chunk)
                stream.flush()
            self.shared["event_bytes"] = int(self.shared["event_bytes"]) + len(chunk)
            decoded = self.decoder.decode(chunk)
            self.line_buffer += decoded
            lines = self.line_buffer.split("\n")
            self.line_buffer = lines.pop()
            for line in lines:
                self._handle_event_line(line.rstrip("\r"))
            self.publish(event_bytes=self.shared["event_bytes"])

    def on_stderr(self, chunk: bytes) -> None:
        with self.lock:
            with self.stderr_path.open("ab") as stream:
                stream.write(chunk)
                stream.flush()
            # stderr diagnostics are persisted but do not count as semantic
            # progress for inactivity timeout.
            self.publish(stderr_bytes=int(self.shared["stderr_bytes"]) + len(chunk))

    def on_poll(self, pid: int, elapsed_seconds: float) -> str | None:
        del elapsed_seconds
        snapshot = _process_snapshot(pid)
        previous = self.last_snapshot
        cpu_seconds = snapshot.get("cpu_seconds")
        io_bytes = snapshot.get("io_bytes")
        process_tree_changed = (
            snapshot.get("process_tree_pids", [])
            != previous.get("process_tree_pids", [])
        )
        activity_changed = process_tree_changed or (
            cpu_seconds is not None and cpu_seconds != self.shared.get("cpu_seconds")
        ) or (
            io_bytes is not None and io_bytes != self.shared.get("io_bytes")
        )
        changes: dict[str, Any] = {
            "observer_heartbeat_at": _now(),
            "provider_alive": bool(snapshot.get("alive")),
            "child_pids": snapshot.get("children", []),
            "process_tree_pids": snapshot.get("process_tree_pids", []),
        }
        if cpu_seconds is not None:
            changes["cpu_seconds"] = cpu_seconds
        if io_bytes is not None:
            changes["io_bytes"] = io_bytes
        if activity_changed:
            now = _now()
            changes["last_process_activity_at"] = now
            changes["last_activity_at"] = now
            self.last_activity_monotonic = time.monotonic()
        self.last_snapshot = snapshot
        self.publish(**changes)
        if (
            self.inactivity_timeout is not None
            and time.monotonic() - self.last_activity_monotonic >= self.inactivity_timeout
        ):
            self.publish(
                state="inactivity_timed_out",
                termination_reason="inactivity_timeout",
            )
            return "inactivity_timed_out"
        return None

    def on_finish(self, pid: int, returncode: int | None, terminal_state: str) -> None:
        del pid, returncode
        remainder = self.decoder.decode(b"", final=True)
        if remainder:
            self.line_buffer += remainder
        if self.line_buffer.strip():
            self._handle_event_line(self.line_buffer.rstrip("\r"))
            self.line_buffer = ""
        self.publish(
            provider_alive=False,
            observer_heartbeat_at=_now(),
            termination_reason=(
                "job_timeout" if terminal_state == "timed_out"
                else "inactivity_timeout" if terminal_state == "inactivity_timed_out"
                else self.shared.get("termination_reason", "")
            ),
        )


def _receipt_cleanup(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "attempted": bool(value.get("attempted", False)),
        "targeted_pids": list(value.get("targeted_pids", [])),
        "terminated_pids": list(value.get("terminated_pids", [])),
        "killed_pids": list(value.get("killed_pids", [])),
        "errors": list(value.get("errors", [])),
        "provider_alive_after_cleanup": bool(value.get("alive_after_cleanup", False)),
    }


def run_observed_provider(
    *,
    command: list[str],
    prompt: str,
    runtime_dir: str | Path,
    backend: str,
    task_id: str,
    candidate_id: str,
    node: str,
    job_timeout: float | None,
    inactivity_timeout: float | None = None,
    observer_interval: float = 1.0,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
) -> ProviderExecution:
    """Execute one observed provider via the canonical bounded process engine."""
    runtime_dir = Path(runtime_dir)
    effective_cwd = Path(cwd).resolve() if cwd is not None else Path.cwd()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    final_output_path = runtime_dir / "final_output.json"
    receipt_path = runtime_dir / "runtime_receipt.json"
    prepared = _prepare_command(command, backend, final_output_path)
    observer = _RuntimeObserver(
        runtime_dir=runtime_dir,
        backend=backend,
        task_id=task_id,
        candidate_id=candidate_id,
        node=node,
        inactivity_timeout=inactivity_timeout,
    )

    try:
        bounded = DEFAULT_PROCESS_RUNNER.run(
            prepared,
            timeout=job_timeout,
            cwd=effective_cwd,
            env=env,
            input_text=input_text,
            observer=observer,
            poll_interval=observer_interval,
            # Runtime artifacts own complete stream persistence. The bounded
            # result retains a generous diagnostic copy without becoming the
            # provenance owner.
            max_output_bytes=4 * 1024 * 1024,
        )
    except OSError as exc:
        observer.publish(state="transport_lost", termination_reason=f"launch_failed: {exc}")
        cleanup = {
            "attempted": False,
            "targeted_pids": [],
            "terminated_pids": [],
            "killed_pids": [],
            "errors": [str(exc)],
            "provider_alive_after_cleanup": False,
        }
        receipt_hash = _finalize_receipt(
            runtime_dir,
            task_id,
            candidate_id,
            node,
            backend,
            command,
            prompt,
            "unknown",
            observer.started_at,
            "transport_lost",
            None,
            None,
            observer.shared,
            cleanup,
            prepared,
            str(effective_cwd),
            job_timeout,
            inactivity_timeout,
            observer_interval,
        )
        return ProviderExecution(
            prepared, 127, "", str(exc), "transport_lost", runtime_dir,
            receipt_path, receipt_hash,
        )

    if bounded.terminal_state == "timed_out":
        final_status = "job_timed_out"
        termination_reason = "job_timeout"
    elif bounded.terminal_state == "inactivity_timed_out":
        final_status = "inactivity_timed_out"
        termination_reason = "inactivity_timeout"
    elif bounded.returncode not in (0, None):
        final_status = "provider_failed"
        termination_reason = "provider_exit_nonzero"
    elif not final_output_path.is_file():
        final_status = "provider_dead"
        termination_reason = "provider_exited_without_final_output"
    else:
        final_status = "succeeded"
        termination_reason = "completed"

    final_output = (
        final_output_path.read_text(encoding="utf-8", errors="replace")
        if final_output_path.is_file() else ""
    )
    stderr_text = (runtime_dir / "stderr.log").read_text(
        encoding="utf-8", errors="replace"
    )
    observer.publish(
        state="validating" if final_status == "succeeded" else final_status,
        provider_alive=False,
        final_output_bytes=len(final_output.encode("utf-8")),
        termination_reason=termination_reason,
    )
    cleanup = _receipt_cleanup(bounded.process_tree_cleanup)
    version = _version_for(prepared)
    receipt_hash = _finalize_receipt(
        runtime_dir,
        task_id,
        candidate_id,
        node,
        backend,
        command,
        prompt,
        version,
        observer.started_at,
        final_status,
        bounded.returncode,
        bounded.pid,
        observer.shared,
        cleanup,
        prepared,
        str(effective_cwd),
        job_timeout,
        inactivity_timeout,
        observer_interval,
    )
    return ProviderExecution(
        prepared,
        int(bounded.returncode or 0),
        final_output,
        stderr_text,
        final_status,
        runtime_dir,
        receipt_path,
        receipt_hash,
    )


def _finalize_receipt(
    runtime_dir: Path,
    task_id: str,
    candidate_id: str,
    node: str,
    backend: str,
    command: list[str],
    prompt: str,
    provider_version: str,
    started_at: str,
    final_status: str,
    exit_code: int | None,
    provider_pid: int | None,
    shared: dict,
    cleanup: dict,
    executed_command: list[str],
    cwd: str,
    job_timeout: float | None,
    inactivity_timeout: float | None,
    observer_interval: float,
) -> str:
    receipt_path = runtime_dir / "runtime_receipt.json"
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "task_id": task_id,
        "attempt_id": os.environ.get("RLR_DEEP_RESEARCH_ATTEMPT_ID", ""),
        "candidate_id": candidate_id,
        "node": node,
        "backend": backend,
        "provider_version": provider_version,
        "command_hash": _sha_text(json.dumps(command, ensure_ascii=False)),
        "executed_command_hash": _sha_text(json.dumps(executed_command, ensure_ascii=False)),
        "command_metadata": {
            "argv0": str(executed_command[0]) if executed_command else "",
            "argument_count": len(executed_command),
            "backend": backend,
        },
        "cwd": cwd,
        "timeout_config": {
            "job_timeout_seconds": job_timeout,
            "inactivity_timeout_seconds": inactivity_timeout,
            "observer_interval_seconds": observer_interval,
        },
        "prompt_hash": _sha_text(prompt),
        "started_at": started_at,
        "ended_at": _now(),
        "provider_pid": provider_pid,
        "thread_id": shared.get("thread_id") or "",
        "final_status": final_status,
        "exit_code": exit_code,
        "last_successful_event": shared.get("last_successful_event") or {},
        "last_provider_event": shared.get("last_provider_event") or {},
        "last_provider_event_at": shared.get("last_provider_event_at") or "",
        "current_item_at_termination": shared.get("current_item") or {},
        "termination_reason": shared.get("termination_reason") or (
            "completed" if final_status == "succeeded" else final_status
        ),
        "timed_out": final_status in {"job_timed_out", "inactivity_timed_out"},
        "process_activity": {
            "cpu_seconds": shared.get("cpu_seconds"),
            "io_bytes": shared.get("io_bytes"),
            "last_process_activity_at": shared.get("last_process_activity_at") or "",
            "last_activity_at": shared.get("last_activity_at") or "",
            "process_tree_pids": shared.get("process_tree_pids") or [],
        },
        "process_tree_cleanup": cleanup,
        "artifacts": {
            "events": _file_record(runtime_dir / "events.jsonl"),
            "stderr": _file_record(runtime_dir / "stderr.log"),
            "final_output": _file_record(runtime_dir / "final_output.json"),
        },
    }
    _write_json_atomic(receipt_path, receipt)
    return _sha_bytes(receipt_path.read_bytes())


def _runtime_dir(project_dir: str | Path) -> tuple[str, Path]:
    env_dir = os.environ.get("RLR_DEEP_RESEARCH_TASK_DIR")
    env_id = os.environ.get("RLR_DEEP_RESEARCH_TASK_ID")
    if env_dir and env_id:
        return env_id, Path(env_dir)
    task_id = f"dr-direct-{uuid.uuid4().hex}"
    path = (
        Path(project_dir).resolve()
        / "08_Audit"
        / "deep_research_runtime"
        / "tasks"
        / task_id
    )
    return task_id, path


def _update_terminal_status(
    runtime_dir: Path,
    state: str,
    *,
    error: str = "",
    run_id: str = "",
) -> None:
    status_path = runtime_dir / "status.json"
    value = _read_json(status_path)
    value.update({
        "schema_version": STATUS_SCHEMA,
        "task_schema_version": _TASK_SCHEMA_V2,
        "state": state,
        "updated_at": _now(),
        "provider_alive": False,
        "revision": int(value.get("revision", 0)) + 1,
    })
    if error:
        value["error"] = error
    if run_id:
        value["run_id"] = run_id
    _write_json_atomic(status_path, value)


def _is_legacy_python_provider(command: str | Sequence[str]) -> bool:
    if isinstance(command, str) or len(command) < 2:
        return False
    executable = Path(str(command[0])).name.lower()
    return executable in {
        "python", "python.exe", "python3", "python3.exe",
    } and str(command[1]) == "exec"


class _ObservedExecutor:
    """ProviderExecutor-compatible view that adds observation, not process ownership."""

    def __init__(self, original: Any) -> None:
        self._original = original

    def run(self, command: str | Sequence[str], **kwargs: Any) -> ProviderExecutionResult:
        context = _CONTEXT.get()
        if (
            context is None
            or context.get("backend") != "codex"
            or _is_legacy_python_provider(command)
        ):
            return self._original.run(command, **kwargs)
        if isinstance(command, str):
            return self._original.run(command, **kwargs)

        execution = run_observed_provider(
            command=[str(part) for part in command],
            prompt=(
                str(kwargs["input_text"])
                if kwargs.get("input_text") is not None
                else str(command[-1])
            ),
            runtime_dir=context["runtime_dir"],
            backend=str(context["backend"]),
            task_id=str(context["task_id"]),
            candidate_id=str(context["candidate_id"]),
            node=str(context["node"]),
            job_timeout=kwargs.get("timeout"),
            observer_interval=float(
                os.environ.get("RLR_PROVIDER_OBSERVER_INTERVAL", "1.0")
            ),
            cwd=kwargs.get("cwd"),
            env=kwargs.get("env"),
            input_text=kwargs.get("input_text"),
        )
        context["execution"] = execution
        command_value = tuple(execution.args)
        if execution.final_status in {"job_timed_out", "inactivity_timed_out"}:
            raise ProviderExecutionError(
                f"external provider/tool timed out after {kwargs.get('timeout')}s",
                command=command_value,
                returncode=execution.returncode,
                stdout=execution.final_output,
                stderr=execution.stderr,
                timed_out=True,
                timeout=kwargs.get("timeout"),
                terminal_state=execution.final_status,
            )
        result = ProviderExecutionResult(
            command=command_value,
            returncode=execution.returncode,
            stdout=execution.final_output,
            stderr=execution.stderr,
            stdout_bytes=len(execution.final_output.encode("utf-8")),
            stderr_bytes=len(execution.stderr.encode("utf-8")),
        )
        if kwargs.get("check", True) and result.returncode != 0:
            raise ProviderExecutionError(
                f"external provider/tool exited {result.returncode}",
                command=command_value,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timeout=kwargs.get("timeout"),
                terminal_state=execution.final_status,
            )
        return result


def install(deep_research_module: Any, detached_task_module: Any) -> None:
    """Install observation over stable Deep Research and detached-task APIs."""
    if getattr(deep_research_module, "_provider_observability_installed", False):
        return
    original_build = deep_research_module.build_invocation
    original_run_and_persist = deep_research_module.run_and_persist
    original_skill_receipt = deep_research_module.skill_receipt
    original_task_status = detached_task_module._status
    original_validate_status = detached_task_module._validate_status
    original_run_worker = detached_task_module.run_worker

    def build_invocation(*args: Any, **kwargs: Any):
        command, prompt = original_build(*args, **kwargs)
        spec = args[0] if args else kwargs.get("spec")
        work_dir = args[4] if len(args) > 4 else kwargs.get("work_dir")
        if getattr(spec, "backend", "") == "codex":
            if "--json" not in command:
                command.append("--json")
            if "--output-last-message" not in command and "-o" not in command:
                command.extend([
                    "--output-last-message",
                    str(Path(work_dir) / "deep_research_final_output.json"),
                ])
        return command, prompt

    def run_and_persist(
        project_dir: Any,
        candidate_id: Any,
        node: Any,
        question: Any,
        claim: Any,
        spec: Any,
        work_dir: Any,
        skill_version: str = "unknown",
        result_context: str = "",
        **kwargs: Any,
    ):
        task_id, runtime_dir = _runtime_dir(project_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        request_path = runtime_dir / "request.json"
        if not request_path.exists():
            _write_json_atomic(request_path, {
                "schema_version": _TASK_SCHEMA_V2,
                "task_id": task_id,
                "created_at": _now(),
                "handler_args": {
                    "project_dir": str(Path(project_dir).resolve()),
                    "cand_id": candidate_id,
                    "node": node,
                    "backend": getattr(spec, "backend", ""),
                    "timeout": getattr(spec, "timeout", None),
                },
            })
        context = {
            "runtime_dir": runtime_dir,
            "task_id": task_id,
            "candidate_id": candidate_id,
            "node": node,
            "backend": getattr(spec, "backend", ""),
            "execution": None,
        }
        token = _CONTEXT.set(context)
        try:
            artifact = original_run_and_persist(
                project_dir,
                candidate_id,
                node,
                question,
                claim,
                spec,
                work_dir,
                skill_version,
                result_context,
                **kwargs,
            )
            _update_terminal_status(
                runtime_dir,
                "succeeded",
                run_id=str(artifact.get("run_id") or ""),
            )
            return artifact
        except Exception as exc:
            execution = context.get("execution")
            existing = _read_json(runtime_dir / "status.json")
            if existing.get("state") not in _TERMINAL_STATES:
                state = (
                    "validation_failed"
                    if execution and execution.final_status == "succeeded"
                    else execution.final_status
                    if execution
                    else "transport_lost"
                )
                _update_terminal_status(runtime_dir, state, error=str(exc))
            raise
        finally:
            _CONTEXT.reset(token)

    def skill_receipt(*args: Any, **kwargs: Any):
        value = original_skill_receipt(*args, **kwargs)
        context = _CONTEXT.get()
        execution = context.get("execution") if context else None
        if execution is not None:
            try:
                relative = execution.runtime_receipt_path.relative_to(
                    Path(context.get("runtime_dir")).parents[3]
                )
                path = str(relative).replace("\\", "/")
            except (ValueError, IndexError):
                path = str(execution.runtime_receipt_path)
            value["runtime_receipt"] = {
                "schema": RECEIPT_SCHEMA,
                "path": path,
                "sha256": execution.runtime_receipt_sha256,
            }
        return value

    # Deep Research already executes through DEFAULT_EXECUTOR. Replace only the
    # executor object with a ProviderExecutor-compatible observational view.
    deep_research_module.DEFAULT_EXECUTOR = _ObservedExecutor(
        deep_research_module.DEFAULT_EXECUTOR
    )
    deep_research_module.build_invocation = build_invocation
    deep_research_module.run_and_persist = run_and_persist
    deep_research_module.skill_receipt = skill_receipt

    detailed_failure_terminal = {
        "provider_failed", "validation_failed", "job_timed_out",
        "inactivity_timed_out", "cancelled", "provider_dead", "transport_lost",
    }

    def task_status(
        task_id: str,
        state: str,
        *,
        error: str = "",
        run_id: str = "",
        attempt_id: str = "",
        attempt_path: str = "",
    ) -> dict:
        task_dir = os.environ.get("RLR_DEEP_RESEARCH_TASK_DIR")
        existing = _read_json(Path(task_dir) / "status.json") if task_dir else {}
        value = original_task_status(
            task_id,
            state,
            error=error,
            run_id=run_id,
            attempt_id=attempt_id,
            attempt_path=attempt_path,
        )
        value["schema_version"] = _TASK_SCHEMA_V2
        value["status_schema"] = STATUS_SCHEMA
        if state == "failed":
            before_state = existing.get("state")
            if before_state == "succeeded":
                value["state"] = "validation_failed"
                value["legacy_state"] = "failed"
            elif before_state in detailed_failure_terminal:
                value["state"] = before_state
                value["legacy_state"] = "failed"
            else:
                value["state"] = "failed"
                value["diagnostic_state"] = "provider_failed"
        else:
            value["state"] = {
                "running": "running",
                "succeeded": "succeeded",
            }.get(state, state)
        if existing:
            previous_revision = int(existing.get("revision", 0))
            existing.update(value)
            existing["revision"] = previous_revision + 1
            value = existing
        else:
            value["revision"] = 1
        return value

    def validate_status(status: dict, task_id: str) -> None:
        schema = status.get("schema_version")
        if schema == _TASK_SCHEMA_V1:
            return original_validate_status(status, task_id)
        if (
            schema not in {_TASK_SCHEMA_V2, STATUS_SCHEMA}
            or status.get("task_id") != task_id
            or status.get("state") not in _ALLOWED_STATES
        ):
            raise detached_task_module.DetachedTaskError(
                f"task {task_id} status identity is invalid"
            )

    def run_worker(project_dir: Any, task_id: str, synchronous_handler: Any):
        task_dir = detached_task_module._task_dir(project_dir, task_id)
        previous_dir = os.environ.get("RLR_DEEP_RESEARCH_TASK_DIR")
        previous_id = os.environ.get("RLR_DEEP_RESEARCH_TASK_ID")
        os.environ["RLR_DEEP_RESEARCH_TASK_DIR"] = str(task_dir)
        os.environ["RLR_DEEP_RESEARCH_TASK_ID"] = task_id
        try:
            return original_run_worker(project_dir, task_id, synchronous_handler)
        finally:
            if previous_dir is None:
                os.environ.pop("RLR_DEEP_RESEARCH_TASK_DIR", None)
            else:
                os.environ["RLR_DEEP_RESEARCH_TASK_DIR"] = previous_dir
            if previous_id is None:
                os.environ.pop("RLR_DEEP_RESEARCH_TASK_ID", None)
            else:
                os.environ["RLR_DEEP_RESEARCH_TASK_ID"] = previous_id

    detached_task_module._status = task_status
    detached_task_module._validate_status = validate_status
    detached_task_module.run_worker = run_worker
    deep_research_module._provider_observability_installed = True
