"""L0.5 Curie: auditable evidence acquisition between L0 and L1."""
from .contracts import (
    COVERAGE_DECISION_SCHEMA_VERSION,
    DISCOVERY_BATCH_SCHEMA_VERSION,
    DISCOVERY_TRANSPORT_SCHEMA_VERSION,
    EVIDENCE_EXTRACT_SCHEMA_VERSION,
    EVIDENCE_PACK_MANIFEST_SCHEMA_VERSION,
    EVIDENCE_PACK_SCHEMA_VERSION,
    GAP_REQUEST_SCHEMA_VERSION,
    MAX_ACQUISITION_ROUNDS,
    QUERY_PLAN_SCHEMA_VERSION,
    CurieContractError,
    build_gap_request,
    judge_coverage,
    validate_coverage_decision,
    validate_discovery_batch,
    validate_evidence_extract,
    validate_gap_request,
    validate_query_plan,
    validate_transport_handshake,
)
from .interfaces import DiscoveryTransport, EvidenceRetriever

# Install optional semantic-admission validation on the canonical store before
# any public or downstream module captures its build/freeze/load functions.
from . import store as _store
from .semantic_pack import install as _install_semantic_pack
_install_semantic_pack(_store)
from .store import (
    build_evidence_pack,
    freeze_evidence_pack,
    load_frozen_evidence_pack,
    next_pack_version,
    render_evidence_context,
)
from .bridge import freeze_l1_deep_research_run
from .gap_loop import (
    AUTH_SCHEMA_VERSION,
    CONSUMPTION_SCHEMA_VERSION,
    authorize_gap_retry,
    consume_gap_retry_authorization,
    load_open_gap_request,
    open_gap_request,
)

del _install_semantic_pack, _store

__all__ = [
    "AUTH_SCHEMA_VERSION",
    "CONSUMPTION_SCHEMA_VERSION",
    "COVERAGE_DECISION_SCHEMA_VERSION",
    "DISCOVERY_BATCH_SCHEMA_VERSION",
    "DISCOVERY_TRANSPORT_SCHEMA_VERSION",
    "EVIDENCE_EXTRACT_SCHEMA_VERSION",
    "EVIDENCE_PACK_MANIFEST_SCHEMA_VERSION",
    "EVIDENCE_PACK_SCHEMA_VERSION",
    "GAP_REQUEST_SCHEMA_VERSION",
    "MAX_ACQUISITION_ROUNDS",
    "QUERY_PLAN_SCHEMA_VERSION",
    "CurieContractError",
    "DiscoveryTransport",
    "EvidenceRetriever",
    "authorize_gap_retry",
    "build_evidence_pack",
    "build_gap_request",
    "consume_gap_retry_authorization",
    "freeze_evidence_pack",
    "freeze_l1_deep_research_run",
    "judge_coverage",
    "load_frozen_evidence_pack",
    "load_open_gap_request",
    "next_pack_version",
    "open_gap_request",
    "render_evidence_context",
    "validate_coverage_decision",
    "validate_discovery_batch",
    "validate_evidence_extract",
    "validate_gap_request",
    "validate_query_plan",
    "validate_transport_handshake",
]
