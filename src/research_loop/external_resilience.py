"""Shared bounded retry mechanics for external HTTP and provider calls.

This module is the sole owner of external-call retry mechanics.  Tenacity owns
attempt/stop/wait orchestration; RLR owns failure classification and the two
bounded policies.  Scientific stages and transport adapters must not grow their
own retry loops.

The module deliberately does not execute HTTP requests or provider processes
itself.  Callers supply a one-attempt callable so existing transport and
ProviderExecutor ownership remain unchanged.
"""
from __future__ import annotations

import http.client
import socket
import ssl
import urllib.error
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from tenacity import Retrying, retry_if_exception, stop_after_attempt


T = TypeVar("T")


@dataclass(frozen=True)
class RetryDecision:
    """One classifier decision for one completed external-call attempt."""

    retry: bool
    reason: str
    delay_seconds: float | None = None


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy independent of any provider or transport."""

    max_attempts: int
    wait_seconds: tuple[float, ...]
    max_override_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("retry max_attempts must be at least 1")
        if len(self.wait_seconds) != self.max_attempts - 1:
            raise ValueError("retry wait_seconds must define one delay per retry")
        if any(value < 0 for value in self.wait_seconds):
            raise ValueError("retry wait_seconds cannot be negative")
        if self.max_override_seconds is not None and self.max_override_seconds < 0:
            raise ValueError("retry max_override_seconds cannot be negative")


HTTP_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    wait_seconds=(1.0, 2.0),
    max_override_seconds=5.0,
)
PROVIDER_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    wait_seconds=(30.0, 60.0),
    max_override_seconds=60.0,
)


_PROVIDER_QUOTA_PATTERNS = (
    "usage limit",
    "quota exceeded",
    "quota exhausted",
    "rate limit exceeded",
    "too many requests",
)
_PROVIDER_TRANSIENT_PATTERNS = (
    "selected model is at capacity",
    "model is at capacity",
    "temporarily unavailable",
    "temporary unavailable",
    "service unavailable",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connection closed",
    "transport error",
    "bad gateway",
    "gateway timeout",
    "http 502",
    "http 503",
    "http 504",
    "status 502",
    "status 503",
    "status 504",
)
_PROVIDER_PERMANENT_PATTERNS = (
    "authentication failed",
    "authentication error",
    "invalid api key",
    "invalid token",
    "unauthorized",
    "forbidden",
    "invalid request",
    "unknown model",
    "model not found",
    "no such file or directory",
    "executable not found",
)
_PROVIDER_TIMEOUT_STATES = {
    "timed_out",
    "job_timed_out",
    "inactivity_timed_out",
}


def _no_retry(reason: str) -> RetryDecision:
    return RetryDecision(False, reason)


def _retry(reason: str, *, delay_seconds: float | None = None) -> RetryDecision:
    return RetryDecision(True, reason, delay_seconds)


def _retry_after_seconds(error: urllib.error.HTTPError) -> float | None:
    headers = getattr(error, "headers", None) or {}
    value = str(headers.get("Retry-After") or "").strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


def classify_http_failure(value: Any) -> RetryDecision:
    """Classify one HTTP/transport outcome without performing a retry."""

    if not isinstance(value, BaseException):
        return _no_retry("http_success")
    if isinstance(value, ssl.SSLError):
        return _no_retry("tls_error")
    if isinstance(value, urllib.error.HTTPError):
        code = int(value.code)
        if code in {429, 502, 503, 504}:
            return _retry(
                f"http_{code}",
                delay_seconds=_retry_after_seconds(value),
            )
        return _no_retry(f"http_{code}")
    if isinstance(value, http.client.IncompleteRead):
        return _retry("incomplete_read")
    if isinstance(value, urllib.error.ContentTooShortError):
        return _retry("content_too_short")
    if isinstance(value, urllib.error.URLError):
        reason = getattr(value, "reason", None)
        if isinstance(reason, BaseException):
            nested = classify_http_failure(reason)
            if nested.retry:
                return RetryDecision(True, f"url_error:{nested.reason}", nested.delay_seconds)
        return _no_retry("url_error")
    if isinstance(value, socket.gaierror):
        if getattr(value, "errno", None) == getattr(socket, "EAI_AGAIN", None):
            return _retry("dns_temporary_failure")
        return _no_retry("dns_failure")
    if isinstance(
        value,
        (
            TimeoutError,
            socket.timeout,
            ConnectionResetError,
            ConnectionAbortedError,
            ConnectionRefusedError,
            BrokenPipeError,
            http.client.RemoteDisconnected,
        ),
    ):
        return _retry(type(value).__name__)
    return _no_retry("unknown_http_failure")


def _provider_text(value: Any) -> str:
    parts = [
        str(getattr(value, "stderr", "") or ""),
        str(getattr(value, "stdout", "") or ""),
    ]
    if isinstance(value, BaseException):
        parts.append(str(value))
    return "\n".join(part for part in parts if part).casefold()


def classify_provider_failure(value: Any) -> RetryDecision:
    """Classify one provider outcome without changing provider execution."""

    terminal_state = str(getattr(value, "terminal_state", "") or "").casefold()
    timed_out = bool(getattr(value, "timed_out", False))
    returncode = getattr(value, "returncode", None)
    text = _provider_text(value)

    if timed_out or terminal_state in _PROVIDER_TIMEOUT_STATES:
        return _no_retry("provider_timeout")

    # Quota/allowance exhaustion is deliberately checked before transient text;
    # messages often contain "try again" but short automatic waits are wasteful.
    if any(pattern in text for pattern in _PROVIDER_QUOTA_PATTERNS):
        return _no_retry("provider_quota")
    if any(pattern in text for pattern in _PROVIDER_PERMANENT_PATTERNS):
        return _no_retry("provider_permanent_failure")
    if any(pattern in text for pattern in _PROVIDER_TRANSIENT_PATTERNS):
        return _retry("provider_transient_failure")

    if isinstance(
        value,
        (ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError),
    ):
        return _retry("provider_transport_failure")

    if not isinstance(value, BaseException):
        if returncode in (0, None) and terminal_state in {"", "completed", "succeeded"}:
            return _no_retry("provider_success")
        return _no_retry("unknown_provider_failure")
    return _no_retry("unknown_provider_exception")


class _RetryableResultError(RuntimeError):
    """Internal bridge that lets Tenacity retry a returned failure result."""

    def __init__(self, result: Any, decision: RetryDecision) -> None:
        super().__init__(decision.reason)
        self.result = result
        self.decision = decision


def _decision_for_exception(
    error: BaseException,
    classifier: Callable[[Any], RetryDecision],
) -> RetryDecision:
    if isinstance(error, _RetryableResultError):
        return error.decision
    return classifier(error)


def _run_with_retry(
    operation: Callable[[], T],
    *,
    classifier: Callable[[Any], RetryDecision],
    policy: RetryPolicy,
    sleep: Callable[[float], Any] | None,
) -> T:
    sleeper = sleep if sleep is not None else __import__("time").sleep

    def should_retry(error: BaseException) -> bool:
        return _decision_for_exception(error, classifier).retry

    def wait_seconds(retry_state) -> float:
        error = retry_state.outcome.exception()
        decision = _decision_for_exception(error, classifier)
        if decision.delay_seconds is not None:
            delay = max(0.0, float(decision.delay_seconds))
            if policy.max_override_seconds is not None:
                delay = min(delay, policy.max_override_seconds)
            return delay
        index = max(0, int(retry_state.attempt_number) - 1)
        if index >= len(policy.wait_seconds):
            return 0.0
        return float(policy.wait_seconds[index])

    retrying = Retrying(
        stop=stop_after_attempt(policy.max_attempts),
        retry=retry_if_exception(should_retry),
        wait=wait_seconds,
        sleep=sleeper,
        reraise=True,
    )
    try:
        for attempt in retrying:
            with attempt:
                result = operation()
                decision = classifier(result)
                if decision.retry:
                    raise _RetryableResultError(result, decision)
                return result
    except _RetryableResultError as error:
        # Preserve existing check=False semantics: exhaustion of a returned
        # non-zero provider result returns the final result, not RetryError.
        return error.result
    raise RuntimeError("unreachable retry state")


def run_http_with_retry(
    operation: Callable[[], T],
    *,
    sleep: Callable[[float], Any] | None = None,
) -> T:
    """Run one idempotent HTTP operation under the shared bounded policy."""

    return _run_with_retry(
        operation,
        classifier=classify_http_failure,
        policy=HTTP_RETRY_POLICY,
        sleep=sleep,
    )


def run_provider_with_retry(
    operation: Callable[[], T],
    *,
    sleep: Callable[[float], Any] | None = None,
) -> T:
    """Run one retry-safe provider invocation under the shared bounded policy."""

    return _run_with_retry(
        operation,
        classifier=classify_provider_failure,
        policy=PROVIDER_RETRY_POLICY,
        sleep=sleep,
    )


__all__ = [
    "HTTP_RETRY_POLICY",
    "PROVIDER_RETRY_POLICY",
    "RetryDecision",
    "RetryPolicy",
    "classify_http_failure",
    "classify_provider_failure",
    "run_http_with_retry",
    "run_provider_with_retry",
]
