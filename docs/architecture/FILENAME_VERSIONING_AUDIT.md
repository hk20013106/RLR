# Filename Versioning Audit

Audit scope: every file and directory in the standalone repository whose name
matches `_v03`, `_v04`, `_v05`, `_v05b`, `v03_`, `v04_`, `v05_`, `V03`, `V04`,
or `V05` patterns.

| Current path | Recommended path | Classification | References | Compatibility impact | Recommended action |
|---|---|---|---|---|---|
| `research_loop_v04.py` | keep temporarily; converge on `src/run_loop.py` | COMPATIBILITY_SHIM | CLI/help tests and historical docs | Existing users may invoke the old entry point | Keep deprecated shim; remove in a later breaking-change PR |
| `src/research_loop_v04.py` | keep temporarily; converge on package API | COMPATIBILITY_SHIM | historical compatibility tests | Preserves import compatibility | Keep deprecated shim with removal plan |
| `legacy/rlr_v05b.py` | keep in `legacy/` | LEGACY_SNAPSHOT | `tests/test_rlr_v05b.py` imports it | Characterization tests require the module | Retain; no active runtime imports |
| `templates/v03_layers/` | `templates/layers/` | LEGACY_TEST_FIXTURE | historical/template migration references | Old template consumers may depend on names | Do not rename in this PR; evaluate in a dedicated compatibility PR |
| `templates/v03_personas/` | `templates/personas/` | LEGACY_TEST_FIXTURE | historical/template migration references | Old template consumers may depend on names | Do not rename in this PR; evaluate in a dedicated compatibility PR |
| `templates/v05b/` | keep under templates until retired | LEGACY_TEST_FIXTURE | legacy template consumers and historical docs | Existing v0.5b template paths may be external inputs | Retain for compatibility; do not rename in this PR |
| `docs/RLR_V05B_README.md` | `docs/archive/RLR_V05B_README.md` | HISTORICAL_DOCUMENT | documentation links | Moving it would change links | Defer to a documentation-only PR |
| `docs/V05_SPLIT_PLAN.md` | `docs/archive/V05_SPLIT_PLAN.md` | HISTORICAL_DOCUMENT | handoff/history links | Moving it would change links | Defer to a documentation-only PR |
| `tests/test_rlr_v05b.py` | keep until compatibility is retired | LEGACY_TEST_FIXTURE | imports `legacy.rlr_v05b` | Guards legacy behavior | Retain with explicit legacy label |
| `tests/test_v05_gate.py` | keep until v0.5 gate compatibility is retired | LEGACY_TEST_FIXTURE | v0.5 gate characterization | Guards compatibility behavior | Retain; no rename in this PR |
| `tests/test_v06_divergence.py` | keep; rename only with test-suite policy change | LEGACY_TEST_FIXTURE | v0.6 divergence-contract characterization | Guards the existing divergence contract | Retain; no rename in this PR |
| `docs/superpowers/plans/2026-07-06-v06-divergence-contract.md` | `docs/archive/` in a later docs PR | HISTORICAL_DOCUMENT | historical design record | Links may be consumed by handoffs | Defer move; leave content unchanged |
| `docs/superpowers/specs/2026-07-06-v06-divergence-contract-design.md` | `docs/archive/` in a later docs PR | HISTORICAL_DOCUMENT | historical design record | Links may be consumed by handoffs | Defer move; leave content unchanged |
| `docs/architecture_reviews/v07-codex-independent-review.md` | keep as dated review | HISTORICAL_DOCUMENT | review record | None | Keep; the version labels describe the reviewed architecture |

No active runtime file should be renamed solely to encode a release version.
`legacy/research_loop_v03.py` is intentionally absent; references to it are
historical text only and point to Git history rather than a present file.

No bulk rename is performed by PR #2.
