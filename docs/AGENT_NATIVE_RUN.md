# RLR Agent E2E Runbook

This is the operating guide for an AI agent using RLR on a user's scientific
question. Read it with the repository `AGENTS.md`; executable code, validators,
and the bound project profile remain authoritative. The goal is to carry one
request through the existing public lifecycle without making the user prompt
each next command:

```text
scientific input → matching/new project → preflight → candidate
  → host-next → current-host cognition → host-submit → resume
  → L0.5 evidence freeze → downstream DAG → next round or terminal report
```

This guide documents existing behavior. It does not add runtime enforcement,
change an owner, or authorize live research, external calls, installation, or
changes to project configuration. In the agent-native path, the current Codex
session is the only cognition owner. `host-next` and `host-submit` use RLR's
existing persisted host protocol; they do not launch a second model. The
headless `run` command is a separate, explicit execution mode.

Use existing RLR lifecycle owners in this order: **use the existing system
directly → adapt its boundary → reuse its components → extend/refactor RLR →
create**. An E2E run follows public behavior; it does not add runtime gates or
serve as an exhaustive sweep for unrelated software failures. At every host
boundary the existing transaction invariant is: model output is a proposal →
validate → persist → receipt/hash → advance.

## What the user needs to provide

The user can start with only:

1. The scientific question, observation, or research topic.
2. The RLR repository/runbook when it is not already clear from the task.

The agent discovers existing projects, runtime bindings, accessible inputs,
and repository conventions before asking for paths or configuration. Scope
constraints and an explicit hypothesis are helpful but not required. The agent
may choose project/candidate labels and draft a candidate claim that is
traceable to the user's question and discovered facts; the claim remains a
proposal for the existing RLR owners to validate. It must not invent data,
provenance, results, citations, or user preferences.

Ask only when a missing fact changes the science or an action the user owns:
which of two incompatible inputs is intended, a source is inaccessible, access
authorization is needed, the scope materially changes the question, or a
required provider/runtime value is genuinely absent. Do not ask the user to
choose ordinary names, commands, or settings already fixed by the repository.
If a required environment, PaperQA2 binding, provider credential, or runtime
setting is absent, report the exact missing item and stop; do not install,
switch providers, borrow another project's readiness authority, or put a
secret in a file.

## Execution environment and startup prerequisite

Run public RLR CLI commands from the repository root in the canonical `rlr`
environment; do not assume the current shell is activated. On this workstation,
`AGENTS.md` specifies the canonical interpreter and prefers direct invocation
from the active `rlr` environment. The formal launcher for RLR-owned
subprocesses remains `formal_runtime_command()` in
`src/research_loop/runtime_preflight.py`. The `micromamba run -n rlr python ...`
prefix shown in this Runbook is the repository's documented CLI example; use it
only when it resolves to the same pinned interpreter and satisfies the formal
environment-marker checks. Do not handcraft a replacement launcher.

Before running `preflight`, `new-candidate`, `host-next`, `host-submit`, `run`,
or `research`, confirm the formal runtime gate in
`src/research_loop/runtime_preflight.py` passes for the invocation and
environment you will use:

```powershell
micromamba run -n rlr python -m research_loop.runtime_preflight
```

Continue only when the report says `status=PASS` and its `sys_executable` is the
canonical interpreter from `AGENTS.md`. Run the requested command through that
same verified environment. Repeat the check after a shell restart or any
interpreter/environment change. If the gate rejects the interpreter or
environment markers, classify it as **DRIVER / INVOCATION / ENVIRONMENT**,
correct the invocation using the existing RLR environment owner, and rerun the
gate; do not change production code or make a run-specific recovery step a new
runtime rule.

## Select or resume the right project

Inspect the user's existing RLR projects and the requested scientific input
before creating anything. Continue an appropriate existing lineage when its
input, scope, and readiness still match. Apply the following decision:

| Observed state | Next public action |
|---|---|
| No matching project exists | Create a project with `new-project`, then run its normal `preflight`. |
| Project exists, has no valid readiness receipt, and no candidate has consumed readiness | Run the existing `preflight` owner; do not hand-edit readiness artifacts. |
| Project is ready and has no candidate for this input | Create a candidate with `new-candidate`. |
| Candidate already exists | Resume that candidate with `host-next --resume`. Do not create a duplicate candidate to avoid recovery. |
| `host-next` reports a persisted `next_candidate_id` | Start that exact child round and resume it. |
| A consumed candidate's receipt/config provenance no longer matches | Stop and classify `INTEGRITY / RECOVERY`. Do not re-attest, re-pin, or force-refresh consumed authority. |

Do not copy a prior project's readiness authority, candidate pin, or
acquisition checkpoint into a new project. A new project is appropriate when
no existing lineage matches or when the user explicitly requests a fresh
acceptance lineage; create it through the public lifecycle and run normal
preflight again.

## Start a fresh project

Use this section only when the project decision above selects a new project.
Work from the intended RLR checkout and its documented environment. First read
the applicable `AGENTS.md`, confirm the repository root and working-tree state,
and inspect existing project/runtime configuration for reusable approved
settings. Keep generated research projects outside the source checkout unless
the user or repository convention specifies otherwise. Use the activated
shared hypothesis store already selected for this RLR environment; a native
project must be bound to it.

The default `new-project` profile is the current native v2.1 profile. Create a
new project and complete preflight **before** creating a candidate:

```powershell
$repo = "D:\research_loop\main"       # Use the checkout actually running RLR.
$project = "D:\research_loop\projects\<project-name>"
$store = $env:RLR_HYPOTHESIS_STORE   # Or the existing approved shared store path.
if (-not $store) { throw "Select the existing approved RLR_HYPOTHESIS_STORE first." }
$env:RLR_HYPOTHESIS_STORE = $store
# Resolve these four values from the pinned PaperQA2 installation/configuration.
# $paperqaPython = ...
# $paperqaBridge = ...
# $paperqaRepo = ...
# $pqaHome = ...
Set-Location $repo

micromamba run -n rlr python research_loop_v04.py new-project `
  $project "<short research topic>" --knowledge-store $store

micromamba run -n rlr python research_loop_v04.py preflight $project `
  --backend codex `
  --paperqa-python $paperqaPython `
  --paperqa-bridge $paperqaBridge `
  --paperqa-repo $paperqaRepo `
  --pqa-home $pqaHome
```

Set the four `$paperqa...` values from the existing pinned PaperQA2 installation
and approved runtime binding. A native v2.1 project requires a complete
PaperQA2 binding; preflight either uses an existing complete binding or takes
all four flags together. Do not use guessed paths. Omit the flags only when the
new project's runtime already contains a complete approved binding. Preflight
is the owner that writes the readiness receipt. Do not edit that receipt or
run `preflight --force` to repair a candidate that already consumed it.

Check the actual preflight result and validate the project-ready receipt before
proceeding. A warning is not automatically a blocker; follow the readiness
result and named consumer. If preflight fails, keep its receipt/logs and
classify the first blocker before taking a dependent step.
Before invoking preflight, inspect the active readiness configuration: a
readiness-only PubMed MCP probe may start the configured process (the default
uses `npx`). In an offline run, invoke preflight only when the isolated
project's probe configuration is proven not to make network calls. Preserve a
warning or unavailable result as such; it does not establish readiness of that
consumer. If no safe offline route exists, stop before the probe and do not
claim `PROJECT_READY`. Do not alter production configuration or forge a
successful probe result to pass the gate.

Create the candidate from the question, a testable claim, and the actual source
input declaration:

```powershell
micromamba run -n rlr python research_loop_v04.py new-candidate $project `
  --title "<concise candidate title>" `
  --question "<frozen scientific question>" `
  --claim "<testable claim/hypothesis>" `
  --input "<plain-language source description>" `
  --input-type files --input-files "<absolute input path>" `
  --input-format "<format>"
```

For a dataset or other supported source declaration, use the corresponding
existing `--input-type`, `--input-location`, `--input-format`, or
`--source-input-file` options shown by `research_loop_v04.py new-candidate
--help`. Use `inline` only when the scientific input truly is inline text. Save
the candidate ID printed by the command. Do not hand-edit the generated L0
contract or candidate status.

## Drive the current-host lifecycle

From the same checkout and environment, use `host-next` / `host-submit` for
agent-native work. Keep the project, candidate, shared store, and runner config
consistent across calls:

```powershell
$candidate = "<candidate-id>"
$config = Join-Path $project "rlr_runner.yaml"
micromamba run -n rlr python run_loop.py host-next $project $candidate `
  --config $config --resume
```

`host-next` returns one JSON action. Interpret its `status` as follows:

| Status | Agent action |
|---|---|
| `needs_host` | Wire value for conceptual **NEEDS_HOST**. Read and hash-check the exact request; perform only the requested cognition in this current session; save a response matching its output contract; submit it with `host-submit`. |
| `continued` | The existing deterministic owner advanced or completed an internal stage. If it includes `next_candidate_id`, switch to that persisted child candidate. Otherwise call `host-next --resume` again for the same candidate. |
| `terminal` | Stop this candidate/round when there is no persisted child. Read the terminal result and final artifacts; an explicit stop such as L0.5 insufficiency is not a completed scientific run. |
| `blocked` | Stop dependent work. Preserve the exact request, response, logs, and error; classify the first blocker and ask only for missing user-owned input/authorization. Do not bypass the gate. |

The agent's next action must be one of these decisions, based on the persisted
result: **CONTINUE** the same candidate; **WAIT FOR USER** for a missing
scientific fact, access authorization, or user-owned choice; **BLOCKED** while
preserving evidence and classifying the blocker; **FROZEN / TERMINAL** when the
current evidence pack or RLR run reached its corresponding persisted state;
or **START NEXT ROUND** only for the `next_candidate_id` returned by RLR.
These are operating decisions, not new protocol statuses.

### When `host-next` returns `needs_host`

1. Treat the action's `status=needs_host` as the conceptual **NEEDS_HOST**
   handoff. Confirm the request identity matches the active project,
   candidate, round, node, and stage. Verify `request_path` has the advertised
   `request_sha256` before using it.
2. Read only the request's authorized rendered context and inputs. Follow its
   persona, allowed-tools policy, and exact output contract. The current Codex
   session is the host cognition owner; do not start or call another model to
   impersonate it. Ask the user only if the request reaches a user-owned
   decision or needs a missing authorized fact.
3. Write a new response file matching the declared schema or host text
   contract, then submit the exact `request_id` and response path:

   ```powershell
   micromamba run -n rlr python run_loop.py host-submit $project $candidate `
     $requestId $responsePath --config $config --resume
   ```

4. Confirm `host-submit` reports `committed`. Then continue automatically:
   for ordinary node cognition call `host-next --resume`; for L0.5 acquisition
   cognition first inspect the returned `continuation`, which may already name
   the next host request, report progress, or return a terminal result. Do not
   ask the user for another prompt between valid host stages, and do not repeat
   cognition merely because the process restarted.

`host-submit` validates and commits through the existing RLR owner. A rejected,
stale, or hash-mismatched request is a blocker, not permission to reconstruct
the request or force a status transition. If Codex or the shell restarts, keep
the same project/candidate/config, call `host-next --resume`, and continue from
the action it returns.

`next-step` is useful for inspecting the controller's current DAG dispatch.
`assemble-context` is the public owner for assembling a node's authorized
context. During a live host handoff, use the exact context manifest and
rendered-context artifacts bound into the request; do not assemble a different
context or manually combine node artifacts. `deep-research-run` and its
start/status/collect variants are explicit public research workflows for their
supported consumers. Use them when the active owner directs that workflow;
they do not replace or advance the current host protocol. `run PROJECT CANDIDATE`
is the separate headless mode and dispatches configured providers; it is not a
fallback for current-host cognition.

## L0.5 cumulative PaperQA2 corpus

For the current native profile, L0.5 Curie owns literature discovery and
acquisition before L1. Its existing flow is:

```text
RLR scientific intent
  → (when the bound mode enables it) pinned PaperQA2 native keyword proposals
  → RLR validation as QueryPlan/v2
  → Europe PMC discovery/acquisition
  → cumulative corpus and native PaperQA2 evidence worker
  → SourceVerifier → SemanticVerifier → current-host coverage decision
  → FROZEN evidence pack or validated gap/replan
```

The PaperQA2 helper proposes keyword searches only. RLR validates the proposal;
Europe PMC remains the sole literature discovery/acquisition owner. PaperQA2
does not own scientific intent, select or rewrite a focus, decide source
identity, admit semantic claims, or decide coverage. The existing PaperQA2
`Docs` retrieval, summarization, relevance, and corpus worker own their native
operations; do not reproduce them in RLR or this runbook. `host-next` returns a
host action only when current-session cognition is needed. The host may receive
planner, semantic-verification, or coverage requests. Answer only the precise
request using its authorized context and contract, then submit through the same
`host-submit` command.

When the L0.5 continuation has `terminal_status=FROZEN`, the evidence pack has
been committed and bound for L1. It does **not** mean the candidate or whole
DAG is finished. Resume with `host-next --resume`; the controller selects L1.
`NO_ADMISSIBLE_REPLAN` also returns control to the existing DAG path. A
terminal result with `terminal_status=L0_5_INSUFFICIENT_STOP` records downstream
nodes as `NOT_ATTEMPTED`; do not call it a successful full E2E result.

Keep these two kinds of iteration separate:

- An L0.5 validated and persisted evidence gap may authorize a bounded
  replan/next acquisition attempt inside the same candidate's frozen-question
  acquisition run. Only that bound gap can supply optional retrieval focus; it
  may change corpus retrieval but cannot change the original scientific
  question, hypothesis, semantic claim, or coverage authority. Coverage PASS
  does not trigger another acquisition attempt. Follow the exact host request
  and configured attempt/paper limits; do not create gaps, alter queries, or
  pad paper counts to reach a target.
- A **new scientific RLR round** is created only when the committed L10b
  `REVISE` decision and the existing StopPolicy persist a `next_candidate_id`.
  Follow that child ID from `continued`, preserve its parent/memory/input
  lineage, and invoke `host-next --resume` for that candidate. Do not create a
  round merely because a local gap remains or a node emitted a suggestion.

For the cumulative PaperQA2 corpus mode, use the already-approved project
binding and settings in `00_Preflight/deep_research_runtime.json`. The existing
native worker uses the bound PaperQA2 interpreter and native `Docs` retrieval;
do not reimplement retrieval, reranking, summarization, or relevance logic.
The default corpus budget values are upper bounds (three attempts, at most 30
new papers per attempt, at most 90 cumulative papers). Early scientific PASS
or fewer usable discoveries may end below those limits. Task receipts and the
acquisition manifest are the evidence of what ran. Offline tests do not prove
live Europe PMC, embedding, summary-model, source-verification, semantic, or
scientific-coverage acceptance.

## Continue through downstream nodes

Use the same `host-next` / `host-submit` loop after L0.5. RLR chooses the next
node and deterministic action from the bound profile and persisted state; do
not manually invoke a later node to skip a gate. The current native order is:

```text
L0 → L0.5 → L1 → L2 → L3 → L4 → L5 → L6 → L7 → L8 → L8.5
   → L9a → finalized L9a snapshot → L9b → L10a → L10b → L10c
```

The current host supplies only the cognition requested by each returned action.
RLR and its existing deterministic owners persist deltas, apply formal
transitions, prepare the controlled L7 workspace, aggregate L10c reports, and
apply the round StopPolicy. At L7, execute only the approved plan in the
prepared allowlisted workspace. At L9b, wait for the authorized finalized L9a
snapshot. If any request is unclear, lacks required authorized evidence, or
asks for a user-owned decision, stop at that request and ask the smallest
necessary question.

After L10c, `host-next` may request the configured read-only REVIEW action
before applying the round StopPolicy. Complete it through the same host
protocol when requested. Then inspect the generated `FINAL_REPORT.md` and
`FINAL_REPORT_CN.md`, round receipt, and terminal/continuation record. The
round is terminal when
`host-next` reports `terminal` with a persisted stop decision and no child
candidate. If the status is `continued` with `next_candidate_id`, this is an
authorized new round: switch to that child and resume. A L0.5 insufficiency
record, a blocked action, or an offline test is not a completed scientific E2E
report.

## Classify blockers before acting

Record the first blocker, its stage, exact error/artifact path, and unattempted
dependent stages. Classify it as one of:

- **DRIVER / INVOCATION / ACCEPTANCE SCRIPT** — wrong arguments, environment
  activation, project/candidate/request ID, or orchestration step.
- **MODEL CONTRACT** — cognition output violates its declared persona/schema or
  asks for authority outside its contract.
- **PRODUCTION BUG** — existing owner or validator behaves contrary to its
  implemented contract.
- **ARCHITECTURE GAP** — no supported public lifecycle path can represent a
  required state or transition.
- **ENVIRONMENT / DEPENDENCY** — required interpreter, package, binding,
  credential, runtime, or service is unavailable.
- **INTEGRITY / RECOVERY** — hash, receipt, checkpoint, cursor, or consumed
  provenance cannot be validated through the public recovery path.

Ask the user only for a missing scientific fact, permission/access, or
user-owned choice; the other classes require a concrete blocker report. Preserve
first-failure evidence and stop dependent steps. If a run encounters sequential
blockers at different layers, stop and report the boundary instead of applying
a chain of compatibility patches. Do not diagnose unrelated historical test
failures during the scientific workflow. A synthetic/offline result is
software/workflow evidence only, not scientific completion.

## Final report to the user

Report the project and candidate/round IDs; frozen question and claim; declared
input sources; runtime/provider facts that were actually observed; each reached
stage and its persisted receipt/artifact; L0.5 discovered, verified, admitted,
and frozen evidence counts when applicable; coverage/replan outcome; final
status (`COMPLETED`, `BLOCKED`, or `INSUFFICIENT_STOP`); exact blocker; and all
unreached stages as `NOT_ATTEMPTED`. Separate real external/scientific E2E from
offline software validation. Do not expose credential values or imply that a
terminal report proves stronger scientific claims than its evidence supports.

## Minimal user start prompt

```text
Read docs/AGENT_NATIVE_RUN.md and use the existing public RLR lifecycle for my
scientific question/topic: <question>. Discover the matching project, inputs,
and approved runtime configuration; create a fresh project only if no suitable
lineage exists. Use this current session as the only host cognition owner.
Continue through host-next / host-submit and resume until RLR returns a
persisted terminal decision or a real blocker. Ask me only for a missing
scientific fact, access authorization, or decision that I own. Do not invent
evidence, alter scientific intent, switch providers, bypass a gate, or claim an
unreached stage passed. Report actual receipts and mark unreached work
NOT_ATTEMPTED.
```

## Runbook dry-run boundary

An offline Runbook dry-run checks whether an agent can select the right project
state, use the public commands, interpret `NEEDS_HOST`, submit a synthetic
contract-valid response, and resume to the next action without another user
prompt. It uses an isolated temporary project and synthetic inputs. Keep model,
Europe PMC, PaperQA2 summary/relevance calls, and other external services
disabled. If invoking public preflight, first prove the isolated project's
readiness probes cannot make network calls, and preserve any warning or
unavailable result without treating that consumer as ready. Never forge a
successful readiness result; if safe public preflight is unavailable offline,
stop before it and record that boundary. This checks operating instructions
and the existing lifecycle, not a new runtime gate, full regression, or
scientific E2E acceptance. Never describe synthetic responses as research
evidence.
