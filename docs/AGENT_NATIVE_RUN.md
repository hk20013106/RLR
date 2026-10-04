# Agent-native RLR run protocol

Use the host protocol when an agent is carrying the cognitive work. The runner
owns the RLR DAG, cursor, persistence, validators, and stop decisions. Each
command returns one current action and does not start a model or nested agent.

## Protocol

From the repository root, keep one host session and repeat:

```powershell
python run_loop.py host-next PROJECT CANDIDATE --config PROJECT/rlr_runner.yaml --resume
```

- For `needs_host`, read the immutable request at `request_path`, verify its
  `request_sha256`, perform only the cognition named by that request, save the
  raw response bytes, then submit them:

  ```powershell
  python run_loop.py host-submit PROJECT CANDIDATE REQUEST_ID RESPONSE_PATH --config PROJECT/rlr_runner.yaml --resume
  ```

- For `continued`, call `host-next` again. The existing controller and
  deterministic owners have advanced the state.
- Stop for `terminal` or `blocked`. A blocked action needs its stated gate or
  missing input resolved before the protocol can continue.

Pass `--knowledge-store PATH` when the project uses a shared hypothesis store
that is not already selected by `RLR_HYPOTHESIS_STORE`. A completed host
response is recovered from its persisted receipt; repeating a request must not
cause a second cognition call. L0.5 planner, semantic and scientific coverage requests remain owned
by the existing acquisition checkpoint and validators.

The request contains the authorized context artifacts and their hashes. Keep
the host's working context scoped to those artifacts. This is artifact-level
separation; it does not physically erase the host's current-session memory. If
the host process dies, reactivate it and resume with `host-next --resume` so
the runner can report the current persisted action.

The host protocol itself does not use `codex.CMD`, a Claude CLI, nested model
subprocesses, model API-key calls, or a silent headless fallback. It supplies
only the authorized response to the existing RLR owner.

## L0.5 cumulative PaperQA2 corpus

Select `paperqa2.worker_mode = "corpus-evidence-v1"` explicitly in the existing
`00_Preflight/deep_research_runtime.json`. Retain the existing interpreter,
bridge, repository and PQA_HOME paths. The same `paperqa2` object contains
native `settings` with explicit `embedding`, `embedding_config`, `summary_llm`
and `summary_llm_config`. Credentials come from the existing process environment,
not Settings artifacts. Corpus validation requires retrieval and summary,
disables text fallback, and bounds native summary concurrency to four.

The default `acquisition_budget` has `max_acquisition_attempts: 3`,
`new_papers_per_attempt: 30`, and `cumulative_paper_limit: 90`. These are upper
bounds. Discovery uses page size 25 without automatic pagination; early PASS
or fewer usable sources need not fill the budget. Configuration and the
original seed freeze in the existing acquisition checkpoint. Each native
worker uses the complete accumulated corpus and native `Docs.aadd_texts` /
`Docs.aget_evidence`. First-attempt focus is null; later retrieval focus can
only reference validated persisted coverage gaps. The semantic claim remains
the original question and hypothesis.

Answer `coverage:<attempt>` through the same host protocol. Only the current
host performs planner, semantic and coverage cognition. Worker embedding and
summary are the configured PaperQA2 calls; the host is never simulated by an
additional model. Source verification, semantic admission and coverage routing
remain RLR responsibilities. Logs and immutable task/settings/result/completion
artifacts are referenced by acquisition manifest v3; the pack stays version 1.

Legacy `l05-acquire-paperqa2-europepmc` retains its PDF-map contract, and ordinary
headless acquisition retains its previous semantics. They cannot take an active
corpus first-owner. L4/document helpers retain their callers; corpus execution
does not use their per-paper lexical query, fuzzy alignment, manual sparse
retrieval or structural section coverage.

Tasks 1–10 provide offline software validation. Live Europe PMC, configured
embedding/summary models, scientific coverage quality and real 30/60/90
acceptance require separate authorization; pytest success does not prove those.

## Explicit headless mode

`python run_loop.py run PROJECT CANDIDATE` remains the explicit headless runner
and dispatches the configured provider. Use it when the configured provider is
intended to perform node cognition. `host-next` and `host-submit` are separate
commands and do not silently change the `run` execution mode.
