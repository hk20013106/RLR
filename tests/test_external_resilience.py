from __future__ import annotations

import http.client
import importlib
import urllib.error
from types import SimpleNamespace

import pytest


def _module():
    return importlib.import_module("research_loop.external_resilience")


def _provider_result(*, returncode: int, stderr: str = "", stdout: str = "", terminal_state: str = "completed"):
    return SimpleNamespace(
        returncode=returncode,
        stderr=stderr,
        stdout=stdout,
        terminal_state=terminal_state,
        timed_out=terminal_state in {"timed_out", "job_timed_out", "inactivity_timed_out"},
    )


def test_http_incomplete_read_retries_and_returns_fresh_full_result():
    resilience = _module()
    attempts = 0
    waits: list[float] = []

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise http.client.IncompleteRead(b"partial", 100)
        return b"complete"

    result = resilience.run_http_with_retry(operation, sleep=waits.append)

    assert result == b"complete"
    assert attempts == 2
    assert waits == [1.0]


def test_http_429_respects_bounded_retry_after():
    resilience = _module()
    attempts = 0
    waits: list[float] = []

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.HTTPError(
                "https://example.test",
                429,
                "Too Many Requests",
                {"Retry-After": "20"},
                None,
            )
        return b"ok"

    assert resilience.run_http_with_retry(operation, sleep=waits.append) == b"ok"
    assert attempts == 2
    assert waits == [5.0]


def test_http_503_retries_but_403_does_not():
    resilience = _module()
    retry_waits: list[float] = []
    retry_attempts = 0

    def transient():
        nonlocal retry_attempts
        retry_attempts += 1
        if retry_attempts == 1:
            raise urllib.error.HTTPError(
                "https://example.test", 503, "Service Unavailable", {}, None
            )
        return b"ok"

    assert resilience.run_http_with_retry(transient, sleep=retry_waits.append) == b"ok"
    assert retry_attempts == 2
    assert retry_waits == [1.0]

    permanent_attempts = 0

    def permanent():
        nonlocal permanent_attempts
        permanent_attempts += 1
        raise urllib.error.HTTPError(
            "https://example.test", 403, "Forbidden", {}, None
        )

    with pytest.raises(urllib.error.HTTPError):
        resilience.run_http_with_retry(permanent, sleep=lambda _seconds: None)
    assert permanent_attempts == 1


def test_provider_capacity_retries_with_bounded_30_60_waits():
    resilience = _module()
    waits: list[float] = []
    responses = iter(
        [
            _provider_result(
                returncode=1,
                terminal_state="provider_failed",
                stderr="Selected model is at capacity. Please try again.",
            ),
            _provider_result(
                returncode=1,
                terminal_state="provider_failed",
                stderr="Selected model is at capacity. Please try again.",
            ),
            _provider_result(returncode=0, terminal_state="completed"),
        ]
    )
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return next(responses)

    result = resilience.run_provider_with_retry(operation, sleep=waits.append)

    assert result.returncode == 0
    assert calls == 3
    assert waits == [30.0, 60.0]


def test_provider_transient_exhaustion_returns_final_result_not_retry_error():
    resilience = _module()
    waits: list[float] = []
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return _provider_result(
            returncode=1,
            terminal_state="provider_failed",
            stderr="Selected model is at capacity. Please try again.",
        )

    result = resilience.run_provider_with_retry(operation, sleep=waits.append)

    assert result.returncode == 1
    assert calls == 3
    assert waits == [30.0, 60.0]


def test_provider_usage_limit_timeout_and_unknown_failure_do_not_retry():
    resilience = _module()

    cases = [
        _provider_result(
            returncode=1,
            terminal_state="provider_failed",
            stderr="You've hit your usage limit; try again at 4:42 PM.",
        ),
        _provider_result(
            returncode=1,
            terminal_state="job_timed_out",
            stderr="external provider/tool timed out",
        ),
        _provider_result(
            returncode=1,
            terminal_state="provider_failed",
            stderr="unclassified provider failure",
        ),
    ]

    for failure in cases:
        calls = 0

        def operation():
            nonlocal calls
            calls += 1
            return failure

        result = resilience.run_provider_with_retry(
            operation, sleep=lambda _seconds: pytest.fail("unexpected retry wait")
        )
        assert result is failure
        assert calls == 1


def test_provider_transient_exception_retries_but_non_retryable_exception_propagates():
    resilience = _module()
    waits: list[float] = []
    calls = 0

    class ProviderLikeError(RuntimeError):
        def __init__(self, message: str, *, terminal_state: str, returncode: int = 1):
            super().__init__(message)
            self.terminal_state = terminal_state
            self.returncode = returncode
            self.stderr = message
            self.stdout = ""
            self.timed_out = terminal_state in {"job_timed_out", "inactivity_timed_out"}

    def transient():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderLikeError(
                "service temporarily unavailable",
                terminal_state="provider_failed",
            )
        return _provider_result(returncode=0)

    assert resilience.run_provider_with_retry(transient, sleep=waits.append).returncode == 0
    assert calls == 2
    assert waits == [30.0]

    permanent_calls = 0

    def permanent():
        nonlocal permanent_calls
        permanent_calls += 1
        raise ProviderLikeError(
            "authentication failed: invalid API key",
            terminal_state="provider_failed",
        )

    with pytest.raises(ProviderLikeError, match="authentication failed"):
        resilience.run_provider_with_retry(permanent, sleep=lambda _seconds: None)
    assert permanent_calls == 1


def test_retry_policy_constants_are_bounded():
    resilience = _module()

    assert resilience.HTTP_RETRY_POLICY.max_attempts == 3
    assert resilience.HTTP_RETRY_POLICY.wait_seconds == (1.0, 2.0)
    assert resilience.HTTP_RETRY_POLICY.max_override_seconds == 5.0

    assert resilience.PROVIDER_RETRY_POLICY.max_attempts == 3
    assert resilience.PROVIDER_RETRY_POLICY.wait_seconds == (30.0, 60.0)


def test_formal_runtime_requires_shared_resilience_dependency():
    from research_loop import runtime_preflight

    assert "tenacity" in runtime_preflight.REQUIRED_DISTRIBUTIONS
    assert "research_loop.external_resilience" in runtime_preflight.REQUIRED_IMPORTS
