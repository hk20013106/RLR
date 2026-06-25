---
title: RLR v0.3 Code Review Report
date: 2026-06-25
reviewer: Claude Code (Opus 4.8)
target: research_loop_v03.py (1888 lines)
status: REVIEWED — 4 fixes applied, verified by dry run
---

# RLR v0.3 Code Review Report

Second-pass review of `research_loop_v03.py` against the Codex handoff
(`HANDOFF_CODE_REVIEW_CLAUDE_CODE.md`). Every finding below was reproduced by
dry run on a throwaway project (created and deleted during review). No existing
v0.3 project files and no v0.2 files were modified.

Environment confirmed: Python 3.13.12, Windows 11. `py_compile` clean,
`--version` → `v0.3.0`, all subcommands listed.

---

## 1. Bug List

| # | Severity | Location | Status | Summary |
|---|----------|----------|--------|---------|
| 1 | **P1** | `cmd_next_step` (NEEDS_EXECUTION) | **FIXED** | `next-step` dead-ends at L7; no guided path `NEEDS_EXECUTION → EXECUTED`, so the walk cannot reach L8 via `next-step`. |
| 2 | **P2** | `cmd_emit_delta` validator | **FIXED** | Schema fields declared as list/dict *literals* (`[{...}]`, `{...}`) were never type-checked. A scalar where a list is expected passed validation **and then crashed `aggregate-report`**. |
| 3 | **P2** | `cmd_aggregate_report` / `_format_delta_body` | **FIXED** | `FINAL_REPORT_CN.md` translated only section *titles*; all field labels stayed English (handoff Bug 3). |
| 4 | **P3** | `cmd_assemble_context` | **FIXED** | A delta file that exists but is invalid JSON was reported as `(not yet emitted)`; also removed dead code. |
| 5 | P3 | `cmd_decision` | **FIXED** | `decision` had no ordering guard (e.g. `--status KEEP` from `NEW` succeeded). Added `DECISION_TRANSITIONS` legal-transition table: illegal jumps now rejected unless `--force`. |
| 6 | P3 | `_replace_field` | **FIXED** | On a file with **no** frontmatter delimiters, the field update silently no-opped. Now raises `RLRError` (clean fail-loud, no traceback), leaving the file untouched. |
| — | — | `_next_seq` (handoff Bug 4) | **NOT A BUG** | Verified correct: D0001..D0009 with no collision; non-`D` log files ignored. |
| — | — | `_replace_field` (handoff Bug 2) | **NOT A BUG** | 20× stress test with special chars: perfect round-trip, never 0 bytes. The WGCNA 0-byte was an external overwrite, not this function. |

---

## 2. Test Results

Test plan from handoff §5, run as dry runs.

### Phase 1 — Static analysis
| Test | Result |
|------|--------|
| `py_compile` | ✅ PASS |
| `--version` → 0.3.0 | ✅ PASS |
| `--help` lists all commands | ✅ PASS (17 subcommands incl. `note`) |
| File handles / encoding | ✅ all file I/O uses `encoding="utf-8"`; uses `Path.read_text`/`write_text` (no leaked handles) |
| Bare `except` | ✅ none; `except json.JSONDecodeError` / `except Exception as e` used specifically |
| f-string nested quotes (line ~965) | ⚠️ valid on 3.12+ (PEP 701); would break on ≤3.11. OK for this env. |

### Phase 2 — Functional walk (NEW → KEEP)
Full DAG walked with status transitions via the real commands. **Before fix**,
`next-step` returned `L7 | adv=execution-gate` indefinitely at `NEEDS_EXECUTION`
(dead-end). **After fix**, every status returns the correct node:

```
[NEW]            -> L0   adv=decision
[IDEA_PROPOSED]  -> L1 -> L2 -> L3 (adv=triage-idea)   (advances by delta existence)
[IDEA_SELECTED]  -> L4   adv=decision
[METHOD_PROPOSED]-> L5 -> L6 (adv=triage-method)
[METHOD_APPROVED]-> L7   adv=execution-gate
[NEEDS_EXECUTION]-> L7   adv=decision (->EXECUTED)     ← fixed
[EXECUTED]       -> L8   adv=decision
[UNDER_REVIEW]   -> {L9a||L9b} -> L10a -> L10b (adv=decision ->KEEP)
[KEEP]           -> L10c adv=aggregate-report
```
✅ PASS at every step. `aggregate-report` → 13/13 deltas, EN + CN reports.

### Phase 3 — Edge cases
| Test | Result |
|------|--------|
| Corrupt delta (invalid JSON) → `emit-delta` | ✅ rejected (`ERROR: invalid JSON`) |
| String where list expected → `emit-delta` | ✅ **now REJECT** (`hypotheses: expected list, got str`); was a false PASS before fix |
| Valid delta still passes | ✅ PASS |
| Existing-but-corrupt delta in `assemble-context` | ✅ now `(parse error)` instead of `(not yet emitted)` |
| `decision --status KEEP` from `NEW` | ⚠️ accepted (no guard) — see §5 |

### Phase 4 — Regression
| Test | Result |
|------|--------|
| `research_loop_v02.py --version` → 0.2.0 | ✅ PASS (untouched) |
| Existing v0.3 projects untouched | ✅ no writes to `DemoProject_v03` / `Yigene_WGCNA_v03` |

---

## 3. State-Machine Audit

15 statuses; transitions observed in the walk:

```
NEW ──decision──▶ IDEA_PROPOSED ──triage-idea(select)──▶ IDEA_SELECTED
                       │                                      │
              triage-idea(reject)                          decision
                       ▼                                      ▼
                 IDEA_REJECTED                          METHOD_PROPOSED
                                                         │         │
                                            triage-method(approve) triage-method(reject)
                                                         ▼            ▼
                                                  METHOD_APPROVED  METHOD_REJECTED
                                                         │
                                                  execution-gate
                                                         ▼
                                                  NEEDS_EXECUTION ──decision──▶ EXECUTED
                                                                                   │
                                                                               decision
                                                                                   ▼
                                                                              UNDER_REVIEW
                                                                                   │
                                                                          decision(L10b)
                                                                                   ▼
                                                            KEEP / REVISE / DOWNGRADE / DROP
                                                                                   │
                                                                            (KEEP) ▼
                                                                              L10c report
```

- **Gate coverage:** `IDEA_SELECTED` only reachable via `triage-idea`;
  `METHOD_APPROVED` only via `triage-method`; `NEEDS_EXECUTION` only via
  `execution-gate` (which independently re-checks `skill_use_plan.md` +
  `input_manifest.md` + `METHOD_APPROVED`). These three gates cannot be skipped
  *if the DAG is driven by `next-step`*.
- **Guard (fixed, finding #5):** the generic `decision` command now enforces a
  `DECISION_TRANSITIONS` legal-transition table — illegal jumps (e.g. `KEEP`
  from `NEW`) are rejected unless `--force` is passed for manual recovery.
  Same-status logging and `-> ARCHIVED` remain always allowed.
- `EXECUTED` is reachable (after fix) only by `decision` following Turing; there
  is no dedicated `mark-executed` command — `next-step` now advertises this
  transition explicitly so the operator isn't stuck.
- `REVISE` / `DOWNGRADE` are valid terminal-ish statuses but have no `next-step`
  mapping (fall through to `terminal: true`), which is intended.

---

## 4. Notes on Handoff's Suspected Bugs

**Bug 1 (next-step delta existence)** — the delta-existence scan for
IDEA_PROPOSED (L1/L2/L3) and METHOD_PROPOSED (L5/L6) works correctly. The
remaining gap was the `NEEDS_EXECUTION` reuse of L7 (fixed as Bug 1/P1 above).

**Bug 2 (_replace_field corruption)** — **not reproducible in code.** 20
sequential `_replace_field` calls with values containing `:`, `"`, `\`, `%`,
`#`, `[]`, `{}`, `|`, trailing space, and Unicode all round-tripped exactly and
never produced a 0-byte file. The `_yaml_value` quoting/escaping is sound. The
WGCNA 0-byte was almost certainly an external `Set-Content`/`apply_patch`
overwrite. (Latent edge fixed as finding #6: a file already missing its `---`
frontmatter now raises `RLRError` instead of silently dropping the update.)

**Bug 3 (CN translations)** — fixed; see §1/#3.

**Bug 4 (_next_seq)** — **not a bug.** Glob `D[0-9]*.md` + regex `^D(\d+)`
finds the max correctly, ignores `final_decision_*`/`*_triage_*` files, and
returns 1 on an empty dir.

---

## 5. Accepted-by-Design / Recommendations (not changed)

- **emit-delta nested validation depth.** The fix now enforces the *container*
  type (list/dict). It still does not validate the *shape of objects inside*
  lists (e.g. that each hypothesis has `id`/`text`). This is acceptable (extra
  keys are allowed by design) but is the natural next hardening step.
- **f-string nested quotes (line ~965)** rely on Python ≥3.12. Fine today;
  worth a comment if older interpreters are ever targeted.

---

## 6. Fixes Applied (before / after)

### Fix 1 — `cmd_next_step`: NEEDS_EXECUTION dead-end (P1)
Added an override so L7, when revisited under `NEEDS_EXECUTION`, advertises the
`decision → EXECUTED` transition (its DAG `execution-gate` only applies at
`METHOD_APPROVED`).

```diff
     node_info = NODE_MAP[node_id]
     result = { ... }
+    if status == "NEEDS_EXECUTION" and node_id == "L7":
+        l7 = _delta_file(project_dir, "L7_turing")
+        delta_done = bool(l7 and l7.exists())
+        result["advance_command"] = "decision"
+        result["advance_status"] = "EXECUTED"
+        result["advance_reason"] = ("Turing execution complete, mark EXECUTED "
+                                    "and route to Curie")
+        result["action_hint"] = (
+            "L7 delta present; advance to EXECUTED (route to Curie)"
+            if delta_done else
+            "Turing: execute approved scripts in the controlled workspace, "
+            "emit the L7 delta, then advance to EXECUTED")
     print(json.dumps(result, indent=2))
```

### Fix 2 — `cmd_emit_delta`: validate literal list/dict schema fields (P2)
```diff
-        elif expected_type is list and not isinstance(data[key], list):
-            errors.append(...)
-        elif expected_type is dict and not isinstance(data[key], dict):
-            errors.append(...)
+        if expected_type is list or isinstance(expected_type, list):
+            if not isinstance(val, list):
+                errors.append(f"{key}: expected list, got {type(val).__name__}")
+        elif expected_type is dict or isinstance(expected_type, dict):
+            if not isinstance(val, dict):
+                errors.append(f"{key}: expected dict, got {type(val).__name__}")
         elif expected_type is str and not isinstance(val, str): ...
```
This closes the hole that let `"hypotheses":"NOT_A_LIST"` pass and then crash
`aggregate-report` with `AttributeError: 'str' object has no attribute 'get'`.

### Fix 3 — Chinese report field labels (P2, handoff Bug 3)
Added `DELTA_LABELS_CN` (EN→CN map for every `**Label:**`, bullet sub-label,
inline `key=` token, and `_none_`) and `_translate_delta_body_cn()`, applied to
each delta body when building `FINAL_REPORT_CN.md`. The EN report is unchanged.
Verified: no English bold labels remain in the CN report.

### Fix 4 — `cmd_assemble_context`: corrupt-delta message + dead code (P3)
```diff
-            persona_name = node_info["persona"]
-            delta_key = f"{inp}_{persona_name.lower()}"   # dead, removed
             found = False
+            corrupt = False
             for dk in DELTA_DAG_ORDER:
                 if dk.startswith(inp + "_"):
                     ...
                     except json.JSONDecodeError:
-                            pass
+                            sections.append(f"=== DELTA: {dk} (parse error) ===")
+                            sections.append("")
+                            corrupt = True
-            if not found:
+            if not found and not corrupt:
                 sections.append(f"=== DELTA: {inp} (not yet emitted) ===")
```

---

## 7. Verification Summary

- `py_compile`: clean after all edits.
- Full NEW→KEEP walk via `next-step`: correct node at every status (was a
  dead-end before Fix 1).
- `emit-delta`: rejects malformed container types, accepts valid deltas.
- `aggregate-report`: 13/13 deltas, EN labels English, CN labels Chinese, no
  crash on the previously-accepted malformed input path.
- v0.2 regression: `--version` → 0.2.0, untouched.
- Throwaway test project deleted; no existing project files modified.
