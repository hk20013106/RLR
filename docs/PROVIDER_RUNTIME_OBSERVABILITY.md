# Provider Runtime Observability Architecture

## Scope

This layer observes and supervises an external Deep Research provider. It does
not discover papers, retrieve source bytes, design methods, alter evidence
eligibility, or change a DAG transition.

## Current path and root cause

### Direct

`deep-research-run` -> `commands.research.cmd_deep_research_run` ->
`deep_research.run_and_persist` -> provider CLI.

Before this extension, `RuntimeSpec.timeout`, loaded from
`00_Preflight/deep_research_runtime.json` or a CLI override, was owned by
`run_and_persist`, and the provider was invoked with
`subprocess.run(..., capture_output=True, timeout=...)`. Provider stdout and
stderr were therefore buffered inside that call until exit or timeout.

### Detached

`deep-research-start` creates a task directory and launches
`_deep-research-worker`. The worker invokes the same synchronous
`cmd_deep_research_run`. Detachment alone moved the wait into another process
but did not change the inner provider boundary, so the worker previously could
observe only its own CLI stdout/stderr and final return code. The observability
extension now supervises the nested provider boundary directly.

## Reused Codex capability

The Codex CLI exposes the required primitives directly:

- `codex exec --json`: JSONL events on stdout;
- `--output-schema FILE`: constrain the final agent response;
- `--output-last-message FILE` / `-o FILE`: write the final response separately;
- `--ephemeral` and `--ignore-user-config`: retained from the existing command.

Observed event types include `thread.started`, `turn.started`, `item.started`,
`item.updated`, `item.completed`, `turn.completed`, `turn.failed`, and `error`.
Item types include `command_execution`, `mcp_tool_call`, `web_search`,
`reasoning`, and `agent_message`.

Therefore the provider path uses CLI streaming rather than a new heartbeat
protocol or an SDK/App Server migration:

```text
provider stdout              -> append-only events.jsonl
provider stderr              -> append-only stderr.log
--output-last-message        -> final_output.json
worker stderr / gate errors  -> append-only worker_stderr.log
```

The final structured response is never parsed from the event stream. Provider
and detached-worker diagnostics have separate ownership so the immutable
provider receipt cannot be invalidated by later evidence-gate or worker output.

## Signal ownership

### Codex semantic events

Codex events supply thread identity, turn lifecycle, current item identity and
item type. RLR projects only safe progress metadata into `status.json`: item
ID/type/status, MCP server/tool, command, or web query. Reasoning text and
agent-message content are not copied into ordinary status output.

A generic `error` event is recorded as provider diagnostic evidence but is not
by itself terminal: a real provider may emit an error and continue. A
`turn.failed` event, non-zero provider exit, timeout, or other terminal runtime
fact determines provider failure.

### RLR supervisor

The supervisor supplies facts Codex events cannot prove:

- worker/provider PID and process liveness;
- observer heartbeat;
- last provider-event time;
- event/stderr/final-output byte counts;
- elapsed job time;
- CPU and I/O counter changes when process telemetry is available;
- timeout ownership and process-tree cleanup.

These signals remain distinct. An observer heartbeat proves only that the
supervisor is alive. A live PID proves only that the provider process exists.
A provider event proves semantic activity. CPU/I/O changes prove process
activity without claiming useful scientific progress. The finalized receipt
retains the last known non-null process telemetry rather than replacing it with
an unavailable snapshot after process exit.

## Mutable runtime status

Mutable state belongs under:

```text
08_Audit/deep_research_runtime/tasks/<task_id>/
```

Files:

```text
request.json
status.json
stdout.log                 detached worker result envelope compatibility
events.jsonl               provider semantic stream
stderr.log                 provider diagnostics; immutable-receipt bound
worker_stderr.log          detached worker / validation diagnostics
final_output.json          final structured provider response
runtime_receipt.json       finalized immutable provider runtime receipt
result.json                completed evidence-run result compatibility
```

`status.json` is atomically replaced and revisioned. Revisions are monotonic
across provider observation and detached-worker finalization. Its state may be
`starting`, `running`, `waiting_external`, `validating`, `persisting`,
`succeeded`, `provider_failed`, `validation_failed`, `job_timed_out`,
`inactivity_timed_out`, `cancelled`, `provider_dead`, or `transport_lost`.
Legacy `DeepResearchDetachedTask/v1` status remains readable.

Provider success is not identical to detached-task success. After provider
completion, evidence validation may still fail closed. In that case the
provider receipt can record successful provider execution while the final task
status is `validation_failed`; `result.json` is not created unless the enclosing
command succeeds.

The implementation retains the existing job timeout. It does not add a default
inactivity timeout because reliable event/process activity measurement must
exist before inactivity policy can be justified.

## Immutable receipt

`ProviderRuntimeReceipt/v1` is finalized after provider termination and process
cleanup. It binds task/candidate/node/backend, provider version, command and
prompt hashes, timestamps, PID/thread ID, provider terminal status, exit code,
last successful event, termination reason, provider artifact paths/hashes/bytes,
timeout facts, last known process activity, and process-tree cleanup results.

The receipt owns `events.jsonl`, provider `stderr.log`, and `final_output.json`.
`worker_stderr.log` is intentionally outside this provider receipt because the
detached worker can continue through persistence and evidence validation after
the provider receipt has already been finalized.

The existing evidence/tool receipt references the finalized runtime receipt by
relative path, schema, and SHA-256. High-frequency status is not copied into the
scientific hypothesis ledger and is not part of an in-progress scientific
artifact hash.

## Scientific boundaries

- L4A remains cognitive method inventory and identifier-first source discovery.
- L4B remains deterministic exact-source acquisition, source-byte retention,
  Methods extraction, evidence cards, and truthful gaps. It does not create
  components, candidates, eligibility, or `execution_required`.
- L4C remains Fisher's cognitive method design. It consumes exact L4A and L4B
  artifacts and creates evidence-bound components and candidates.
- L4.5 remains deterministic lineage, hash, and required-path validation.
- L5 consumes the committed L4.5 method projection to critique assumptions,
  QC, and failure rules. It does not redo L4A discovery, L4B acquisition, or
  L4C selection.

Thus L4C -> L5 is design -> critique; L4.5 -> L5 is immutable validated
projection -> downstream QC. Runtime observability is provider infrastructure
below those scientific stages and cannot alter their authority, contracts, or
gates.

## Ten review answers

1. Direct invokes the provider synchronously; detached invokes that same path in
   a background worker.
2. The provider invocation layer owns the current job timeout.
3. The old `subprocess.run(capture_output=True)` boundary buffered provider
   stdout/stderr; the new boundary streams them separately.
4. Detached runtime status now observes provider lifecycle as well as the outer
   worker finalization state.
5. Codex thread/turn/item/error events are provider progress/diagnostic signals;
   a generic `error` is not necessarily terminal.
6. PID/liveness, observer heartbeat, CPU/I/O activity, byte counts, timeout, and
   cleanup come from the RLR supervisor.
7. Mutable status belongs only in the runtime task directory and revisions remain
   monotonic through finalization.
8. The provider runtime receipt is generated after provider exit/termination and
   cleanup, before later worker/evidence-gate diagnostics can mutate its files.
9. The evidence/tool receipt binds the finalized runtime receipt
   path/schema/hash; provider and worker stderr are separate files.
10. The change is orthogonal to and preserves L4A/L4B/L4C/L4.5/L5 authority.
