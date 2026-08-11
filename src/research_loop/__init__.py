"""research_loop: modular v0.9 engine package."""

# Install focused extensions on stable module objects before CLI modules import
# their functions and schemas.
from research_loop import deep_research as deep_research
from research_loop.source_payload_integrity import (
    install as _install_source_payload_integrity,
)
from research_loop.method_evidence import install as _install_method_evidence
from research_loop.method_evidence_compat import install as _install_method_evidence_compat
from research_loop import method_review_navigation as _review_navigation
from research_loop.method_navigation_compat import install as _install_navigation_compat
from research_loop.review_status_compat import install as _install_review_status_compat
from research_loop.user_sources import registered_sources as _registered_sources

_install_source_payload_integrity(deep_research)
_install_method_evidence(deep_research)
_install_method_evidence_compat(deep_research)
deep_research.registered_sources = _registered_sources
_review_navigation._REVIEW_TYPES.update({
    "systematic review", "meta-analysis", "meta analysis", "review/meta-analysis",
})
_install_navigation_compat(_review_navigation)
_review_navigation.install(deep_research)
_install_review_status_compat(deep_research)

# The historical staged pipeline and provenance validators remain installed for
# compatibility. Native v2.1 L4 runs are intercepted after those boundaries by
# l4_evidence_bundle. Historical profiles retain their original provider path.
from research_loop import l4_pipeline as _l4_pipeline_module
from research_loop.l4_pipeline import install as _install_l4_pipeline
from research_loop.l4_pipeline_compat import install as _install_l4_pipeline_compat
from research_loop import l4_lineage as _l4_lineage_module
from research_loop import l4_provenance as _l4_provenance_module
from research_loop.l4_provenance import install as _install_l4_provenance
from research_loop.l4_provenance_compat import (
    install as _install_l4_provenance_compat,
)
from research_loop.l4_path_safety import install as _install_l4_path_safety
from research_loop.l4_lineage import install as _install_l4_lineage
from research_loop.l45_context_binding import install as _install_l45_context_binding
from research_loop import l4_inventory as _l4_inventory_module
from research_loop import l4_method_registry as _l4_method_registry_module
from research_loop.l4_registry_projection_integrity import (
    install as _install_l4_registry_projection_integrity,
)
from research_loop.l4_inventory_projection import (
    install as _install_l4_inventory_projection,
)
from research_loop import l4_evidence_bundle as _l4_evidence_bundle_module
from research_loop.l4_evidence_bundle import install as _install_l4_evidence_bundle
from research_loop.l4_runtime_compat import install as _install_l4_runtime_compat

_install_l4_pipeline(deep_research)
_install_l4_pipeline_compat(_l4_pipeline_module, deep_research)
_install_l4_provenance(
    _l4_pipeline_module,
    deep_research,
    _l4_lineage_module,
)
_install_l4_provenance_compat(
    _l4_pipeline_module,
    _l4_provenance_module,
)
_install_l4_path_safety(_l4_pipeline_module, deep_research)
_install_l4_registry_projection_integrity(
    _l4_method_registry_module,
    _l4_inventory_module,
)
_install_l4_inventory_projection(_l4_inventory_module, deep_research)
_install_l4_evidence_bundle(_l4_pipeline_module, deep_research)
_install_l4_runtime_compat(deep_research, _l4_evidence_bundle_module)
_install_l4_lineage(deep_research)
_install_l45_context_binding(_l4_pipeline_module)

# Provider observability is installed after all scientific Deep Research/L4
# wrappers so it supervises the final runtime boundary without changing their
# contracts, validators, persistence, or authority.
from research_loop import deep_research_task as _deep_research_task_module
from research_loop.provider_runtime_observability import (
    install as _install_provider_runtime_observability,
)
from research_loop.provider_runtime_compat import (
    install as _install_provider_runtime_compat,
)

_install_provider_runtime_observability(deep_research, _deep_research_task_module)
_install_provider_runtime_compat(
    deep_research, _deep_research_task_module, _l4_pipeline_module
)

from research_loop import hypothesis_contracts as hypothesis_contracts
from research_loop.method_contracts import install as _install_method_contracts
from research_loop.hypothesis_reactivation_contracts import (
    install as _install_reactivation_contracts,
)

_install_method_contracts(hypothesis_contracts)
_install_reactivation_contracts(hypothesis_contracts)

from research_loop import hypothesis_ledger as hypothesis_ledger
from research_loop import constraint_validation as _constraint_validation
from research_loop.ledger_receipt_idempotency import (
    install as _install_receipt_idempotency,
)
from research_loop.hypothesis_reactivation import (
    install as _install_hypothesis_reactivation,
)
from research_loop.hypothesis_reactivation_constraints import (
    install as _install_reactivation_constraints,
)
from research_loop.conditional_skip_constraints import (
    install as _install_conditional_skip_constraints,
)
from research_loop.hypothesis_reactivation_compat import (
    install as _install_reactivation_compat,
)

_install_receipt_idempotency(hypothesis_ledger)
_install_hypothesis_reactivation(hypothesis_ledger)
_install_reactivation_constraints(hypothesis_ledger)
_install_conditional_skip_constraints(hypothesis_ledger, _constraint_validation)
_install_reactivation_compat(hypothesis_ledger, _constraint_validation)

from research_loop import topology as topology
from research_loop.topology_extensions import install as _install_topology_extensions

_install_topology_extensions(topology)

from research_loop.commands import lifecycle as _lifecycle
from research_loop.commands import ledger as _ledger_commands
from research_loop import context as _context
from research_loop.conditional_routing import install as _install_conditional_routing
from research_loop.hypothesis_recall_context import (
    install as _install_hypothesis_recall_context,
)
from research_loop.l45_ledger import install as _install_l45_ledger

_install_l45_ledger(_ledger_commands)
_install_conditional_routing(_lifecycle, _context)
_install_hypothesis_recall_context(_context, _ledger_commands)

# CLI extensions are installed only after the canonical CLI module has defined
# its parser and main entry point. Importing research_loop.cli therefore returns
# the same stable module object with additive commands registered.
from research_loop import cli as _cli
from research_loop.hypothesis_pool_cli import install as _install_hypothesis_pool_cli

_install_hypothesis_pool_cli(_cli)

del _install_source_payload_integrity
del _install_method_evidence, _install_method_evidence_compat
del _review_navigation, _install_navigation_compat
del _install_review_status_compat, _registered_sources
del _install_l4_pipeline, _install_l4_pipeline_compat
del _install_l4_provenance, _install_l4_provenance_compat
del _install_l4_path_safety, _install_l4_lineage
del _install_l4_registry_projection_integrity
del _install_l4_inventory_projection, _install_l4_evidence_bundle
del _install_l4_runtime_compat, _install_l45_context_binding
del _install_provider_runtime_observability, _install_provider_runtime_compat
del _deep_research_task_module
del _l4_pipeline_module, _l4_lineage_module
del _l4_provenance_module, _l4_inventory_module
del _l4_method_registry_module, _l4_evidence_bundle_module
del _install_method_contracts, _install_reactivation_contracts
del _install_receipt_idempotency, _install_hypothesis_reactivation
del _install_reactivation_constraints, _install_conditional_skip_constraints
del _install_reactivation_compat
del _install_topology_extensions, _install_l45_ledger
del _install_conditional_routing, _install_hypothesis_recall_context
del _install_hypothesis_pool_cli
del _constraint_validation, _lifecycle, _ledger_commands, _context, _cli
