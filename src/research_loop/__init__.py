"""research_loop: modular v0.9 engine package."""

# Install focused extensions on stable module objects before CLI modules import
# their functions and schemas.
from research_loop import deep_research as deep_research
from research_loop.method_evidence import install as _install_method_evidence
from research_loop.method_evidence_compat import install as _install_method_evidence_compat
from research_loop.method_review_navigation import install as _install_review_navigation
from research_loop.user_sources import registered_sources as _registered_sources

_install_method_evidence(deep_research)
_install_method_evidence_compat(deep_research)
deep_research.registered_sources = _registered_sources
_install_review_navigation(deep_research)

from research_loop import hypothesis_contracts as hypothesis_contracts
from research_loop.method_contracts import install as _install_method_contracts

_install_method_contracts(hypothesis_contracts)

from research_loop import topology as topology
from research_loop.topology_extensions import install as _install_topology_extensions

_install_topology_extensions(topology)

from research_loop.commands import lifecycle as _lifecycle
from research_loop import context as _context
from research_loop.conditional_routing import install as _install_conditional_routing

_install_conditional_routing(_lifecycle, _context)

del _install_method_evidence, _install_method_evidence_compat
del _install_review_navigation, _registered_sources
del _install_method_contracts, _install_topology_extensions
del _install_conditional_routing, _lifecycle, _context
