"""Thin provider/tool execution facade over the shared ProcessRunner."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from research_loop.process_runner import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_PROCESS_RUNNER,
    ProcessResult,
    ProcessRunner,
)


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
    timed_out: bool = False
    terminal_state: str = "completed"


class ProviderExecutionError(RuntimeError):
    """Normalized provider/tool failure with replayable execution details."""

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
        terminal_state: str = "",
        process_tree_cleanup: Mapping[str, Any] | None = None,
        process_result: ProcessResult | None = None,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.timeout = timeout
        self.terminal_state = terminal_state
        self.process_tree_cleanup = process_tree_cleanup or {}
        self.process_result = process_result


class ProviderExecutor:
    """Provider-specific result/error semantics over one shared ProcessRunner."""

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or DEFAULT_PROCESS_RUNNER

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
        observer: Any = None,
        poll_interval: float = 0.05,
    ) -> ProviderExecutionResult:
        command_value = self._command_value(command)
        try:
            process = self.runner.run(
                command,
                timeout=timeout,
                shell=shell,
                cwd=cwd,
                env=env,
                input_text=input_text,
                encoding=encoding,
                errors=errors,
                max_output_bytes=max_output_bytes,
                observer=observer,
                poll_interval=poll_interval,
            )
        except OSError as exc:
            raise ProviderExecutionError(
                f"external provider/tool launch failed: {exc}",
                command=command_value,
                stderr=str(exc),
                timeout=timeout,
                terminal_state="launch_failed",
            ) from exc

        if process.terminal_state != "completed":
            timed_out = process.terminal_state in {
                "timed_out", "job_timed_out", "inactivity_timed_out"
            }
            raise ProviderExecutionError(
                (
                    f"external provider/tool timed out after {timeout}s"
                    if timed_out
                    else f"external provider/tool terminated: {process.terminal_state}"
                ),
                command=command_value,
                returncode=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
                timed_out=timed_out,
                timeout=timeout,
                terminal_state=process.terminal_state,
                process_tree_cleanup=process.process_tree_cleanup,
                process_result=process,
            )

        returncode = int(process.returncode or 0)
        result = ProviderExecutionResult(
            command=command_value,
            returncode=returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            stdout_truncated=process.stdout_truncated,
            stderr_truncated=process.stderr_truncated,
            stdout_bytes=process.stdout_bytes,
            stderr_bytes=process.stderr_bytes,
            process_tree_cleanup=process.process_tree_cleanup,
            timed_out=False,
            terminal_state=process.terminal_state,
        )
        if check and result.returncode != 0:
            raise ProviderExecutionError(
                f"external provider/tool exited {result.returncode}",
                command=command_value,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timeout=timeout,
                terminal_state="provider_failed",
                process_tree_cleanup=result.process_tree_cleanup,
                process_result=process,
            )
        return result


DEFAULT_EXECUTOR = ProviderExecutor()


__all__ = [
    "ProcessRunner",
    "ProviderExecutionResult",
    "ProviderExecutionError",
    "ProviderExecutor",
    "DEFAULT_EXECUTOR",
]
