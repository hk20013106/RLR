"""Shared bounded external-process mechanics for RLR.

This module is intentionally infrastructure-only.  It owns process creation,
stream draining, hard timeout enforcement, bounded diagnostics and process-tree
cleanup.  Provider semantics, scientific provenance and runtime status belong
to higher layers.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import psutil


DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    terminal_state: str
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_bytes: int
    stderr_bytes: int
    timeout_seconds: float | None
    process_tree_cleanup: Mapping[str, Any]
    stdout_tail: str = ""
    stderr_tail: str = ""
    pid: int | None = None


class _BoundedCapture:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def append(self, chunk: bytes) -> None:
        self.total += len(chunk)
        remaining = self.max_bytes - len(self.head)
        if remaining > 0:
            self.head.extend(chunk[:remaining])
        if self.max_bytes > 0:
            self.tail.extend(chunk)
            if len(self.tail) > self.max_bytes:
                del self.tail[:-self.max_bytes]

    @property
    def truncated(self) -> bool:
        return self.total > self.max_bytes


async def _notify(observer: Any, method: str, *args: Any) -> Any:
    if observer is None:
        return None
    callback = getattr(observer, method, None)
    if callback is None:
        return None
    value = callback(*args)
    if inspect.isawaitable(value):
        return await value
    return value


async def _read_stream(
    stream: asyncio.StreamReader | None,
    capture: _BoundedCapture,
    observer: Any,
    callback_name: str,
) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            return
        capture.append(chunk)
        await _notify(observer, callback_name, bytes(chunk))


async def _write_input(
    stream: asyncio.StreamWriter | None,
    payload: bytes,
) -> None:
    if stream is None:
        return
    try:
        stream.write(payload)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        stream.close()
        wait_closed = getattr(stream, "wait_closed", None)
        if wait_closed is not None:
            try:
                await wait_closed()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass


def _terminate_with_psutil(pid: int, grace: float) -> dict[str, Any]:
    targeted: list[int] = []
    terminated: list[int] = []
    killed: list[int] = []
    errors: list[str] = []
    try:
        root = psutil.Process(pid)
        children = root.children(recursive=True)
        targeted = [child.pid for child in children] + [root.pid]
        for member in [*reversed(children), root]:
            try:
                member.terminate()
                terminated.append(member.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                errors.append(f"terminate {member.pid}: {exc}")
        _, alive = psutil.wait_procs(children + [root], timeout=grace)
        for member in alive:
            try:
                member.kill()
                killed.append(member.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                errors.append(f"kill {member.pid}: {exc}")
        psutil.wait_procs(alive, timeout=grace)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        errors.append(str(exc))
    return {
        "attempted": True,
        "targeted_pids": targeted or [pid],
        "terminated_pids": terminated,
        "killed_pids": killed,
        "errors": errors,
        "alive_after_cleanup": psutil.pid_exists(pid),
    }


async def _terminate_process_tree(
    process: asyncio.subprocess.Process,
    grace: float = 2.0,
) -> dict[str, Any]:
    if process.returncode is not None:
        return {
            "attempted": False,
            "targeted_pids": [],
            "terminated_pids": [],
            "killed_pids": [],
            "errors": [],
            "alive_after_cleanup": False,
        }

    cleanup = await asyncio.to_thread(_terminate_with_psutil, process.pid, grace)
    try:
        await asyncio.wait_for(process.wait(), timeout=grace + 1.0)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=grace)
        except asyncio.TimeoutError:
            pass
    cleanup = dict(cleanup)
    cleanup["alive_after_cleanup"] = process.returncode is None
    return cleanup


class ProcessRunner:
    """Synchronous facade over asyncio's cross-platform process streams."""

    def run(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        encoding: str = "utf-8",
        errors: str = "replace",
        shell: bool = False,
        input_text: str | None = None,
        observer: Any = None,
        poll_interval: float = 0.05,
    ) -> ProcessResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.run_async(
                    command,
                    timeout=timeout,
                    cwd=cwd,
                    env=env,
                    max_output_bytes=max_output_bytes,
                    encoding=encoding,
                    errors=errors,
                    shell=shell,
                    input_text=input_text,
                    observer=observer,
                    poll_interval=poll_interval,
                )
            )
        raise RuntimeError(
            "ProcessRunner.run() cannot be used inside a running event loop; "
            "await ProcessRunner.run_async() instead"
        )

    async def run_async(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        encoding: str = "utf-8",
        errors: str = "replace",
        shell: bool = False,
        input_text: str | None = None,
        observer: Any = None,
        poll_interval: float = 0.05,
    ) -> ProcessResult:
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive when provided")
        if max_output_bytes < 0:
            raise ValueError("max_output_bytes must be non-negative")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")

        kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "stdin": (
                asyncio.subprocess.PIPE
                if input_text is not None
                else asyncio.subprocess.DEVNULL
            ),
        }
        if cwd is not None:
            kwargs["cwd"] = str(cwd)
        if env is not None:
            kwargs["env"] = dict(env)
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        if shell:
            if not isinstance(command, str):
                raise TypeError("shell=True requires a string command")
            process = await asyncio.create_subprocess_shell(command, **kwargs)
        else:
            argv = [str(command)] if isinstance(command, str) else [str(x) for x in command]
            if not argv:
                raise ValueError("command must not be empty")
            process = await asyncio.create_subprocess_exec(*argv, **kwargs)

        try:
            await _notify(observer, "on_start", process.pid)
        except BaseException:
            await _terminate_process_tree(process)
            raise

        stdout_capture = _BoundedCapture(max_output_bytes)
        stderr_capture = _BoundedCapture(max_output_bytes)
        stdout_task = asyncio.create_task(
            _read_stream(process.stdout, stdout_capture, observer, "on_stdout")
        )
        stderr_task = asyncio.create_task(
            _read_stream(process.stderr, stderr_capture, observer, "on_stderr")
        )
        input_task = None
        if input_text is not None:
            input_task = asyncio.create_task(
                _write_input(process.stdin, input_text.encode(encoding, errors=errors))
            )

        cleanup: dict[str, Any] = {
            "attempted": False,
            "targeted_pids": [],
            "terminated_pids": [],
            "killed_pids": [],
            "errors": [],
            "alive_after_cleanup": False,
        }
        terminal_state = "completed"
        loop = asyncio.get_running_loop()
        started = loop.time()
        wait_task = asyncio.create_task(process.wait())

        try:
            while not wait_task.done():
                for reader in (stdout_task, stderr_task):
                    if reader.done() and reader.exception() is not None:
                        cleanup = await _terminate_process_tree(process)
                        raise RuntimeError("process stream observer failed") from reader.exception()

                elapsed = loop.time() - started
                requested_state = await _notify(
                    observer, "on_poll", process.pid, elapsed
                )
                if requested_state:
                    terminal_state = str(requested_state)
                    cleanup = await _terminate_process_tree(process)
                    break
                if timeout is not None and elapsed >= timeout:
                    terminal_state = "timed_out"
                    cleanup = await _terminate_process_tree(process)
                    break
                await asyncio.sleep(poll_interval)

            if not wait_task.done():
                try:
                    await asyncio.wait_for(wait_task, timeout=3.0)
                except asyncio.TimeoutError:
                    cleanup = await _terminate_process_tree(process)
            else:
                await wait_task

            await asyncio.gather(stdout_task, stderr_task)
            if input_task is not None:
                await input_task
        except BaseException:
            if process.returncode is None:
                await _terminate_process_tree(process)
            for task in (stdout_task, stderr_task, input_task, wait_task):
                if task is not None and not task.done():
                    task.cancel()
            raise

        await _notify(
            observer, "on_finish", process.pid, process.returncode, terminal_state
        )
        stdout = bytes(stdout_capture.head).decode(encoding, errors=errors)
        stderr = bytes(stderr_capture.head).decode(encoding, errors=errors)
        stdout_tail = bytes(stdout_capture.tail).decode(encoding, errors=errors)
        stderr_tail = bytes(stderr_capture.tail).decode(encoding, errors=errors)
        return ProcessResult(
            returncode=process.returncode,
            terminal_state=terminal_state,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_capture.truncated,
            stderr_truncated=stderr_capture.truncated,
            stdout_bytes=stdout_capture.total,
            stderr_bytes=stderr_capture.total,
            timeout_seconds=timeout,
            process_tree_cleanup=cleanup,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            pid=process.pid,
        )


DEFAULT_PROCESS_RUNNER = ProcessRunner()
BoundedProcessResult = ProcessResult


def run_bounded_process(command: str | Sequence[str], **kwargs: Any) -> ProcessResult:
    return DEFAULT_PROCESS_RUNNER.run(command, **kwargs)


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "ProcessResult",
    "BoundedProcessResult",
    "ProcessRunner",
    "DEFAULT_PROCESS_RUNNER",
    "run_bounded_process",
]
