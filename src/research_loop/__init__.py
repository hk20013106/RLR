"""research_loop: modular v0.9 engine package."""

# Install focused extensions on stable module objects before CLI modules import
# their functions and schemas.
from research_loop import deep_research as deep_research
from research_loop.method_evidence import install as _install_method_evidence
from research_loop.method_evidence_compat import install as _install_method_evidence_compat
from research_loop import method_review_navigation as _review_navigation
from research_loop.method_navigation_compat import install as _install_navigation_compat
from research_loop.review_status_compat import install as _install_review_status_compat
from research_loop.user_sources import registered_sources as _registered_sources

_install_method_evidence(deep_research)
_install_method_evidence_compat(deep_research)
deep_research.registered_sources = _registered_sources
_review_navigation._REVIEW_TYPES.update({
    "systematic review", "meta-analysis", "meta analysis", "review/meta-analysis",
})
_install_navigation_compat(_review_navigation)
_review_navigation.install(deep_research)
_install_review_status_compat(deep_research)

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

_install_receipt_idempotency(hypothesis_ledger)
_install_hypothesis_reactivation(hypothesis_ledger)
_install_reactivation_constraints(hypothesis_ledger)
_install_conditional_skip_constraints(hypothesis_ledger, _constraint_validation)

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

_install_conditional_routing(_lifecycle, _context)
_install_hypothesis_recall_context(_context, _ledger_commands)

# CLI extensions are installed only after the canonical CLI module has defined
# its parser and main entry point. Importing research_loop.cli therefore returns
# the same stable module object with additive commands registered.
from research_loop import cli as _cli
from research_loop.hypothesis_pool_cli import install as _install_hypothesis_pool_cli

_install_hypothesis_pool_cli(_cli)

del _install_method_evidence, _install_method_evidence_compat
del _review_navigation, _install_navigation_compat
del _install_review_status_compat, _registered_sources
del _install_method_contracts, _install_reactivation_contracts
del _install_receipt_idempotency, _install_hypothesis_reactivation
del _install_reactivation_constraints, _install_conditional_skip_constraints
del _install_topology_extensions, _install_conditional_routing
del _install_hypothesis_recall_context, _install_hypothesis_pool_cli
del _constraint_validation, _lifecycle, _ledger_commands, _context, _cli
