# AGENTS.md — Research Loop

## Project mission

Research Loop is a DAG-based, multi-agent system for auditable scientific research.

Primary priorities, in order:

1. Scientific and logical correctness.
2. Contract integrity and provenance.
3. Node isolation and authority boundaries.
4. Reproducibility and backward compatibility.
5. Implementation speed and convenience.

Do not trade a higher-priority property for a lower-priority one.

## Sources of truth

Before modifying code:

1. Inspect the current repository, relevant tests, and `git status`.
2. Trace the real runtime path and identify callers, data contracts, and side effects.
3. Treat executable code and passing tests as more authoritative than old plans, reports, or architecture notes.
4. Report any conflict between documentation and current code; do not silently choose the more convenient interpretation.

Do not hard-code transient facts such as current branch names, commit hashes, test counts, line numbers, or roadmap phase status into production logic.

## Phase-gated workflow

For nontrivial work, organize execution into phases. Each phase must define:

* Goal
* Inputs
* Constraints
* Done when
* Validation

Default behavior:

* Ground the task in the real code before editing.
* Make one coherent, reviewable change at a time.
* Stop at a phase boundary unless the user explicitly authorized end-to-end execution.
* When end-to-end execution is authorized, continue through all defined phases without requesting routine confirmation.
* Do not begin later phases while an earlier phase has unresolved failures.

A plan is not implementation. Do not claim progress from a plan-only artifact.

## Core invariants

The following are correctness boundaries, not optional conventions.

### DAG and authority

* Preserve the declared DAG. Do not introduce backward dependencies or hidden cross-node communication.
* Preserve node-specific information visibility.
* L9a and L9b must remain mutually invisible during their parallel execution; only DAG-declared downstream nodes may combine their outputs.
* Only the designated decision authority may change candidate status.
* Only the designated execution node may execute analysis code.
* Cognitive nodes must operate on their assembled, DAG-authorized context rather than arbitrary repository state.

### State and artifacts

* Preserve candidate identity and input-contract provenance after creation. Candidate status changes must use explicitly defined, schema-validated transitions rather than ad hoc edits.
* Persist state transitions through schema-validated delta artifacts, not ad hoc edits.
* Preserve append-only semantics for audit and pitfall records unless a versioned migration explicitly changes the model.
* Do not duplicate large source documents in deltas. Store stable IDs, hashes, cards, or explicit references unless the schema requires the full content.
* Never fabricate missing state, paths, lineage, decisions, conclusions, hashes, references, or scientific results.

### Gates and validation

* Missing required dependencies or artifacts must fail closed.
* Never bypass a gate by:

  * inserting a sentinel string without validating the underlying artifact;
  * weakening a validator to accept malformed data;
  * using `verified: false` or an equivalent escape;
  * catching validation errors and continuing;
  * inferring required lineage or round metadata;
  * modifying fixtures only to suppress a legitimate failure.
* Use one authoritative validator for each contract. All entry points that consume that contract must call the same validator.
* Validation must occur at the actual boundary of use, not only during object creation.
* Error messages must identify the failed invariant and the affected artifact.

### L0 input contract

* Any candidate reaching L0 must satisfy the current strict L0 input contract.
* Legacy data may remain readable, but it must be explicitly migrated before entering L0.
* `round_type` must be explicit; never infer it from file presence or another boolean.
* File and directory inputs with missing paths must hard-fail.
* Remote datasets require a stable locator or ID, an explicit verification status, and a reason when not verified.
* Preserve separate fields for hypothesis, decision, conclusion, round lineage, and memory hash. Do not combine them into overloaded strings.
* Revalidate the on-disk artifact and its hash immediately before provider dispatch.

## Architecture rules

Maintain separation among:

* DAG topology and node authority
* context assembly and information filtering
* contract/schema validation
* gate registration and dispatch
* provider abstraction and prompt composition
* controlled execution workspace
* persistence, reporting, and optional integrations

Rules:

* Do not create or enlarge a god module when a narrow module has a clear responsibility.
* Do not duplicate schema or gate logic across the CLI, context builder, provider, and orchestrator.
* Keep pure validation and transformation logic free of filesystem or provider side effects where practical.
* Preserve the distinction between cognitive context isolation and controlled execution isolation.
* Do not change public CLI commands, provider interfaces, artifact locations, or schema semantics silently.
* Schema changes require explicit versioning, compatibility analysis, and migration tests.
* Compatibility shims may be removed only when all callers and tests have been migrated.
* Optional integrations must not silently become hard dependencies.

## Implementation discipline

* Prefer the smallest reversible change that satisfies the task.
* No unrelated refactoring, formatting sweeps, renaming, or dependency upgrades.
* Inspect all callers before changing a public function, class, CLI option, schema field, or artifact path.
* Search for existing implementations before adding a new module or helper.
* Keep a single source of truth; remove or deprecate superseded duplicate logic deliberately.
* Never use broad `except: pass` around validation, persistence, provenance, or dispatch.
* Preserve UTF-8 explicitly for subprocess input/output and generated text.
* Avoid machine-specific absolute paths in committed code and fixtures.
* Tests must exercise the real runtime boundary where feasible, not merely mocks or internal fields.
* Use unique sentinels to prove physical prompt/context injection and absence from unauthorized nodes.
* Do not weaken production behavior to make legacy tests pass; migrate fixtures when the new contract is intentionally strict.

## Scientific integrity

* Do not invent references, DOIs, datasets, tool outputs, statistical results, or biological interpretations.
* Separate observed inputs, computed results, and inferred interpretations.
* Preserve negative, ambiguous, and contradictory evidence.
* A statistically significant result is not automatically biologically important.
* A biologically plausible explanation is not evidence that the mechanism is true.
* Record the provenance of external searches, literature cards, methods, parameters, and generated artifacts.
* Do not claim that a scientific conclusion is supported unless the required evidence is present in the authorized context.
* Synthetic tests prove software behavior only; they do not validate a scientific conclusion.

## Testing and verification

Run the narrowest relevant tests first, then the full regression suite for production changes.

Preferred commands on the current workstation:

```powershell
rtk proxy python -m pytest path\to\relevant_test.py -q
rtk proxy python -m pytest -q
git diff --check
python run_loop.py --help
```

If `rtk` is unavailable, use the equivalent direct `python -m pytest ...` command and report that substitution.

Additional requirements:

* Run contract, gate, context-isolation, provider-dispatch, and CLI compatibility tests when their code paths are affected.
* Run an end-to-end or sentinel test when changing prompt composition, context injection, lineage, or artifact flow.
* Verify generated hashes and artifact paths when changing persistence.
* Never report that tests pass unless the command was run in the current workspace and its output was observed.
* Report the exact command, pass/fail result, and any skipped or uncollected tests.
* A targeted test passing does not establish full regression safety.
* Do not claim completion while required verification is failing.

## Git and workspace safety

Before editing:

```powershell
git status --short
git branch --show-current
```

Rules:

* Preserve unrelated modified and untracked files.
* Stage only files belonging to the requested change.
* Do not use destructive commands such as `git reset --hard`, `git clean -fd`, forced checkout, history rewriting, or mass deletion without explicit approval.
* Do not commit, push, merge, open a pull request, or delete a branch unless explicitly requested.
* Do not conceal a dirty working tree or attribute pre-existing changes to the current task.
* Keep generated scratch files outside tracked paths or remove only scratch files created by the current task.

## Completion report

A completion report must include:

1. What changed and why.
2. Files changed.
3. Runtime path or contracts affected.
4. Compatibility and migration implications.
5. Verification commands and observed results.
6. Remaining risks, failures, or unverified assumptions.
7. Current git status; include commit and branch only when a commit was requested and created.

Do not use “done”, “fixed”, “all green”, or equivalent language without the corresponding verification evidence.

## What does not belong in this file

Keep this file stable and operational. Do not place the following here:

* current sprint tasks or temporary plans;
* current branch names, commits, test counts, or line numbers;
* complete architecture reports or roadmaps;
* model personality prose;
* scientific conclusions for a particular candidate;
* phase-specific instructions that belong in the task prompt or a dedicated plan.

For each new phase, supply a separate task specification containing its goal, inputs, constraints, completion criteria, and validation.
