<!-- Generated: 2026-07-08 | Re-verification after CLAUDE.md rule update -->

# Re-Verification Report: research_loop Architecture

**Trigger:** User flagged that Claude's first-pass codemap (backend.md, since merged into backend_combine.md) understated the codebase vs. Hermes's numbers. Root cause: `tokensave_context` was queried against an index scoped to `D:\skills` (2962 files, mixed languages) rather than `D:\research_loop` (9 Python modules). Every query returned irrelevant matches; rather than falling back to direct file reads, LOC and module lists were estimated from partial `Read` calls.

**Fix applied:** Added a mandatory rule to `~/.claude/CLAUDE.md` — "Verify tokensave scope before trusting its results" — requiring `tokensave_status` scope check before trusting `tokensave_context`/`tokensave_search`, with a fallback to direct `wc -l`/`grep -n`/`Read` when scope doesn't match.

**This document:** Re-ran the analysis using real `wc -l` and `grep -n`, no estimates.

---

## Step 1: tokensave scope check (per new rule)

```
tokensave_status → file_count: 2962, files_by_language: {Python: 110, JavaScript: 392, ...}
```

Target project (`D:\research_loop`) has 9 core Python modules. 2962 files spanning JS/Rust/Swift/etc. confirms the index covers `D:\skills`, not the target. **Per rule: fall back to direct verification.**

## Step 2: Real line counts (`wc -l`)

```
   4843  research_loop_v04.py
    863  run_loop.py
    399  orchestrator.py
    448  pitfall_ledger.py
     79  ars_card_adapter.py
    243  manage_literature_db.py
    555  sync_to_obsidian.py
    559  rlr_v05b.py
   2433  research_loop_v03.py
  10422  total
```

**Result: matches Hermes's figures exactly** (research_loop_v04.py=4843, run_loop.py=863, orchestrator.py=399, pitfall_ledger.py=448, ars_card_adapter.py=79). Claude's first pass had estimated ~1500 / ~600 / ~300 / ~400 respectively — all understated, ars_card_adapter.py and sync_to_obsidian.py omitted entirely.

## Step 3: Real gate function locations (`grep -n "^def _audit_"`)

```
823:  def _audit_dir(project_dir):
888:  def _audit_pre_research(project_dir, node_id, pr_cfg):
3968: def _audit_branch_coverage(project_dir, cand_id):
4061: def _audit_divergence(project_dir, node_id, cand_id):
4095: def _audit_l10_traceability(project_dir, cand_id, delta):
4126: def _audit_l7_manifest(project_dir, cand_id, delta):
4174: def _audit_l6_traceability(project_dir, cand_id, delta):
4208: def _audit_l4_methods(project_dir, cand_id, delta):
4237: def _audit_l0_memory(project_dir, cand_id, delta):
```

**Result: matches Hermes's line numbers exactly** (888, 4061, 4095, 4126, 4174, 4208, 4237). Claude's first pass gave these only as concepts with no line numbers.

## Step 4: Real CLI command count (`grep -c "add_parser("`)

```
29 subcommands registered
```

Hermes listed 13 (a curated subset, not "all commands"). Claude's first pass listed 0. Full 29 includes: demo, new-project, preflight, check-deps, new-candidate, next-step, assemble-context, emit-delta, route, note, triage-idea, triage-method, execution-gate, prepare-turing-workspace, decision, emit-loop-memory, branch-status, modality-scan, aggregate-report, pre-research, audit-pre-research, obsidian-sync, list, show, record-pitfall + 4 more (list-pitfalls, pitfall-scan, and 2 others not individually confirmed in this pass — flagging as unconfirmed rather than guessing).

---

## Verdict

| Metric | Claude (1st pass, tokensave-only) | Hermes | Claude (2nd pass, wc-l/grep-n) |
|--------|-----------------------------------|--------|----------------------------------|
| research_loop_v04.py LOC | ~1500 (estimate) | 4843 | **4843 (verified)** |
| run_loop.py LOC | ~600 (estimate) | 863 | **863 (verified)** |
| Gate function line numbers | not given | given, exact | **verified exact match** |
| ars_card_adapter.py / sync_to_obsidian.py | omitted | 79 / 555 | **79 / 555 (verified)** |
| CLI command count | 0 (not attempted) | 13 (curated) | **29 (verified count, full list mostly confirmed)** |

**Conclusion:** the gap in the first pass was not model capability — it was skipping verification when the exploration tool's results were clearly off-scope, and filling the gap with estimates instead of a direct file read. The new CLAUDE.md rule closes this: tokensave scope must be checked before trusting its output, with mandatory fallback to `wc -l`/`grep -n`/`Read` when scope doesn't match. This re-run, done with the rule applied, reproduces Hermes's ground-truth numbers exactly.

