# legacy/ — reference only, not runtime

These files are **prototypes retained for reference and characterization tests**.
They are **not** part of the active runtime and must not be presented as the
current engine. Full history is in git.

| File | What it was | Superseded by |
|------|-------------|---------------|
| `rlr_v05b.py` | v0.5b literature-gated DAG prototype (L4a/L4b split); its deep-research gate was promoted into the canonical engine | `research_loop/engine.py::_audit_pre_research`, enforced by `assemble-context` |

## Active runtime (use this)

```
python run_loop.py run PROJECT CAND        # canonical loop entry point
python research_loop_v04.py <cmd>          # compat shim -> research_loop.cli:main
```

The engine lives at `research_loop/engine.py`; the stable in-process interface is
`research_loop.api.EngineAPI`.

## Isolation contract

No runtime module imports `legacy/` — verified by grep in Phase 6 and guarded by
`tests/test_no_cycles.py` (the intra-repo import graph never reaches `legacy.*`
from a runtime module). The only importer is `test_rlr_v05b.py`, which imports
`legacy.rlr_v05b` to exercise the prototype's own DAG. `rlr_v05b.py` still does
`import research_loop_v04 as rl` (reference→runtime is fine; runtime→legacy is not).
