# Full DAG Authority & Contract Closure

## Purpose and scope

This document describes the executable pre-E2E closure model for the native RLR v2.1 DAG. Its purpose is to determine, without invoking a provider, whether every required L0→L10 dependency, typed authority, provider/canonical contract boundary, execution receipt field, and committed-state recovery path is statically closed.

The implementation is deliberately read-only with respect to scientific state. It does not run a real L0→L10 cycle, Fisher, Deep Research, or execution code. The machine-readable owner is `research_loop.pre_e2e_closure.audit_static_closure()`.

Historical compatibility profiles remain isolated. The native v2.1 profile is the target for the next clean E2E.

## Architectural invariants

The closure layer preserves the existing RLR invariants:

- **Single owner.** Each canonical authority has one declared producer. The closure auditor reads existing owners rather than creating replacement registries.
- **No second source of truth.** `context_inputs`, topology, schema registries, L4 binding rules, L0 data validation, provider receipts, and recovery logic remain owned by their existing modules.
- **Hash exact canonical bytes.** Authority projection verifies the canonical artifact and, for small JSON inputs, verifies the bound file hash before exposing a bounded semantic projection.
- **Least authority / least context.** Execution-only authority is not copied into cognitive prompts, and bulk scientific matrices are never rendered into provider context by the authority projector.
- **Fail closed.** Any unresolved required path, malformed closure report, or closure-audit exception prevents the canonical runner from reaching provider startup.

## Graph 1 — Node dependency reachability

Topology remains the owner of DAG ordering and `context_inputs`. The closure auditor reads `topology_for_profile(profile_id)` and checks every declared prior-delta dependency against the active profile sequence.

A dependency is closed only when its producer is present and precedes its consumer, except for explicit special sources such as `candidate_frontmatter` and `ALL`.

This is intentionally separate from typed authorities: `context_inputs` controls visibility of prior node outputs, while typed authorities represent canonical cross-cutting artifacts that are produced once and consumed at specific runtime boundaries.

## Graph 2 — Canonical authority ownership

The typed authority registry is `research_loop.authority.AUTHORITY_REGISTRY`.

For the current native contract:

| Authority | Canonical producer | Schema | Context consumer | Execution consumer |
| --- | --- | --- | --- | --- |
| `current_round_data_binding` | L0 | `CurrentRoundDataBinding/v1` | L4 | L7 |

The resolver does not reconstruct the binding. It delegates verification to the existing L0 owner, `verify_current_round_data_binding()`, then verifies that the canonical artifact exists and that its schema matches the registry declaration.

The closure auditor checks both sides of this contract: the producer must declare that it produces the authority, and every consumer must be explicitly authorized by mode.

## Graph 3 — Authority propagation

The same L0-owned `current_round_data_binding` reaches two different boundaries without creating a second identity:

```text
L0 canonical CurrentRoundDataBinding
        │
        ├── context mode ──> L4 bounded verified projection
        │
        └── execution mode ──> L7 execution input resolver
```

For L4, `project_context_authorities()` emits only a compact deterministic projection. It includes canonical artifact identity, schema, SHA-256, authorized-input role/origin/path/hash/size/reason, and bounded semantics for small hash-verified JSON artifacts. It does not inject tabular/raw matrices.

For L7, the execution boundary resolves the same named authority through the generic `resolve_authority()` path. The closure auditor explicitly rejects a native L7 implementation that bypasses this resolver.

## Graph 4 — Provider → canonical → persisted contracts

The closure auditor reads the existing provider and persisted schema owners:

```text
provider schema
      │
      ├── native L4: local E/G/A handles
      │       ↓ deterministic handle binder
      │    canonical *_ids
      │
      └── other native nodes: identity wire mapping
              ↓
canonical submission schema
              ↓
persisted ledger schema
```

For native L4, the field transformation is taken from the existing `_L4C_REFERENCE_FIELDS` declaration and the existing `resolve_l4c_reference_handles()` binder. The closure auditor verifies that provider-side handle fields and canonical ID fields compose correctly; it does not perform fuzzy matching, infer IDs, or create a second bound artifact.

For other native ledger nodes, the wire contract is an identity mapping. Provider-required fields must be representable in the canonical schema, and the persisted schema must contain the canonical submission contract plus ledger-owned persisted identities.

## Graph 5 — Execution receipt and committed-state recovery

The execution closure verifies that `RunReceipt` contains the runtime outcome fields required to prove provider-call observability:

- `exit_code`
- `timed_out`
- `terminal_state`
- `execution_status`

It also verifies that the canonical runner binds these fields into the receipt writer and that provider failures use the same receipt path with an explicit failed execution status.

Committed-state recovery is checked separately. The recovery hook must execute before provider dispatch, and a committed recovery path may advance deterministic state only. It must not invoke `provider_for`, `exec_cognitive`, or `exec_turing`, preventing a second canonical provider execution after commit.

## Pre-E2E runner gate

The canonical automated runner is `src/run_loop.py`; the repository-root `run_loop.py` is only a compatibility entry point that delegates to it.

Before provider preflight, main-agent handoff, or an explicit manual/debug provider can start, `cmd_run()` resolves the active profile and calls the existing `audit_static_closure(profile_id)` owner.

```text
candidate/dependency checks
        ↓
deterministic state restore
        ↓
audit_static_closure(profile_id)
        │
        ├── exception / malformed audit → exit 3
        ├── unresolved required path → exit 3
        └── e2e_start_allowed = true
                    ↓
             provider preflight / handoff
```

This gate intentionally calls the existing closure auditor rather than duplicating any authority, schema, receipt, or recovery validation logic in the runner.

## Closure report

`audit_static_closure()` returns `PreE2EClosureReport/v1`, including:

- a row for every native topology node;
- provider/canonical/persisted contract-transform status;
- execution-receipt closure;
- committed-state recovery closure;
- `unresolved_required_paths`;
- `e2e_start_allowed`.

The implementation uses fail-closed status values such as `CLOSED`, `NO_PRODUCER`, `UNBOUND`, `UNAUTHORIZED`, `UNREACHABLE`, `TYPE_MISMATCH`, and `CONTRACT_MISMATCH`. Any unresolved required row makes `e2e_start_allowed=false`.

## Goal 10 regression

The Goal 10 orthology case is retained as an architecture regression, not as a hard-coded scientific special case. A small verified `MC1OrthologyBinding/v1` file is first authorized by the ordinary L0 data-binding contract. L4 then receives its bounded semantic projection through the generic authority resolver, while L7 consumes the same L0-owned authority at the execution boundary.

This proves the intended ownership chain:

```text
scientific input
  → L0 canonical authorization
  → one CurrentRoundDataBinding identity
  → generic authority resolver
  → L4 context and L7 execution consumers
```

No MC1-specific path is required in the authority framework.

## Verification and readiness rule

Before another real clean E2E, all of the following must be true on the same final Git commit:

1. `audit_static_closure()` reports no unresolved required path and `e2e_start_allowed=true` for the native profile.
2. Regression tests prove that an open closure or closure-audit failure stops the runner before all provider modes, including main-agent and explicit manual/debug handoff.
3. The full Windows Python 3.13 GitHub Actions pytest/coverage job passes on that exact commit.
4. The final repository tree contains no temporary patch workflow or alternate closure implementation.
5. The remote `codex/full-dag-authority-closure` ref points to that verified commit.

Only after those conditions are freshly verified may Goal 11 be classified `READY_FOR_ONE_FINAL_CLEAN_E2E`.
