---
title: RLR v0.3 Subagent Architecture Implementation Handoff
date: 2026-06-24
status: READY_FOR_IMPLEMENTATION
author: Codex (GPT-5)
audience: Any coding agent (Codex / Claude Code / Antigravity)
---

# Handoff: RLR v0.3 Subagent Physical Isolation Architecture

> This document is self-contained. Read it from top to bottom and you can
> start implementing immediately. No prior conversation context required.

---

## 1. What Is This Project

Research Loop Room (RLR) is a gated multi-loop scientific council framework.
It manages a research question through 13 DAG nodes (L0-L10c), each executed
by a named persona (Linnaeus, Einstein, Feynman, Oppenheimer, Fisher, Tukey,
Turing, Curie, Darwin, Jobs). The framework enforces structural invariants:
only Oppenheimer changes status, only Turing executes code, execution requires
approved plans.

**v0.1** (deleted) was a flat state machine.
**v0.2** (current, working) runs all 10 personas in a single agent context.
**v0.3** (to build) converts each persona into an independent subagent with
physical context isolation via DAG topology.

---

## 2. Current State (Verified 2026-06-24)

### Working code
- `D:/research_loop/research_loop_v02.py` (v0.2.0, 50KB, dependency-free)
  - Commands: demo, new-project, preflight, new-candidate, route, note,
    triage-idea, triage-method, execution-gate, decision, obsidian-sync, list, show
  - obsidian-sync was patched to copy files to Obsidian vault + generate wikilinks
    (uses `--vault` arg, default `C:/Users/hk200/Documents/Obsidian Vault`)
- `D:/research_loop/README_v0.2.md` (v0.2 documentation)
- `D:/research_loop/templates/v02_personas/` (10 persona templates)
- `D:/research_loop/templates/v02_layers/` (11 layer templates L0-L10)

### Completed projects
- `D:/research_loop/DemoProject_v02/` (demo, walks all 10 personas)
- `D:/research_loop/Yigene_WGCNA_v02/` (WGCNA analysis, status=KEEP)
  - FINAL_REPORT.md and FINAL_REPORT_CN.md exist
  - 33 files synced to Obsidian vault
- `D:/research_loop/Yigene_WGCNA/` (v0.1 project, deprecated, not deleted)

### Key environment
- Windows 11, 64GB RAM, PowerShell
- Python 3.13 at system default
- R 4.6.0 at `D:/Programs/R/R-4.6.0/bin/Rscript.exe`
- R library: `D:/R-HK/Seurat5_lib` (798 packages, must .libPaths() before library())
- Obsidian vault: `C:/Users/hk200/Documents/Obsidian Vault`
- EverOS memory: http://127.0.0.1:9000, user_id=kai, agent_id=codex
- AGENTS.md: `C:/Users/hk200/.codex/AGENTS.md` (global rules, auto-loaded)

---

## 3. AGENTS.md Hard Rules (Must Follow)

Read `C:/Users/hk200/.codex/AGENTS.md` in full before starting. Key rules:

### PowerShell hard rules
- Native PowerShell only; no bash syntax in PowerShell
- Here-strings for multiline (`@'`/`'@` must each be on own line)
- Use `-LiteralPath` for exact paths, `-Path` for wildcards
- Complex commands with mixed quotes: write to .ps1/.py script file, then execute

### File writing hard rules (added 2026-06-24)
- apply_patch: only for files <50 lines, no `===`, `@@`, `#` headers. Fails on
  Chinese text. Use `Set-Content` or Python `open().write()` for large files.
- Never pipe Python code through PowerShell (`$` interpolated, `-` treated as
  unary operator). Write .py script file first, then `python <file>`.
- Same method fails 2 times: MUST switch method or handoff. No 3rd attempt.
- Windows paths in Python source: use forward slashes `/` or raw strings `r''`.
  Backslashes like `\r`, `\a`, `\v` become control characters in Python strings.

### Other rules
- No file overwrites unless explicitly requested; use timestamped names
- Check `D:/skills/skills_inventory.md` before complex tasks
- R scripts: `.libPaths()` first, `cor <- WGCNA::cor`, `disableWGCNAThreads()`,
  `nThreads=1`, no `sink()`, `colnames(datExpr)`=genes not `rownames`
- Handoff files go in the project's local disk directory, not temp dirs

---

## 4. v0.3 Architecture: What to Build

### Core principle
Cognitive agents: isolation by information invisibility (Path B).
Execution agent (Turing): isolation by workspace + command allowlist (Path A).
Do NOT pretend spawn_agent is an OS sandbox.

### New file: `D:/research_loop/research_loop_v03.py`
Keep v0.2 untouched. v0.3 is a new standalone script.

### DAG topology (14 nodes, L9a/L9b parallel)

| Node | Persona | Inputs (context to embed) | Isolated from | Output delta |
|------|---------|--------------------------|---------------|--------------|
| L0 | Linnaeus | AGENTS.md, skills_inventory, data paths | all exec notes | L0_linnaeus_delta.json |
| L1 | Einstein | candidate_frontmatter, L0 delta | L2+ | L1_einstein_delta.json |
| L2 | Feynman | candidate_frontmatter, L1 delta | L3+ | L2_feynman_delta.json |
| L3 | Oppenheimer | L1 delta, L2 delta | L4+ | L3_oppenheimer_delta.json |
| L4 | Fisher | L1 delta, L3 delta, L2 delta | L5+ | L4_fisher_delta.json |
| L5 | Tukey | L4 delta, L2 delta (ref) | L6+ | L5_tukey_delta.json |
| L6 | Oppenheimer | L4 delta, L5 delta | L7+ | L6_oppenheimer_delta.json |
| L7 | Turing | L6 delta, L0 delta, skill_plan (Path A) | L1-L5 history | L7_turing_delta.json |
| L8 | Curie | L7 delta, L6 delta, candidate_frontmatter | L9+ | L8_curie_delta.json |
| L9a | Feynman | L1 delta, L7 delta, L8 delta | L9b, L10 | L9a_feynman_delta.json |
| L9b | Darwin | L1 delta, L7 delta, L8 delta | L9a, L10 | L9b_darwin_delta.json |
| L10a | Jobs | candidate_frontmatter, L8, L9a, L9b deltas | L10b+ | L10a_jobs_delta.json |
| L10b | Oppenheimer | L10a, L8, L9a, L9b deltas | - | L10b_oppenheimer_delta.json |
| L10c | Linnaeus | ALL delta files | - | FINAL_REPORT.md + _CN.md |

---

---

## 4b. Persona-Subagent Mapping (1:1)

Each persona is a separate subagent, spawned via `spawn_agent`:

| Node | Persona | spawn_agent type | What it does |
|------|---------|-----------------|--------------|
| L0 | Linnaeus | default | Skill scan, data verification, preflight |
| L1 | Einstein | default | Hypothesis generation |
| L2 | Feynman | default | Idea falsification (blind review of L1) |
| L3 | Oppenheimer | default | Triage: select/reject hypotheses |
| L4 | Fisher | default | Method design |
| L5 | Tukey | default | Method falsification |
| L6 | Oppenheimer | default | Approve/reject method |
| L7 | Turing | worker | Execute R/Python scripts (Path A) |
| L8 | Curie | default | Evidence audit |
| L9a | Feynman (separate instance) | default | Result falsification |
| L9b | Darwin (separate instance) | default | Biology interpretation |
| L10a | Jobs | default | Value assessment, manuscript framing |
| L10b | Oppenheimer | default | Final decision |
| L10c | Linnaeus | default | Aggregate all deltas into FINAL_REPORT |

Key points:
- L2 Feynman and L9a Feynman are DIFFERENT subagent instances. Same persona
  name, but spawned independently with different context. L2 sees L1 only;
  L9a sees L7+L8+L1 but NOT L2's own earlier note.
- L3/L6/L10b Oppenheimer are also separate instances. Each gets only its DAG
  inputs, not the full history.
- L7 Turing uses agent_type=worker because it executes code. All others use
  agent_type=default (cognitive only).
- Each subagent is closed after its delta is collected. No subagent persists
  across DAG nodes.

---

## 4c. Memory Sharing Between Subagents

Subagents do NOT share memory at runtime. They share state through files.
There are exactly three layers:

### Layer 1: Delta JSON (primary, project-internal)

Each subagent outputs a structured delta JSON file:
  `02_Agent_Notes/<persona>/<node>_<persona>_delta.json`

The next subagent in the DAG receives the relevant deltas as embedded context
(via assemble-context). This is the ONLY way project state flows between
subagents.

Example flow:
  Einstein (L1) writes L1_einstein_delta.json
  -> Feynman (L2) receives L1 delta content in its spawn message
  -> Feynman writes L2_feynman_delta.json
  -> Oppenheimer (L3) receives L1 + L2 deltas in its spawn message
  -> Oppenheimer writes L3_oppenheimer_delta.json
  ...

The DAG topology table (Section 4) defines exactly which deltas each node
can see. Anything NOT listed is physically absent from the subagent context.
The subagent has no other way to learn about upstream work.

### Layer 2: Candidate frontmatter (read-only anchor)

The candidate file's YAML frontmatter (candidate_id, title, question, claim)
is stripped to a dict and embedded into every subagent's context. This gives
each subagent the scientific question without exposing the candidate body
(which accumulates status/history and could leak downstream information).

The candidate file itself is NEVER modified by subagents. Only the main
controller writes status changes via `decision` / `triage-*` commands.

### Layer 3: EverOS (cross-session, optional)

EverOS at http://127.0.0.1:9000 (user_id=kai, agent_id=codex) stores durable
facts that survive across sessions: WGCNA crash patterns, verified R
parameters, file-writing failure modes. A subagent MAY search EverOS at
startup for relevant technical knowledge, but this is optional.

EverOS does NOT store project-internal state. Delta flow (Layer 1) is the
sole mechanism for that.

### What is NOT a memory sharing mechanism

- No shared context window: each subagent has its own isolated context.
- No shared variables: subagents communicate only through delta JSON files.
- No direct file system access for cognitive agents (Path B): they receive
  context as text in spawn_agent message, not by reading files.
- No EverOS for project state: EverOS is for durable technical facts only.
- No candidate body access: only frontmatter is passed.

### Main controller role

The main Codex agent (orchestrator) is NOT a persona. It does not do
analysis. Its job:
1. Run `next-step` to get the next DAG node
2. Run `assemble-context` to build the context text
3. `spawn_agent` with that context
4. `wait_agent` for the result
5. Run `emit-delta` to validate and save the delta
6. Run `decision` / `triage-*` / `route` to advance status
7. Repeat until terminal status

The orchestrator reads delta files to build context, but it does not
interpret or modify their content. It is a pipe, not a thinker.

## 5. New CLI Commands to Implement

### `next-step PROJECT_DIR CAND_ID`
Reads candidate status, outputs JSON scheduling packet for the next DAG node.
Output includes: node, persona, is_parallel, is_execution, context_files list,
template_path, persona_template_path, action_hint, advance_command.
L9 outputs is_parallel=true with two nodes (L9a+L9b).
L7 outputs is_execution=true with allowlisted_files.
Terminal when status is KEEP/DROP/ARCHIVED.

### `assemble-context PROJECT_DIR CAND_ID --node L1`
Path B core. Reads DAG-specified delta files + stripped candidate frontmatter,
outputs plain text context block for spawn_agent message embedding.
Subagent prompt includes: 'Your entire input is below. Do not access filesystem.'
Uses strip_candidate_to_frontmatter() to only return metadata, not body.

### `emit-delta PROJECT_DIR CAND_ID --node L1 --persona Einstein --file delta.json`
Validates delta JSON against persona schema, writes to
`02_Agent_Notes/<persona>/<node>_<persona>_delta.json`.
Schema validation is structural (required keys present, types match).
Reject missing required keys or wrong types. Allow extra keys with warning.

### `aggregate-report PROJECT_DIR CAND_ID`
L10c Linnaeus. Reads all delta JSON in DAG order, generates
FINAL_REPORT.md + FINAL_REPORT_CN.md. Replaces manual report writing.

### `prepare-turing-workspace PROJECT_DIR CAND_ID`
Path A. Uses shutil.copy2 to copy allowlisted files to
`PROJECT_DIR/_turing_workspace_<timestamp>/` (same disk, no os.link).
Output: workspace path + list of copied files.

### Modified commands
- `new-candidate`: split frontmatter into question/claim (separate fields)
  Keep claim_or_question as deprecated compat field.
- `route`/`decision`/`triage-*`/`execution-gate`: logic unchanged, read delta JSON
  instead of Markdown notes for status fields.
- `obsidian-sync`: copy delta JSON + FINAL_REPORT to vault.

---

## 6. Delta Schemas (Hardcoded in Python)

Each persona outputs a structured delta JSON. Schemas are Python dicts
checked by a simple validator (no external JSON Schema library).

```python
DELTA_SCHEMAS = {
    "L0_linnaeus": {
        "skills_found": list, "skills_gaps": list, "input_verified": dict,
        "environment": dict, "skill_use_plan": list, "forbidden_shortcuts": list
    },
    "L1_einstein": {
        "hypotheses": [{"id": str, "text": str, "testable": bool, "rationale": str}],
        "key_uncertainty": str, "primary_hypothesis": str
    },
    "L2_feynman": {
        "attacks": [{"hypothesis_id": str, "severity": str, "text": str}],
        "confounders": [{"name": str, "severity": str, "text": str}],
        "diagnostic_tests": [{"name": str, "text": str}], "verdict": str
    },
    "L3_oppenheimer": {
        "selected": list, "rejected": list, "reason": str, "route_to": str
    },
    "L4_fisher": {
        "strategies": [{"id": str, "name": str, "steps": list, "samples": int, "status": str}],
        "recommended": str,
        "scripts_needed": [{"name": str, "purpose": str, "status": str}],
        "key_decisions": list
    },
    "L5_tukey": {
        "attacks": [{"target": str, "severity": str, "text": str}],
        "qc_checkpoints": [{"name": str, "text": str}],
        "failure_stop_rules": [{"name": str, "text": str}]
    },
    "L6_oppenheimer": {
        "approved_strategy": str, "modifications": list, "reason": str,
        "analysis_plan": {"scripts": list, "parameters": dict, "outputs": list}
    },
    "L7_turing": {
        "scripts_run": [{"name": str, "exit_code": int, "output_files": list}],
        "key_results": dict, "warnings": list, "failures": list
    },
    "L8_curie": {
        "evidence_verified": [{"file": str, "check": str, "result": str}],
        "evidence_level": str, "caveats": list
    },
    "L9a_feynman": {
        "falsification_risks": [{"name": str, "severity": str, "resolvable": bool, "text": str}],
        "survives": list, "falsified": list
    },
    "L9b_darwin": {
        "module_interpretations": [{"module": str, "meaning": str, "genes": list, "evidence": str}],
        "convergent_evolution": str, "limitations": list
    },
    "L10a_jobs": {
        "value_assessment": str, "headline": str,
        "publishable_now": list, "needs_more_work": list,
        "manuscript_framing": str
    },
    "L10b_oppenheimer": {
        "decision": str, "evidence_level": str, "reason": str, "next_steps": list
    },
}
```

---

## 7. Two Execution Interfaces (Python Functions)

### Path B: `assemble_context_for_spawn(node, deltas_dir, candidate_path) -> str`
Reads DAG topology table for the node's context_files.
For each context file: if 'candidate_frontmatter', call strip_candidate_to_frontmatter().
If a delta file (e.g. L1_einstein_delta), read and JSON-parse it.
Concatenate all into a plain text block with clear section headers.
Prepend isolation directive: 'Your entire input is below. Do not access
the filesystem. Work only with the information provided.'
Append the persona template + layer template content.
Return the assembled string.

### Path A: `prepare_turing_workspace(allowlisted_files, project_dir) -> str`
Create `project_dir/_turing_workspace_<timestamp>/`.
For each file in allowlisted_files: `shutil.copy2(src, dst)` (NOT os.link).
Return workspace path. Main controller runs Rscript in this workspace.

### strip_candidate_to_frontmatter(candidate_path) -> dict
Read Markdown, parse YAML frontmatter only (between `---` markers).
Return dict with: candidate_id, title, question, claim, current_status.
Do NOT return the body (which may contain downstream info).

---

## 8. L9a/L9b Parallel Execution

`next-step` at L9 outputs:
```json
{
  "is_parallel": true,
  "nodes": [
    {"node": "L9a", "persona": "Feynman", "context_files": ["L1", "L7", "L8"], ...},
    {"node": "L9b", "persona": "Darwin", "context_files": ["L1", "L7", "L8"], ...}
  ]
}
```
Main controller: spawn_agent for both, then wait_agent([id_a, id_b]).
Both see identical inputs but cannot see each other's output.
Safe because both are read-only cognitive layers.

---

## 9. Status Flow (15 statuses, unchanged from v0.2)

``
NEW -> IDEA_PROPOSED -> IDEA_SELECTED -> METHOD_PROPOSED -> METHOD_APPROVED
  -> NEEDS_EXECUTION -> EXECUTED -> UNDER_REVIEW -> KEEP | REVISE | DOWNGRADE | DROP
Also: IDEA_REJECTED, METHOD_REJECTED, ARCHIVED
```

Gate invariants (unchanged):
- Only Oppenheimer changes status (decision/triage/gate commands)
- Only Turing executes code (execution gate requires METHOD_APPROVED + manifests)
- execution-gate exits 1 unless skill_use_plan + input_manifest exist

---

## 10. File Structure to Create

```
D:/research_loop/
  research_loop_v03.py              # NEW main script
  README_v0.3.md                     # NEW documentation
  DAG_TOPOLOGY.md                    # NEW topology reference doc
  templates/
    v03_personas/                     # 10 persona templates (copy from v02, add delta schema note)
    v03_layers/                       # 14 layer templates (L0-L10c, mark DAG deps)
  research_loop_v02.py                # KEEP, mark deprecated in README
  Yigene_WGCNA_v02/                   # KEEP existing results
  DemoProject_v02/                    # KEEP existing demo
```

---

## 11. Implementation Order

Phase 1 (core, ~400 lines):
  1. DAG_TOPOLOGY.md (document the topology table)
  2. research_loop_v03.py skeleton: imports, version, DAG table, delta schemas,
     strip_candidate_to_frontmatter(), status flow, gate logic (reuse v0.2)
  3. `new-project` + `new-candidate` (with split frontmatter)
  4. `next-step` command
  5. `assemble-context` command
  6. `emit-delta` command (with schema validation)

Phase 2 (aggregation, ~300 lines):
  7. `aggregate-report` command (reads all deltas, generates FINAL_REPORT)
  8. `obsidian-sync` (copy deltas + report to vault)
  9. `prepare-turing-workspace` command

Phase 3 (templates + docs, ~200 lines):
  10. Copy v02 personas/layers to v03, add delta schema annotations
  11. README_v0.3.md
  12. Demo project walkthrough

**CRITICAL: Use Python script files for writing research_loop_v03.py.**
The file will be ~900 lines. apply_patch will fail. PowerShell pipe will fail.
Write a _build_v03.py generator script that constructs the file content and writes it.
Use `Set-Content` to write the generator, then `python _build_v03.py` to generate v03.
All Windows paths in Python source use forward slashes.

---

## 12. Test Plan

1. `next-step` on demo project from NEW to KEEP: each step outputs correct DAG node
2. `assemble-context` for each node: output contains only DAG-specified deltas,
   no isolated content leaks
3. `emit-delta` schema validation: rejects missing required keys, allows extra keys
4. L9a/L9b: `next-step` outputs is_parallel=true with two nodes
5. Turing workspace: shutil.copy2 only copies allowlisted files, same disk
6. `aggregate-report`: reads all deltas, generates complete FINAL_REPORT (EN+CN)
7. `strip_candidate_to_frontmatter`: returns only frontmatter dict, not body
8. Regression: v0.2 commands still work on research_loop_v02.py

---

## 13. Key Lessons from v0.2 Implementation (Avoid These Mistakes)

1. apply_patch fails on files >50 lines, Chinese text, or content with `===`/`@@`/`#`.
   Use `Set-Content` or Python `open().write()` instead.
2. PowerShell pipe breaks Python code: `$` interpolated, `-` = unary operator,
   triple-quote boundary confusion. Write .py file first, then execute.
3. Windows paths in Python: `\r`=`CR`, `\a`=`BEL`, `\v`=`VT`. Use `/` or `r''`.
4. WGCNA silent crashes on Windows: 9 documented points in CRASH_LOG.md.
   Key fixes: .libPaths() first, cor <- WGCNA::cor, disableWGCNAThreads(),
   nThreads=1, no sink(), colnames(datExpr)=genes.
5. Same method fails 2x: switch method. No 3rd attempt. (AGENTS.md rule)

---

## 14. Existing WGCNA Results (for reference, do not modify)

All results in `D:/R-HK/yigene/results_wgcna_loop/`:
- all_sample/: 5 modules (turquoise 1720, blue 1440, brown 1257, yellow 291, green 179)
- atrium/: 4 modules (n=23)
- ventricle/: 5 modules (n=48)
- preservation/: Sk<->Sm Zsummary (turquoise Z=16.9, green Z=20.2, brown Z=4.5)
- overlap/: 108 Fisher tests (turquoise vs ventricle_shared_down OR=5.9)
- enrichment/: green module 49 GO-BP, 15 GO-MF, 1 KEGG
- reports/: convergent_module_summary.csv (turquoise+brown = convergent)
- Scripts: `D:/R-HK/yigene/scripts_wgcna_loop/` (stepA-D + 02-07)
- Crash log: `D:/R-HK/yigene/scripts_wgcna_loop/CRASH_LOG.md`

---

## 15. Controller Orchestration Pseudocode

```python
# Main controller (Codex/Claude Code/Antigravity) orchestration loop
# This is NOT in research_loop_v03.py - it is the calling agent's behavior.

while True:
    step = json.loads(run("python research_loop_v03.py next-step PROJECT CAND_ID"))
    if step is None:
        break  # terminal status reached

    if step.get('is_parallel'):
        # L9a + L9b
        ctx_a = run('python research_loop_v03.py assemble-context --node L9a')
        ctx_b = run('python research_loop_v03.py assemble-context --node L9b')
        agent_a = spawn_agent(message=ctx_a)
        agent_b = spawn_agent(message=ctx_b)
        wait_agent([agent_a, agent_b])
        # Collect outputs, emit deltas
        run('emit-delta --node L9a --persona Feynman --file result_a.json')
        run('emit-delta --node L9b --persona Darwin --file result_b.json')

    elif step.get('is_execution'):
        # L7 Turing
        ws = run('python research_loop_v03.py prepare-turing-workspace')
        result = exec_command('Rscript script.R', workdir=ws)
        delta = build_turing_delta(result)
        run('emit-delta --node L7 --persona Turing --file delta.json')

    else:
        # Cognitive layer (Path B)
        ctx = run('python research_loop_v03.py assemble-context --node ' + step['node'])
        agent = spawn_agent(message=ctx)
        wait_agent(agent)
        run('emit-delta --node ' + step['node'] + ' --persona ' + step['persona'])

    # Advance status
    cmd = step.get('advance_command')
    if cmd == 'triage-idea':
        run('triage-idea ...')
    elif cmd == 'triage-method':
        run('triage-method ...')
    elif cmd == 'execution-gate':
        run('execution-gate ...')
    elif cmd == 'decision':
        run('decision ...')

    if step['node'] == 'L10c':
        run('aggregate-report')
        break
```

---

## 16. How to Start

1. Read this document fully
2. Read `C:/Users/hk200/.codex/AGENTS.md`
3. Read `D:/research_loop/research_loop_v02.py` (reference implementation)
4. Read `D:/research_loop/README_v0.2.md` (v0.2 spec)
5. Create `DAG_TOPOLOGY.md` (Section 4 topology table)
6. Write `research_loop_v03.py` using a Python generator script
   (NOT apply_patch, NOT PowerShell pipe - see Section 11)
7. Test with `python research_loop_v03.py demo`
8. Run the test plan (Section 12)

---

## 17. Point of Contact

User: Kai (Shinohara Lab, biology researcher)
Primary agent: Codex (GPT-5)
Fallback agents: Claude Code, Antigravity
EverOS memory: user_id=kai, agent_id=codex, http://127.0.0.1:9000

If EverOS is offline, inform the user but do not crash.
If you hit a wall, write a sub-handoff in the same directory with date prefix.
