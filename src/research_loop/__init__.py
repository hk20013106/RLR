"""research_loop: modular v0.9 engine package."""

# Install focused extensions on stable module objects before CLI modules import
# their functions and schemas.
from research_loop import deep_research as deep_research
from research_loop.method_evidence import install as _install_method_evidence
from research_loop.method_evidence_compat import install as _install_method_evidence_compat

_install_method_evidence(deep_research)
_install_method_evidence_compat(deep_research)

from research_loop import hypothesis_contracts as hypothesis_contracts
from research_loop.method_contracts import install as _install_method_contracts

_install_method_contracts(hypothesis_contracts)

from research_loop.commands import lifecycle as _lifecycle
from research_loop import context as _context
from research_loop.conditional_routing import install as _install_conditional_routing

_install_conditional_routing(_lifecycle, _context)

del _install_method_evidence, _install_method_evidence_compat
del _install_method_contracts, _install_conditional_routing, _lifecycle, _context
