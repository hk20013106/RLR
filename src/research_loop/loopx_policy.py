"""Deterministic Loop X failure classification and retry decisions."""
from __future__ import annotations

import hashlib
import json


FAILURE_CLASSES = frozenset({
    "ARCHITECTURE", "IMPLEMENTATION", "CONTRACT", "CONFIGURATION",
    "EXTERNAL", "DATA", "EVIDENCE_GAP", "MODEL_STOCHASTICITY",
})


class LoopXPolicyError(ValueError):
    pass


def failure_fingerprint(node: str, failure_class: str, failure_code: str) -> str:
    """Create a stable fingerprint without importing free-form error text."""
    identity = {
        "node": str(node),
        "failure_class": str(failure_class),
        "failure_code": str(failure_code),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class LoopXRetryPolicy:
    """Track repeated failures and prohibit unsafe prompt-only re-dispatch."""

    def __init__(self, retry_threshold: int = 2):
        if (not isinstance(retry_threshold, int) or isinstance(retry_threshold, bool)
                or retry_threshold < 1):
            raise LoopXPolicyError("retry_threshold must be a positive integer")
        self.retry_threshold = retry_threshold
        self._attempts: dict[str, int] = {}

    def record(self, node: str, failure_class: str, failure_code: str) -> dict:
        if failure_class not in FAILURE_CLASSES:
            raise LoopXPolicyError(f"unknown Loop X failure class: {failure_class}")
        if not str(node).strip() or not str(failure_code).strip():
            raise LoopXPolicyError("Loop X node and failure_code are required")
        fingerprint = failure_fingerprint(node, failure_class, failure_code)
        count = self._attempts.get(fingerprint, 0) + 1
        self._attempts[fingerprint] = count
        if failure_class in {"ARCHITECTURE", "IMPLEMENTATION", "CONTRACT"}:
            action = "ESCALATE_ARCHITECTURE_REVIEW"
        elif failure_class == "CONFIGURATION":
            action = "HALT_FOR_CONFIGURATION"
        elif failure_class == "DATA":
            action = "HALT_FOR_DATA"
        elif failure_class == "EVIDENCE_GAP":
            action = "HALT_FOR_EVIDENCE_GAP"
        elif count >= self.retry_threshold:
            action = "ESCALATE_ARCHITECTURE_REVIEW"
        else:
            action = "RETRY_SAME_NODE"
        return {
            "failure_class": failure_class,
            "node": str(node),
            "failure_fingerprint": fingerprint,
            "attempt_count": count,
            "recommended_action": action,
        }
