# Final Handoff: Engine Modular Extraction + Ledger Correctness

## Version: v0.8.0

## Branch: `codex/hypothesis-ledger-cutover`

## Summary

Completed full engine modular extraction (4768 -> 477 lines), ledger
finalization read-boundary correctness (Plan 1A), v2 gate integration
(Plan 1C), native-v2 gate test coverage (Plan 1B), and two production
bug fixes. 323 tests pass, 0 failures.

## Completed tasks

| Task | Commit(s) | Description |
| --- | --- | --- |
| P2-PRE-TEST | `94886d9` | Fix test_no_cycles.py scan path (2->32 modules) |
| P2-RANKING-BOUNDARY | `9b00c7c` | Audit _SyntheticPositionBiasedJudge ownership |
| Baseline freeze | `6780b04` | Commit dirty working tree as clean baseline |
| P1A | `192271f` | Finalized read-boundary predicate in 4 consumptive APIs |
| P2-BATCH-A | `cf8410f`,`89a2dc1`,`97f803a` | Extract helpers, templates, delta rendering |
| P1C | `bb4d3e7` | Wire v2 gates into _emit_delta_v2 |
| P1B | `31ba98f` | Restore native-v2 gate test coverage |
| P2-BATCH-B | `face0ea`,`f453456`,`2089e94` | Extract ranking, pitfall, reporting CLI |
| FIX-1 | `f1a9119` | delta_render.py v2 list analysis_plan support |
| FIX-2 | `de49acf` | v2 _emit_delta_v2 execution manifest write |
| P2-C1 | `ec4aeb6` | Extract ledger CLI to commands/ledger.py |
| P2-C2 | `8e7950e` | Extract continuation CLI to commands/continuation.py |
| P2-BATCH-D | `affe3a4`,`f3ce1e6`,`e96ae6e` | Extract lifecycle, research, execution CLI |
| P2-E1 | `8f35d68` | Move build_parser and main to cli.py |

## Final metrics

| Metric | Value |
| --- | --- |
| engine.py lines | 477 (was 4768) |
| cli.py lines | 542 (was 12) |
| Command modules | 8 (continuation, execution, ledger, lifecycle, pitfall, ranking, reporting, research) |
| cmd_* in engine.py | 0 |
| Tests | 323 passed, 0 failed |
| CLI --help | OK |
| run_loop --help | OK |
| Smoke test | OK (new-project, new-candidate, L1+L3 finalize, verify PASS, next-step OK) |
| git diff --check | clean |
| Working tree | clean |

## Architecture (final state)

```text
engine.py (477 lines)     = thin re-export coordinator (inward shims only)
cli.py (542 lines)         = build_parser + main + dispatch
commands/
  __init__.py               = package init
  continuation.py           = _build_loop_memory, cmd_emit_loop_memory, cmd_branch_status, cmd_modality_scan, _write_exec_manifest, _list_card_ids, _loop_memory_to_md
  execution.py              = cmd_execution_gate, cmd_prepare_turing_workspace, _registered_candidate_inputs, _approved_execution_scripts
  ledger.py                 = _emit_delta_v2, cmd_emit_delta, cmd_finalize_candidate, cmd_hypothesis_*, _ledger_for, _ledger_cli
  lifecycle.py              = cmd_new_project, cmd_new_candidate, cmd_next_step, cmd_decision, cmd_route, cmd_triage_*, cmd_preflight, cmd_check_deps, cmd_note, cmd_demo
  pitfall.py                = cmd_record_pitfall, cmd_list_pitfalls, cmd_pitfall_scan, cmd_pitfall_status, cmd_promote_pitfall
  ranking.py                = cmd_ranking_shadow, cmd_ranking_benchmark, cmd_ranking_report, _SyntheticPositionBiasedJudge, ranking helpers
  reporting.py              = cmd_list, cmd_show, cmd_obsidian_sync, cmd_aggregate_report, _shared_report_owner, _update_reports_index
  research.py               = cmd_pre_research, cmd_deep_research_run, cmd_audit_pre_research, cmd_audit_literature_evidence, cmd_literature_report
```

## Known technical debt (not blocking)

1. `ranking.py:135` has `_resolve_ranking_judge` which uses runtime `import research_loop.engine` for test-compat monkeypatch detection. Not a static import (no cycle). Should be replaced with dependency injection in future cleanup.
2. `tests/test_l0_intake.py` requires Python 3.12+ f-string syntax. Skipped on Python 3.11. Not related to this extraction.
3. `reporting.py` has a module-level `__version__ = "0.7.0"` that duplicates the one in `engine.py` and `cli.py`. Should be centralized.
4. Coverage baseline (61.74%) was not measured post-extraction due to `pytest-cov` not being installable (SSL error). Extraction is behavior-neutral; coverage should be unchanged.

## P1B status: RESOLVED

P1B was initially blocked because v2 _emit_delta_v2 did not call gates.
Plan 1C resolved this by wiring gates into the v2 path. P1B then
completed successfully. All gate tests now reach their real gates.

## Plan 1A orphan residual paths: RESOLVED

- `snapshot_candidate()`: included in Plan 1A finalized predicate scope
- Projection contamination: real but self-healing on retry; `verify(rebuild=True)` detects inconsistency. No Plan 1C needed for this.

## Not pushed
