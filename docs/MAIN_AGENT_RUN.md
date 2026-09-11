# Main-Agent Run Protocol (RLR V0.9)

> Native v2.1: L0.5/L4/L8.5 use the canonical Curie-owned evidence paths and
> `assemble-context` fails closed without their exact receipts and located
> evidence. Historical profiles retain the `deep-research-run` compatibility
> path and its original evidence-pack contract.

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

Before the loop, run `micromamba run -n rlr python research_loop_v04.py preflight PROJECT` (or
`check-deps PROJECT`). This is the **L0 hard gate**: it verifies every required
dependency listed in `00_Preflight/dependencies.md` (framework: PyYAML; plus any
project deps you declare, e.g. `- command: Rscript`). If any required dependency
is **MISSING, the command exits non-zero and you MUST HALT** — do not proceed to
L1, do not skip. Install the missing dependency, re-run preflight, then continue.
`run_loop.py` enforces this automatically before round 1.

For a Codex-hosted PowerShell session, set `$env:RLR_HOST_BACKEND='codex'`
before the first command. Do not set that value on a non-Codex host. Every
formal RLR command, including the canonical runner and its L0 stop run, must
use `micromamba run -n rlr python`; the runner performs the fail-closed formal
runtime preflight before controller/provider startup.

Before a native contextual L4A/SPECTER2 run, also run the heavy formal
runtime gate. It verifies the `rlr` interpreter, the PaperQA2/SPECTER2 stack,
and one real adapter forward; a non-zero result is a hard stop:

```powershell
micromamba run -n rlr python -m research_loop.runtime_preflight
```

## Profile-owned evidence

Native `v2.1-catalog-1` projects do not invoke the Academic Research Skill as a
pre-research dependency. L0.5 freezes the canonical Curie multisource
EvidencePack for L1; L4 uses Curie multisource/PaperQA2/verifier evidence; and
L8.5 verifies findings derived from the actual L7/L8 results. These receipts and
evidence blocks are injected by the profile-owned context path.

Historical profiles retain Deep Research before L1, L4, and L8.5. The command
name remains profile-aware and does **not** change the 15-node DAG topology:

| Before | Step | What you do |
|--------|------|-------------|
| **L0.5** (native L1 input) | Curie multisource | Freeze source-located EvidencePack and bind it to native L1. |
| **L4** (native method design) | Curie multisource + PaperQA2/verifiers | Persist exact method inventory, source-located Methods evidence, and truthful gaps. |
| **L8.5** (native verification) | finding-derived Curie verification | Verify exactly the actual L7/L8 findings; DOI/PMID metadata alone is not verification. |
| **L1/L4/L8.5** (historical profiles) | Deep Research compatibility | Persist the historical source-located evidence pack under the original contract. |
| **L7** (execution) | code search | Search GitHub / Bioconductor / CRAN for existing pipelines; summarize reusable tools and the gap you must write yourself. |

For native projects, use the profile-owned `next-step`/`assemble-context` path
and the profile-aware `deep-research-run` entry point only where the stage
requires an explicit run. It uses the existing Curie multisource, PaperQA2,
and independent verifier owners; it does not add an Academic Research
Skill/plugin, second retriever, identity/dedup layer, verifier, or EvidencePack
owner. For historical profiles, the same command retains the configured
historical runtime and compatible note.

## Step-by-step protocol

For native v2.1 emissions, `RECEIPT` must bind the exact raw file passed as
`--file`; do not reserialize or copy that provider artifact before emission.
At L4, Fisher uses only the E/G/A handles in assembled context. The
`emit-delta` commit boundary resolves those handles to the frozen L4B registry,
persists the canonical delta once, and records the raw-to-canonical provenance
edge.

```
while not terminal:
    1. step = micromamba run -n rlr python research_loop_v04.py next-step PROJECT CAND
    1b. # Evidence is profile-owned: native Curie stages bind their canonical
        # receipt/evidence block; historical profiles run the compatibility
        # command before L1/L4/L8.5.
        if historical_profile and step.node in (L1, L4, L8.5):
            micromamba run -n rlr python research_loop_v04.py deep-research-run PROJECT CAND --node step.node
    2. if step.is_parallel:  # historical v2.0 L9a + L9b only
         for sub in step.nodes:
             ctx = micromamba run -n rlr python research_loop_v04.py assemble-context PROJECT CAND --node sub.node
             delta = act_as(sub.persona, ctx)
             write delta to temp file
             micromamba run -n rlr python research_loop_v04.py emit-delta PROJECT CAND --node sub.node --persona sub.persona --file temp.json --context-manifest MANIFEST --provider-receipt RECEIPT
    3. elif step.is_execution:  # L7 Turing
         micromamba run -n rlr python research_loop_v04.py prepare-turing-workspace PROJECT CAND
         run approved scripts in the workspace
         build L7 delta from results
         micromamba run -n rlr python research_loop_v04.py emit-delta PROJECT CAND --node L7 --persona Turing --file delta.json --context-manifest MANIFEST --provider-receipt RECEIPT
    4. else:  # cognitive node
         ctx = micromamba run -n rlr python research_loop_v04.py assemble-context PROJECT CAND --node step.node
         delta = act_as(step.persona, ctx)
         write delta to temp file
         micromamba run -n rlr python research_loop_v04.py emit-delta PROJECT CAND --node step.node --persona step.persona --file temp.json --context-manifest MANIFEST --provider-receipt RECEIPT
    5. run step.advance_command (decision / triage-idea / triage-method / execution-gate)
    6. if step.node == L10c:
         micromamba run -n rlr python research_loop_v04.py aggregate-report PROJECT CAND
         # REQUIRED end-of-round step: sync human-readable output to Obsidian
         micromamba run -n rlr python sync_to_obsidian.py PROJECT --cand CAND   # needs $OBSIDIAN_VAULT
         evaluate StopPolicy
         if stop: break
         else: create child candidate, continue
```

## End-of-round Obsidian sync (REQUIRED)

After `aggregate-report` at the end of **every round**, run
`micromamba run -n rlr python sync_to_obsidian.py PROJECT --cand CAND`. It writes the human-readable
view (per-node NOTE.md, ROUND_SUMMARY, figures, FINAL_REPORT, index) into the
vault at `$OBSIDIAN_VAULT/ResearchLoop/<project>/`. Set `$OBSIDIAN_VAULT` (or
pass `--vault`) first; if it is unset the script fails loud and writes nothing
(it does NOT create stray directories). This is part of the loop, not optional.

## L7 Turing workspace

Turing is the only node with filesystem access (Path A). Use
`prepare-turing-workspace` to create an isolated workspace. Run R/Python scripts
only inside that workspace. Copy results out, build the L7 delta JSON, emit it.

## L9a/L9b native sequence

Native v2.1 runs are serial. Generate and finalize L9a first. Only then
assemble L9b: its context contains the exact L9a snapshot authorized by the
fixed ledger cursor, never arbitrary repository state. L9a never sees L9b.
Historical v2.0 verification retains parallel, mutually invisible L9a/L9b and
cannot create new emissions.

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
