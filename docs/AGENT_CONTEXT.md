# Research Loop agent context

This is the compact architecture and operational context for an agent taking
over Research Loop (RLR). It complements, but never overrides, executable
code, validators, and tests.

## Read order

1. [`AGENTS.md`](../AGENTS.md): non-negotiable safety, scientific-integrity,
   compatibility, and verification rules.
2. This file: runtime map and handoff procedure.
3. [`DAG_TOPOLOGY.md`](DAG_TOPOLOGY.md) and
   [`MAIN_AGENT_RUN.md`](MAIN_AGENT_RUN.md): node protocol.
4. The narrow source module and test for the behavior being changed.

The project is an auditable scientific-research DAG. It prioritizes scientific
correctness, contract/provenance integrity, authority isolation,
reproducibility, then convenience. Never fabricate scientific evidence,
citations, datasets, hashes, lineage, or computed results.

## Runtime map

```text
run_loop.py                 public runner shim
research_loop_v04.py        public engine CLI / import-compatibility shim
src/run_loop.py             loop runner, main-agent orchestration protocol
src/research_loop/engine.py command dispatch, gates, persistence
src/research_loop/topology.py executable DAG, transitions, authority metadata
src/research_loop/context.py scoped cognitive-context assembly
src/research_loop/delta.py  delta schemas and candidate-owned resolution
src/research_loop/gates.py  boundary gates and traceability checks
src/research_loop/l0_contract.py strict L0 contract and authoritative validator
src/research_loop/deep_research.py ARS evidence receipts/packs
src/research_loop/providers/ optional non-main-agent providers
src/research_loop/api.py    runner-to-engine in-process CLI-compatible facade
```

Run public commands from the repository root:

```powershell
python research_loop_v04.py --help
python run_loop.py --help
python run_loop.py run PROJECT CANDIDATE
```

The historical `research_loop_v04.py` filename is an intentional compatibility
surface. Do not silently change CLI spelling, public shims, schema meaning,
artifact locations, or provider interfaces.

## DAG, authority, and isolation

The executable source of truth is
[`src/research_loop/topology.py`](../src/research_loop/topology.py).

```text
L0 → L1 → L2 → L3 → L4 → L5 → L6 → L7 → L8 → L8.5
                                               ↓
                                      { L9a ∥ L9b }
                                               ↓
                                      L10a → L10b → L10c
```

| Node(s) | Authority |
| --- | --- |
| L0 Linnaeus | Validate inputs, dependencies, capability plan; no code or scientific interpretation. |
| L1 Einstein / L2 Feynman | Generate and falsify testable hypotheses. |
| L3 Oppenheimer | Formal hypothesis triage through `triage-idea`. |
| L4 Fisher / L5 Tukey | Method design and QC/falsification. |
| L6 Oppenheimer | Formal method approval/rejection through `triage-method`. |
| L7 Turing | Only node allowed to execute the approved analysis plan. |
| L8 Curie / L8.5 Curie | Audit outputs/reproducibility, then literature verification. |
| L9a Feynman / L9b Darwin | Parallel result falsification and biological interpretation. |
| L10a Jobs / L10b Oppenheimer | Value assessment, then formal final decision. |
| L10c Linnaeus | Aggregate final reports; never chooses a new winner. |

Only declared decision commands may change candidate status. The optional
ranking system is advisory; it must never change a formal transition, candidate
selection, or gate result.

### Path B: cognitive context invisibility

For any cognitive node, call `assemble-context` and use only that output. It
uses the node's `context_inputs` in `topology.py`. Do not read a disallowed
delta file directly, manually merge contexts, or carry private reasoning from
one persona to another.

L9a and L9b are mutually invisible while they run. Both must be emitted before
downstream nodes combine their outputs.

### Path A: controlled execution

L7 alone runs code. First call `prepare-turing-workspace`; execute only
approved scripts inside that prepared allowlisted workspace; record exit codes
and output files in the L7 delta. A workspace does not permit executing an
unapproved plan or touching arbitrary project paths.

## State, contracts, and fail-closed gates

Candidate identity and its input provenance persist after creation. State moves
through schema-validated deltas and explicit commands, not handwritten status
edits.

- Use `emit-delta` to validate and persist a node result.
- Use `decision`, `triage-idea`, `triage-method`, and `execution-gate` only at
  their designated transition boundaries.
- Keep hypothesis, decision, conclusion, round lineage, and memory hash as
  separate fields.
- Keep audit and pitfall records append-only unless a versioned migration says
  otherwise.
- Revalidate an on-disk artifact and hash immediately before the consuming
  boundary, especially provider dispatch.

L0 is strict. `research_loop.l0_contract.validate_l0_input_contract` is the
single authoritative validator. It requires explicit `round_type`, verifiable
input provenance, existing local paths, and stable/verified remote locators.
Legacy data may be read but must be explicitly migrated before entering L0.

Never bypass a gate with a sentinel, `verified: false`, inferred lineage,
weakened validation, swallowed error, or a fixture change made only to hide a
real production failure.

## Evidence and research stages

Before L1, L4, and L8.5, run:

```powershell
python research_loop_v04.py deep-research-run PROJECT CANDIDATE --node NODE
```

The Academic Research Skills path persists source-located evidence, receipts,
metadata, and an evidence pack. `assemble-context` fails closed when required
evidence is missing or invalid. L7 instead has its own code-search step for
existing pipelines; do not substitute one for the other.

Separate observed inputs, computed results, and interpretation in all deltas
and reports. A passing synthetic test is evidence of software behavior only,
not a scientific conclusion.

## Main-agent operating loop

For Codex, Claude, Antigravity, or similar hosts, the normal mode is
**main-agent mode**: the host agent orchestrates the DAG itself. It does not
use a Python provider for those cognitive steps.

```text
preflight / check-deps
repeat until terminal:
    next-step
    deep-research-run before L1, L4, and L8.5
    assemble-context for the active node
    create a schema-conforming delta
    emit-delta
    execute the declared advance command
L7: prepare workspace → execute approved scripts → emit L7 delta
L9: emit L9a and L9b independently
L10c: aggregate-report → human-readable sync → StopPolicy
```

Use `next-step` instead of reconstructing control flow from memory. It returns
the active node(s), persona, allowed context inputs, and advance command.

After L10c, stop for terminal outcomes. For a genuine `REVISE` decision with
executable next steps, create a child candidate with lineage; do not overwrite
the parent candidate to represent another round.

The prescribed end-of-round human-readable sync needs an explicit Obsidian
vault (`OBSIDIAN_VAULT` or `--vault`) and fails loudly if unavailable.

## Providers and artifacts

`providers/` offers explicit optional non-main-agent paths:

- `HeadlessProvider`: unattended configured host command.
- `CommandProvider`: explicit command template.
- `ManualProvider`: debugging/manual operation.
- `AgentProvider` and `RunReceipt`: common invocation/provenance contract.

`make_provider` has no silent default. Providers never import the engine;
preserve that dependency direction and pass only valid scoped context.

Stable project artifact anchors include:

- `01_Candidates/<candidate>.md`: candidate identity/frontmatter.
- `02_Agent_Notes/_pre_research/<node>_research.md`: compatible pre-research
  summary path.
- `08_Audit/`: audits and advisory ranking artifacts.
- `09_Literature_Database/evidence_packs/`: verified research evidence.
- `_turing_workspace_*`: generated L7 controlled workspaces.
- `templates/layers/`, `templates/personas/`: prompt supplements, not authority
  sources.

Use public commands and path helpers rather than duplicating artifact-naming
logic.

## Fast takeover checklist

1. Read `AGENTS.md`, this document, the relevant DAG/run protocol, and the
   narrow test.
2. Check `git status --short`; preserve unrelated user changes and untracked
   files.
3. Trace the actual entry point and callers before editing a public function,
   command, schema, provider, or path.
4. Identify the narrow owner: topology, context, contract, gate, persistence,
   provider, or runner. Do not enlarge a god module.
5. For a schema change, analyse compatibility and add migration coverage.
6. Run targeted tests first; for production changes also run the full suite,
   `git diff --check`, and affected CLI/help checks.
7. Report observed commands/results and remaining unverified assumptions.

## Primary references

- [`AGENTS.md`](../AGENTS.md)
- [`DAG_TOPOLOGY.md`](DAG_TOPOLOGY.md)
- [`MAIN_AGENT_RUN.md`](MAIN_AGENT_RUN.md)
- [`README.md`](../README.md)
- [`src/research_loop/topology.py`](../src/research_loop/topology.py)
- [`src/research_loop/context.py`](../src/research_loop/context.py)
- [`src/research_loop/engine.py`](../src/research_loop/engine.py)
