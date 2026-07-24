# Implementation Plan: `engine.py` Staged Modular Extraction (Phase 3 continuation)

> Scope: continue the **already-established, test-guarded strangler-fig migration**
> that reduces `src/research_loop/engine.py` (4768 lines, 42 `cmd_*` handlers)
> to a thin residual coordinator. Behavior-preserving only - **no CLI behavior,
> no gate semantics, no ledger logic changes** in this plan. Plan only; no
> production code is modified by this document.
>
> **Sequencing:** this plan is **Plan 2**. It runs after
> [`ledger-finalization-read-boundaries.md`](./ledger-finalization-read-boundaries.md)
> (Plan 1A + 1B) has landed and stabilized. Plan 1A/1B and Batch A may run in
> parallel after P2-PRE. See
> [`hermes-multi-agent-ledger-engine-plan.md`](./hermes-multi-agent-ledger-engine-plan.md)
> §5 for the full dependency graph.
>
> **Source of truth:** [`engine-symbol-manifest.md`](./engine-symbol-manifest.md)
> is the authoritative symbol inventory. Line numbers in this document are
> guides; symbol-level ownership is authoritative.

## Real structure (verified 2026-07-24 against current working tree)

### `engine.py` measurements

| Metric | Value |
| --- | --- |
| Total lines | 4768 |
| `cmd_*` handlers | 44 |
| Top-level functions/classes | 103 |
| Inward shims already present | 12 |
| `from research_loop.*` imports | 14 |

### `cmd_*` handler inventory (verified by grep)

| Handler | Line | Family |
| --- | --- | --- |
| `cmd_next_step` | 893 | lifecycle |
| `cmd_pre_research` | 1037 | research |
| `cmd_audit_pre_research` | 1409 | research |
| `cmd_deep_research_run` | 1467 | research |
| `cmd_audit_literature_evidence` | 1515 | research |
| `cmd_literature_report` | 1522 | research |
| `_ledger_for` | 1549 | ledger (private) |
| `_write_hypothesis_commit_receipt` | 1562 | ledger (private) |
| `_emit_delta_v2` | 1577 | ledger (private) |
| `cmd_emit_delta` | 1629 | ledger |
| `cmd_new_project` | 1934 | lifecycle |
| `cmd_new_candidate` | 1963 | lifecycle |
| `cmd_normalize_l0_input` | 2174 | lifecycle |
| `cmd_preflight` | 2266 | lifecycle |
| `cmd_check_deps` | 2356 | lifecycle |
| `cmd_note` | 2399 | lifecycle |
| `cmd_demo` | 2428 | lifecycle |
| `cmd_decision` | 2504 | lifecycle |
| `cmd_route` | 2556 | lifecycle |
| `cmd_triage_idea` | 2583 | lifecycle |
| `cmd_triage_method` | 2639 | lifecycle |
| `cmd_finalize_candidate` | 2695 | ledger |
| `cmd_hypothesis_show` | 2733 | ledger |
| `cmd_hypothesis_history` | 2746 | ledger |
| `cmd_hypothesis_search` | 2759 | ledger |
| `cmd_hypothesis_verify` | 2767 | ledger |
| `cmd_hypothesis_migrate` | 2781 | ledger |
| `cmd_hypothesis_authorize_context` | 2808 | ledger |
| `cmd_execution_gate` | 2824 | execution |
| `cmd_prepare_turing_workspace` | 2937 | execution |
| `cmd_list` | 3075 | reporting |
| `cmd_show` | 3094 | reporting |
| `cmd_obsidian_sync` | 3107 | reporting |
| `cmd_aggregate_report` | 3609 | reporting |
| `cmd_record_pitfall` | 3715 | pitfall |
| `cmd_list_pitfalls` | 3735 | pitfall |
| `cmd_pitfall_scan` | 3755 | pitfall |
| `cmd_pitfall_status` | 3784 | pitfall |
| `cmd_promote_pitfall` | 3796 | pitfall |
| `cmd_ranking_shadow` | 4005 | ranking |
| `cmd_ranking_benchmark` | 4166 | ranking |
| `cmd_ranking_report` | 4253 | ranking |
| `cmd_branch_status` | 3532 | continuation |
| `cmd_modality_scan` | 3548 | continuation |
| `cmd_emit_loop_memory` | 3560 | continuation |
| `build_parser` | 4274 | dispatch |
| `main` | 4737 | dispatch |

### Already-extracted logic leaves

| Module | Lines | Inward shim in engine |
| --- | --- | --- |
| `topology.py` | 240 | L62 |
| `paths.py` | 62 | L149 |
| `delta.py` | 226 | L166 |
| `common.py` | 42 | L67 |
| `preresearch.py` | 172 | L91, L424 |
| `gates.py` | 259 | L429 |
| `context.py` | 735 | L464 |
| `ranking.py` | 504 | (used, not shimmed) |
| `deep_research.py` | 515 | (used, not shimmed) |
| `l0_contract.py` | 409 | (used, not shimmed) |
| `l0_intake.py` | 157 | (used, not shimmed) |
| `yamlio.py` | 52 | L458 |
| `ledger.py` | 43 | L3387 |
| `errors.py` | 4 | L56 |
| `hypothesis_ledger.py` | 1228 | (used, not shimmed) |
| `hypothesis_contracts.py` | 271 | (used, not shimmed) |
| `hypothesis_migration.py` | 311 | (used, not shimmed) |
| `providers/` | 6 files | (used, not shimmed) |

### `research_loop_v04.py` compatibility mechanism (verified)

31 lines. PEP 562 `__getattr__` delegates every attribute lookup to
`research_loop.engine`. No name enumeration - `rl.cmd_x`, `rl._private_helper`,
`rl.CONSTANT` all resolve to `engine.<name>`. This means the engine must
continue to expose (by re-import) every name it exposes today.

### `cli.py` current state (verified)

12 lines. Re-exports `build_parser` and `main` from engine. Docstring defers
the `cmd_*` split: *"Splitting the 29 `cmd_*` handlers physically out of the
engine is deferred (strangler-fig); this module is the seam that makes that
later split a drop-in."* (Note: actual count is 44, not 29 - the docstring is
stale.)

### Patch points verified

- `engine.ranking.DeterministicFakeJudge` - `ranking.py:47`, used by
  `engine.py:3920` and `tests/test_ranking_cli.py:183`. Already in the logic
  leaf; engine accesses it via `from research_loop import ranking`.
- `_SyntheticPositionBiasedJudge` - defined **in** `engine.py:4083`. Used only
  within engine (L4113, L4180). **Should move to `ranking.py`** before Batch B
  ranking extraction (see §Prerequisite).
- `_build_loop_memory` - defined in `engine.py:3409`. Imported by
  `tests/native_v2_helpers.py:125` as
  `from research_loop.engine import _build_loop_memory`. **Must be re-exported
  from engine after Batch C extraction** or the test import breaks.
- `tests/test_no_cycles.py` - scans `REPO / "research_loop"` (L32), **not**
  `REPO / "src" / "research_loop"`. The actual package lives under `src/`. This
  means the cycle guard may be **partially vacuous** for the real package path.
  **Must be corrected** before relying on it as an extraction gate.

## The invariant that makes this safe

Every step preserves **one rule**: `engine.py` continues to expose (by
re-import) every name it exposes today. The two shims depend on this:

- `research_loop_v04.__getattr__` -> `getattr(engine, name)` - so `rl.cmd_x`,
  `rl._private_helper`, `rl.CONSTANT` all still resolve.
- `test_public_api_compat` fails the instant a re-export is dropped.
- `test_no_cycles` fails the instant a command module imports back into
  `research_loop.engine` (the forbidden back-edge) - **once corrected to scan
  `src/research_loop`**.

## Prerequisite: split safety-net fix and symbol audit

P2-PRE is split into two independent tasks (see
[`hermes-multi-agent-ledger-engine-plan.md`](./hermes-multi-agent-ledger-engine-plan.md)
§8):

### P2-PRE-TEST (tests only, no production code)

- Correct `test_no_cycles.py` `_local_module_files()` (L26-36) to discover
  `REPO / "src" / "research_loop"` in addition to `REPO / "research_loop"`.
- Verify the test discovers the actual package.
- Separate commit. No production code modified.

### P2-RANKING-BOUNDARY (production symbol audit, separate commit)

- Audit `_SyntheticPositionBiasedJudge` (engine.py:4083).
- **Evidence:** Used only by `_ranking_accuracy` (L4103), `cmd_ranking_benchmark`
  (L4113, L4180). All callers are ranking CLI benchmark functions.
- **Decision:** It is benchmark-specific test-fixture logic, not reusable
  ranking algorithm logic. Move with `commands/ranking.py` in Batch B.
- Do NOT move to `ranking.py` logic leaf unless evidence shows reuse outside
  benchmark CLI.
- Separate commit.

## Target module map (symbol-level, verified against current working tree)

Line ranges are approximate guides only; **symbol-level ownership** is the
source of truth. Overlapping ranges (e.g. lifecycle 874-2504 overlaps research
1037-1548) are resolved by function name, not line number.

| Family | Symbols (engine.py) | Target | Coupling | Notes |
| --- | --- | --- | --- | --- |
| Shared helpers | `_slug`, `_next_seq`, `_require_status`, `_set_status`, `_append_decision`, `_mkdirs`, `_fmt_list`, `_fmt_dict`, `_empty_value_for_schema`, `_sha256_file`, `_load_loop_memory`, `_render_extra_front`; `_port_open`, `_dep_present`, `_dep_fix_hint`, `_parse_declared_deps`, `_check_dependencies` | `common.py` (extend) or new `commands/_helpers.py` | leaf | Batch A |
| Templates | `_knowledge_base_md`, `_dependencies_md`, `_candidate_template`, `_index_template`, `_handoff_template`, `_decision_log_template`, `_note_template`, `_preflight_template` | new `templates.py` | low (pure string) | Batch A |
| Delta rendering | `_translate_delta_body_cn`, `_format_delta_body` + `SECTION_TITLES_EN/CN`, `DELTA_LABELS_CN` | new `delta_render.py` | low | Batch A |
| Ranking CLI | `_read_ranking_delta`, `_ranking_candidates`, `_ranking_formal_decisions`, `_ranking_advisory_records`, `_validate_ranking_resume_provenance`, `_ranking_judge`, `_ranking_events`, `_ranking_output_targets`, `_write_ranking_complete_marker`, `_ranking_write_outputs`, `cmd_ranking_shadow`, `cmd_ranking_benchmark`, `_validate_ranking_report_artifact`, `cmd_ranking_report`, `_ranking_accuracy`, `_naive_benchmark`, `_average`, `_fair_false_first_win_rate`, `_load_benchmark_gold` | new `commands/ranking.py` (over existing logic leaf `ranking.py`) | low-med | Batch B. `_SyntheticPositionBiasedJudge` moves to `ranking.py` first (prerequisite). |
| Pitfall CLI | `cmd_record_pitfall`, `cmd_list_pitfalls`, `cmd_pitfall_scan`, `cmd_pitfall_status`, `cmd_promote_pitfall` | new `commands/pitfall.py` (over `pitfall_ledger.py`) | low | Batch B |
| Reporting / views | `cmd_aggregate_report`, `_shared_report_owner`, `_update_reports_index`; `cmd_list`, `cmd_show`, `cmd_obsidian_sync` | new `commands/reporting.py` | low-med | Batch B |
| Research / context | `cmd_assemble_context`, `cmd_pre_research`, `cmd_audit_pre_research`, `_deep_research_spec_from_args`, `cmd_deep_research_run`, `cmd_audit_literature_evidence`, `cmd_literature_report` | new `commands/research.py` (over `deep_research.py`, `context.py`, `preresearch.py`) | med | Batch D |
| Execution workspace | `cmd_execution_gate`, `_registered_candidate_inputs`, `_approved_execution_scripts`, `cmd_prepare_turing_workspace` | new `commands/execution.py` | med | Batch D |
| **Ledger / emit CLI** | `_ledger_for`, `_write_hypothesis_commit_receipt`, `_emit_delta_v2`, `cmd_emit_delta`, `cmd_finalize_candidate`, `_ledger_cli`, `cmd_hypothesis_show/history/search/verify/migrate/authorize_context` | new `commands/ledger.py` | **med-HIGH - semantically coupled to Plan 1** | Batch C |
| **Continuation / loop memory** | `_build_loop_memory`, `_write_exec_manifest`, `_loop_memory_to_md`, `_list_card_ids`, `cmd_emit_loop_memory`, `cmd_branch_status`, `cmd_modality_scan` | new `commands/continuation.py` | **HIGH - idempotency-sensitive** | Batch C. `_build_loop_memory` is imported by `native_v2_helpers.py:125`; must re-export from engine. |
| Lifecycle | `cmd_new_project`, `cmd_new_candidate`, `_print_intake_failure`, `cmd_normalize_l0_input`, `cmd_preflight`, `cmd_check_deps`, `cmd_note`, `cmd_demo`, `cmd_next_step`, `cmd_decision`, `cmd_route`, `cmd_triage_idea`, `cmd_triage_method`, `_pitfall_warnings_for_node` | new `commands/lifecycle.py` | HIGH | Batch D |
| Dispatch | `build_parser`, `main` | move into existing `research_loop/cli.py` | terminal | Batch E |

Residual constants still defined in engine (`LAYERS` @378, `SECTION_TITLES_*`
@3119/3136, `DELTA_LABELS_CN` @3158, `SEED_SCHEMA_KEYS` @3376, `VALID_STATUSES`,
`FINAL_STATUSES`, `PREFLIGHT_FILES`, `REQUIRED_DEPENDENCIES`) move with their
owning family and are re-exported.

Package shape: add a `research_loop/commands/` subpackage for the CLI wrappers.
This keeps the existing logic-leaf name `research_loop.ranking` distinct from its
CLI wrapper `research_loop.commands.ranking`.

## Per-family dependency analysis

### Helpers (Batch A)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (scattered: 205-293, 399-580) |
| Target module | `common.py` (extend) or new `commands/_helpers.py` |
| Imported dependencies | `topology`, `paths`, `common` (already extracted leaves) |
| Names re-exported through engine | `_slug`, `_next_seq`, `_require_status`, `_set_status`, `_append_decision`, `_mkdirs`, `_fmt_list`, `_fmt_dict`, `_empty_value_for_schema`, `_sha256_file`, `_load_loop_memory`, `_render_extra_front`, `_port_open`, `_dep_present`, `_dep_fix_hint`, `_parse_declared_deps`, `_check_dependencies` |
| Tests covering the family | `test_engine_api.py`, `test_public_api_compat.py` (indirect) |
| Potential cycle/back-edge | None - leaf module |
| Files modified | `engine.py`, `common.py` or new `commands/_helpers.py` |
| Acceptance command | `pytest tests/test_public_api_compat.py tests/test_no_cycles.py tests/test_engine_api.py -q` |
| Rollback unit | Revert engine.py shim + new module file |

### Templates (Batch A)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (294-874) |
| Target module | new `templates.py` |
| Imported dependencies | None (pure string constants) |
| Names re-exported | All template function names |
| Tests | `test_template_contract.py`, `test_template_currentness.py` |
| Potential cycle | None - pure strings |
| Acceptance | `pytest tests/test_template_contract.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` |
| Rollback | Revert engine.py shim + delete `templates.py` |

### Delta rendering (Batch A)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (3119-3401) |
| Target module | new `delta_render.py` |
| Imported dependencies | None (pure string manipulation) |
| Names re-exported | `_format_delta_body`, `_translate_delta_body_cn`, `SECTION_TITLES_EN`, `SECTION_TITLES_CN`, `DELTA_LABELS_CN` |
| Tests | `test_engine_api.py`, CLI snapshot |
| Potential cycle | None |
| Acceptance | `pytest tests/test_engine_api.py tests/test_gate_cli_snapshot.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` |
| Rollback | Revert + delete module |

### Ranking CLI (Batch B)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (3814-4272) |
| Target module | new `commands/ranking.py` (over `ranking.py` logic leaf) |
| Imported dependencies | `ranking` (leaf), `hypothesis_ledger`, `common`/`_helpers`, `topology` |
| Names re-exported | `cmd_ranking_shadow`, `cmd_ranking_benchmark`, `cmd_ranking_report`, `_read_ranking_delta`, `_ranking_candidates`, etc. |
| Tests | `test_ranking_cli.py`, `test_ranking_reliability.py`, `test_ranking_runner_hook.py` |
| Potential cycle | `commands/ranking.py` must NOT import `engine` - use `ranking` leaf directly |
| Prerequisite | Move `_SyntheticPositionBiasedJudge` to `ranking.py` first |
| Acceptance | `pytest tests/test_ranking_cli.py tests/test_ranking_reliability.py tests/test_public_api_compat.py tests/test_no_cycles.py tests/test_engine_api.py tests/test_gate_cli_snapshot.py -q` |
| Rollback | Revert engine.py shim + delete `commands/ranking.py` |

### Pitfall CLI (Batch B)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (3715-3813) |
| Target module | new `commands/pitfall.py` (over `pitfall_ledger.py`) |
| Imported dependencies | `pitfall_ledger`, `common`/`_helpers` |
| Tests | `test_pitfall_ledger.py` |
| Potential cycle | None |
| Acceptance | `pytest tests/test_pitfall_ledger.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` |
| Rollback | Revert + delete module |

### Reporting (Batch B)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (3075-3220, 3593-3714) |
| Target module | new `commands/reporting.py` |
| Imported dependencies | `common`/`_helpers`, `topology`, `yamlio` |
| Tests | `test_engine_api.py`, CLI snapshot |
| Potential cycle | None |
| Acceptance | `pytest tests/test_engine_api.py tests/test_gate_cli_snapshot.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` |
| Rollback | Revert + delete module |

### Ledger CLI (Batch C)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (1549-2823) |
| Target module | new `commands/ledger.py` |
| Imported dependencies | `hypothesis_ledger`, `hypothesis_contracts`, `hypothesis_migration`, `delta`, `common`/`_helpers`, `topology`, `paths` |
| Names re-exported | `_emit_delta_v2`, `cmd_emit_delta`, `cmd_finalize_candidate`, `cmd_hypothesis_show`, `cmd_hypothesis_history`, `cmd_hypothesis_search`, `cmd_hypothesis_verify`, `cmd_hypothesis_migrate`, `cmd_hypothesis_authorize_context`, `_ledger_for`, `_write_hypothesis_commit_receipt`, `_ledger_cli` |
| Tests | `test_hypothesis_ledger.py`, `test_hypothesis_migration.py`, `test_hypothesis_contracts.py`, `test_cross_round_e2e.py` |
| Potential cycle | Must NOT import `engine` - all deps are leaf modules |
| Special | `_emit_delta_v2` calls `commit_delta` + `finalize_emission`; Plan 1A's finalized predicate must be preserved |
| Acceptance | `pytest tests/test_hypothesis_ledger.py tests/test_hypothesis_migration.py tests/test_hypothesis_contracts.py tests/test_cross_round_e2e.py tests/test_v06_divergence.py tests/test_public_api_compat.py tests/test_no_cycles.py tests/test_engine_api.py tests/test_gate_cli_snapshot.py -q` |
| Rollback | Revert + delete module |

### Continuation (Batch C)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (3402-3591) |
| Target module | new `commands/continuation.py` |
| Imported dependencies | `hypothesis_ledger`, `common`/`_helpers`, `topology`, `paths` |
| Names re-exported | `_build_loop_memory`, `_write_exec_manifest`, `_loop_memory_to_md`, `_list_card_ids`, `cmd_emit_loop_memory`, `cmd_branch_status`, `cmd_modality_scan` |
| Tests | `test_cross_round_e2e.py`, `test_candidate_aware_next_step.py`, `test_v06_divergence.py` |
| Potential cycle | Must NOT import `engine` |
| Special | `_build_loop_memory` imported by `native_v2_helpers.py:125` - engine re-export required |
| Acceptance | `pytest tests/test_cross_round_e2e.py tests/test_candidate_aware_next_step.py tests/test_v06_divergence.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` |
| Rollback | Revert + delete module |

### Lifecycle (Batch D)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (874-2504) |
| Target module | new `commands/lifecycle.py` |
| Imported dependencies | `topology`, `context`, `gates`, `l0_contract`, `l0_intake`, `common`/`_helpers`, `paths`, `yamlio`, `preresearch` |
| Tests | `test_engine_api.py`, `test_l0_input_contract.py`, `test_l0_intake.py`, `test_v05_gate.py`, `test_run_loop_guards.py` |
| Potential cycle | Must NOT import `engine` |
| Acceptance | `pytest tests/test_engine_api.py tests/test_l0_input_contract.py tests/test_l0_intake.py tests/test_v05_gate.py tests/test_run_loop_guards.py tests/test_public_api_compat.py tests/test_no_cycles.py tests/test_gate_cli_snapshot.py -q` |
| Rollback | Revert + delete module |

### Research (Batch D)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (1037-1548) |
| Target module | new `commands/research.py` (over `deep_research.py`, `context.py`, `preresearch.py`) |
| Imported dependencies | `deep_research`, `context`, `preresearch`, `common`/`_helpers` |
| Tests | `test_deep_research.py`, `test_context_isolation.py`, `test_pr1_provenance.py`, `test_pr2_gate.py`, `test_pr3_templates.py` |
| Potential cycle | Must NOT import `engine` |
| Acceptance | `pytest tests/test_deep_research.py tests/test_context_isolation.py tests/test_pr1_provenance.py tests/test_pr2_gate.py tests/test_pr3_templates.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` |
| Rollback | Revert + delete module |

### Execution (Batch D)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (2824-3074) |
| Target module | new `commands/execution.py` |
| Imported dependencies | `gates`, `common`/`_helpers`, `topology` |
| Tests | `test_engine_api.py`, `test_turing_workspace_hydration.py` |
| Potential cycle | Must NOT import `engine` |
| Acceptance | `pytest tests/test_engine_api.py tests/test_turing_workspace_hydration.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` |
| Rollback | Revert + delete module |

### Dispatch (Batch E)

| Field | Value |
| --- | --- |
| Current owner | `engine.py` (4274-4768) |
| Target module | move into existing `research_loop/cli.py` |
| Imported dependencies | All command families (via their leaf/command modules) |
| Tests | `test_engine_api.py`, `test_gate_cli_snapshot.py`, `test_public_api_compat.py` |
| Potential cycle | `cli.py` imports command modules -> command modules import leaves. No engine import. |
| Acceptance | `pytest tests/test_engine_api.py tests/test_gate_cli_snapshot.py tests/test_public_api_compat.py tests/test_no_cycles.py -q` + `python research_loop_v04.py --help` + `python run_loop.py --help` |
| Rollback | Revert `cli.py` + restore `build_parser`/`main` in engine |

## Sequencing (limited dual-track parallelism)

```text
                         ┌─ Plan 1A -> Plan 1B ─────────┐
H3 -> P2-PRE ────────────┤                              ├─ SYNC BARRIER
           (safety nets) └─ Plan 2 Batch A ─────────────┘
                                                           ↓
                                              Plan 2 Batch B
                                                           ↓
                                              Plan 2 Batch C (C1 -> C2)
                                                           ↓
                                              Plan 2 Batch D
                                                           ↓
                                              Plan 2 Batch E (E1 -> E2)
```

### Rules

1. **Plan 1A/1B and Batch A may run in parallel** after P2-PRE completes.
   - Plan 1A/1B touches `hypothesis_ledger.py` + test files.
   - Batch A touches `engine.py` + new leaf modules.
   - File sets are disjoint; `engine.py` single-writer rule respected (P1A
     does not touch `engine.py`).
2. **Batch B does NOT parallel Plan 1.**
   - Ranking extraction shares `test_ranking_cli.py` fixture expectations with
     Plan 1A.
   - Plan 1B modifies CLI/gate test baselines.
3. **Batch C waits for**: Plan 1A pass, Plan 1B pass, Batch A pass, Batch B pass.
4. **Sync barrier**: after parallel tracks converge, run a joint regression
   test on the merged snapshot before releasing Batch B.
5. Only Hermes may release parallel tasks, and only when file sets, worktrees,
   and test responsibilities are fully independent.
6. **No unmeasured duration estimates.** Do not claim "30-40% faster" without
   task-timing data.

### Batch task merging

Micro-tasks are merged into batch tasks to reduce handoff and gate overhead:

| Batch | Merged tasks | Internal checkpoints | Handoffs |
| --- | --- | --- | --- |
| Batch A | helpers + templates + delta rendering | 3 local commits | 1 batch handoff |
| Batch B | ranking + pitfall + reporting | 3 local commits | 1 batch handoff |
| Batch C | C1 (ledger) + C2 (continuation) | 2 tasks, separate | 2 handoffs |
| Batch D | lifecycle + research + execution | 3 local commits | 1 batch handoff |
| Batch E | dispatch + final verify | 2 tasks (E1, E2) | 1 handoff |

Each checkpoint runs family tests + Phase-0 nets. Any checkpoint may be
independently rolled back. One verifier gate per batch.

## Implementation steps (per-family loop)

Each family extraction is one reversible commit-sized unit following the same
loop. **Do one family at a time; never batch two families in one edit.**

1. **Green baseline** - run the Phase-0 nets and the family's own suite:
   ```powershell
   rtk proxy python -m pytest tests\test_public_api_compat.py tests\test_no_cycles.py tests\test_engine_api.py -q
   ```
   Plus the family suite. Record counts.

2. **Create the target module** - move the family's functions **verbatim**
   (cut, not copy). Its imports resolve to leaf modules + `commands/_helpers.py`
   only. **Assert it does not import `research_loop.engine`.**

3. **Add the inward shim in engine.py** - replace the moved bodies with a single
   `from research_loop.commands.<family> import (...)  # inward shim (Phase 7x)`
   re-export block, mirroring the 12 existing shim lines.

4. **Move owned constants** with their family; re-export from engine.

5. **Run the nets + family suite again** - `test_public_api_compat`,
   `test_no_cycles`, `test_engine_api`, `test_gate_cli_snapshot`, and the family
   suite must all stay green. If `test_no_cycles` flags a back-edge, a helper
   the command still needs is itself still in engine - extract that helper to a
   leaf first (that's why Batch A precedes B-D).

6. **Full regression at batch end** (not per-family):
   ```powershell
   rtk proxy python -m pytest -q
   rtk proxy python run_loop.py --help
   rtk proxy python research_loop_v04.py --help
   rtk git diff --check
   ```

## Behavior preservation rules (strict)

- **Verbatim extraction only** - cut and paste, no logic changes.
- **No CLI output changes** - `test_gate_cli_snapshot` is the guard.
- **No gate semantics changes** - `gates.py` logic untouched.
- **No ledger protocol changes** - `hypothesis_ledger.py` logic untouched.
- **No parameter default value changes.**
- **No public function renames.**
- **No business logic cleanup** - any behavior bug found during extraction is
  recorded to a separate issue/plan, not fixed in the extraction commit.
- **Each command family is an independent, reversible commit unit.**

## Terminal state

### Preferred terminal state (Plan 2 Definition of Done)

```text
engine.py = thin compatibility/re-export coordinator
  - defines no cmd_* bodies
  - only inward-shim re-exports
  - preserves the current public import surface

cli.py = build_parser + main + dispatch

commands/* = CLI command ownership

logic leaves = domain logic
```

### Optional later state

Retire `engine.py` entirely. Only considered when:
- All direct `from research_loop.engine import ...` in tests and production
  have been migrated to their new owners.
- The compat shim (`research_loop_v04.py` `__getattr__`) is updated to delegate
  to `cli.py` or individual modules.
- API contract allows the rename.

This is **not** part of Plan 2. Plan 2's Definition of Done is the preferred
terminal state above.

## Risks and mitigation

| Risk | Mitigation |
| --- | --- |
| Dropped re-export silently breaks `run_loop.py`/tests | `test_public_api_compat` pins the surface; runs every step. |
| New command module imports engine -> cycle | `test_no_cycles` fails immediately (after correction to scan `src/research_loop`). |
| CLI output drifts (byte-for-byte) | `test_gate_cli_snapshot`, `test_engine_api` are the snapshot net; run per family. |
| Extracting ledger CLI churns Plan 1 lines | Batch C is strictly sequenced after Plan 1A+1B. |
| Continuation idempotency regressed during move | Verbatim move + `test_cross_round_e2e.py` + `test_candidate_aware_next_step.py` in Batch C's family suite. |
| `_build_loop_memory` import path breaks | Re-export from engine after Batch C; assert import binds via `native_v2_helpers.py` test. |
| `_SyntheticPositionBiasedJudge` in engine blocks ranking extraction | Move to `ranking.py` as prerequisite before Batch B. |
| `test_no_cycles.py` scans wrong path | Fix as prerequisite before any extraction. |
| Constant left behind / duplicated | Move constant with its family; grep `engine.py` for stragglers at batch end. |
| Scope creep into logic changes | Each step is a verbatim move; any behavior edit is out of scope. |
| Coverage gate (61.74% < 80%) confused with extraction | Extraction is behavior-neutral; report coverage unchanged. Do not conflate with Plan 1 coverage work. |
| Line ranges overlap between families | Symbol-level ownership manifest resolves overlaps; line ranges are guides only. |

## Definition of Done

- Every batch leaves the full suite green with an auditable count; the Phase-0
  nets (`test_public_api_compat`, `test_no_cycles`) never go red.
- `engine.py` no longer defines `cmd_*` bodies - only inward-shim re-exports.
- No import cycle; `providers/` still never imports the engine.
- `python research_loop_v04.py <cmd>` and `import research_loop_v04 as rl`
  behave byte-for-byte as before (snapshot + api tests prove it).
- `_SyntheticPositionBiasedJudge` lives in `ranking.py`.
- `test_no_cycles.py` scans `src/research_loop`.
- No commit/push unless separately requested; stage only extraction files.
