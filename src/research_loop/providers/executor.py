"""Single process-execution boundary for external RLR providers and tools.

This module owns the only general-purpose process-spawning implementation used
by RLR provider/research/maintenance commands. It preserves the tested bounded
process semantics (hard timeout, bounded output, process-tree cleanup, and
cross-platform process groups) and layers the ProviderExecutor error contract
on top. Scientific provenance remains owned by RunReceipt/EvidenceRunReceipt.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import psutil
except ImportError:  # pragma: no cover - stdlib fallback for minimal installs
    psutil = None


DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024


@dataclass(frozen=True)
class BoundedProcessResult:
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


@dataclass(frozen=True)
class ProviderExecutionResult:
    """Normalized result from one external provider/tool process."""

    command: str | tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    process_tree_cleanup: Mapping[str, Any] | None = None


class ProviderExecutionError(RuntimeError):
    """Normalized external-process failure with replayable execution details."""

    def __init__(
        self,
        message: str,
        *,
        command: str | tuple[str, ...],
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
        timeout: float | None = None,
        process_tree_cleanup: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.timeout = timeout
        self.process_tree_cleanup = process_tree_cleanup or {}


def _terminate_process_tree(
    process: subprocess.Popen, grace: float = 2.0
) -> dict[str, Any]:
    attempted = process.poll() is None
    targeted: list[int] = []
    terminated: list[int] = []
    killed: list[int] = []
    errors: list[str] = []
    if attempted and psutil is not None:
        try:
            root = psutil.Process(process.pid)
            children = root.children(recursive=True)
            targeted = [child.pid for child in children] + [root.pid]
            for child in reversed(children):
                try:
                    child.terminate()
                    terminated.append(child.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                    errors.append(f"terminate {child.pid}: {exc}")
            try:
                root.terminate()
                terminated.append(root.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                errors.append(f"terminate {root.pid}: {exc}")
            _, alive = psutil.wait_procs(children + [root], timeout=grace)
            for remaining in alive:
                try:
                    remaining.kill()
                    killed.append(remaining.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                    errors.append(f"kill {remaining.pid}: {exc}")
            psutil.wait_procs(alive, timeout=grace)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            errors.append(str(exc))
    elif attempted:
        targeted = [process.pid]
        try:
            process.terminate()
            process.wait(timeout=grace)
            terminated.append(process.pid)
        except (subprocess.TimeoutExpired, OSError):
            try:
                process.kill()
                process.wait(timeout=grace)
                killed.append(process.pid)
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(str(exc))
    alive_after = process.poll() is None
    return {
        "attempted": attempted,
        "targeted_pids": targeted,
        "terminated_pids": terminated,
        "killed_pids": killed,
        "errors": errors,
        "alive_after_cleanup": alive_after,
    }


class _BoundedReader:
    def __init__(self, stream: Any, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._kept = bytearray()
        self._tail = bytearray()
        self._total = 0
        self._truncated = False

    def read(self) -> None:
        while True:
            chunk = self._stream.read(65536)
            if not chunk:
                break
            self._total += len(chunk)
            remaining = self._max_bytes - len(self._kept)
            if remaining > 0:
                self._kept.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self._truncated = True
            elif chunk:
                self._truncated = True
            if self._max_bytes > 0:
                self._tail.extend(chunk)
                if len(self._tail) > self._max_bytes:
                    del self._tail[:-self._max_bytes]
            else:
                self._truncated = True

    def result(self) -> tuple[bytes, bytes, int, bool]:
        return bytes(self._kept), bytes(self._tail), self._total, self._truncated


class _InputWriter:
    def __init__(self, stream: Any, payload: bytes) -> None:
        self._stream = stream
        self._payload = payload

    def write(self) -> None:
        try:
            self._stream.write(self._payload)
            self._stream.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                self._stream.close()
            except OSError:
                pass


def run_bounded_process(
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
) -> BoundedProcessResult:
    """Run one external command through RLR's bounded process engine."""
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive when provided")
    if max_output_bytes < 0:
        raise ValueError("max_output_bytes must be non-negative")

    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        "shell": bool(shell),
    }
    if cwd is not None:
        popen_kwargs["cwd"] = str(cwd)
    if env is not None:
        popen_kwargs["env"] = dict(env)
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)
    stdout_reader = _BoundedReader(process.stdout, max_output_bytes)
    stderr_reader = _BoundedReader(process.stderr, max_output_bytes)
    stdout_thread = threading.Thread(target=stdout_reader.read, daemon=True)
    stderr_thread = threading.Thread(target=stderr_reader.read, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    input_thread = None
    if input_text is not None:
        input_thread = threading.Thread(
            target=_InputWriter(
                process.stdin,
                input_text.encode(encoding, errors=errors),
            ).write,
            daemon=True,
        )
        input_thread.start()

    cleanup: dict[str, Any] = {
        "attempted": False,
        "targeted_pids": [],
        "terminated_pids": [],
        "killed_pids": [],
        "errors": [],
        "alive_after_cleanup": False,
    }
    timed_out = False
    started = time.monotonic()
    while process.poll() is None:
        if timeout is not None and time.monotonic() - started >= timeout:
            timed_out = True
            cleanup = _terminate_process_tree(process)
            break
        time.sleep(0.02)

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        returncode = process.poll()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if input_thread is not None:
        input_thread.join(timeout=1)

    stdout, stdout_tail, stdout_bytes, stdout_truncated = stdout_reader.result()
    stderr, stderr_tail, stderr_bytes, stderr_truncated = stderr_reader.result()
    return BoundedProcessResult(
        returncode=returncode,
        terminal_state="timed_out" if timed_out else "completed",
        stdout=stdout.decode(encoding, errors=errors),
        stderr=stderr.decode(encoding, errors=errors),
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        timeout_seconds=timeout,
        process_tree_cleanup=cleanup,
        stdout_tail=stdout_tail.decode(encoding, errors=errors),
        stderr_tail=stderr_tail.decode(encoding, errors=errors),
    )


class ProviderExecutor:
    """Provider/tool execution facade over the single bounded process engine."""

    @staticmethod
    def _command_value(command: str | Sequence[str]) -> str | tuple[str, ...]:
        if isinstance(command, str):
            return command
        return tuple(str(part) for part in command)

    def run(
        self,
        command: str | Sequence[str],
        *,
        timeout: float | None = None,
        shell: bool = False,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        check: bool = True,
        encoding: str = "utf-8",
        errors: str = "replace",
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> ProviderExecutionResult:
        command_value = self._command_value(command)
        try:
            bounded = run_bounded_process(
                command,
                timeout=timeout,
                shell=shell,
                cwd=cwd,
                env=env,
                input_text=input_text,
                encoding=encoding,
                errors=errors,
                max_output_bytes=max_output_bytes,
            )
        except OSError as exc:
            raise ProviderExecutionError(
                f"external provider/tool launch failed: {exc}",
                command=command_value,
                stderr=str(exc),
                timeout=timeout,
            ) from exc

        if bounded.terminal_state == "timed_out":
            raise ProviderExecutionError(
                f"external provider/tool timed out after {timeout}s",
                command=command_value,
                returncode=bounded.returncode,
                stdout=bounded.stdout,
                stderr=bounded.stderr,
                timed_out=True,
                timeout=timeout,
                process_tree_cleanup=bounded.process_tree_cleanup,
            )

        returncode = int(bounded.returncode or 0)
        result = ProviderExecutionResult(
            command=command_value,
            returncode=returncode,
            stdout=bounded.stdout,
            stderr=bounded.stderr,
            stdout_truncated=bounded.stdout_truncated,
            stderr_truncated=bounded.stderr_truncated,
            stdout_bytes=bounded.stdout_bytes,
            stderr_bytes=bounded.stderr_bytes,
            process_tree_cleanup=bounded.process_tree_cleanup,
        )
        if check and result.returncode != 0:
            raise ProviderExecutionError(
                f"external provider/tool exited {result.returncode}",
                command=command_value,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timeout=timeout,
                process_tree_cleanup=result.process_tree_cleanup,
            )
        return result


DEFAULT_EXECUTOR = ProviderExecutor()


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "BoundedProcessResult",
    "ProviderExecutionResult",
    "ProviderExecutionError",
    "ProviderExecutor",
    "DEFAULT_EXECUTOR",
    "run_bounded_process",
]
