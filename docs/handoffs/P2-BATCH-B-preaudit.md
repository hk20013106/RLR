# P2-BATCH-B Symbol Boundary Pre-Audit Report

> Pre-extraction boundary audit for **P2-BATCH-B**: extraction of **RANKING**, **PITFALL**, and **REPORTING** command families from `src/research_loop/engine.py`.
> Generated on 2026-07-25 against working tree branch `rlr/p2b-preaudit`.
> **Status:** Pre-audit complete. No production code modified. Extraction NOT started.

---

## 1. Overview & Extraction Scope

Batch B extracts three independent CLI command families out of `src/research_loop/engine.py` into dedicated subpackage command modules under `src/research_loop/commands/`:

1. `src/research_loop/commands/ranking.py` (RANKING family - 20 symbols)
2. `src/research_loop/commands/pitfall.py` (PITFALL family - 5 symbols)
3. `src/research_loop/commands/reporting.py` (REPORTING family - 6 symbols)

All extracted symbols will be re-exported from `src/research_loop/engine.py` via inward shims to maintain complete backward compatibility with `research_loop_v04.py` and existing test suites.

---

## 2. Family-by-Family Symbol Boundary Audit

### 2.1 RANKING Family

The RANKING family comprises 20 symbols (19 functions and 1 class) located between line 2964 and line 3419 in `src/research_loop/engine.py`.

| # | Symbol Name | Line Range | Imported Leaf Modules / Dependencies Used | References `_SyntheticPositionBiasedJudge` | Referenced Directly by Tests | Notes |
|---|---|---|---|---|---|---|
| 1 | `_read_ranking_delta` | L2964-L2972 | `research_loop.delta` (`_delta_for_candidate`), `json`, `pathlib.Path` | No | Indirectly via `cmd_ranking_shadow` | Delta reader for candidate ranking |
| 2 | `_ranking_candidates` | L2975-L2997 | `research_loop.ranking`, `research_loop.paths` (`_candidate_file`), `research_loop.common` (`_sha256`), `_read_ranking_delta` | No | Indirectly via `cmd_ranking_shadow` | Candidate snapshot extractor |
| 3 | `_ranking_formal_decisions` | L3000-L3025 | `research_loop.common` (`_sha256`), `_read_ranking_delta` | No | Indirectly via `cmd_ranking_shadow` | Extracts formal L10 decisions |
| 4 | `_ranking_advisory_records` | L3028-L3054 | `research_loop.ranking` | No | Indirectly via `cmd_ranking_shadow` | Extracts advisory ranking records |
| 5 | `_validate_ranking_resume_provenance` | L3057-L3065 | Builtins (`ValueError`) | No | Indirectly via `cmd_ranking_shadow` | Validates checkpoint provenance |
| 6 | `_ranking_judge` | L3068-L3077 | `research_loop.providers` (`ProviderConfig`, `ProviderError`, `make_provider`), `research_loop.ranking` | No | **Yes** (`tests/test_ranking_cli.py` L57, L103, L116 monkeypatches `engine._ranking_judge`) | **Re-export critical** for test patching |
| 7 | `_ranking_events` | L3080-L3095 | `json`, `pathlib.Path` | No | Indirectly via `cmd_ranking_shadow` | Loads ranking run events |
| 8 | `_ranking_output_targets` | L3098-L3107 | `re`, `pathlib.Path` | No | Indirectly via `cmd_ranking_shadow` | Computes output file paths |
| 9 | `_write_ranking_complete_marker` | L3110-L3138 | `research_loop.ranking`, `research_loop.common` (`_sha256`), `json`, `os`, `tempfile`, `pathlib.Path` | No | Indirectly via `cmd_ranking_shadow` | Atomic marker writer |
| 10 | `_ranking_write_outputs` | L3141-L3152 | `research_loop.ranking`, `_write_ranking_complete_marker`, `pathlib.Path` | No | Indirectly via `cmd_ranking_shadow` | Writes shadow artifacts |
| 11 | `cmd_ranking_shadow` | L3155-L3230 | `research_loop.providers` (`ProviderError`), `research_loop.hypothesis_ledger` / `_ledger_for`, `research_loop.common` (`_stamp`), ranking helpers (`_ranking_*`) | No | **Yes** (`tests/test_ranking_cli.py`, `tests/test_ranking_runner_hook.py` via `engine.main(["ranking-shadow", ...])`) | CLI handler |
| 12 | `_SyntheticPositionBiasedJudge` | L3233-L3250 | Builtins (`random`, `seed`) | **Defined Here** (Class Definition) | Indirectly via `_naive_benchmark` / `cmd_ranking_benchmark` | Benchmark synthetic judge fixture. Per P2-RANKING-BOUNDARY, moves with `commands/ranking.py`. |
| 13 | `_ranking_accuracy` | L3253-L3258 | Builtins (`sum`, `len`, `min`) | No | Indirectly via `cmd_ranking_benchmark` | Benchmark accuracy metric |
| 14 | `_naive_benchmark` | L3261-L3281 | `_SyntheticPositionBiasedJudge` (L3266) | **Yes** (L3266) | Indirectly via `cmd_ranking_benchmark` | Naive position-biased benchmark baseline |
| 15 | `_average` | L3284-L3285 | Builtins (`sum`, `len`) | No | Indirectly via `cmd_ranking_benchmark` | Arithmetic mean helper |
| 16 | `_fair_false_first_win_rate` | L3288-L3292 | Builtins (`sum`, `len`) | No | Indirectly via `cmd_ranking_benchmark` | Benchmark win rate metric |
| 17 | `_load_benchmark_gold` | L3295-L3313 | `research_loop.ranking`, `json`, `pathlib.Path` | No | Indirectly via `cmd_ranking_benchmark` | Gold evidence loader |
| 18 | `cmd_ranking_benchmark` | L3316-L3384 | `_SyntheticPositionBiasedJudge` (L3343), `_naive_benchmark`, `_average`, `_fair_false_first_win_rate`, `_load_benchmark_gold`, `_ranking_accuracy`, `pathlib.Path` | **Yes** (L3343) | **Yes** (`tests/test_ranking_cli.py` via `engine.main(["ranking-benchmark", ...])`) | CLI handler |
| 19 | `_validate_ranking_report_artifact` | L3387-L3400 | `research_loop.ranking` | No | Indirectly via `cmd_ranking_report` | Report artifact schema validator |
| 20 | `cmd_ranking_report` | L3403-L3419 | `research_loop.ranking`, `_validate_ranking_report_artifact`, `json`, `re`, `sys`, `pathlib.Path` | No | **Yes** (`tests/test_ranking_cli.py` via `engine.main(["ranking-report", ...])`) | CLI handler |

---

### 2.2 PITFALL Family

The PITFALL family comprises 5 CLI command handlers located between line 2865 and line 2959 in `src/research_loop/engine.py`. All 5 functions are thin CLI wrappers over the `pitfall_ledger.py` logic leaf module (imported as `pl`).

| # | Symbol Name | Line Range | Imported Leaf Modules / Dependencies Used | References `_SyntheticPositionBiasedJudge` | Referenced Directly by Tests | Notes |
|---|---|---|---|---|---|---|
| 1 | `cmd_record_pitfall` | L2865-L2882 | `pitfall_ledger` (`pl`), `sys`, `ValueError` | No | Indirectly via CLI dispatch (`test_pitfall_ledger.py` tests `pl` directly) | CLI handler for recording runtime pitfalls |
| 2 | `cmd_list_pitfalls` | L2885-L2902 | `pitfall_ledger` (`pl`), `json` | No | Indirectly via CLI dispatch | CLI handler for filtering and listing pitfalls |
| 3 | `cmd_pitfall_scan` | L2905-L2931 | `pitfall_ledger` (`pl`), `json`, `sys` | No | Indirectly via CLI dispatch | CLI handler for scanning active pitfalls / hard-stop gate |
| 4 | `cmd_pitfall_status` | L2934-L2943 | `pitfall_ledger` (`pl`), `sys`, `KeyError`, `ValueError` | No | Indirectly via CLI dispatch | CLI handler for L8 Curie status confirmation |
| 5 | `cmd_promote_pitfall` | L2946-L2959 | `pitfall_ledger` (`pl`), `sys`, `KeyError`, `ValueError` | No | Indirectly via CLI dispatch | CLI handler for rule promotion |

---

### 2.3 REPORTING Family

The REPORTING family comprises 6 symbols (4 CLI handlers and 2 internal helper functions) located in two line ranges in `src/research_loop/engine.py` (L2486-L2524 and L2743-L2860).

| # | Symbol Name | Line Range | Imported Leaf Modules / Dependencies Used | References `_SyntheticPositionBiasedJudge` | Referenced Directly by Tests | Notes |
|---|---|---|---|---|---|---|
| 1 | `cmd_list` | L2486-L2502 | `research_loop.yamlio` (`_load_yaml_front`), `pathlib.Path` | No | Indirectly via CLI dispatch / snapshot tests | Lists project candidates |
| 2 | `cmd_show` | L2505-L2514 | `research_loop.paths` (`_candidate_file`), `sys`, `pathlib.Path` | No | Indirectly via CLI dispatch / snapshot tests | Displays candidate contents |
| 3 | `cmd_obsidian_sync` | L2518-L2524 | `sync_to_obsidian` | No | **Yes** (`tests/test_obsidian_sync.py` via `engine.main(["obsidian-sync", ...])`) | Syncs deltas to Obsidian vault |
| 4 | `_shared_report_owner` | L2743-L2748 | `re`, `pathlib.Path` | No | Indirectly via `cmd_aggregate_report` | Extracts report owner from markdown header |
| 5 | `_update_reports_index` | L2751-L2756 | `pathlib.Path` | No | Indirectly via `cmd_aggregate_report` | Updates `00_Index.md` reports table |
| 6 | `cmd_aggregate_report` | L2759-L2860 | `research_loop.paths` (`_candidate_file`), `research_loop.yamlio` (`_load_yaml_front`), `research_loop.delta` (`_delta_for_candidate`), `research_loop.delta_render` (`SECTION_TITLES_EN`, `SECTION_TITLES_CN`, `_translate_delta_body_cn`, `_format_delta_body`), `research_loop.topology` (`DELTA_DAG_ORDER`, `DELTA_PERSONA`), `research_loop.common` (`_now`), `_shared_report_owner`, `_update_reports_index`, `pathlib.Path` | No | **Yes** (`tests/test_public_api_compat.py` pinned as `REQUIRED_CALLABLE`, `tests/test_v06_divergence.py`, `tests/test_engine_api.py`) | **Re-export critical** for `test_public_api_compat.py` |

---

## 3. Boundary Verifications

### 3.1 Verification against P1A-Owned Files (`hypothesis_ledger.py`)

- **Result:** **ZERO OVERLAP CONFIRMED.**
- **Details:** `hypothesis_ledger.py` (P1A) owns the SQLite ledger storage engine, schema definitions, migration handlers, and canonical JSON encoding. None of the 31 Batch B symbols are defined in or modify `hypothesis_ledger.py`.
- `cmd_ranking_shadow` and `cmd_aggregate_report` call `_ledger_for` / read project files as standard callers of the ledger interface, maintaining clean consumer-to-service decoupling.

### 3.2 Verification against P2-BATCH-A Extracted Files (`common.py`, `templates.py`, `delta_render.py`)

- **Result:** **ZERO OVERLAP CONFIRMED.**
- **Details:**
  - `common.py` owns general utility helpers (`_slug`, `_now`, `_stamp`, `_sha256_file`, `_mkdirs`, etc.).
  - `templates.py` owns markdown document template generators (`_candidate_template`, `_handoff_template`, etc.).
  - `delta_render.py` owns delta formatting and localization constants/functions (`SECTION_TITLES_EN`, `SECTION_TITLES_CN`, `_translate_delta_body_cn`, `_format_delta_body`).
- None of the 31 Batch B symbols exist in or overlap with these Batch A leaf files.
- `cmd_aggregate_report` imports formatting constants and functions from `delta_render.py` and `_now` from `common.py`. `_write_ranking_complete_marker` imports `_sha256` from `common.py`. These are clean leaf imports.

---

## 4. Required Leaf Module Imports for Batch B Target Modules

When extracting Batch B into the `src/research_loop/commands/` subpackage, each module must import the following dependencies:

### 4.1 Target `src/research_loop/commands/ranking.py`
```python
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from research_loop import common as _common
from research_loop import delta as _delta
from research_loop import paths as _paths
from research_loop import providers as _providers
from research_loop import ranking as _ranking
from research_loop.common import _sha256, _stamp
from research_loop.delta import _delta_for_candidate
from research_loop.paths import _candidate_file
from research_loop.providers import ProviderConfig, ProviderError, make_provider
# For ledger interaction in cmd_ranking_shadow:
from research_loop.engine import _ledger_for # or commands/ledger if extracted
```

### 4.2 Target `src/research_loop/commands/pitfall.py`
```python
import json
import sys

import pitfall_ledger as pl
```

### 4.3 Target `src/research_loop/commands/reporting.py`
```python
import re
import sys
from pathlib import Path

import sync_to_obsidian
from research_loop.common import _now
from research_loop.delta import _delta_for_candidate
from research_loop.delta_render import (
    DELTA_LABELS_CN,
    SECTION_TITLES_CN,
    SECTION_TITLES_EN,
    _format_delta_body,
    _translate_delta_body_cn,
)
from research_loop.paths import _candidate_file
from research_loop.topology import DELTA_DAG_ORDER, DELTA_PERSONA
from research_loop.yamlio import _load_yaml_front
```

---

## 5. Summary & Handoff Checklist for Batch B Extraction

- [x] **RANKING family symbols mapped:** 20 symbols (L2964-L3419) cataloged.
- [x] **PITFALL family symbols mapped:** 5 symbols (L2865-L2959) cataloged.
- [x] **REPORTING family symbols mapped:** 6 symbols (L2486-L2524, L2743-L2860) cataloged.
- [x] **`_SyntheticPositionBiasedJudge` audited:** Confirmed referenced ONLY by `_naive_benchmark` (L3266) and `cmd_ranking_benchmark` (L3343). Moves to `commands/ranking.py` as part of the RANKING family.
- [x] **P1A overlap verified:** 0 symbols overlap.
- [x] **P2-BATCH-A overlap verified:** 0 symbols overlap.
- [x] **Test patching points identified:** `tests/test_ranking_cli.py` monkeypatches `research_loop.engine._ranking_judge`. `tests/test_public_api_compat.py` pins `cmd_aggregate_report`. All extracted symbols MUST be re-exported from `src/research_loop/engine.py`.
