# Research Loop Room (RLR)

[English](README.md) | [中文](docs/README_CN.md)

**RLR turns a scientific question into a structured, evidence-gated, multi-agent research loop.**

RLR has **15 formal DAG nodes (L0 → L10c)** and **10 expert personas**. Each cognitive node sees only the information allowed by the DAG. Literature evidence is acquired through verifiable evidence packs, scientific data are authorized explicitly before execution, and only Turing (L7) may run code in a controlled workspace.

> **Core principle:** cognitive agents are isolated by information invisibility (Path B). Turing is isolated by an allowlisted workspace and command boundary (Path A). RLR does not pretend that an agent process is an operating-system sandbox.

## Current main status

`main` now contains the validated **V0.9 / native-v2.1 architecture line**.

The default native profile is `v2.1-catalog-1`. The current mainline includes:

- **Round-data continuity (PR #16):** continuation rounds can explicitly reuse verified prior artifacts, combine them with new data, freeze a single `CurrentRoundDataBinding/v1`, and guarantee that L7 stages only currently authorized scientific inputs.
- **L6 → L7 script-contract unification (PR #16):** structured script declarations retain traceability metadata (`name`, `grounding`, `branch_id`), while L6 gates and L7 execution resolve script names through the same contract owner.
- **Meta-RLR maintenance boundary (PR #17):** RLR software/runtime failures can enter an external maintenance loop without adding a scientific DAG node or a second scientific-state owner.
- **Meta-RLR historical scope correction (PR #18):** the Phase-1 architecture invariant is pinned to the exact qualified PR #17 range rather than treating all future RLR changes as Meta-RLR changes.
- **Promotion and governance (PRs #19–#21):** the validated stable line was promoted to `main`, and `AGENTS.md` now explicitly requires architecture-first, root-cause-first changes instead of patch stacks or parallel authorities.

PRs #19–#21 are governance/promotion changes; they do **not** add scientific runtime semantics.

---

## The scientific DAG

Current native sequence:

```text
L0 → L1 → L2 → L3 → L4 → L5 → L6 → L7 → L8 → L8.5
   → L9a → finalized L9a snapshot → L9b → L10a → L10b → L10c
```

Historical `v2.0-legacy` projects retain their historical topology. New projects use the native `v2.1-catalog-1` profile.

### Persona / role table

This is the shortest way to understand who does what.

| Persona | Formal node(s) | Core responsibility |
|---|---|---|
| **Linnaeus** | L0, L10c | Opens and closes the round: verifies readiness/data/continuity at L0; aggregates reports and freezes round evidence at L10c. |
| **Einstein** | L1 | Generates explicit, testable scientific hypotheses with predeclared falsification criteria. |
| **Feynman** | L2, L9a | Attacks ideas early (L2) and hard-falsifies result-level claims late (L9a). |
| **Oppenheimer** | L3, L6, L10b | Makes the three formal scientific judgments: hypothesis triage, method approval, final KEEP/REVISE/DOWNGRADE/DROP decision. |
| **Fisher** | L4 (cognitive L4C inside staged L4) | Designs the analysis/experimental strategy using frozen method evidence. |
| **Tukey** | L5, L8 in native v2.1 | Challenges method/QC assumptions before execution and audits reproducibility/results after execution. |
| **Turing** | L7 | The **only** persona allowed to execute code; runs approved scripts only against binding-authorized data in the controlled workspace. |
| **Curie** | L8.5; also the evidence-research persona before L1/L4 | Acquires/locates literature evidence and verifies actual results against published literature. |
| **Darwin** | L9b | Produces bounded biological interpretation after receiving the authorized finalized L9a snapshot. |
| **Jobs** | L10a | Assesses scientific/practical value and frames manuscript direction without changing the formal decision. |

**Important compatibility note:** current native v2.1 uses **Tukey at L8** and serial **L9a → finalized snapshot → L9b**. Historical v2.0 used Curie at L8 and parallel L9 behavior.

---

## What each node actually does

The table below is the reader-facing description of the executable topology in `src/research_loop/topology.py` and the current gate/data contracts.

| Node | Persona | What it reads / depends on | What it actually does | Formal boundary |
|---|---|---|---|---|
| **L0** | Linnaeus | Candidate frontmatter, authoritative `l0_input`, runtime/readiness state; for continuations, prior round manifest + selected inherited refs | Runs **pre-flight + state restore + current-round data binding**. Verifies current local files, restores and hash-verifies prior evidence for continuation rounds, verifies selected `inherited_inputs`, and freezes exactly one `CurrentRoundDataBinding/v1`. It does **not** interpret data. | Fail-closed on blocking readiness, contract, restore, selector, or hash errors; successful L0 moves the round from `NEW` toward hypothesis generation. |
| **L1** | Einstein | Candidate question/frontmatter + L0 + verified pre-research evidence | Generates testable hypotheses. Each proposal must be operationalizable and include at least one predeclared falsification criterion. | Produces the hypothesis delta; does not design methods or execute code. |
| **L2** | Feynman | L1 hypotheses + candidate anchor | Blindly attacks every L1 hypothesis: confounders, logical weaknesses, diagnostic tests, severity, and exhaustive verdicts are bound to hypothesis IDs. | Critique only; no status change and no execution. |
| **L3** | Oppenheimer | L1 + L2 | Triages the debate: selects hypotheses worth testing and rejects weak ones with explicit reasons. | `triage-idea` produces the formal hypothesis selection. Optional ranking may run afterward as advisory-only shadow output. |
| **L4** | Fisher | Selected hypotheses + L1/L2/L3 + method evidence | Formal method-planning node. Internally executes the auditable **L4A → L4B → L4C → L4.5** pipeline: discovery, evidence construction, Fisher method design, deterministic commit. | Produces `L4_fisher` / `METHOD_PROPOSED`; no code execution. |
| **L5** | Tukey | L4 plan + L2 attacks | Reviews every selected hypothesis/strategy from an EDA/QC perspective; defines QC checkpoints, failure rules, and method attacks bound to hypothesis/strategy IDs. | Method critique only; does not change status. |
| **L6** | Oppenheimer | L4 + L5 | Approves, revises, or rejects the analysis plan. For native/from-memory plans, approved script declarations remain structured traceability objects carrying canonical `name`, `grounding`, and `branch_id`. | `triage-method`; successful approval reaches `METHOD_APPROVED`. |
| **L7** | Turing | L6-approved plan + L0/current data binding + code-search results | Executes **only approved scripts**. `execution-gate` is the one-time transition from `METHOD_APPROVED` to `NEEDS_EXECUTION`; an already-`NEEDS_EXECUTION` candidate resumes directly at workspace preparation. Before creating a workspace, RLR revalidates the binding and every bound file hash, stages only authorized files, resolves approved structured scripts by canonical name, then executes in the controlled workspace. | Only execution node. Tampered/missing bound data fail before a successful workspace is created; successful execution reaches `EXECUTED`. |
| **L8** | Tukey (native v2.1) | L7 outputs + L6 plan + candidate anchor | Audits every claimed output, reproducibility, QC, and evidence level. It verifies execution rather than rerunning or inventing analysis. | `EXECUTED → AUDITED`; no new code execution. |
| **L8.5** | Curie | L7 actual results + L8 audit + verified literature runtime | Searches/uses real literature based on **actual results**, assesses each active hypothesis once, and cites source-located evidence IDs plus real PMIDs/DOIs. | Literature verification; `AUDITED → UNDER_REVIEW`. |
| **L9a** | Feynman | L1 + L7 + L8 + L8.5 | Performs hard statistical/logical falsification of the result-level claims: identifies surviving claims, falsified claims, risks, and missing proof. | Native v2.1 serial first review stage; must be finalized before L9b is authorized. |
| **L9b** | Darwin | L1 + L7 + L8 + L8.5 + **authorized finalized L9a snapshot** | Produces biological interpretation for each active hypothesis, bounded by verified evidence and explicit limitations. | Cannot run before the finalized L9a snapshot is authorized; no execution and no formal status decision. |
| **L10a** | Jobs | L8/L8.5/L9a/L9b + candidate framing | Assesses scientific value, practical/manuscript potential, and how strongly the work can be framed without overclaiming. | Value assessment only. |
| **L10b** | Oppenheimer | L10a + L8 + L8.5 + L9a + L9b | Makes the final formal scientific decision and must justify it using the audited/falsified/verified evidence. | `KEEP`, `REVISE`, `DOWNGRADE`, or `DROP`. Optional ranking afterward remains advisory only. |
| **L10c** | Linnaeus | All permitted finalized deltas/artifacts | Aggregates the round into `FINAL_REPORT.md` and `FINAL_REPORT_CN.md`, completes the required human-readable projection, and freezes round evidence. | Finalization owner; does not execute code or invent a new scientific winner. |

### Why L0 is now more than a dependency check

PR #16 made round-to-round data continuity explicit:

```text
previous round manifest
        ↓ verify all registered path/SHA evidence
L0EvidenceBinding/v1
        ↓ select only explicit inherited_inputs
        ┐
        ├── + current-round l0_input declarations
        ↓
CurrentRoundDataBinding/v1
        ↓
L7 binding revalidation
        ↓
Turing workspace
```

`l0_input.yaml` is the declaration authority. `L0EvidenceBinding/v1` represents the verified prior-round evidence universe. `CurrentRoundDataBinding/v1` is the **narrower current-round scientific-input authorization**.

Important consequences:

- native L0 writers use schema 1.1; historical schema 1.0 remains readable;
- continuation rounds may be inherited-only, new-only, or inherited + new;
- inherited files must match verified prior `source`, `intermediate`, or `result` path + SHA-256 exactly;
- prior `literature`, `audit`, and `receipt` artifacts cannot silently become execution data;
- current local files are hash-bound;
- remote/non-file declarations may be represented, but cannot be executed until materialized as verified local files;
- `input_manifest.md`, `input_alias`, and `--file` do **not** create or expand scientific-data authority;
- L7 revalidates the current binding before workspace creation, so post-L0 tampering fails closed.

This path has been exercised in a real Round N → N+1 → L7 acceptance pilot, including inherited + new data, exclusion of unselected prior data, actual script reads, and tamper fail-closed tests.

---

## Internal L4 method-planning pipeline

L4 remains **one formal DAG node** (`L4_fisher`) but internally has four auditable stages:

```text
L3 selected hypotheses
        ↓
L4A  Literature Discovery
        ↓  L4ADiscoveryManifest/v1
L4B  Evidence Construction
        ↓  verified Methods/source payload/anchors
L4C  Fisher Method Design
        ↓  L4_fisher delta
L4.5 Deterministic Commit
        ↓
L5 Tukey
```

- **L4A — discovery only:** query planning, metadata discovery, identifier-first deduplication, relevance selection, full-text availability. It cannot fabricate method anchors.
- **L4B — evidence construction:** consumes the frozen L4A selection and uses the existing Academic Research/RLR evidence stack for full-text retrieval, Methods extraction, source-payload retention, anchor validation, and method candidates.
- **L4C — Fisher cognition:** designs the actual method/analysis plan.
- **L4.5 — deterministic commit:** revalidates the exact L4A manifest, L4B evidence, and L4C delta hash before persisting the formal method projection.

These are internal responsibilities, **not four new DAG nodes**.

---

## Literature evidence

Before L1, L4, and L8.5, RLR uses verifiable Academic Research evidence rather than trusting handwritten summaries.

- **L1:** located Results/Discussion/Conclusion evidence for hypothesis generation.
- **L4:** frozen metadata discovery plus primary-study Methods and review-search evidence.
- **L8.5:** result-driven verification against located published evidence.

Evidence packs retain runtime receipts, source metadata, available source payload, located excerpts, and hashes. Missing required evidence fails closed.

RLR follows a **reuse-first adapter boundary**: mature search/retrieval/parser systems should be attached behind explicit adapters rather than reimplemented as a second evidence authority. Literature Search MCP, Zotero, GROBID, Docling, PaperQA2, etc. are not made base authorities merely because an adapter is planned.

---

## L0 readiness and dependency model

Current L0 separates **blocking dependencies** from **readiness-only probes**.

Blocking framework-owned checks correspond to real current consumers, including:

- core Python/packages and filesystem requirements;
- Academic Research runtime;
- activated hypothesis ledger;
- evidence-store/project evidence availability;
- Obsidian projection requirements.

**PubMed MCP and Zotero are currently readiness-only probes**, not heavy blocking base dependencies, until their planned direct consumers are wired. Provider/main-agent readiness is runner-bound because the active provider configuration is known at invocation time. L7 execution/workspace readiness remains deferred to the L7 gate.

A warning from a readiness-only probe is not equivalent to a blocking L0 failure.

---

## Isolation and authority

### Path B — cognitive isolation

Cognitive personas receive only a controller-built context containing DAG-authorized inputs. They do not independently walk the project filesystem or previous-round directories.

### Path A — Turing execution isolation

Turing receives a controlled workspace containing approved scripts, required support artifacts, and only the local scientific files authorized by `CurrentRoundDataBinding`.

### Formal authorities

Different artifacts have different jobs; they are not interchangeable registries:

- **Hypothesis Ledger:** formal hypothesis lifecycle and finalized-emission authority.
- **Candidate/frontmatter + deltas:** round-local scientific state projections.
- **RLRRoundEvidenceManifest/v1:** frozen physical evidence for a completed round.
- **L0EvidenceBinding/v1:** verified prior-round evidence exposed to a continuation.
- **CurrentRoundDataBinding/v1:** exact scientific data authorized for the current round/L7.
- **Loop memory:** semantic continuation state that references an already-frozen round manifest.

---

## Meta-RLR maintenance plane (outside the scientific DAG)

PR #17 added `src/rlr_maintenance/` as a **separate software-maintenance boundary**. It is not L11, not a hidden RLR node, and not a second scientific-state owner.

```text
RLR / CI / acceptance failure
        ↓ observe + normalize
RLRMaintenanceEvent/v1
        ↓
LoopX maintenance state
        ↓ bounded repair task
Codex repair worker
        ↓
RLR-native tests / contracts / CI / real acceptance
        ↓
qualified repair or no repair
```

Boundary rules:

- `research_loop` remains authoritative for scientific state and contracts;
- `rlr_maintenance` may observe/verify RLR, but RLR core must not depend on LoopX/maintenance state;
- LoopX owns maintenance goal/todo/evidence/replan state only;
- Codex is the bounded repair worker, not a new scientific persona;
- RLR-native tests, contracts, CI, and real acceptance pilots remain repair authority;
- **native Windows is the authoritative runtime for RLR/Meta-RLR repair qualification**; WSL/Linux-only failures are compatibility/environment evidence until reproduced or classified appropriately on Windows.

PR #18 fixed the historical Meta-RLR scope test so it verifies the exact qualified PR #17 implementation range instead of treating later legitimate RLR changes as Meta-RLR violations.

---

## Architecture-first change discipline

`AGENTS.md` now requires every nontrivial modification to start from the full architecture and project mission:

1. identify the violated invariant/root cause, not only the symptom;
2. locate the existing canonical owner;
3. preserve declared authority boundaries;
4. prefer one unified/root solution over duplicated logic or workaround paths;
5. reject second sources of truth, hidden fallbacks, or compatibility patch stacks;
6. keep scope minimal and coherent.

This is a repository-development rule; it does not add a scientific DAG node.

---

## Commands

Common runtime commands:

| Command | Description |
|---|---|
| `demo` | Generate a minimal demo project |
| `new-project` | Create a native project and bind its compatibility profile / hypothesis store |
| `new-candidate` | Create a candidate/research question |
| `normalize-l0-input` | Normalize explicit request/data declarations into the strict L0 contract |
| `preflight` | Run L0 pre-flight/readiness checks |
| `check-deps` | Standalone dependency/readiness report |
| `next-step` | Return the next DAG dispatch packet |
| `deep-research-run` | Run configured Academic Research and persist a verified evidence pack |
| `audit-literature-evidence` / `literature-report` | Audit / render source-located literature evidence |
| `assemble-context` | Build isolated Path-B context for one node |
| `emit-delta` | Validate and persist a node delta |
| `triage-idea` | L3 hypothesis selection |
| `triage-method` | L6 method approval/rejection |
| `execution-gate` | One-time `METHOD_APPROVED → NEEDS_EXECUTION` execution authorization |
| `prepare-turing-workspace` | Revalidate current data authority and build the L7 workspace |
| `decision` | Apply an allowed formal status transition |
| `aggregate-report` | L10c final report aggregation |
| `obsidian-sync` | Human-readable Obsidian projection |
| `ranking-shadow` / `ranking-benchmark` / `ranking-report` | Advisory hypothesis-ranking layer; never formal decision authority |
| `list` / `show` | Inspect candidates |

Canonical runner:

```bash
micromamba run -n rlr python run_loop.py run PROJECT CAND
```

The historical `research_loop_v04.py` filename remains as a compatibility CLI/import shim; new code should use `research_loop.cli`, `research_loop.engine`, or `research_loop.api` directly.

---

## Installation and quick check

```powershell
micromamba create --channel-priority strict -n rlr -f environment.yml
micromamba run -n rlr python -m pip install -r requirements-specter2.txt
micromamba run -n rlr python -m pip install -e D:\research_loop\paper-qa

$env:PYTHONPATH = "src"
micromamba run -n rlr python -m research_loop.runtime_preflight
micromamba run -n rlr python research_loop_v04.py demo
micromamba run -n rlr python research_loop_v04.py --help
micromamba run -n rlr python run_loop.py --help
```

A real research run must satisfy the current L0 blocking contracts and later stage-specific gates; readiness-only warnings are reported but are not silently promoted into blockers.

---

## File structure (current architecture)

```text
research_loop/
├── AGENTS.md                         # repository architecture/change discipline
├── research_loop_v04.py              # historical CLI/import compatibility shim
├── run_loop.py                       # root runner entry point
├── src/run_loop.py                   # canonical multi-round runner + StopPolicy
├── src/research_loop/
│   ├── cli.py                        # stable CLI dispatch
│   ├── engine.py                     # orchestration operations
│   ├── commands/                     # extracted command families
│   ├── topology.py                   # executable DAG/persona/visibility truth
│   ├── compatibility.py              # immutable project profiles
│   ├── context.py                    # Path-B context assembly
│   ├── gates.py                      # L0/L4/L6/L7/L10 traceability/status gates
│   ├── delta.py                      # delta schemas + shared L6 script projection
│   ├── l0_contract.py                # L0 contract schema/validation
│   ├── l0_intake.py                  # request/data normalization
│   ├── l0_state.py                   # previous-round restore/state binding
│   ├── l0_data.py                    # CurrentRoundDataBinding/v1
│   ├── deep_research.py              # Academic Research receipts/evidence packs
│   ├── ranking.py                    # advisory shadow ranking
│   └── providers/                    # main-agent/command/headless/manual providers
├── src/rlr_maintenance/              # Meta-RLR maintenance boundary; outside DAG
│   ├── contracts.py
│   ├── observer.py
│   ├── profiles.py
│   ├── verification.py
│   └── loopx_cli.py
├── docs/DAG_TOPOLOGY.md              # detailed reader-facing DAG description
├── docs/MAIN_AGENT_RUN.md            # orchestration protocol
├── docs/MAIN_AGENT_PROMPT.md         # main-agent startup prompt
├── docs/RUNNER.md                    # runner modes / StopPolicy
└── templates/                        # layer/persona/project templates
```

Generated research projects and large runtime artifacts are not source code and should not be promoted into the repository merely because they exist locally.

---

## Hard invariants

- L0 fails closed on blocking readiness, invalid current input, failed prior-round restore, invalid inherited selection, or bound-file hash mismatch.
- `l0_input.yaml` is the input declaration authority; `CurrentRoundDataBinding/v1` is the current-round execution-data authority.
- `input_manifest.md`, `input_alias`, and `--file` cannot expand scientific-data authority.
- Only Turing/L7 executes code, only approved scripts, only in the prepared workspace.
- Native v2.1 L8 is Tukey; native review order is **L9a → finalized authorized snapshot → L9b**.
- Hypothesis Ledger remains the formal hypothesis lifecycle authority.
- L10c owns round finalization and frozen round evidence; loop memory references that frozen evidence rather than replacing it.
- Meta-RLR is outside the scientific DAG and cannot own scientific state.
- Repository changes should fix the canonical owner/root cause rather than accumulate duplicate authorities or compatibility patch stacks.

For the full executable-node overview, see [docs/DAG_TOPOLOGY.md](docs/DAG_TOPOLOGY.md).
