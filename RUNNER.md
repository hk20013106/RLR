# RLR v0.3 Loop Runner

Two **new** files extend the RLR controller into a half/auto-automated,
provider-neutral loop runner. The controller (`research_loop_v03.py`) is
**unchanged** — these only call its CLI and read its outputs.

## Files

| File | Role |
|------|------|
| `orchestrator.py` | Provider-neutral agent invocation. `AgentProvider` interface + **automatic** providers `HostAgentProvider` (current host agent, headless, default) and `CommandProvider` (external headless CLI) + `ManualProvider` (**debug-only**). `ProviderConfig` (YAML/JSON; PyYAML optional). `RunReceipt`. `ProviderError`. **No** Codex/Claude/AntiGravity hard-coding. |
| `run_loop.py` | The loop. Drives the DAG via the controller, runs an optional Review gate after L10c, and a hybrid `StopPolicy` decides stop/continue. Bounded by `max_rounds` (default 3). |
| `rlr_runner.yaml` | Auto-generated default config in the project dir on first run. |

## Default mode is AUTOMATIC

The goal is **one launch, runs the whole L0→L10 loop automatically** — no human
copying prompts between nodes. The default provider is `host`
(`HostAgentProvider`): it invokes the current host agent (Codex / Claude Code /
AntiGravity / Hermes / ...) headlessly, **one fresh subprocess per node**.

Point it at your host's headless command once (no config edit needed):

```bash
export RLR_HOST_AGENT_CMD='python my_agent.py --prompt {prompt_file} --out {output_file} --node {node} --persona {persona}'
python run_loop.py run <PROJECT_DIR> <CAND_ID>
```

The command **must write the delta JSON to `{output_file}`**. Or pin a
`command` provider in `rlr_runner.yaml` (see the commented templates there).

**If no automatic provider resolves, the runner FAILS LOUD** and tells you to
configure `HostAgentProvider`/`CommandProvider` — it never falls back to manual.

```bash
# plan only — no model calls, no state changes
python run_loop.py run DemoProject_v03 <CAND_ID> --dry-run

# DEBUG manual mode (single-step, you paste each node's delta) — explicit only:
python run_loop.py run <PROJECT_DIR> <CAND_ID> --provider manual
```

Options: `--max-rounds N` (default 3), `--provider host|command|manual`,
`--dry-run`, `--stop-after-node L3`, `--no-review`, `--resume`.

`ManualProvider` is **debug/manual-test only**. It is never the default and is
never used as a fallback; enable it explicitly with `--provider manual`.

## Stop policy (the point: don't spin on "polish / new angle")

The question is **not** "are there issues" but **"would another round plausibly
change the conclusion"**.

**STOP** if: status in DROP/DOWNGRADE/ARCHIVED; KEEP + review accept/weak_accept;
`max_rounds` reached; REVISE with empty/non-executable next_steps;
`marginal_gain_score <= 2`; two consecutive rounds add no new key evidence;
L7 fails twice; review = reject.
**CONTINUE** if: L10b decision REVISE, or review major_revision, or next_steps
are concrete & executable — and `round < max_rounds`. A continue opens a **child
candidate** (`parent_candidate_id` + `round_id` recorded), never overwriting the
parent.

## Review gate

Optional external reviewer after L10c (reads FINAL_REPORT + L8/L9a/L9b/L10b,
returns scores + `review_verdict`). It is **only an input** to `StopPolicy`,
never the sole decider. If unavailable (no FINAL_REPORT, disabled, `--no-review`,
or no reviewer provider) it is skipped gracefully — the loop still runs on L10b +
StopPolicy.

## Audit

Each agent call writes a `RunReceipt` under
`08_Run_Receipts/<cand>/round_NN/<node>_<persona>_receipt.json`
(provider, context hash, prompt/delta paths, workspace, tools, EverOS scope,
`fresh_session`).

Context-pollution guard: every ManualProvider prompt opens with a "start a NEW
session, do not carry over the previous node's history" banner (EN+CN), and the
receipt records `fresh_session: true`. Disable per node with
`fresh_session: false` in the provider spec. CommandProvider is fresh by
construction (a new subprocess per node), so it records `fresh_session: true`.
The per-round `stop_decision.json` records why the loop stopped/continued. This
is separate from the controller's `08_Audit/` manifests+receipts.

## Current limitations (v1)

- **Automatic by default (`host`)** — a real run needs `$RLR_HOST_AGENT_CMD`
  (or a `command` provider) resolving to a headless command that writes the
  delta JSON to `{output_file}`. No automatic provider configured ⇒ fail loud.
  Vendor adapters (Codex/Claude/AntiGravity/Hermes) are intentionally **not**
  hard-coded; you supply the one-line command/wrapper. `ManualProvider` remains
  for debugging only (`--provider manual`).
- **L9a/L9b run sequentially** (the parallel interface is in place for later).
- **L10b structured scores** (evidence/method/novelty/...): the controller's
  L10b schema isn't changed; `StopPolicy` reads scores from the Review gate, or
  from L10b extra keys if a reviewer adds them. `marginal_gain_score` therefore
  comes from the Review gate in practice.
- **Round summaries are in-memory** within one `run` invocation; `--resume`
  recovers `round_id` from candidate frontmatter but not prior summaries.
- The runner trusts the controller's exit codes; it does not re-validate deltas
  itself (the controller already does, recursively).
