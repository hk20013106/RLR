"""legacy — reference-only prototypes, NOT the active runtime.

`research_loop_v03.py` (v0.3 engine) and `rlr_v05b.py` (v0.5b literature-gated
prototype) live here so they are visibly out of the runtime path. No runtime
module (research_loop/*, run_loop.py, research_loop_v04.py) imports this package;
only `test_rlr_v05b.py` imports `legacy.rlr_v05b` to characterize the prototype.
See README.md. The active engine is `research_loop.engine` (CLI: run_loop.py /
python research_loop_v04.py).
"""
