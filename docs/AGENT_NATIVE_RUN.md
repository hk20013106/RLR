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
cause a second cognition call. L0.5 planner and semantic requests remain owned
by the existing acquisition checkpoint and validators.

The request contains the authorized context artifacts and their hashes. Keep
the host's working context scoped to those artifacts. This is artifact-level
separation; it does not physically erase the host's current-session memory. If
the host process dies, reactivate it and resume with `host-next --resume` so
the runner can report the current persisted action.

The host protocol itself does not use `codex.CMD`, a Claude CLI, nested model
subprocesses, model API-key calls, or a silent headless fallback. It supplies
only the authorized response to the existing RLR owner.

## Explicit headless mode

`python run_loop.py run PROJECT CANDIDATE` remains the explicit headless runner
and dispatches the configured provider. Use it when the configured provider is
intended to perform node cognition. `host-next` and `host-submit` are separate
commands and do not silently change the `run` execution mode.
