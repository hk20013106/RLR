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
candidate frontmatter (L0 gets the real `source_input` path; others get
`input_alias` only), and emits a plain-text context block for embedding in a
spawn_agent message. Includes the directive: "Your entire input is below. Do not
access the filesystem." Also writes a `08_Audit/context_manifest_*.json`
recording exactly what was shown (per-delta sha256 + declared tools/EverOS
policy) for later receipt verification.

### emit-delta
Validates a subagent's delta JSON against the persona schema **recursively**
(container types AND the required keys of objects inside lists/dicts; extra keys
allowed with a warning) and writes it to
`02_Agent_Notes/<persona>/<node>_<persona>_delta.json`. With optional
`--receipt <context_manifest>` it verifies the upstream deltas still match the
manifest hashes (rejects on mismatch) and writes a `08_Audit/run_receipt_*.json`.

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

The design goal is **"enough but not too much" + declared, traceable,
replayable** — controllable information routing, not maximal isolation.

1. **Delta JSON (primary, project-internal).** Each subagent writes a delta; the
   next subagent receives only the DAG-allowed deltas as embedded context. This
   is the only way project state flows between subagents.
2. **Candidate frontmatter (read-only anchor).** candidate_id, title, question,
   claim, current_status, current_owner are embedded in every subagent's
   context. Input visibility is graded: the input-verification node (L0) sees
   the real `source_input` path; every other cognitive node sees only
   `input_alias` (a path-free label) so it has no incentive to "go read the
   file". The candidate body (status/history) is never passed.
3. **EverOS (cross-session) with namespace routing.** Durable technical facts at
   http://127.0.0.1:9000. EverOS is governed by sub-namespaces rather than hard
   isolation:
   - `global_methods/` — all nodes: generic experience, failure modes, param
     conventions.
   - `projects/<id>/public/` — all nodes of this project: stable project facts.
   - `projects/<id>/node_outputs/<node>/` — archive; injected to a later node
     **only if the DAG already grants that node** (mirrors `context_inputs`).
   - `projects/<id>/execution/L7/` — Turing execution records / env / errors.

   Each node's allowed EverOS scopes are **declared** in its
   `everos_read_scopes` (derived from `context_inputs`, so EverOS can never open
   a channel the delta DAG doesn't) and surfaced in the context manifest. The
   script declares; the orchestrator enforces.

## Audit & info-flow policy (declared, not physically enforced)

Isolation here is **default-soft for cognition + strong sandbox for L7 +
full-trace audit**. The script can't grant/revoke a subagent's tools or police
EverOS (that is the orchestrator's job), so instead it *declares and records*:

- `assemble-context` writes `08_Audit/context_manifest_<node>_<ts>.json`: the
  node, persona, allowed inputs, **sha256 of every injected delta**, the
  declared `tools_policy` (`no-fs` for cognitive nodes, `workspace-fs` for L7),
  `everos_read_scopes`, workspace, timestamp. `next-step` also carries
  `tools_policy` + `everos_read_scopes` so the orchestrator can set tool grants
  before spawning.
- `emit-delta --receipt <manifest>` (optional but verified) re-hashes the
  upstream deltas the node consumed and **rejects** if any changed since
  `assemble-context` (catches an upstream delta re-emitted mid-flight). It then
  writes `08_Audit/run_receipt_<node>_<ts>.json` (output hash, manifest id,
  verification result) — the delta itself stays pure.

Not a memory mechanism: no shared context window, no shared variables, no
candidate body access. Physical no-fs for cognitive agents and EverOS scoping
are enforced by the orchestrator using the declared policy above.

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
+-- 08_Audit/                     # context_manifest_* + run_receipt_* (info-flow trail)
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
