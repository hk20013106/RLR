# Main-agent startup prompt retirement notice

The copy-paste main-agent startup prompt is retired and is intentionally not
reproduced here.

Use the canonical runner instead:

```powershell
C:\Users\hk200\miniforge3\envs\rlr\python.exe run_loop.py run PROJECT_DIR CAND_ID
```

Configure execution in `PROJECT_DIR/rlr_runner.yaml`:

```yaml
provider:
  default:
    type: headless
    command: 'YOUR_COMMAND {prompt_file} {output_file}'
```

The command provider must write the node's canonical JSON output to
`{output_file}`. L7 pre-research free text uses the same provider object and
command authority.

If an old project contains `mode: main_agent`, remove it. RLR rejects that
mode rather than silently reinterpreting it as another provider. The
`print-main-agent-prompt` compatibility command exits non-zero and writes a
migration message to stderr.
