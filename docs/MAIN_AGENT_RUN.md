# Main-agent mode retirement notice

The historical host-session main-agent orchestration path is retired.

RLR has one production orchestration path:

```text
run_loop.py run
→ preflight / restore / static closure
→ run_round
→ AgentProvider
→ canonical provider output
→ RunReceipt
→ emit-delta
→ HypothesisLedger
→ advance
```

Configure node cognition under `provider.default` and optional
`provider.nodes.<node>` entries in `rlr_runner.yaml`. Supported automatic
provider names are `headless`, `host`, `auto`, and `command`;
`manual` remains an explicit debug-only backend.

Legacy configurations containing `mode: main_agent` fail closed. Remove that
line and configure the `provider:` section instead. A CLI
`--provider main_agent` override is also rejected.

The compatibility command `print-main-agent-prompt` remains only so old
automation receives a clear migration error on stderr and a non-zero exit code.
It no longer emits an orchestration protocol.

Providers are node cognition backends. They do not own DAG orchestration,
receipt schemas, state transitions, or ledger persistence. See
[AGENT_CONTEXT.md](AGENT_CONTEXT.md) and [DAG_TOPOLOGY.md](DAG_TOPOLOGY.md)
for the current architecture.
