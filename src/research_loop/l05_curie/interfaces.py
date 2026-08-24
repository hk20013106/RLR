"""Provider-neutral interfaces for L0.5 evidence acquisition."""
from __future__ import annotations

from typing import Protocol


class DiscoveryTransport(Protocol):
    """Deterministic discovery adapter; cognitive planning lives outside it."""

    def handshake(self) -> dict:
        """Return a DiscoveryTransport/v1 capability handshake."""
        ...

    def search(self, request: dict) -> dict:
        """Return one normalized, receipt-bound discovery batch."""
        ...


class EvidenceRetriever(Protocol):
    """Source-text retrieval engine such as a future PaperQA2 adapter."""

    def retrieve(self, *, paper: dict, question: str) -> list[dict]:
        """Return candidate L05EvidenceExtract/v1 records for verification."""
        ...
