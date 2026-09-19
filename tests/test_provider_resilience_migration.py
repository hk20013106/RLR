from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from research_loop import deep_research
from research_loop import external_resilience
from research_loop import provider_runtime_observability as observability
from research_loop.providers import base as provider_base
from research_loop.providers import CommandProvider, ProviderError
from research_loop.providers.executor import (
    ProviderExecutionError,
    ProviderExecutionResult,
)


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex_jsonl.py"


def _result(
    *,
    returncode: int,
    stderr: str = "",
    stdout: str = "",
    terminal_state: str = "completed",
) -> ProviderExecutionResult:
    return ProviderExecutionResult(
        command=("codex", "exec", "--model", "gpt-5.6-sol"),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=terminal_state in {
            "timed_out",
            "job_timed_out",
            "inactivity_timed_out",
        },
        terminal_state=terminal_state,
    )


class _RecordingExecutor:
    def __init__(self, outcomes):
        self._outcomes = iter(outcomes)
        self.calls: list[tuple[object, dict]] = []

    def run(self, command, **kwargs):
        self.calls.append((command, dict(kwargs)))
        outcome = next(self._outcomes)
        if callable(outcome):
            return outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _install_zero_wait_retry(monkeypatch) -> list[float]:
    waits: list[float] = []
    shared_owner = external_resilience.run_provider_with_retry

    def run_now(operation):
        return shared_owner(operation, sleep=waits.append)

    monkeypatch.setattr(external_resilience, "run_provider_with_retry", run_now)
    return waits


def _execution_error(message, *, terminal_state="provider_failed", timed_out=False):
    return ProviderExecutionError(
        message,
        command="provider command",
        returncode=1,
        stderr=message,
        timed_out=timed_out,
        terminal_state=terminal_state,
    )


def _automatic_provider(monkeypatch, outcomes):
    executor = _RecordingExecutor(outcomes)
    monkeypatch.setattr(provider_base, "DEFAULT_EXECUTOR", executor)
    waits = _install_zero_wait_retry(monkeypatch)
    provider = CommandProvider({
        "command": "provider --prompt {prompt_file} --output {output_file}",
        "timeout": 91,
    })
    return provider, executor, waits


def _write_success(path, content):
    def write():
        path.write_text(content, encoding="utf-8")
        return _result(returncode=0)

    return write


def test_agent_provider_retries_capacity_through_shared_owner_without_mutation(
    tmp_path, monkeypatch
):
    provider, executor, waits = _automatic_provider(
        monkeypatch,
        [
            _execution_error("Selected model is at capacity"),
            _execution_error("Selected model is at capacity"),
            _write_success(
                tmp_path / "L1_Einstein_delta.json",
                '{"schema_version":"2.1"}',
            ),
        ],
    )

    assert provider.run_agent("L1", "Einstein", "context", run_dir=tmp_path) == {
        "schema_version": "2.1"
    }
    assert waits == [30.0, 60.0]
    assert len(executor.calls) == 3
    assert executor.calls[0] == executor.calls[1] == executor.calls[2]


def test_text_provider_retries_capacity_through_the_same_shared_owner(
    tmp_path, monkeypatch
):
    provider, executor, waits = _automatic_provider(
        monkeypatch,
        [
            _execution_error("service temporarily unavailable"),
            _write_success(tmp_path / "prefetch_L7_out.md", "located code"),
        ],
    )

    assert provider.run_text(
        "find existing code", tmp_path, "prefetch_L7", timeout=91
    ) == "located code"
    assert waits == [30.0]
    assert len(executor.calls) == 2
    assert executor.calls[0] == executor.calls[1]


def test_agent_provider_never_accepts_output_left_by_a_failed_retry_attempt(
    tmp_path, monkeypatch
):
    output = tmp_path / "L1_Einstein_delta.json"

    def write_stale_then_fail():
        output.write_text('{"stale":true}', encoding="utf-8")
        raise _execution_error("Selected model is at capacity")

    provider, executor, waits = _automatic_provider(
        monkeypatch, [write_stale_then_fail, _result(returncode=0)]
    )

    with pytest.raises(ProviderError, match="invalid JSON"):
        provider.run_agent("L1", "Einstein", "context", run_dir=tmp_path)
    assert len(executor.calls) == 2
    assert waits == [30.0]


def test_text_provider_never_accepts_output_left_by_a_failed_retry_attempt(
    tmp_path, monkeypatch
):
    output = tmp_path / "prefetch_L7_out.md"

    def write_stale_then_fail():
        output.write_text("stale located code", encoding="utf-8")
        raise _execution_error("service temporarily unavailable")

    provider, executor, waits = _automatic_provider(
        monkeypatch, [write_stale_then_fail, _result(returncode=0)]
    )

    with pytest.raises(ProviderError, match="readable text"):
        provider.run_text("find existing code", tmp_path, "prefetch_L7", timeout=91)
    assert len(executor.calls) == 2
    assert waits == [30.0]


@pytest.mark.parametrize(
    "failure",
    [
        _execution_error("quota exceeded"),
        _execution_error("authentication failure: invalid API key"),
        _execution_error("provider timed out", terminal_state="job_timed_out", timed_out=True),
        _execution_error("unclassified provider failure"),
    ],
)
def test_agent_provider_does_not_retry_non_retryable_failures(
    tmp_path, monkeypatch, failure
):
    provider, executor, waits = _automatic_provider(monkeypatch, [failure])

    with pytest.raises(ProviderError):
        provider.run_agent("L1", "Einstein", "context", run_dir=tmp_path)
    assert len(executor.calls) == 1
    assert waits == []


def test_json_parse_failure_does_not_reinvoke_provider(tmp_path, monkeypatch):
    output = tmp_path / "L1_Einstein_delta.json"
    provider, executor, waits = _automatic_provider(
        monkeypatch, [_write_success(output, "not json")]
    )

    with pytest.raises(
        provider_base.ProviderOutputContractError,
        match="failed JSON contract",
    ):
        provider.run_agent("L1", "Einstein", "context", run_dir=tmp_path)

    assert len(executor.calls) == 1
    assert waits == []
    assert output.read_text(encoding="utf-8") == "not json"
    assert provider.last_exit_code == 0
    assert provider.last_terminal_state == "completed"
    assert provider.last_execution_status == "failed"


def test_logical_provider_redispatch_preserves_prior_attempt_artifacts(
    tmp_path, monkeypatch
):
    first_output = tmp_path / "L1_Einstein_delta.json"
    second_output = tmp_path / "L1_Einstein_delta.2.json"
    provider, executor, waits = _automatic_provider(
        monkeypatch,
        [
            _write_success(first_output, "not json"),
            _write_success(second_output, '{"schema_version":"2.1"}'),
        ],
    )

    with pytest.raises(provider_base.ProviderOutputContractError):
        provider.run_agent("L1", "Einstein", "context", run_dir=tmp_path)
    first_prompt = tmp_path / "L1_Einstein_prompt.txt"
    first_prompt_bytes = first_prompt.read_bytes()
    first_output_bytes = first_output.read_bytes()

    assert provider.run_agent(
        "L1", "Einstein", "context", run_dir=tmp_path
    ) == {"schema_version": "2.1"}

    assert waits == []
    assert len(executor.calls) == 2
    assert provider.last_attempt_number == 2
    assert provider.last_prompt_file == str(tmp_path / "L1_Einstein_prompt.2.txt")
    assert provider.last_delta_file == str(second_output)
    assert first_prompt.read_bytes() == first_prompt_bytes
    assert first_output.read_bytes() == first_output_bytes
    assert second_output != first_output


def _invoke(monkeypatch, outcomes):
    executor = _RecordingExecutor(outcomes)
    monkeypatch.setattr(deep_research, "DEFAULT_EXECUTOR", executor)
    waits = _install_zero_wait_retry(monkeypatch)
    command = ["codex", "exec", "--model", "gpt-5.6-sol", "frozen prompt"]
    invocation_kwargs = {"input": "frozen scientific input"}
    result = deep_research.execute_provider_invocation(
        command,
        invocation_kwargs,
        timeout=91,
        label="Provider resilience fixture",
    )
    return result, executor.calls, waits, command, invocation_kwargs


def test_canonical_provider_boundary_retries_capacity_without_mutating_invocation(
    monkeypatch,
):
    result, calls, waits, command, invocation_kwargs = _invoke(
        monkeypatch,
        [
            _result(
                returncode=1,
                terminal_state="provider_failed",
                stderr="Selected model is at capacity. Please try a different model.",
            ),
            _result(returncode=0, stdout='{"ok": true}'),
        ],
    )

    assert result.returncode == 0
    assert len(calls) == 2
    assert waits == [30.0]
    assert all(call_command == command for call_command, _ in calls)
    assert all(
        call_kwargs
        == {
            "timeout": 91,
            "input_text": invocation_kwargs["input"],
            "check": False,
            "encoding": "utf-8",
            "errors": "strict",
        }
        for _, call_kwargs in calls
    )


def test_canonical_provider_boundary_uses_bounded_30_60_retry_sequence(monkeypatch):
    transient = _result(
        returncode=1,
        terminal_state="provider_failed",
        stderr="service temporarily unavailable",
    )
    result, calls, waits, _, _ = _invoke(
        monkeypatch,
        [transient, transient, _result(returncode=0, stdout='{"ok": true}')],
    )

    assert result.returncode == 0
    assert len(calls) == 3
    assert waits == [30.0, 60.0]


def test_canonical_provider_boundary_preserves_failure_after_retry_exhaustion(
    monkeypatch,
):
    transient = _result(
        returncode=1,
        terminal_state="provider_failed",
        stderr="HTTP 503 service unavailable",
    )
    result, calls, waits, _, _ = _invoke(
        monkeypatch,
        [transient, transient, transient],
    )

    assert len(calls) == 3
    assert waits == [30.0, 60.0]
    assert result.returncode == 1
    assert result.terminal_state == "provider_failed"


@pytest.mark.parametrize(
    "message",
    [
        "You've hit your usage limit; try again at 4:42 PM.",
        "quota exceeded",
        "authentication failure: invalid API key",
        "unauthorized",
        "forbidden",
        "invalid request",
        "unknown model",
        "model not found",
        "unclassified provider failure",
    ],
)
def test_canonical_provider_boundary_does_not_retry_terminal_or_unknown_failures(
    monkeypatch, message
):
    failure = _result(
        returncode=1,
        terminal_state="provider_failed",
        stderr=message,
    )
    result, calls, waits, _, _ = _invoke(monkeypatch, [failure])

    assert result is failure
    assert len(calls) == 1
    assert waits == []


def test_canonical_provider_boundary_does_not_retry_timeout(monkeypatch):
    timeout = _result(
        returncode=1,
        terminal_state="job_timed_out",
        stderr="provider timed out",
    )
    result, calls, waits, _, _ = _invoke(monkeypatch, [timeout])

    assert result is timeout
    assert len(calls) == 1
    assert waits == []


@pytest.mark.parametrize(
    ("terminal_state", "returncode"),
    [
        ("provider_failed", 9),
        ("transport_lost", 127),
        ("provider_dead", 0),
    ],
)
def test_observed_executor_preserves_observed_terminal_state(
    tmp_path, monkeypatch, terminal_state, returncode
):
    receipt_path = tmp_path / "provider_runtime" / ("a" * 64) / "runtime_receipt.json"
    execution = observability.ProviderExecution(
        args=["codex", "exec"],
        returncode=returncode,
        final_output="",
        stderr="observed provider failure",
        final_status=terminal_state,
        runtime_dir=tmp_path / "runtime",
        runtime_receipt_path=receipt_path,
        runtime_receipt_sha256="a" * 64,
    )
    monkeypatch.setattr(observability, "run_observed_provider", lambda **_kwargs: execution)

    class _UnexpectedOriginal:
        def run(self, *_args, **_kwargs):
            raise AssertionError("observed Codex invocation bypassed observability")

    context = {
        "runtime_dir": tmp_path / "runtime",
        "invocation_work_dir": tmp_path / "work",
        "task_id": "dr-carrier",
        "candidate_id": "C1",
        "node": "L4",
        "backend": "codex",
        "execution": None,
    }
    token = observability._CONTEXT.set(context)
    try:
        result = observability._ObservedExecutor(_UnexpectedOriginal()).run(
            ["codex", "exec", "frozen prompt"],
            input_text="frozen scientific input",
            timeout=30,
            check=False,
        )
    finally:
        observability._CONTEXT.reset(token)

    assert result.terminal_state == terminal_state
    assert result.returncode == returncode


def test_retry_attempts_keep_independent_immutable_runtime_receipts(
    tmp_path, monkeypatch
):
    counter = tmp_path / "provider-attempt-count.txt"
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "capacity_once")
    monkeypatch.setenv("RLR_FAKE_CODEX_COUNTER_FILE", str(counter))
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    waits = _install_zero_wait_retry(monkeypatch)
    runtime_dir = tmp_path / "08_Audit" / "deep_research_runtime" / "tasks" / "dr-retry"
    invocation_work_dir = tmp_path / "invocation"
    context = {
        "runtime_dir": runtime_dir,
        "project_dir": tmp_path,
        "invocation_work_dir": invocation_work_dir,
        "task_id": "dr-retry",
        "candidate_id": "C1",
        "node": "L4",
        "backend": "codex",
        "execution": None,
    }
    token = observability._CONTEXT.set(context)
    try:
        result = deep_research.execute_provider_invocation(
            [sys.executable, str(FIXTURE), "exec", "--json"],
            {"input": "immutable receipt retry fixture"},
            timeout=3,
        )
    finally:
        observability._CONTEXT.reset(token)

    receipts = sorted(
        (invocation_work_dir / "provider_runtime").glob("*/runtime_receipt.json")
    )
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in receipts]

    assert result.returncode == 0
    assert counter.read_text(encoding="utf-8") == "2"
    assert waits == [30.0]
    assert len(receipts) == 2
    assert {payload["final_status"] for payload in payloads} == {
        "provider_failed",
        "succeeded",
    }
    for path in receipts:
        assert path.parent.name == hashlib.sha256(path.read_bytes()).hexdigest()
        observability.validate_runtime_receipt_reference(
            tmp_path,
            {
                "schema": observability.RECEIPT_SCHEMA,
                "path": path.relative_to(tmp_path).as_posix(),
                "sha256": path.parent.name,
            },
            require_success=False,
        )
