# Meta-RLR LoopX Maintenance Boundary Design

Date: 2026-08-13

## 1. Purpose

RLR already owns the scientific research lifecycle: strict input validation, DAG-authorized cognition, controlled execution, evidence persistence, cross-round restoration, finalization, and fail-closed gates. The missing capability is not another scientific node and not another research state machine. The missing capability is a durable software-maintenance control loop that can observe real RLR failures over time, preserve maintenance state across agent sessions, route bounded repair work to Codex, and require RLR-native verification before a repair is considered successful.

The architectural goal is therefore:

> Add a formal maintenance boundary between RLR and LoopX so that RLR remains the source of truth for research state and software contracts, while LoopX becomes the durable control plane for maintenance goals, todos, evidence, monitoring, replanning, and long-horizon architectural warnings.

The first implementation must prove this boundary without modifying the RLR scientific DAG, without creating a second RLR database or scheduler, without modifying the LoopX fork, and without granting autonomous merge authority.

## 2. Baselines

### RLR

Implementation work is based on the stable line that contains the merged L4A→L4B contract and PR #15 L0 state-restore work:

- branch lineage: `codex/l4a-source-metadata-contract`
- design branch base: `d6352c0ceeb649efa892e36acc66f209d33920be`

This baseline is selected because Meta-RLR must consume the current fail-closed evidence and cross-round contracts rather than an older `main` state.

### LoopX

The controlled fork is:

- `hk20013106/loopx`
- upstream: `huangruiteng/loopx`
- initial pinned revision: `80877982216577174e3e7c7cca9804c5a3a3148b`
- release at that revision: 0.4.5

The fork remains unmodified in Phase 1. RLR integrates with LoopX through documented provider-neutral interfaces, primarily the LoopX CLI JSON contracts, rather than importing LoopX internal modules.

The pinned LoopX revision is configuration/provenance for a maintenance run; it is not a permanent production constant.

## 3. Global architecture review

Before selecting a design, five questions were applied.

### Why is this modification needed?

Real-data RLR runs already expose software and architecture defects that cannot be solved by one chat session or one CI run. The missing capability is durable maintenance continuity: the system needs to remember failures, evidence, repairs, unresolved blockers, repeated failure patterns, and the next validated maintenance action across many Codex sessions and repository states.

### Does it fit existing responsibilities?

Yes, only if the maintenance loop remains outside the research DAG. RLR owns scientific truth, evidence contracts, runtime invariants, and acceptance tests. LoopX owns long-lived maintenance coordination. Codex owns semantic diagnosis and code changes inside an authorized workspace. GitHub remains authoritative for source revisions, PR state, CI, review, and merge state.

### Does it serve the core project goal?

Yes. The purpose is to make RLR capable of long-running real research with progressively fewer repeated software failures and less architectural drift. It does not add a feature unrelated to scientific reliability.

### Is there a more fundamental solution than a local adapter patch?

Yes. The stable abstraction is a provider-neutral **RLR Maintenance Boundary**, not a collection of issue-specific parsers. LoopX is one consumer of that boundary. This avoids coupling RLR's maintenance semantics directly to one LoopX command or one historical failure.

### Does the design unnecessarily expand scope?

The first phase deliberately excludes automatic merge, automatic contract changes, custom Dreaming algorithms, LoopX modifications, research-DAG changes, and scientific-result interpretation. It establishes only the durable observation and verification boundary needed for later automation.

## 4. Rejected designs

### A. Add a Meta node to L0→L10c

Rejected. Software maintenance and scientific reasoning have different authority, evidence, and rollback semantics. Adding a self-repair node to the research DAG would allow implementation pressure to leak into scientific gates and would create backward dependencies from software maintenance into research execution.

### B. Build a new Meta-RLR scheduler/database

Rejected. LoopX already provides durable goals, todos, claims, gates, quotas, evidence, monitoring, handoffs, replanning, self-repair guidance, change-quality checks, and long-running agent wakeups. Reimplementing these functions would create duplicate state ownership and unnecessary complexity.

### C. Use LoopX as the maintenance control plane through a narrow RLR boundary

Selected. It preserves single ownership on both sides and minimizes new code.

## 5. Authority model

The system is split into four authorities.

### RLR object plane

Owns:

- scientific DAG and node authority;
- L0 input and previous-round state contracts;
- evidence hashes and manifests;
- provider dispatch boundaries;
- L4 frozen-corpus and evidence rules;
- L10c finalization semantics;
- scientific project artifacts;
- RLR-native verification commands and acceptance pilots.

RLR does **not** own maintenance scheduling, maintenance todo lifecycle, or long-term repair coordination.

### RLR Maintenance Boundary

Owns only two provider-neutral contracts:

1. **Observe** — convert authoritative RLR/GitHub/runtime facts into a compact maintenance event.
2. **Verify** — execute or describe RLR-native verification profiles and return structured verification outcomes.

It does not decide how to repair code, does not mutate scientific state, and does not maintain an independent source of project truth.

### LoopX control plane

Owns:

- maintenance goal identity;
- maintenance todo/claim lifecycle;
- compact maintenance evidence references;
- scheduler/heartbeat state;
- monitor/wait/replan state;
- cross-session handoff;
- later Dreaming/refactor-warning proposals.

LoopX does not reinterpret RLR scientific artifacts or override RLR validators.

### Codex / maintenance agent

Owns:

- root-cause analysis;
- implementation planning within the current authorized todo;
- isolated source edits;
- RED/GREEN test workflow;
- bounded repair proposal;
- invoking the approved verification commands.

Codex completion claims are never sufficient evidence by themselves.

### GitHub

Remains authoritative for:

- repository revision;
- branches and pull requests;
- CI check status;
- code review state;
- merge state.

## 6. Repository boundary

The RLR scientific package remains `src/research_loop/`.

Phase 1 should introduce the maintenance integration as a separate top-level Python namespace under `src/`, for example:

```text
src/
├── research_loop/          # existing scientific object plane
└── rlr_maintenance/        # maintenance boundary; no DAG ownership
```

This separation is intentional. `rlr_maintenance` may consume narrow, documented RLR validators and artifact readers where needed, but `research_loop` must not import `rlr_maintenance` and must not import LoopX.

Dependency direction:

```text
LoopX CLI
   ↑↓ JSON
rlr_maintenance
   ↓ read/verify through public or narrow RLR contracts
research_loop
```

Forbidden dependency:

```text
research_loop → rlr_maintenance
research_loop → loopx
```

No LoopX source is vendored into RLR.

## 7. Contract 1: RLRMaintenanceEvent/v1

A maintenance event is a compact, immutable observation of a software/runtime condition. It records facts and provenance; it does not prescribe a code change.

Minimum shape:

```json
{
  "schema_version": "RLRMaintenanceEvent/v1",
  "event_id": "content-derived stable id",
  "event_type": "contract_failure",
  "component": "l0_restore",
  "severity": "blocking",
  "observed_at": "ISO-8601 timestamp",
  "rlr_revision": "git SHA",
  "project_ref": "optional public-safe project identity",
  "candidate_ref": "optional candidate identity",
  "round_ref": "optional round identity",
  "observed": {},
  "expected_contract": "stable contract identifier",
  "evidence_refs": [],
  "source_receipts": [],
  "dedup_fingerprint": "sha256",
  "suggested_route": "repair"
}
```

### Event principles

- Events state **what happened**, not the proposed fix.
- `expected_contract` names a durable invariant, not a historical bug or PR number.
- Evidence references point to authoritative RLR/GitHub artifacts; raw private logs are not copied into LoopX state.
- The same underlying failure should produce the same deduplication fingerprint when the stable facts are unchanged.
- Unknown or incomplete facts remain unknown; the observer must not infer missing lineage or scientific meaning.
- A maintenance event cannot change candidate status or scientific project state.

### Initial event classes

Phase 1 should support only event classes backed by existing machine-readable evidence:

- `contract_failure`
- `runtime_failure`
- `verification_failure`
- `ci_failure`
- `acceptance_failure`

`architecture_drift` and repeated-pattern synthesis belong to a later phase after enough normalized history exists.

## 8. Contract 2: RLRVerificationProfile/v1

A verification profile defines how a class of repair is judged. It is not a hard-coded list of commands for one bug. It binds a repair class to RLR-native invariants and validation surfaces.

Conceptual shape:

```json
{
  "schema_version": "RLRVerificationProfile/v1",
  "profile_id": "l0_state_integrity",
  "risk_class": "high",
  "protected_contracts": [
    "l0_restore_fail_closed",
    "provider_after_restore_only",
    "round_manifest_hash_integrity"
  ],
  "required_validation": [
    "targeted_regression",
    "affected_contract_suite",
    "full_regression",
    "real_acceptance_when_boundary_requires_it"
  ],
  "forbidden_success_shortcuts": [
    "weaken_validator",
    "convert_fail_to_warn",
    "skip_required_test",
    "rewrite_expected_hash",
    "introduce_parallel_state_owner"
  ]
}
```

Profiles describe durable architecture invariants. Historical incidents may be used as fixtures, but they do not become the architecture definition.

### Initial protected contract families

The first implementation should encode verification profiles for existing, already-defined boundaries rather than inventing new RLR policy:

- L0 input and previous-round evidence restore;
- provider-before-restore ordering;
- round-manifest and continuation integrity;
- L4A→L4B frozen-corpus/evidence boundary;
- L10c single-owner finalization.

These are maintenance verification metadata around existing contracts, not replacement validators.

## 9. LoopX integration contract

The integration uses LoopX as an external executable/control plane.

Phase 1 must prefer documented CLI JSON interfaces over Python imports from LoopX internals. This preserves provider neutrality, lets the fork track upstream, and prevents RLR from depending on unstable implementation details.

The adapter may invoke a bounded sequence equivalent to:

```text
LoopX read current goal/quota packet
→ claim or create maintenance todo
→ attach compact event/evidence references
→ hand one bounded repair task to Codex
→ validate real outcome
→ write back result/evidence
→ refresh state
```

Exact commands are selected during implementation from the pinned LoopX version and must be discovered from its current CLI contract rather than duplicated from old documentation.

LoopX state is maintenance coordination state only. RLR and GitHub remain authoritative for whether a failure exists and whether a repair actually passes.

## 10. Failure classification

The maintenance boundary should distinguish failure ownership before a repair todo is promoted.

Initial classification:

```text
RLR product/contract bug
Test or fixture defect
Environment/dependency failure
External provider/tool failure
Insufficient/ambiguous evidence
```

This classification prevents a common patching failure mode: changing production code when the failure belongs to a fixture or environment.

Classification may be proposed by Codex, but the evidence packet must preserve the observations used to justify it.

## 11. Repair lifecycle

Phase 1 lifecycle:

```text
RLR/GitHub emits authoritative failure evidence
        ↓
RLR Maintenance Observe
        ↓
RLRMaintenanceEvent/v1
        ↓
LoopX maintenance goal/todo/evidence
        ↓
Codex diagnosis
        ↓
Failure classification
        ↓
Isolated branch/worktree
        ↓
Reproduce before production change
        ↓
Minimal coherent repair
        ↓
RLR Verification Profile
        ↓
Targeted tests → affected contract tests → full CI → pilot when required
        ↓
Verification evidence written back to LoopX
        ↓
Draft PR / reviewed change
        ↓
STOP before merge
```

The lifecycle must not automatically merge in Phase 1.

## 12. Root-cause and anti-patch rules

Every promoted repair must answer, in structured maintenance evidence or the repair plan:

1. Why is the change necessary?
2. Which layer owns the defect?
3. Why is that the correct ownership boundary?
4. Is there an existing helper/contract/validator that should be reused?
5. Is the proposed change correcting a root cause or only hiding a symptom?
6. Does the change create a second source of truth, second state owner, compatibility wrapper, or special case?
7. What is explicitly out of scope?

A repair is blocked from promotion when the easiest way to make validation pass is any of the following:

- weaken a validator;
- change a blocking failure to warning;
- catch and ignore a fail-closed exception;
- edit expected hashes to match mutated evidence;
- remove/skip a required test;
- add a parallel state path;
- add a one-off compatibility wrapper without an explicit migration owner;
- broaden unrelated refactoring.

This layer does not duplicate RLR validators. It prevents the maintenance process from claiming success by bypassing them.

## 13. Data and privacy boundary

LoopX receives compact maintenance facts and references, not raw scientific payloads by default.

Default allowed:

- repository-relative code paths;
- Git SHAs;
- contract/error codes;
- test/check identifiers;
- exit codes;
- hashes;
- public-safe receipt references;
- compact failure summaries.

Default excluded:

- large scientific datasets;
- raw private research files;
- credentials;
- full provider transcripts;
- unbounded logs;
- private literature payloads unless an explicitly authorized maintenance task requires them.

A repair agent that needs real scientific data for an acceptance pilot receives that access through the existing RLR project/runtime boundary, not because LoopX copied the data into its own state.

## 14. Versioning and reproducibility

Each Meta-RLR maintenance run should be attributable to:

- exact RLR base SHA;
- exact candidate repair SHA/diff fingerprint;
- exact LoopX revision;
- verification profile version;
- relevant test/CI run identity;
- acceptance-pilot identity when used.

Upgrading LoopX is a controlled dependency change:

```text
upstream LoopX update
→ sync/test hk20013106/loopx
→ run Meta-RLR compatibility checks
→ update pinned revision
```

RLR must never automatically follow `huangruiteng/loopx@main` for a trusted long-running research environment.

## 15. Testing strategy

Implementation follows TDD.

### Contract tests

- valid and invalid `RLRMaintenanceEvent/v1`;
- deterministic dedup fingerprint;
- no inferred missing provenance;
- private/raw payload rejection or redaction at the boundary;
- verification-profile validation.

### Observer tests

Use existing synthetic RLR receipts/artifacts to prove normalization of:

- L0 contract failure;
- runtime exit-code failure;
- CI/verification failure;
- acceptance-pilot failure.

Observer tests must read the same authoritative artifacts the real runtime writes where feasible.

### Dependency-direction tests

- `research_loop` does not import `rlr_maintenance`;
- `research_loop` does not import LoopX;
- `rlr_maintenance` does not import private LoopX Python modules.

### LoopX adapter tests

Use a fake CLI process or controlled fixture that exercises the documented JSON boundary. Do not mock the maintenance contract itself. At least one later local pilot must use the real pinned LoopX executable.

### Verification tests

Seed a known historical failure, require reproduction before repair, and prove that the verification profile detects both a correct repair and a forbidden shortcut such as weakening the validator or skipping the gate.

### Regression

Production changes require the relevant RLR contract suite followed by the full existing RLR suite and `git diff --check`.

## 16. MVP acceptance experiment

The first end-to-end pilot should use a disposable branch seeded with the already-understood historical root-entrypoint exit-code defect:

```text
root run_loop.py calls main() without propagating the return code
```

The pilot is successful only if the maintenance loop can independently reconstruct the contract chain:

```text
tampered previous-round artifact
→ L0 hash mismatch
→ provider/main-agent invocation remains 0
→ canonical runner returns fail-closed code 3
→ root compatibility entrypoint must propagate code 3
```

Required outcome:

- event captured through the generic maintenance boundary;
- LoopX creates/preserves maintenance state;
- Codex classifies the root cause correctly;
- RED reproduction exists before the production edit;
- patch is minimal and touches no protected unrelated contract;
- RLR verification passes;
- LoopX receives a verification result;
- no real research data is modified;
- no automatic merge occurs.

The historical bug is a test case, not a special production rule.

## 17. Later phases, explicitly deferred

Only after the MVP boundary proves reliable should the project consider:

### Phase 2: repeated-pattern synthesis

Feed normalized maintenance history to LoopX Dreaming/refactor-warning mechanisms so repeated local failures can be promoted into architecture-review proposals.

### Phase 3: controlled PR lifecycle

Let LoopX monitor CI/review/mergeability and replan after material transitions. Human approval remains the merge boundary.

### Phase 4: narrowly autonomous promotion

Consider only after substantial empirical evidence, and only for allowlisted low-risk changes. Core RLR integrity contracts remain outside autonomous self-modification authority.

These phases are not part of the first implementation.

## 18. Phase 1 implementation surface

The implementation plan should aim for the smallest coherent new surface, approximately:

```text
src/rlr_maintenance/
├── contracts.py          # event/profile schemas + validation
├── observe.py            # authoritative RLR/GitHub fact normalization
├── verify.py             # verification profile planning/result normalization
└── loopx_cli.py          # narrow provider-neutral LoopX CLI adapter

tests/
└── maintenance/          # focused contract/observer/adapter tests

config/
└── maintenance/          # versioned RLR verification profiles, if static files are justified
```

This file layout is a design target, not permission to create every file. During implementation, any module without a distinct responsibility or real consumer must be omitted.

No modification to `src/research_loop/topology.py`, L0/L4/L10c business logic, or the LoopX fork is justified merely to establish this boundary.

## 19. Success criteria for the design

The design is correct only if all statements remain true:

1. RLR scientific execution is unchanged when Meta-RLR is absent.
2. LoopX is optional to normal RLR execution and never becomes an implicit L0 dependency.
3. RLR remains the sole authority for scientific state and its own software invariants.
4. LoopX remains the sole maintenance-control-state owner.
5. Codex cannot declare a repair successful without independent RLR/GitHub verification.
6. The first implementation creates no second database, scheduler, DAG, evidence manifest, or source-of-truth projection.
7. Maintenance observations are generic contracts, not hard-coded historical bug handlers.
8. Repair policy favors root-cause correction, reuse, and minimal coherent scope over compatibility patches and local workarounds.
9. All changes are reversible and attributable to exact revisions.
10. The MVP stops before autonomous merge.
