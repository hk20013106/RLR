"""legacy — reference-only prototypes, NOT the active runtime.

`rlr_v05b.py` is retained here because its compatibility behavior is explicitly
characterized by `test_rlr_v05b.py`. No runtime module (research_loop/*,
run_loop.py, research_loop_v04.py) imports this package. The active engine is
`research_loop.engine` (CLI: run_loop.py / python research_loop_v04.py).
"""
