"""Bounded external Codex CLI adapter for Meta-RLR repairs."""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


DEFAULT_REPAIR_JOB_TIMEOUT = 900.0
DEFAULT_REPAIR_INACTIVITY_TIMEOUT = 180.0
DEFAULT_REPAIR_OBSERVER_INTERVAL = 1.0


class CodexError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexRepairResult:
    status: str
    summary: str
    tests_requested: tuple[str, ...]
    blocker: str | None


def _command_prefix(executable: str | Sequence[str]) -> tuple[str, ...]:
    values = (executable,) if isinstance(executable, str) else tuple(str(x) for x in executable)
    if not values or any(not item for item in values):
        raise ValueError("Codex executable must be non-empty")
    return values


_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"enum": ["changed", "no_change", "blocked"]},
        "summary": {"type": "string", "maxLength": 2048},
        "tests_requested": {"type": "array", "maxItems": 32, "items": {"type": "string", "maxLength": 512}},
        "blocker": {"type": ["string", "null"], "maxLength": 2048},
    },
    "required": ["status", "summary", "tests_requested", "blocker"],
    "additionalProperties": False,
}


def _default_observed_runner(**kwargs: object) -> object:
    """Load the existing bounded provider runner only at the repair boundary."""
    from research_loop.provider_runtime_observability import run_observed_provider

    return run_observed_provider(**kwargs)


class CodexCli:
    def __init__(
        self,
        executable: str | Sequence[str] = "codex",
        runner: Callable[..., object] | None = None,
        *,
        observed_runner: Callable[..., object] | None = None,
        job_timeout: float = DEFAULT_REPAIR_JOB_TIMEOUT,
        inactivity_timeout: float = DEFAULT_REPAIR_INACTIVITY_TIMEOUT,
        observer_interval: float = DEFAULT_REPAIR_OBSERVER_INTERVAL,
    ) -> None:
        if runner is not None and observed_runner is not None:
            raise ValueError("Codex runner and observed runner are mutually exclusive")
        if job_timeout <= 0 or inactivity_timeout <= 0 or observer_interval <= 0:
            raise ValueError("Codex repair runtime bounds must be positive")
        self._executable = _command_prefix(executable)
        self._runner = runner
        self._observed_runner = (
            observed_runner if observed_runner is not None else _default_observed_runner
        )
        self._job_timeout = float(job_timeout)
        self._inactivity_timeout = float(inactivity_timeout)
        self._observer_interval = float(observer_interval)

    @staticmethod
    def _parse_result(payload: object) -> CodexRepairResult:
        if not isinstance(payload, Mapping) or set(payload) != {"status", "summary", "tests_requested", "blocker"}:
            raise CodexError("Codex final result has invalid fields")
        status, summary = payload["status"], payload["summary"]
        tests, blocker = payload["tests_requested"], payload["blocker"]
        if status not in {"changed", "no_change", "blocked"}:
            raise CodexError("Codex final result has invalid status")
        if not isinstance(summary, str) or len(summary) > 2048:
            raise CodexError("Codex final result has invalid summary")
        if not isinstance(tests, list) or len(tests) > 32 or any(not isinstance(x, str) or len(x) > 512 for x in tests):
            raise CodexError("Codex final result has invalid tests_requested")
        if blocker is not None and (not isinstance(blocker, str) or len(blocker) > 2048):
            raise CodexError("Codex final result has invalid blocker")
        return CodexRepairResult(status=status, summary=summary, tests_requested=tuple(tests), blocker=blocker)

    def run_repair(self, *, worktree: str | Path, prompt: str) -> CodexRepairResult:
        root = Path(worktree)
        if not root.is_dir():
            raise CodexError("Codex repair worktree must exist")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Codex repair prompt must be non-empty")
        with tempfile.TemporaryDirectory(prefix="meta-rlr-codex-") as tmp:
            temp_root = Path(tmp)
            schema_path = temp_root / "result.schema.json"
            output_path = temp_root / "last-message.json"
            schema_path.write_text(json.dumps(_RESULT_SCHEMA, sort_keys=True), encoding="utf-8")
            command = [*self._executable, "exec", "--ephemeral", "--sandbox", "workspace-write", "-C", str(root), "--output-schema", str(schema_path), "--output-last-message", str(output_path), "-"]
            if self._runner is not None:
                completed = self._runner(command, cwd=root, input=prompt, text=True, encoding="utf-8", capture_output=True, shell=False)
                returncode = int(getattr(completed, "returncode"))
                if returncode != 0:
                    raise CodexError(f"Codex command failed with exit code {returncode}")
                if not output_path.is_file():
                    raise CodexError("Codex final result file is missing")
                result_text = output_path.read_text(encoding="utf-8")
            else:
                try:
                    runtime_dir = Path(tempfile.mkdtemp(prefix=f".{root.name}.meta-rlr-runtime-", dir=root.parent))
                except OSError as exc:
                    raise CodexError("Codex repair runtime directory could not be created") from exc
                execution = self._observed_runner(
                    command=command,
                    prompt=prompt,
                    runtime_dir=runtime_dir,
                    backend="codex",
                    task_id=f"meta-rlr-repair-{runtime_dir.name}",
                    candidate_id="maintenance",
                    node="Meta-RLR",
                    job_timeout=self._job_timeout,
                    inactivity_timeout=self._inactivity_timeout,
                    observer_interval=self._observer_interval,
                    cwd=root,
                    input_text=prompt,
                )
                final_status = str(getattr(execution, "final_status", "unknown"))
                if final_status != "succeeded":
                    receipt_path = getattr(execution, "runtime_receipt_path", runtime_dir / "runtime_receipt.json")
                    raise CodexError(
                        f"Codex repair terminated with status {final_status}; runtime receipt {receipt_path}"
                    )
                result_text = str(getattr(execution, "final_output", ""))
                if not result_text:
                    raise CodexError("Codex final result file is missing")
            try:
                payload = json.loads(result_text)
            except json.JSONDecodeError as exc:
                raise CodexError("Codex final result is not valid JSON") from exc
            return self._parse_result(payload)
