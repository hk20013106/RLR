---
title: Handoff - RLR v0.3 Code Review and Bug Audit
date: 2026-06-25
author: Codex (GPT-5)
audience: Claude Code
status: READY_FOR_REVIEW
---

# Handoff: RLR v0.3 Code Review and Bug Audit

> This document is self-contained. Read it top to bottom, then start working.
> No prior conversation context required.

---

## 1. What You Are Reviewing

Research Loop Room (RLR) v0.3 is a DAG-driven subagent coordination framework
for scientific research workflows. It manages a research question through 14
DAG nodes (L0-L10c), each executed by a named persona (Linnaeus, Einstein,
Feynman, Oppenheimer, Fisher, Tukey, Turing, Curie, Darwin, Jobs) running as
an independent subagent with physical context isolation.

Your task: perform a full second-pass code review and bug audit on
`research_loop_v03.py` and its supporting files.

---

## 2. Files to Review

### Primary (must read in full)

| File | Lines | Priority |
|------|-------|----------|
| `D:/research_loop/research_loop_v03.py` | ~1652 | P0 - core script |
| `D:/research_loop/DAG_TOPOLOGY.md` | 67 | P0 - topology reference |
| `D:/research_loop/README_v0.3.md` | ~200 | P1 - architecture doc |
| `D:/research_loop/README.md` | ~161 | P1 - root README |

### Secondary (read if touching templates)

| Path | Files |
|------|-------|
| `D:/research_loop/templates/v03_personas/` | 10 persona templates |
| `D:/research_loop/templates/v03_layers/` | 14 layer templates (L0-L10c) |

### Reference (context only, do not modify)

| Path | Note |
|------|------|
| `D:/research_loop/research_loop_v02.py` | v0.2 script, deprecated, do not touch |
| `D:/research_loop/HANDOFF_V03_SUBAGENT_ARCHITECTURE.md` | original build handoff |
| `D:/research_loop/LESSONS_LOG.md` | recurring failure patterns |
| `D:/research_loop/V03_PROGRESS.md` | build progress + test results |
| `D:/research_loop/PROGRESS_V03.md` | earlier progress notes |

### Test projects (read-only, for regression checks)

| Path | Note |
|------|------|
| `D:/research_loop/DemoProject_v03/` | demo project, walked full L0-L10c |
| `D:/research_loop/Yigene_WGCNA_v03/` | real WGCNA project, walked full DAG |

---

## 3. Known Bugs and Issues

### Bug 1 (FIXED): next-step did not check delta existence

**Original problem:** `cmd_next_step` mapped `current_status` to a single node,
but L1/L2/L3 all run under `IDEA_PROPOSED` status, and L5/L6 both run under
`METHOD_PROPOSED`. So after L1 delta was emitted, next-step kept returning L1
instead of advancing to L2.

**Fix applied (lines ~822-875):** Replaced single-node mapping with
`status_to_nodes` dict that lists all candidate nodes per status. The function
now scans for the first node whose delta file does not yet exist and returns
that one. If all deltas exist for the current status, it returns the last
candidate (whose advance_command should trigger a status transition).

**What to verify:**
- Walk a demo project from NEW to KEEP and confirm next-step returns the
  correct node at every step
- Edge case: what happens if a delta file exists but is invalid JSON?
  Currently `next-step` only checks file existence, not validity
- Edge case: what if someone manually deletes a delta file? next-step would
  re-emit that node, potentially creating duplicates in decision log

### Bug 2 (SUSPECTED): _replace_field may corrupt candidate files

**Symptom:** During the WGCNA v0.3 run, the candidate file was found at 0
bytes after a sequence of decision commands. The exact cause was not
determined. It may have been an accidental overwrite by an external operation
(Set-Content or apply_patch), not a bug in `_replace_field` itself.

**What to verify:**
- Read `_replace_field` (line ~399) and `_load_yaml_front` (line ~359)
- Check: does the regex `^key: .*$` handle multi-line YAML values correctly?
- Check: does `_yaml_value` properly escape quotes, backslashes, special chars?
- Check: what happens if the candidate file has no frontmatter delimiters?
- Stress test: run 20 sequential `_replace_field` calls on a candidate and
  verify file integrity after each

### Bug 3 (KNOWN): aggregate-report Chinese translations incomplete

**Symptom:** `cmd_aggregate_report` (line ~1658) generates FINAL_REPORT_CN.md
but some section headers and field labels remain in English (e.g. "Skills
found", "Input verified", "Skill use plan").

**What to verify:**
- Read `_format_delta_body` (line ~1552) and `cmd_aggregate_report`
- Check all hardcoded English strings that should have Chinese equivalents
- The Chinese report should be fully readable by a Chinese-speaking scientist

### Bug 4 (KNOWN): _next_seq glob pattern may miss or duplicate

**History:** The original v0.1/v0.2 `_next_seq` had a bug where the glob
pattern silently overwrote every decision as D0001. This was fixed in v0.2.
v0.3 inherits the v0.2 fix, but the fix should be re-verified.

**What to verify:**
- Read `_next_seq` (line ~340)
- Check: does the glob pattern correctly find the highest sequence number?
- Check: what happens if the decision log directory is empty?
- Check: what happens if there are non-numeric suffixes in filenames?

---

## 4. Areas Requiring Deep Review

### 4.1 Delta schema validation (cmd_emit_delta, line ~972)

The schema validator checks:
- Required keys exist
- Types match (isinstance checks)
- Extra keys are allowed (with warning)

**What to verify:**
- Are the schemas in `DELTA_SCHEMAS` (line ~213) consistent with the persona
  templates in `templates/v03_personas/`?
- Does the validator handle nested structures (lists of dicts) correctly?
- What happens if a subagent outputs a string where a list is expected?
- Are there schemas that are too strict (rejecting valid output) or too loose
  (accepting garbage)?

### 4.2 Context assembly (cmd_assemble_context, line ~895)

This is the core of Path B isolation. It reads delta files and embeds them as
text in the subagent context.

**What to verify:**
- Does `strip_candidate_to_frontmatter` (line ~424) truly strip the body?
  What if the candidate file has no `---` delimiters?
- Does the delta reference resolution (line ~922) correctly map short node IDs
  (e.g. "L1") to delta keys (e.g. "L1_einstein")?
- What happens if a required delta file is missing? Currently it prints
  "(not yet emitted)" - should this be an error instead?
- For L10c (ALL deltas): does it correctly read all 13 delta files?
- Check: does any node's context accidentally include a delta it should NOT
  see? Cross-reference with DAG_TOPOLOGY.md

### 4.3 Status machine and gate logic

**What to verify:**
- Read `cmd_triage_idea` (line ~1262), `cmd_triage_method` (line ~1289),
  `cmd_execution_gate` (line ~1318), `cmd_decision` (line ~1197)
- Are all 15 statuses reachable? Draw the state diagram
- Can any status transition skip a gate? (e.g. EXECUTED without
  NEEDS_EXECUTION, or KEEP without UNDER_REVIEW)
- Does `execution-gate` correctly check for skill_use_plan.md AND
  input_manifest.md AND METHOD_APPROVED status?
- What happens if someone runs `decision --status KEEP` from NEW?
  Is there a guard?

### 4.4 Obsidian sync (cmd_obsidian_sync, line ~1387)

**What to verify:**
- Does it correctly copy delta JSON + FINAL_REPORT to the vault?
- Are wikilinks correctly formatted? (Obsidian uses `[[...]]` syntax)
- Does it handle missing directories gracefully?
- Does it overwrite existing files in the vault, or append?

### 4.5 Turing workspace (prepare_turing_workspace)

**What to verify:**
- This function is mentioned in README_v0.3.md but may not be fully
  implemented in the script. Check if it exists as a function or is only
  described as a pattern
- If it exists: does it use `shutil.copy2` (not `os.link`)?
- Does it create the workspace on the same disk as the project?
- Does it clean up after execution?

---

## 5. Test Plan for Claude Code

### Phase 1: Static analysis

1. Run `python -m py_compile research_loop_v03.py` - confirm syntax
2. Run `python research_loop_v03.py --version` - confirm 0.3.0
3. Run `python research_loop_v03.py --help` - confirm all 15 commands listed
4. Read the full source, flag any:
   - Unclosed file handles
   - Missing encoding parameter on file I/O
   - Bare except clauses
   - String formatting bugs (f-string with dict keys containing quotes)
   - Off-by-one errors in sequence numbering

### Phase 2: Functional tests on demo project

5. Run `python research_loop_v03.py demo` - confirm DemoProject_v03 created
6. Walk the full DAG on the demo:
   - `next-step` at each status
   - `assemble-context` for each node
   - `emit-delta` with valid and invalid JSON
   - Status transitions via triage-idea, triage-method, execution-gate, decision
7. Run `aggregate-report` - confirm 13/13 deltas, EN + CN reports
8. Run `obsidian-sync` - confirm files copied to vault

### Phase 3: Edge case tests

9. Delete a delta file mid-walk - does next-step handle it?
10. Corrupt a delta file (invalid JSON) - does emit-delta catch it?
11. Run decision out of order (e.g. KEEP from NEW) - does it reject?
12. Run triage-method on wrong status - does it reject?
13. Run execution-gate without preflight - does it reject?
14. Create a candidate with special characters in title/claim - does
    _replace_field handle it?

### Phase 4: Regression

15. Confirm `research_loop_v02.py --version` still returns 0.2.0
16. Confirm DemoProject_v02 still has all expected files
17. Confirm Yigene_WGCNA_v02 project is untouched

### Phase 5: Real project walk

18. Create a new v0.3 project with `new-project`
19. Create a candidate with `new-candidate` (use split frontmatter)
20. Walk L0-L10c using next-step + assemble-context + emit-delta
21. Use `spawn_agent` (or equivalent in Claude Code) to actually run each
    persona as an independent subagent
22. Verify L9a/L9b parallel execution and mutual isolation
23. Verify L7 Turing workspace isolation (Path A)

---

## 6. Output Expected from Claude Code

Create a file `CODE_REVIEW_REPORT.md` in `D:/research_loop/` with:

1. **Bug list** - every bug found, with file, line number, severity (P0-P3),
   description, and suggested fix
2. **Test results** - pass/fail for each test in the test plan above
3. **Schema audit** - table of each delta schema vs persona template, noting
   any mismatches
4. **State machine audit** - full state diagram, noting any unreachable
   states or missing transitions
5. **Fixes applied** - if Claude Code fixes any bugs, list each fix with
   before/after diff

Do NOT modify `research_loop_v02.py` or any v0.2 project files.
Do NOT modify existing v0.3 project files (DemoProject_v03, Yigene_WGCNA_v03)
unless a bug makes them invalid.

---

## 7. Environment

- Windows 11, PowerShell, Python 3.13
- R 4.6.0 at `D:/Programs/R/R-4.6.0/bin/Rscript.exe`
- R library: `D:/R-HK/Seurat5_lib` (call .libPaths() before library())
- Obsidian vault: `C:/Users/hk200/Documents/Obsidian Vault`
- EverOS memory: http://127.0.0.1:9000, user_id=kai, agent_id=codex
- Git: repo at https://github.com/hk20013106/RLR, branch main
- Proxy: 127.0.0.1:7890 (check before git operations)

---

## 8. Rules from AGENTS.md

Read `C:/Users/hk200/.codex/AGENTS.md` in full before starting. Key rules:

- PowerShell native only, no bash syntax
- Here-strings for multiline (`@'`/`'@` on own lines)
- apply_patch only for files <50 lines, no `===`/`@@`/`#` headers
- Never pipe Python through PowerShell
- Same method fails 2 times: switch method or handoff
- No file overwrites unless explicitly requested
- R scripts: .libPaths() first, cor <- WGCNA::cor, no sink(),
  colnames(datExpr) = genes, nThreads=1
