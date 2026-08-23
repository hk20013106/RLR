"""Single process-execution boundary for external RLR providers and research tools."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProviderExecutionResult:
    """Normalized result from one external provider/tool process."""

    command: str | tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


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
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.timeout = timeout


class ProviderExecutor:
    """Execute an external provider/tool process with one failure contract.

    RLR's scientific receipts remain owned by ``RunReceipt`` and Deep Research
    evidence receipts.  This class owns only process execution semantics:
    captured UTF-8 text, timeout handling, exit status, and launch errors.
    """

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
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        check: bool = True,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> ProviderExecutionResult:
        command_value = self._command_value(command)
        try:
            completed = subprocess.run(
                command,
                shell=shell,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                input=input_text,
                capture_output=True,
                text=True,
                encoding=encoding,
                errors=errors,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(encoding, errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(encoding, errors="replace")
            raise ProviderExecutionError(
                f"external provider/tool timed out after {timeout}s",
                command=command_value,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
                timeout=timeout,
            ) from exc
        except OSError as exc:
            raise ProviderExecutionError(
                f"external provider/tool launch failed: {exc}",
                command=command_value,
                stderr=str(exc),
                timed_out=False,
                timeout=timeout,
            ) from exc

        result = ProviderExecutionResult(
            command=command_value,
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if check and result.returncode != 0:
            raise ProviderExecutionError(
                f"external provider/tool exited {result.returncode}",
                command=command_value,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=False,
                timeout=timeout,
            )
        return result


DEFAULT_EXECUTOR = ProviderExecutor()
