# Research Loop Room v0.3 - Subagent Architecture

A gated multi-loop scientific council where each persona runs as an
**independent subagent** with physical context isolation. v0.3 keeps v0.2's
gates and status flow, but replaces the single-context council with a 14-node
DAG in which subagents communicate only through structured delta JSON files.

It remains a **dependency-free** file/structure manager. It does not call
external APIs or CLIs itself; an orchestrating agent drives `spawn_agent`.

> Core principle: the controller is a pipe, not a thinker. It reads delta
> files to build context, spawns subagents, validates and saves their deltas,
> and advances status. It never interprets or modifies delta content.

---

## What changed from v0.2

| | v0.2 | v0.3 |
| --- | --- | --- |
| Context | all 10 personas in one agent | each persona = isolated subagent |
| State | free-form Markdown notes | structured delta JSON per node |
| Topology | linear layers 0-10 | 14-node DAG (L9a/L9b parallel) |
| Isolation | none | Path B (context invisibility) + Path A (Turing workspace) |
| Memory sharing | shared context window | 3 layers: delta JSON, candidate frontmatter, EverOS |
| Commands | note/route/decision... | + next-step, assemble-context, emit-delta, aggregate-report, prepare-turing-workspace |

v0.2 projects and `research_loop_v02.py` are untouched. v0.3 is a new standalone
script (`research_loop_v03.py`) writing a superset layout.

---

## DAG topology (14 nodes)

See `DAG_TOPOLOGY.md` for the full table. Summary:

```
L0 Linnaeus -> L1 Einstein -> L2 Feynman -> L3 Oppenheimer
 -> L4 Fisher -> L5 Tukey -> L6 Oppenheimer -> L7 Turing
 -> L8 Curie -> { L9a Feynman || L9b Darwin } -> L10a Jobs
 -> L10b Oppenheimer -> L10c Linnaeus
```

Each node sees only its DAG-specified input deltas. L9a and L9b run in parallel
and cannot see each other. L7 (Turing) is the only execution node.

---

## New commands

```
python research_loop_v03.py next-step PROJECT_DIR CAND_ID
python research_loop_v03.py assemble-context PROJECT_DIR CAND_ID --node L1
python research_loop_v03.py emit-delta PROJECT_DIR CAND_ID --node L1 --persona Einstein --file delta.json
python research_loop_v03.py aggregate-report PROJECT_DIR CAND_ID
python research_loop_v03.py prepare-turing-workspace PROJECT_DIR CAND_ID
```

### next-step
Reads candidate status, outputs a JSON scheduling packet for the next DAG node:
node, persona, is_parallel, is_execution, context_files, template_path,
persona_template_path, action_hint, advance_command. Terminal when status is
KEEP/DROP/ARCHIVED. At L9 it returns is_parallel=true with L9a+L9b. At L7 it
returns is_execution=true with allowlisted files.

### assemble-context
Path B core. Reads the deltas the DAG allows for the node, plus the stripped
candidate frontmatter, and emits a plain-text context block for embedding in a
spawn_agent message. Includes the directive: "Your entire input is below. Do not
access the filesystem." Uses `strip_candidate_to_frontmatter()` to pass only
candidate metadata, never the body.

### emit-delta
Validates a subagent's delta JSON against the persona schema (structural:
required keys present, types match; extra keys allowed with a warning) and
writes it to `02_Agent_Notes/<persona>/<node>_<persona>_delta.json`.

### aggregate-report
L10c Linnaeus. Reads all delta JSON in DAG order and generates FINAL_REPORT.md +
FINAL_REPORT_CN.md. Does not overwrite existing reports (timestamped names).

### prepare-turing-workspace
Path A. Copies allowlisted files with shutil.copy2 to
`PROJECT_DIR/_turing_workspace_<timestamp>/` (same disk, no hard links).

Modified v0.2 commands (route/decision/triage-*/execution-gate) read delta JSON
instead of Markdown notes for status fields. obsidian-sync copies delta JSON +
FINAL_REPORT to the vault.

---

## Delta JSON format

Each subagent outputs a structured delta. Schemas are hardcoded (see Section 6
of the handoff and each persona template's "Delta Output Schema" section).
Example (L1 Einstein):

```json
{
  "hypotheses": [{"id": "H1", "text": "...", "testable": true, "rationale": "..."}],
  "key_uncertainty": "...",
  "primary_hypothesis": "H1"
}
```

Validation is structural only (no external JSON Schema library).

---

## Memory sharing (3 layers)

1. **Delta JSON (primary, project-internal).** Each subagent writes a delta; the
   next subagent receives relevant deltas as embedded context. This is the only
   way project state flows between subagents.
2. **Candidate frontmatter (read-only anchor).** candidate_id, title, question,
   claim are stripped from the candidate YAML and embedded in every subagent's
   context. The candidate body (which carries status/history) is never passed.
3. **EverOS (cross-session, optional).** Durable technical facts (crash
   patterns, verified parameters) at http://127.0.0.1:9000, user_id=kai,
   agent_id=codex. A subagent MAY search EverOS at startup. EverOS does NOT store
   project state.

Not a memory mechanism: no shared context window, no shared variables, no
filesystem access for cognitive agents, no EverOS for project state, no
candidate body access.

---

## How to use with spawn_agent

The orchestrating agent (Codex/Claude Code/Antigravity) loops:

```
step  = next-step(PROJECT, CAND)               # JSON scheduling packet
ctx   = assemble-context(PROJECT, CAND, --node step.node)
agent = spawn_agent(message=ctx)               # Path B (or Path A workspace for L7)
wait_agent(agent)
emit-delta(PROJECT, CAND, --node, --persona, --file result.json)
# run step.advance_command (triage-idea / triage-method / execution-gate / decision)
# repeat; on L10c run aggregate-report and stop
```

For L9a/L9b: spawn both, wait on both, emit both deltas.
For L7: prepare-turing-workspace, run Rscript in the workspace, build the delta
from results, emit-delta.

---

## Migration from v0.2

- `research_loop_v02.py` and all v0.2 projects are untouched and still work.
- v0.3 is a new script; existing v0.2 projects can be continued with v0.2.
- To migrate a project: re-run preflight under v0.3, then drive the DAG with
  next-step/assemble-context/emit-delta. Old Markdown notes are preserved; new
  state is recorded in delta JSON.
- Templates: `templates/v03_personas/` and `templates/v03_layers/` add delta
  schema + DAG dependency annotations on top of the v0.2 templates.

---

## Directory layout (v0.3, superset of v0.2)

```
Project/
+-- 00_Project_Index.md
+-- 00_Preflight/                 # L0 boot gate (Linnaeus)
+-- 01_Candidates/
+-- 02_Agent_Notes/<persona>/     # <node>_<persona>_delta.json per node
+-- 03_Handoffs/
+-- 04_Analysis_Outputs/
+-- 05_Decision_Log/
+-- 06_Manuscript_Direction/
+-- 07_Obsidian_Sync/
+-- _turing_workspace_<ts>/       # Path A isolated execution workspace (L7)
+-- FINAL_REPORT.md / FINAL_REPORT_CN.md   # L10c aggregate
```

---

## Hard invariants (unchanged from v0.2)

- Only Oppenheimer changes candidate status.
- Only Turing executes code, and only after the execution gate passes.
- Linnaeus runs first; no execution before L0 + L6 complete.
- All deltas are append-only and auditable.

**Version:** 0.3.0 - subagent architecture - 2026-06-25
