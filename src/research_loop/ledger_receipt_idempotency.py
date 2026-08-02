"""Make commit receipts temporally idempotent across exact retries.

The ledger's immutable emission row already owns the canonical commit time.
This extension makes every timestamp created during a new commit use one fixed
transaction timestamp, and makes retry receipts reuse the original emission's
``committed_at`` value instead of sampling the wall clock again.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any


_COMMIT_CLOCK: ContextVar[dict[str, Any] | None] = ContextVar(
    "rlr_commit_clock", default=None
)


def install(ledger_module) -> None:
    """Install a concurrency-safe timestamp binding around ``commit_delta``."""
    if getattr(ledger_module, "_RECEIPT_IDEMPOTENCY_INSTALLED", False):
        return

    ledger_cls = ledger_module.HypothesisLedger
    original_now = ledger_module._now
    original_receipt = ledger_cls._receipt
    original_commit_delta = ledger_cls.commit_delta

    def stable_now() -> str:
        context = _COMMIT_CLOCK.get()
        return str(context["transaction_time"]) if context else original_now()

    def stable_receipt(
        self,
        project_id,
        candidate_id,
        round_id,
        node,
        persona,
        delta_hash,
        commit_seq,
        event_ids,
        *,
        profile=None,
    ):
        receipt = original_receipt(
            self,
            project_id,
            candidate_id,
            round_id,
            node,
            persona,
            delta_hash,
            commit_seq,
            event_ids,
            profile=profile,
        )
        context = _COMMIT_CLOCK.get()
        if context:
            receipt["created_at"] = context["existing_emissions"].get(
                str(delta_hash), context["transaction_time"]
            )
        return receipt

    def commit_delta(self, **kwargs):
        existing_emissions: dict[str, str] = {}
        try:
            binding = self.require_binding(kwargs["project_dir"])
            con = self._connect(readonly=True)
            try:
                rows = con.execute(
                    "SELECT delta_hash,committed_at FROM emissions "
                    "WHERE project_id=? AND candidate_id=? AND round_id=? "
                    "AND node=?",
                    (
                        str(binding["project_id"]),
                        str(kwargs["candidate_id"]),
                        str(kwargs["round_id"]),
                        str(kwargs["node"]),
                    ),
                ).fetchall()
            finally:
                con.close()
            existing_emissions = {
                str(row["delta_hash"]): str(row["committed_at"]) for row in rows
            }
        except Exception:
            # Preserve the original fail-closed validation path. Invalid binding,
            # arguments, or stores are diagnosed by the wrapped implementation.
            existing_emissions = {}

        token = _COMMIT_CLOCK.set({
            "transaction_time": original_now(),
            "existing_emissions": existing_emissions,
        })
        try:
            return original_commit_delta(self, **kwargs)
        finally:
            _COMMIT_CLOCK.reset(token)

    ledger_module._now = stable_now
    ledger_cls._receipt = stable_receipt
    ledger_cls.commit_delta = commit_delta
    ledger_module._RECEIPT_IDEMPOTENCY_INSTALLED = True
