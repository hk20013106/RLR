# RLR V0.7 Loop Runner

**Canonical runtime entry point:** `python run_loop.py run PROJECT CAND`. It
drives the V0.7 engine (`research_loop_v04.py`), whose `assemble-context`
enforces the Deep Research gate — L1/L4/L8.5 fail closed (rc=3) without a
successful ARS receipt and a valid source-located evidence pack.
(`rlr_v05b.py` is a LEGACY prototype, not the runtime.)

Three run modes, in order of recommendation:

## 1. Main-agent mode (RECOMMENDED)

The current host agent (Claude Code / Codex / AntiGravity / Hermes) acts as the
orchestrator. It loops through the DAG by calling `research_loop_v04.py` CLI,
playing each persona, generating delta JSON, and advancing state.

- No per-node copy-paste
- No Python provider needed
- The host agent IS the orchestrator

Start:
```bash
python run_loop.py print-main-agent-prompt PROJECT_DIR CAND_ID
```
This prints the orchestration protocol. Paste it into your host agent's chat.

Or read [MAIN_AGENT_RUN.md](MAIN_AGENT_RUN.md) for the full protocol and
[MAIN_AGENT_PROMPT.md](MAIN_AGENT_PROMPT.md) for a copy-paste starter prompt.

Default config (`rlr_runner.yaml`):
```yaml
mode: main_agent
max_rounds: 3
```

### Deep Research evidence (V0.7)

Before **L1 / L4 / L8.5** the runner invokes Academic Research Skills and embeds
the validated evidence result
into that node's `assemble-context` (the 14-node DAG is unchanged):

- **L1** Results/Discussion/Conclusion → **L4** Methods/review evidence →
  **L8.5** result verification evidence. L7 remains a separate code search.
- Configure `deep_research_runtime.json`; the runner calls
  `deep-research-run PROJECT CAND --node Lx` using Codex `$academic-research-suite`
  or Claude's configured ARS plugin. Missing configuration or invalid evidence
  is fatal for the literature node; there is no generic-headless fallback.

## 2. Headless command mode (UNATTENDED)

Python calls an external AI CLI/wrapper per node. True unattended execution.

```yaml
mode: headless
headless:
  enabled: true
  command: "your_wrapper --prompt {prompt_file} --output {output_file}"
```

Set `$RLR_HEADLESS_CMD` or configure `headless.command` in `rlr_runner.yaml`.
The command MUST write delta JSON to `{output_file}`.

```bash
python run_loop.py run PROJECT_DIR CAND_ID --provider headless
```

## 3. Manual debug mode (DEBUG ONLY)

Human-in-the-loop. User copies prompts and pastes delta JSON back. NOT for
production use.

```bash
python run_loop.py run PROJECT_DIR CAND_ID --provider manual
```

## StopPolicy

After L10c, the loop evaluates whether to stop or continue:
- STOP: KEEP + review accept; terminal status; max_rounds; REVISE with no
  executable next_steps; marginal_gain <= 2; L7 failed 2x.
- CONTINUE: REVISE with executable next_steps; review major_revision; round <
  max_rounds. Continue = create child candidate.

## Files

| File | Role |
|------|------|
| `run_loop.py` | Loop driver + print-main-agent-prompt command |
| `orchestrator.py` | Provider abstraction (HeadlessProvider, CommandProvider, ManualProvider) |
| `MAIN_AGENT_RUN.md` | Main-agent execution protocol |
| `MAIN_AGENT_PROMPT.md` | Copy-paste startup prompt for host agents |
| `research_loop_v04.py` | Core DAG controller (v0.4.5; called via CLI) |
