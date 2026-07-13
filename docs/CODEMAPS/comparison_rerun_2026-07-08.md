<!-- Generated: 2026-07-08 (new session) | Re-run trigger: tokensave install --local --agent claude completed prior session; this session verifies scope + re-derives codemap -->

# Re-run Comparison: New Session Codemap vs Hermes vs Prior Claude Passes

## Step 1: tokensave scope verification

```
tokensave_status → file_count: 91, files_by_language: {Other: 63, Python: 28}
active_branch: v0.6 (was "not tracked, serving from main" until this session ran
  `tokensave branch add v0.6` → 1 added, 0 modified, 0 removed)
```

91 files / 28 Python matches project scale (prior session's local install reported ~90/28).
**Not** the D:\skills 2962-file index. Scope confirmed correct — proceeded without fallback-only mode.

`tokensave_context` was still usable for code (not just docs) once `path_include`/`path_exclude`
filters excluded `docs/CODEMAPS/*.md` — first call surfaced markdown headers before that filter
was added, second call (path_include: [".py"]) correctly returned real code symbols
(`build_parser` in research_loop_v04.py:4531, run_loop.py:820, rlr_v05b.py:524, matching real
file sizes). Used 2 of the 3-call budget; remainder of verification done via direct `grep -n`/`wc -l`
per the standing CLAUDE.md rule (belt-and-suspenders, not because tokensave was wrong this time).

## Step 2: Real LOC re-verification (`wc -l`, this session)

| File | verification_rerun.md (2026-07-08, prior session) | This session | Match |
|------|------|------|-------|
| research_loop_v04.py | 4843 | 4843 | Yes |
| run_loop.py | 863 | 863 | Yes |
| orchestrator.py | 399 | 399 | Yes |
| pitfall_ledger.py | 448 | 448 | Yes |
| ars_card_adapter.py | 79 | 79 | Yes |
| manage_literature_db.py | 243 | 243 | Yes |
| sync_to_obsidian.py | 555 | 555 | Yes |
| rlr_v05b.py | 559 (from backend_combine.md, not in prior wc-l list) | 559 | Yes |
| research_loop_v03.py | not re-verified prior session ("~2600" estimate from Hermes/backend_combine.md) | **2433 (real)** | **No — correction** |

**Finding:** `research_loop_v03.py` was carried as Hermes's `~2600` estimate (hedged with `~`) into
`backend_combine.md` without independent verification. Real count is **2433**, an 8% overstatement.
Small, but it means even Hermes's numbers need the same "verify before trusting" treatment — the
prior fix wasn't "trust Hermes blindly," it was "verify against real files," and this is the one
spot that slipped through unverified.

## Step 3: Previously undocumented files (found via `git status` untracked list + `Glob **/*.py`)

None of these appear with a real LOC figure in any prior codemap. `backend_cc.md`'s dependency
graph names `rebuild_deltas.py` and `deep_extract_deltas.py` as boxes with no LOC; `extract_deltas.py`
and `extract_deltas_v2.py` aren't mentioned anywhere.

| File | LOC (`wc -l`, verified) | Role (from git status / naming) |
|------|------|------|
| `rebuild_deltas.py` | 342 | Delta recovery (named in backend_cc.md dependency graph, previously unquantified) |
| `deep_extract_deltas.py` | 110 | Post-hoc delta mining (named in backend_cc.md, previously unquantified) |
| `extract_deltas.py` | 81 | Delta extraction utility — **not in any prior codemap** |
| `extract_deltas_v2.py` | 71 | Delta extraction utility v2 — **not in any prior codemap** |

All four are untracked in git (`?? ` status) as of this session's start — working-tree scratch
utilities, not yet committed. Included here for completeness since they're real, present files;
flagged as untracked so it's clear they aren't part of the committed v0.6 baseline.

## Step 4: CLI subcommand list — resolves prior "unconfirmed" gap

`verification_rerun.md` counted 29 subcommands via `grep -c` but only named 25, flagging
`pitfall-status`, `promote-pitfall`, and 2 unnamed others as "not individually confirmed."
This session extracted the full list via `grep -oP 'add_parser\("([a-z0-9_-]+)"'`:

```
demo, new-project, preflight, check-deps, new-candidate, next-step, assemble-context,
emit-delta, route, note, triage-idea, triage-method, execution-gate,
prepare-turing-workspace, decision, emit-loop-memory, branch-status, modality-scan,
aggregate-report, pre-research, audit-pre-research, obsidian-sync, list, show,
record-pitfall, list-pitfalls, pitfall-scan, pitfall-status, promote-pitfall
```

29 confirmed, all named. The 2 previously-unnamed commands are `pitfall-status` and
`promote-pitfall` (both pitfall-ledger CLI ops, consistent with the ledger's draft-to-confirmed
lifecycle already documented).

## Step 5: DAG topology / persona count — verified by direct read (not grep)

Read `DAG_NODES` list literal in `research_loop_v04.py` (lines ~114-300+) directly. Confirms:
- **15 nodes**: L0, L1, L2, L3, L4, L5, L6, L7, L8, L8.5, L9a, L9b, L10a, L10b, L10c
- **10 unique personas**: Linnaeus (L0, L10c), Einstein (L1), Feynman (L2, L9a), Oppenheimer
  (L3, L6, L10b), Fisher (L4), Tukey (L5), Turing (L7), Curie (L8, L8.5), Darwin (L9b), Jobs (L10a)

Matches both Claude's and Hermes's prior "15 nodes / 10 personas" claims exactly — no correction
needed here.

## Step 6: Gate function line numbers — re-verified, unchanged

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

Identical to `verification_rerun.md` and `backend_hermes.md`. No drift since 2026-07-07/08 —
the recent commits (`L10b decision-traceability gate`, `L7 execution-traceability manifest + gate`,
`branch-status + modality-scan ledger commands`, `candidate-scoped aggregate-report` fix) were
already reflected in those docs; this re-run confirms nothing moved after them.

---

## 一致之处 (Agreement)

Everything in `comparison_claude_vs_hermes.md`'s "一致之处" section still holds: architecture
overview, 15 DAG nodes, 10 personas, Path A/B/C separation, pre-research fail-closed gate,
core module identity, hard invariants. This session adds independent re-verification, not new
agreement — no changes needed to that section.

## 不一致之处 (Disagreements) — one new item

The version-baseline / LOC-estimate gap documented previously is **closed** (Claude's 2nd-pass
numbers matched Hermes exactly, per `verification_rerun.md`). This session found exactly one new
discrepancy: **`research_loop_v03.py`: Hermes said `~2600`, real is `2433`** (see Step 2). Everything
else in `backend_hermes.md` / `architecture_hermes.md` / `dependencies_hermes.md` matches real
numbers exactly on re-check.

## 互补之处 (Complementary)

Unchanged from `comparison_claude_vs_hermes.md`: `backend_cc.md`'s coupling analysis remains the
one Hermes has no equivalent for (coupling matrix, circular-dependency proof, hot-spot/refactor
roadmap, coupling scores). This session adds one more complementary item: the **4 utility-script
LOC figures** (Step 3) that neither Hermes nor prior Claude passes quantified.

## 冲突矛盾 (True Conflicts)

**One, minor:** `research_loop_v03.py` LOC (`~2600` vs real `2433`, 8% off). Everything else:
zero conflicts, consistent with the prior finding.

---

## Verdict

Prior session's fix (verify tokensave scope, fall back to `wc -l`/`grep -n` on mismatch) held up:
this session's independent re-run reproduces the same ground-truth numbers for every previously-
verified figure, resolves the CLI-list gap (29/29 named), and surfaces 4 real files + 1 real
correction that no prior pass caught. Feeds into `backend_final.md`.
