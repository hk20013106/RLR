"""research_loop: modular v0.9 engine package."""

# Load the provider/runtime module first, then install the focused L4 method
# evidence extension.  Consumers continue to import ``research_loop.deep_research``
# through the same stable module object.
from research_loop import deep_research as deep_research
from research_loop.method_evidence import install as _install_method_evidence

_install_method_evidence(deep_research)

del _install_method_evidence
