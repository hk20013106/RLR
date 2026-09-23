# External Reuse Gate

## Purpose

Research Loop must not grow a second implementation of a mechanism it already
has, or of a mechanism that a mature external project already solved. This
document defines the project-level **EXTERNAL REUSE GATE**: before an
architecture-level change is designed or coded, the author must show that they
searched RLR itself and real external prior art, read the most relevant actual
source, and explained why REUSE / ADAPT / EXTEND / REFACTOR is insufficient
before CREATE is allowed.

The gate is a governance rule, not a new agency or skill. It reuses the existing
governance owners:

* the CI change-scope entry point (`tools/ci_change_scope.py` and the `scope`
  job in `.github/workflows/ci.yml`);
* the structured, fail-closed audit-report conventions of
  [`FULL_DAG_AUTHORITY_CLOSURE.md`](FULL_DAG_AUTHORITY_CLOSURE.md) /
  `research_loop.pre_e2e_closure`.

The single enforcement owner is `tools/external_reuse_gate.py`.

## Decision order

```text
Understand first
  → Search internal history and code
  → Search external prior art and actual source code
  → REUSE > ADAPT > EXTEND > REFACTOR > CREATE
```

`CREATE` is the last resort, not the default. When the change still concludes
`CREATE`, `WHY_NEW_CODE_IS_NECESSARY` must record why every earlier rung failed.

## Trigger

The gate applies to any change that touches the **architecture surface**:

| Area | Watched owners (see `ARCHITECTURE_*` in the tool) |
| --- | --- |
| state/memory | hypothesis ledger/pool/recall/migration/reactivation, L0 state, ranking, research seed |
| schema/contract | node and method contracts, L0 contract, compatibility, version, constraint validation |
| agent handoff | providers, personas, engine, API facade |
| evidence provenance | deep research, authority, L4 evidence bundle/provenance, L8.5 verification, source-payload integrity |
| workflow/orchestration | runner entry points, topology, conditional routing, node skips, context assembly, CI workflows |
| database/persistence | L4 pipeline, delta resolution, hypothesis ledger persistence, receipt idempotency, L4.5 ledger |
| validation/recovery | gates, L0/formal preflight, pre-E2E closure, path safety, L0 intake |
| skills/tools | templates, dependency manifests, process runner, external resilience |
| governance (self-watch) | `AGENTS.md`, `docs/architecture/EXTERNAL_REUSE_GATE.md`, `tools/external_reuse_gate.py` |

Concretely: `src/research_loop/**`, `src/rlr_maintenance/**`, `templates/**`,
`.github/workflows/**`, the runner entry points (`src/run_loop.py`,
`run_loop.py`, `research_loop_v04.py`), the dependency manifests
(`environment.yml`, `requirements*.txt`), and the gate's own owners
(`AGENTS.md`, `docs/architecture/EXTERNAL_REUSE_GATE.md`,
`tools/external_reuse_gate.py`).

The gate **self-watches**: its own rule, spec, and enforcement tool are on the
architecture surface, so the rule cannot be relaxed without a valid
external-reuse audit in the same change.

Tests (`tests/**`) and other documentation (`docs/**` except the gate spec,
`README*`) do not trigger the gate on their own. A change that touches an
architecture path *and* tests/docs triggers on the architecture path. The
external-reuse audit artifacts themselves
(`docs/architecture/external-reuse/*.json`) are evidence, not architecture, and
never trigger the gate.

## Required steps

For a triggered change, before design/coding is considered complete:

1. **Internal search.** Search RLR code and history for an existing owner,
   validator, registry, or pattern. Name the exact files.
2. **External search.** Search for real GitHub projects, packages, or published
   systems that solve the same problem. Prefer reading actual source over prose.
3. **Read the most relevant source.** For the closest internal and external
   candidates, read the implementation, not just the README.
4. **Decide.** Choose `REUSE`, `ADAPT`, `EXTEND`, `REFACTOR`, or `CREATE`.
5. **Record.** Commit a valid `ExternalReuseAudit/v1` artifact under
   `docs/architecture/external-reuse/` **in the same change set**.

## Audit format (`ExternalReuseAudit/v1`)

Structured JSON, machine-validated by `tools/external_reuse_gate.py`. Required
fields:

```text
EXISTING_IMPLEMENTATIONS_REVIEWED=
REUSABLE_COMPONENTS=
ADOPTED_PATTERN=
WHY_NEW_CODE_IS_NECESSARY=
```

Schema:

```jsonc
{
  "schema_version": "ExternalReuseAudit/v1",
  "change_id": "short-stable-id",
  "EXISTING_IMPLEMENTATIONS_REVIEWED": [
    {"scope": "internal", "reference": "src/research_loop/<owner>.py",
     "finding": "what this owner already does"},
    {"scope": "external", "reference": "https://github.com/<org>/<repo>",
     "finding": "what the real implementation does"}
  ],
  "REUSABLE_COMPONENTS": [
    {"reference": "src/research_loop/<owner>.py",
     "disposition": "REUSE|ADAPT|EXTEND|REFACTOR|REJECT",
     "reason": "why this disposition"}
  ],
  "ADOPTED_PATTERN": "REUSE|ADAPT|EXTEND|REFACTOR|CREATE",
  "WHY_NEW_CODE_IS_NECESSARY": "why the earlier rungs are insufficient"
}
```

Machine-verifiable rules:

* `EXISTING_IMPLEMENTATIONS_REVIEWED` must contain at least one `internal` and at
  least one `external` entry, each with a non-empty `reference` and `finding`.
* `REUSABLE_COMPONENTS` must be non-empty, with a valid `disposition` and reason.
* `WHY_NEW_CODE_IS_NECESSARY` must be substantive (≥ 40 characters; ≥ 80 when
  `ADOPTED_PATTERN` is `CREATE`).
* `CREATE` additionally requires at least one `REUSABLE_COMPONENTS` entry whose
  disposition is `REUSE` / `ADAPT` / `EXTEND` / `REFACTOR`, proving the earlier
  rungs were actually evaluated.
* Placeholder values (`n/a`, `none`, `todo`, …) are rejected.

## Exceptions

* **Not applicable.** Only a *known, complete* change set that touches no
  architecture path needs no artifact; the gate reports `NOT_APPLICABLE`. An
  undetermined diff is never treated as "no architecture change" (see below).
* **Superseding artifact.** A change may rely on an artifact added or modified in
  the same change set. A pre-existing artifact alone does not satisfy the gate,
  so a stale blanket audit cannot be reused.
* **Explicit waiver.** A genuine emergency may proceed only with an explicit,
  reviewed waiver recorded in the pull request; the waiver is not machine-granted
  and must name the reason. Silent bypass is never permitted.

## Machine enforcement

`tools/external_reuse_gate.py check --repo-root . --changed <paths-file>
[--diff-known true|false]` reads the changed paths, finds the architecture
surface, and requires at least one valid
`docs/architecture/external-reuse/*.json` artifact in that change set.

```text
diff base/head known?  ── no ──> UNKNOWN_DIFF → FAIL (exit 1)
   │ yes
   ↓
architecture surface?  ── no ──> NOT_APPLICABLE (proceed)
   │ yes
   ↓
valid audit artifact in this change?  ── yes ──> PASS (proceed)
   │ no
   ↓
FAIL (exit 1) — NO ARCHITECTURE CHANGE
```

When CI cannot determine the base/head (for example an unknown push base), the
`scope` job sets `diff_known=false` and passes `--diff-known false`. The gate
then returns `UNKNOWN_DIFF` / `FAIL` with a non-zero exit, because an empty
change set is not proof that no architecture edit occurred.

The check runs in the existing `scope` job of `.github/workflows/ci.yml`. The
report `ExternalReuseGateReport/v1` is fail-closed: an unknown diff, a missing or
malformed audit artifact, or an unreadable change set makes
`allowed_to_proceed=false`. The gate self-watches (its own owners are on the
architecture surface), and the enforcement remains a single owner
(`tools/external_reuse_gate.py`) inside the existing scope job.

`python tools/external_reuse_gate.py validate <artifact.json>` validates a single
artifact.

## Relationship to other owners

* `research_loop.pre_e2e_closure.audit_static_closure()` remains the runtime DAG
  closure owner. The reuse gate is a change-governance concern and does not
  duplicate or replace it.
* `tools/ci_change_scope.py` remains the docs-only fast-path classifier. The reuse
  gate is a separate step in the same `scope` job, not a second job.
* No new agency, skill, or validator registry is created.
