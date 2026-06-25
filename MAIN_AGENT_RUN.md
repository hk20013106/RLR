# Main-Agent Run Protocol (RLR v0.4)

## What this is

The main-agent mode is the recommended way to run RLR. The current host agent
(Claude Code / Codex / AntiGravity / Hermes) acts as the orchestrator. It loops
through the DAG by calling `research_loop_v04.py` CLI commands, playing each
persona in turn, generating delta JSON, and advancing state -- all in one
session, no copy-paste.

## What this is NOT

- **NOT ManualProvider**: the user does not copy-paste prompts between nodes.
- **NOT Python controlling the chat UI**: Python cannot drive the current live
  session. The host agent itself reads the protocol and executes it.
- **NOT a Python provider**: main-agent mode uses NO python provider. The
  `orchestrator.py` providers (HeadlessProvider, CommandProvider,
  ManualProvider) are not involved.

## L0 dependency gate (run FIRST, do not skip)

Before the loop, run `python research_loop_v04.py preflight PROJECT` (or
`check-deps PROJECT`). This is the **L0 hard gate**: it verifies every required
dependency listed in `00_Preflight/dependencies.md` (framework: PyYAML; plus any
project deps you declare, e.g. `- command: Rscript`). If any required dependency
is **MISSING, the command exits non-zero and you MUST HALT** — do not proceed to
L1, do not skip. Install the missing dependency, re-run preflight, then continue.
`run_loop.py` enforces this automatically before round 1.

## Pre-research (v0.4)

Three pre-research steps run automatically *before* their node — they do **not**
change the 14-node DAG topology; their results are embedded into the node's
`assemble-context` as extra reference context:

| Before | Step | What you do |
|--------|------|-------------|
| **L1** (hypotheses) | deep research | Use academic-research skills to search the literature for the candidate's question; summarize key findings, methods, gaps. |
| **L4** (method design) | method literature review | Search how others did similar analyses; summarize methods, recommended approach, pitfalls. |
| **L7** (execution) | code search | Search GitHub / Bioconductor / CRAN for existing pipelines; summarize reusable tools and the gap you must write yourself. |

Run `pre-research PROJECT CAND --node L1|L4|L7`; it prints a prompt **grounded in
this candidate's question/claim** (with seed queries to adapt). Write the summary
to `02_Agent_Notes/_pre_research/<node>_research.md`. The next `assemble-context
--node <node>` embeds it under a `=== PRE-RESEARCH (...) ===` section and records
it in the context manifest (`pre_research` field). If you skip it, the context
shows a `NOT YET RUN` note.

## Step-by-step protocol

```
while not terminal:
    1. step = python research_loop_v04.py next-step PROJECT CAND
    1b. # v0.4 PRE-RESEARCH: before L1/L4/L7, do the pre-step FIRST
        if step.node in (L1, L4, L7):
            python research_loop_v04.py pre-research PROJECT CAND --node step.node
            # follow the printed prompt; write the structured summary to
            # 02_Agent_Notes/_pre_research/<node>_research.md
            # assemble-context will then embed it automatically.
    2. if step.is_parallel:  # L9a + L9b
         for sub in step.nodes:
             ctx = python research_loop_v04.py assemble-context PROJECT CAND --node sub.node
             delta = act_as(sub.persona, ctx)
             write delta to temp file
             python research_loop_v04.py emit-delta PROJECT CAND --node sub.node --persona sub.persona --file temp.json
    3. elif step.is_execution:  # L7 Turing
         python research_loop_v04.py prepare-turing-workspace PROJECT CAND
         run approved scripts in the workspace
         build L7 delta from results
         python research_loop_v04.py emit-delta PROJECT CAND --node L7 --persona Turing --file delta.json
    4. else:  # cognitive node
         ctx = python research_loop_v04.py assemble-context PROJECT CAND --node step.node
         delta = act_as(step.persona, ctx)
         write delta to temp file
         python research_loop_v04.py emit-delta PROJECT CAND --node step.node --persona step.persona --file temp.json
    5. run step.advance_command (decision / triage-idea / triage-method / execution-gate)
    6. if step.node == L10c:
         python research_loop_v04.py aggregate-report PROJECT CAND
         # REQUIRED end-of-round step: sync human-readable output to Obsidian
         python sync_to_obsidian.py PROJECT --cand CAND   # needs $OBSIDIAN_VAULT
         evaluate StopPolicy
         if stop: break
         else: create child candidate, continue
```

## End-of-round Obsidian sync (REQUIRED)

After `aggregate-report` at the end of **every round**, run
`python sync_to_obsidian.py PROJECT --cand CAND`. It writes the human-readable
view (per-node NOTE.md, ROUND_SUMMARY, figures, FINAL_REPORT, index) into the
vault at `$OBSIDIAN_VAULT/ResearchLoop/<project>/`. Set `$OBSIDIAN_VAULT` (or
pass `--vault`) first; if it is unset the script fails loud and writes nothing
(it does NOT create stray directories). This is part of the loop, not optional.

## L7 Turing workspace

Turing is the only node with filesystem access (Path A). Use
`prepare-turing-workspace` to create an isolated workspace. Run R/Python scripts
only inside that workspace. Copy results out, build the L7 delta JSON, emit it.

## L9a/L9b independence

L9a (Feynman falsification) and L9b (Darwin biology) must be as independent as
possible. Generate L9a's delta WITHOUT looking at L9b's output, and vice versa.
The `assemble-context` command enforces this: L9a's context does not include
L9b's delta, and L9b's context does not include L9a's delta.

## StopPolicy

After L10c (FINAL_REPORT generated), evaluate:

- **STOP** if: KEEP + review accept; DROP/DOWNGRADE/ARCHIVED; max_rounds
  reached; REVISE with no executable next_steps; marginal_gain <= 2; L7 failed
  2x; two consecutive rounds with no new evidence.
- **CONTINUE** if: REVISE with executable next_steps; review major_revision;
  round < max_rounds. Continue = create a child candidate (not overwrite parent).

## Child candidate

When continuing, create a new candidate with `parent_candidate_id` and
`round_id` set. The child inherits the question/claim but focuses on the
executable next_steps from the parent's L10b decision.

## Avoiding context pollution

- Only use `assemble-context` output as input for each node.
- Do NOT read other delta files directly.
- Do NOT carry over reasoning from one persona to the next.
- The `assemble-context` output includes an isolation directive.
