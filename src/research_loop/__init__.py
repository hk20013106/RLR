"""research_loop: modular v0.9 engine package."""

# Install focused extensions on the stable module objects before CLI modules
# import their functions and schemas.
from research_loop import deep_research as deep_research
from research_loop.method_evidence import install as _install_method_evidence

_install_method_evidence(deep_research)

from research_loop import hypothesis_contracts as hypothesis_contracts
from research_loop.method_contracts import install as _install_method_contracts

_install_method_contracts(hypothesis_contracts)

del _install_method_evidence, _install_method_contracts
