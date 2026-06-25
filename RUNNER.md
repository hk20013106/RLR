# RLR v0.3 Loop Runner

Two **new** files extend the RLR controller into a half/auto-automated,
provider-neutral loop runner. The controller (`research_loop_v03.py`) is
**unchanged** — these only call its CLI and read its outputs.

## Files

| File | Role |
|------|------|
| `orchestrator.py` | Provider-neutral agent invocation. `AgentProvider` interface + `ManualProvider` (human-in-the-loop) + `CommandProvider` (generic shell template). `ProviderConfig` (YAML/JSON; PyYAML optional). `RunReceipt`. **No** Codex/Claude/AntiGravity hard-coding. |
| `run_loop.py` | The loop. Drives the DAG via the controller, runs an optional Review gate after L10c, and a hybrid `StopPolicy` decides stop/continue. Bounded by `max_rounds` (default 3). |
| `rlr_runner.yaml` | Auto-generated default config in the project dir on first run. |

## Run

```bash
# plan only — no model calls, no state changes
python run_loop.py run DemoProject_v03 <CAND_ID> --dry-run

# real run (ManualProvider prompts you to run each node in your agent of choice)
python run_loop.py run <PROJECT_DIR> <CAND_ID> --config rlr_runner.yaml
```

Options: `--max-rounds N` (default 3), `--provider manual|command`,
`--dry-run`, `--stop-after-node L3`, `--no-review`, `--resume`.

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
(provider, context hash, prompt/delta paths, workspace, tools, EverOS scope).
The per-round `stop_decision.json` records why the loop stopped/continued. This
is separate from the controller's `08_Audit/` manifests+receipts.

## Current limitations (v1)

- **ManualProvider is the default** — a real run is interactive (you paste each
  node's delta JSON). `CommandProvider` exists for non-interactive external
  CLIs; Codex/Claude/AntiGravity adapters are intentionally **not** wired in.
- **L9a/L9b run sequentially** (the parallel interface is in place for later).
- **L10b structured scores** (evidence/method/novelty/...): the controller's
  L10b schema isn't changed; `StopPolicy` reads scores from the Review gate, or
  from L10b extra keys if a reviewer adds them. `marginal_gain_score` therefore
  comes from the Review gate in practice.
- **Round summaries are in-memory** within one `run` invocation; `--resume`
  recovers `round_id` from candidate frontmatter but not prior summaries.
- The runner trusts the controller's exit codes; it does not re-validate deltas
  itself (the controller already does, recursively).
