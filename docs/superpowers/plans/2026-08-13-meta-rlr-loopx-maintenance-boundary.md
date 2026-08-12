# Meta-RLR LoopX Maintenance Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral maintenance boundary that turns authoritative RLR software/runtime failures into durable maintenance events, validates repair classes against RLR-native invariants, and exchanges maintenance state with LoopX through its documented CLI JSON boundary without changing the scientific DAG or creating a second state owner.

**Architecture:** Add a separate `rlr_maintenance` namespace beside `research_loop`. The new package owns only observation normalization, maintenance contracts, verification profiles, and an external LoopX CLI adapter. `research_loop` must never import the maintenance package or LoopX. RLR/GitHub remain authoritative for scientific state, software contracts, source revisions, CI, and acceptance; LoopX owns only maintenance goal/todo/evidence/monitor/replan state.

**Tech Stack:** Python 3.13, stdlib only for production code (`dataclasses`, `hashlib`, `json`, `pathlib`, `subprocess`, `typing`), pytest for tests, LoopX 0.4.5 pinned at `80877982216577174e3e7c7cca9804c5a3a3148b` for the first real integration pilot.

## Global Constraints

- Base implementation lineage is `d6352c0ceeb649efa892e36acc66f209d33920be`; the working branch is `feat/meta-rlr-loopx-adapter`.
- Do not modify the RLR scientific DAG, L0/L4/L10c business semantics, or candidate/scientific state.
- Do not modify `hk20013106/loopx` in Phase 1.
- Do not vendor LoopX source and do not import private LoopX Python modules.
- Do not create a second maintenance database, scheduler, manifest system, or source of scientific truth.
- Do not depend on the still-open PR #16 round-data-continuity implementation; Meta-RLR may read only stable receipts/contract outcomes/CI facts already present on the base line.
- Do not auto-merge. Phase 1 stops at a verified Draft PR / reviewed change.
- Never weaken a validator, convert a blocking failure to warning, rewrite expected hashes, skip required tests, or add a parallel state owner to make a repair pass.
- Use TDD: every production behavior begins with a failing test and each task ends with an independently reviewable commit.

---

## File Structure

Create:

```text
src/rlr_maintenance/
├── __init__.py          # public maintenance-boundary exports only
├── contracts.py         # RLRMaintenanceEvent/v1 + verification-result contracts
├── observer.py          # normalize authoritative failure facts into events
├── profiles.py          # immutable RLRVerificationProfile/v1 definitions
├── verification.py      # execute profile steps and return structured outcomes
└── loopx_cli.py         # external LoopX CLI JSON boundary only

tests/
├── test_meta_rlr_contracts.py
├── test_meta_rlr_observer.py
├── test_meta_rlr_profiles.py
├── test_meta_rlr_verification.py
├── test_meta_rlr_loopx_cli.py
└── test_meta_rlr_architecture.py
```

Do not add new files under `src/research_loop/` unless a later test proves an existing public read boundary is insufficient. If that occurs, stop and re-audit ownership before touching RLR core.

---

### Task 1: Define the maintenance event contract

**Files:**
- Create: `src/rlr_maintenance/__init__.py`
- Create: `src/rlr_maintenance/contracts.py`
- Test: `tests/test_meta_rlr_contracts.py`

**Interfaces:**
- Produces: `MaintenanceContractError`, `EvidenceRef`, `build_maintenance_event(...) -> dict`, `validate_maintenance_event(value) -> dict`, `canonical_json(value) -> str`
- Consumes: stdlib only

- [ ] **Step 1: Write RED tests for exact schema, stable IDs, and privacy-safe references**

```python
from rlr_maintenance.contracts import (
    MaintenanceContractError,
    build_maintenance_event,
    validate_maintenance_event,
)


def test_event_id_is_stable_when_only_observed_at_changes():
    common = dict(
        event_type="contract_failure",
        component="l0_restore",
        severity="blocking",
        rlr_revision="a" * 40,
        observed={"error_code": "L0_RESTORE_ARTIFACT_HASH_MISMATCH"},
        expected_contract="l0_restore_fail_closed",
        evidence_refs=[{"kind": "rlr_artifact", "ref": "08_Audit/x.json", "sha256": "b" * 64}],
    )
    a = build_maintenance_event(observed_at="2026-08-13T00:00:00Z", **common)
    b = build_maintenance_event(observed_at="2026-08-13T01:00:00Z", **common)
    assert a["event_id"] == b["event_id"]
    assert a["dedup_fingerprint"] == b["dedup_fingerprint"]


def test_event_rejects_absolute_private_artifact_path():
    with pytest.raises(MaintenanceContractError, match="relative"):
        validate_maintenance_event({
            "schema_version": "RLRMaintenanceEvent/v1",
            "event_id": "x",
            "event_type": "runtime_failure",
            "component": "runner",
            "severity": "blocking",
            "observed_at": "2026-08-13T00:00:00Z",
            "rlr_revision": "a" * 40,
            "observed": {"exit_code": 3},
            "expected_contract": "runner_nonzero_propagation",
            "evidence_refs": [{"kind": "rlr_artifact", "ref": "D:/private/data.csv"}],
            "source_receipts": [],
            "dedup_fingerprint": "b" * 64,
            "suggested_route": "repair",
        })
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_contracts.py -q
```

Expected: import failure because `rlr_maintenance` does not exist.

- [ ] **Step 3: Implement the smallest pure contract layer**

`contracts.py` must:

```python
MAINTENANCE_EVENT_SCHEMA = "RLRMaintenanceEvent/v1"
_ALLOWED_EVENT_TYPES = {
    "contract_failure",
    "runtime_failure",
    "verification_failure",
    "ci_failure",
    "acceptance_failure",
}
_ALLOWED_SEVERITIES = {"blocking", "warning", "info"}
_ALLOWED_REF_KINDS = {"rlr_artifact", "github_check", "test", "pilot"}

class MaintenanceContractError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

`build_maintenance_event` computes the deduplication payload without `observed_at`, then sets both `dedup_fingerprint=sha256(canonical_payload)` and `event_id=f"rme-{fingerprint[:20]}"`. `validate_maintenance_event` validates required fields, enum values, 40/64-character hex SHAs where present, and rejects absolute `rlr_artifact` references. It must not inspect or mutate scientific payloads.

- [ ] **Step 4: Run GREEN**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rlr_maintenance/__init__.py src/rlr_maintenance/contracts.py tests/test_meta_rlr_contracts.py
git commit -m "feat(meta): add maintenance event contract"
```

---

### Task 2: Normalize failures without coupling to RLR core internals

**Files:**
- Create: `src/rlr_maintenance/observer.py`
- Test: `tests/test_meta_rlr_observer.py`

**Interfaces:**
- Consumes: `build_maintenance_event`
- Produces:
  - `observe_contract_failure(...) -> dict`
  - `observe_process_failure(...) -> dict`
  - `observe_verification_failure(...) -> dict`
  - `observe_acceptance_failure(...) -> dict`

The observer consumes already-authoritative facts. It must not import `research_loop.l0_state`, PR #16 code, or LoopX.

- [ ] **Step 1: Write RED normalization tests**

```python
from rlr_maintenance.observer import observe_contract_failure, observe_process_failure


def test_contract_failure_preserves_error_code_without_proposing_fix():
    event = observe_contract_failure(
        component="l0_restore",
        error_code="L0_RESTORE_ARTIFACT_HASH_MISMATCH",
        detail="03_Source_Data/input.csv",
        expected_contract="l0_restore_fail_closed",
        rlr_revision="a" * 40,
        evidence_refs=[{"kind": "rlr_artifact", "ref": "08_Audit/round_manifests/r1.json"}],
        observed_at="2026-08-13T00:00:00Z",
    )
    assert event["observed"]["error_code"] == "L0_RESTORE_ARTIFACT_HASH_MISMATCH"
    assert "fix" not in event
    assert event["suggested_route"] == "repair"


def test_process_failure_records_exit_code_not_raw_log():
    event = observe_process_failure(
        component="root_entrypoint",
        command=["python", "run_loop.py"],
        exit_code=3,
        expected_contract="runner_nonzero_propagation",
        rlr_revision="a" * 40,
        observed_at="2026-08-13T00:00:00Z",
    )
    assert event["observed"]["exit_code"] == 3
    assert "stderr" not in event["observed"]
```

- [ ] **Step 2: Confirm RED**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_observer.py -q
```

- [ ] **Step 3: Implement normalization functions as thin constructors**

Each function builds only compact facts. `observe_process_failure` stores command basename/arguments only when they are repository-safe and never copies stdout/stderr. `observe_verification_failure` records validator/check identifier and outcome. `observe_acceptance_failure` records acceptance id, failing condition, and compact evidence references.

- [ ] **Step 4: Run contract + observer GREEN**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_contracts.py tests\test_meta_rlr_observer.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/rlr_maintenance/observer.py tests/test_meta_rlr_observer.py
git commit -m "feat(meta): normalize maintenance observations"
```

---

### Task 3: Define verification profiles as metadata around existing RLR contracts

**Files:**
- Create: `src/rlr_maintenance/profiles.py`
- Test: `tests/test_meta_rlr_profiles.py`

**Interfaces:**
- Produces: `VerificationStep`, `VerificationProfile`, `get_profile(profile_id)`, `all_profiles()`
- No profile function may change RLR state.

- [ ] **Step 1: Write RED tests for profile ownership and forbidden shortcuts**

```python
from rlr_maintenance.profiles import get_profile


def test_l0_profile_names_durable_invariants_not_incident_ids():
    profile = get_profile("l0_state_integrity")
    assert "l0_restore_fail_closed" in profile.protected_contracts
    assert "provider_after_restore_only" in profile.protected_contracts
    assert all("PR15" not in value for value in profile.protected_contracts)


def test_l0_profile_forbids_gate_weakening():
    profile = get_profile("l0_state_integrity")
    assert "weaken_validator" in profile.forbidden_success_shortcuts
    assert "convert_fail_to_warn" in profile.forbidden_success_shortcuts
    assert "rewrite_expected_hash" in profile.forbidden_success_shortcuts
```

- [ ] **Step 2: Confirm RED**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_profiles.py -q
```

- [ ] **Step 3: Implement immutable dataclasses and the initial profile catalog**

```python
@dataclass(frozen=True)
class VerificationStep:
    step_id: str
    command: tuple[str, ...]
    required: bool = True

@dataclass(frozen=True)
class VerificationProfile:
    schema_version: str
    profile_id: str
    risk_class: str
    protected_contracts: tuple[str, ...]
    required_validation: tuple[VerificationStep, ...]
    forbidden_success_shortcuts: tuple[str, ...]
```

Initial profiles:

- `l0_state_integrity`
- `l4_frozen_corpus_integrity`
- `l10c_finalization_integrity`

Use exact repository-native test selectors, not replacement validators. For `l0_state_integrity`, required steps include:

```python
VerificationStep("meta_contract", (sys.executable, "-m", "pytest", "tests/test_meta_rlr_contracts.py", "tests/test_meta_rlr_observer.py", "-q")),
VerificationStep("l0_contract_regression", (sys.executable, "-m", "pytest", "-q", "-k", "l0_state or l0_input_contract or cross_round")),
VerificationStep("full_regression", (sys.executable, "-m", "pytest", "-q")),
```

Profiles must not include shell strings, destructive git commands, or commands that mutate project data.

- [ ] **Step 4: Run GREEN**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_profiles.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/rlr_maintenance/profiles.py tests/test_meta_rlr_profiles.py
git commit -m "feat(meta): define RLR verification profiles"
```

---

### Task 4: Execute verification profiles and emit structured receipts

**Files:**
- Create: `src/rlr_maintenance/verification.py`
- Test: `tests/test_meta_rlr_verification.py`

**Interfaces:**
- Consumes: `VerificationProfile`
- Produces: `VerificationStepResult`, `VerificationReceipt`, `run_profile(profile_id, repo_root, runner=subprocess.run) -> VerificationReceipt`

- [ ] **Step 1: Write RED tests using an injected runner**

```python
from types import SimpleNamespace
from rlr_maintenance.verification import run_profile


def test_required_failure_stops_receipt_from_passing(tmp_path):
    def fake_run(command, **kwargs):
        rc = 1 if "full_regression" in str(command) else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr="")

    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)
    assert receipt.passed is False
    assert any(step.returncode != 0 for step in receipt.steps)
```

Also test that `cwd` is always the explicit repository root, `shell=False` is used, and stdout/stderr are summarized by byte counts/digests rather than persisted wholesale.

- [ ] **Step 2: Confirm RED**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_verification.py -q
```

- [ ] **Step 3: Implement deterministic execution**

`run_profile` executes each step in order with:

```python
runner(
    list(step.command),
    cwd=Path(repo_root),
    text=True,
    encoding="utf-8",
    capture_output=True,
    shell=False,
)
```

The receipt stores `step_id`, command tuple, return code, stdout/stderr SHA-256 and byte length. It does not store unbounded logs. Any required nonzero step makes the receipt fail. No retry or repair happens inside the verifier.

- [ ] **Step 4: Run GREEN**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_profiles.py tests\test_meta_rlr_verification.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/rlr_maintenance/verification.py tests/test_meta_rlr_verification.py
git commit -m "feat(meta): execute verification profiles"
```

---

### Task 5: Add a provider-neutral LoopX CLI JSON adapter

**Files:**
- Create: `src/rlr_maintenance/loopx_cli.py`
- Test: `tests/test_meta_rlr_loopx_cli.py`

**Interfaces:**
- Produces: `LoopXError`, `LoopXCli.run_json(args, cwd=None) -> dict`, `LoopXCli.agent_onboard(...) -> dict`, `LoopXCli.quota_should_run(...) -> dict`
- Consumes: external `loopx` executable only; no LoopX imports

- [ ] **Step 1: Write RED subprocess-boundary tests**

Use a temporary fake executable/script that records argv and emits one JSON document. Assert that the adapter:

```python
client = LoopXCli(executable=str(fake_loopx))
packet = client.quota_should_run(goal_id="meta-rlr", agent_id="codex-maintainer", capabilities=("shell",))
assert packet["ok"] is True
assert recorded_argv[:3] == ["--format", "json", "quota"]
```

Also assert nonzero exit, invalid JSON, or multiple JSON documents raise `LoopXError` and do not synthesize success.

- [ ] **Step 2: Confirm RED**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_loopx_cli.py -q
```

- [ ] **Step 3: Implement only documented external commands**

Base runner:

```python
class LoopXCli:
    def __init__(self, executable: str = "loopx", registry: str | None = None): ...

    def run_json(self, args: Sequence[str], *, cwd: str | Path | None = None) -> dict:
        command = [self.executable, "--format", "json"]
        if self.registry:
            command.extend(["--registry", self.registry])
        command.extend(args)
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            capture_output=True,
            shell=False,
        )
        ...
```

High-level methods are limited to commands documented by LoopX 0.4.5 custom-runner integration:

```text
agent-onboard --agent-type other-agent --project <repo> --goal-id <id> --agent-id <id> --task-text <text> --available-capability shell
quota should-run --goal-id <id> --agent-id <id> --available-capability shell
```

Do not add undocumented lifecycle commands by guessing. Event writeback/todo mutation remains driven by the fresh LoopX packet during the real qualification pilot until its exact CLI contract is read from the pinned executable.

- [ ] **Step 4: Run GREEN**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_loopx_cli.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/rlr_maintenance/loopx_cli.py tests/test_meta_rlr_loopx_cli.py
git commit -m "feat(meta): add LoopX CLI boundary"
```

---

### Task 6: Enforce architecture direction and non-overlap with PR #16

**Files:**
- Create: `tests/test_meta_rlr_architecture.py`

**Interfaces:**
- Consumes repository source tree
- Produces executable dependency-direction guardrails

- [ ] **Step 1: Write RED architecture tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_research_loop_never_imports_maintenance_or_loopx():
    offenders = []
    for path in (ROOT / "src" / "research_loop").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "rlr_maintenance" in text or "import loopx" in text or "from loopx" in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_maintenance_does_not_import_loopx_python_modules():
    offenders = []
    for path in (ROOT / "src" / "rlr_maintenance").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import loopx" in text or "from loopx" in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
```

Add an explicit assertion that Phase 1 changed paths do not include `src/research_loop/l0_contract.py`, `src/research_loop/l0_state.py`, L7 data-continuity owners, L4 pipeline owners, or L10c finalization owners. The check should compare the feature branch against base SHA `d6352c0ceeb649efa892e36acc66f209d33920be` using `git diff --name-only` in the test environment only when `.git` is available; otherwise skip only that repository-history assertion, not the source dependency assertions.

- [ ] **Step 2: Run RED before production package is complete, then GREEN after Tasks 1–5**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_architecture.py -q
```

- [ ] **Step 3: Run all Meta-RLR tests**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_contracts.py tests\test_meta_rlr_observer.py tests\test_meta_rlr_profiles.py tests\test_meta_rlr_verification.py tests\test_meta_rlr_loopx_cli.py tests\test_meta_rlr_architecture.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_meta_rlr_architecture.py
git commit -m "test(meta): enforce maintenance ownership boundaries"
```

---

### Task 7: Qualify the historical exit-code defect as the first end-to-end maintenance case

**Files:**
- Test: `tests/test_meta_rlr_historical_case.py`
- No production RLR core change is allowed in this task.

**Interfaces:**
- Consumes: observer, event contract, verification profile, LoopX CLI boundary
- Produces: one deterministic software-level acceptance case; real LoopX execution remains a later local pilot

- [ ] **Step 1: Write a RED/characterization test for the contract chain**

Build a disposable fixture that represents the historical failure facts:

```text
tampered previous-round artifact
→ L0 hash mismatch
→ provider invocation count 0
→ canonical runner result 3
→ root wrapper incorrectly returns 0 (seeded bad variant only)
```

The test must prove that the generic observer produces a `contract_failure`/`runtime_failure` event and that `l0_state_integrity` is selected. It must not contain production special-case logic keyed to PR #15.

- [ ] **Step 2: Confirm the seeded bad variant fails the expected assertion**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_historical_case.py -q
```

Expected: the seeded compatibility wrapper loses exit code and the characterization catches it.

- [ ] **Step 3: Point the case at the current fixed root wrapper and confirm GREEN**

The production repository-root `run_loop.py` must remain unchanged. The case should execute the current wrapper with a deterministic fail-closed input or reuse the already established subprocess-style regression fixture and assert OS return code `3` when the canonical runner returns `3`.

- [ ] **Step 4: Run Meta-RLR + affected RLR regression**

```powershell
rtk proxy python -m pytest tests\test_meta_rlr_historical_case.py -q
rtk proxy python -m pytest -q -k "l0_state or l0_input_contract or cross_round or root_run_loop"
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_meta_rlr_historical_case.py
git commit -m "test(meta): qualify historical fail-closed repair case"
```

---

### Task 8: Full verification, Draft PR, then real local LoopX qualification

**Files:**
- Modify documentation only if observed behavior differs from the approved design; do not change contracts to make the pilot easier.

**Interfaces:**
- Consumes all prior tasks
- Produces GitHub CI evidence and a real local LoopX/Codex pilot result

- [ ] **Step 1: Run full repository verification**

```powershell
rtk proxy python -m pytest -q
rtk git diff --check
python run_loop.py --help
```

Expected: full suite PASS, diff check PASS, root CLI help exits 0.

- [ ] **Step 2: Audit exact scope against base**

```powershell
git diff --name-only d6352c0ceeb649efa892e36acc66f209d33920be...HEAD
```

Allowed implementation paths are only:

```text
src/rlr_maintenance/**
tests/test_meta_rlr_*.py
docs/superpowers/specs/2026-08-13-meta-rlr-loopx-maintenance-boundary-design.md
docs/superpowers/plans/2026-08-13-meta-rlr-loopx-maintenance-boundary.md
```

Any RLR core path requires stopping and re-auditing the architecture before proceeding.

- [ ] **Step 3: Open a Draft PR against `codex/l4a-source-metadata-contract`**

PR body must state:

```text
- scientific DAG unchanged
- LoopX fork unchanged
- PR #16 data-continuity path untouched
- no auto-merge authority
- RLR/GitHub remain sources of truth
- exact LoopX pinned SHA
- exact tests and observed results
- local real LoopX pilot still pending until it is actually run
```

- [ ] **Step 4: Wait for GitHub CI results and classify any failure before editing**

Any CI failure must first be classified as product bug, test/fixture defect, environment/dependency failure, external-tool failure, or insufficient evidence. No patch is allowed before that classification.

- [ ] **Step 5: Run the real local LoopX qualification on pinned 0.4.5**

Use `hk20013106/loopx@80877982216577174e3e7c7cca9804c5a3a3148b`, the real `loopx` executable, and a disposable RLR worktree/branch seeded with the historical exit-code defect. The host must use fresh LoopX JSON packets each turn, not cached transcript state.

Acceptance chain:

```text
real seeded RLR failure
→ generic RLRMaintenanceEvent/v1
→ LoopX goal/todo/evidence state survives a fresh process/session
→ Codex receives one bounded repair todo
→ failure reproduced before edit
→ minimal repair
→ RLR verification profile passes
→ provider invocation after failed restore remains 0
→ root exit code becomes 3
→ Draft PR / evidence writeback
→ STOP before merge
```

Required local report fields:

```text
RLR_BASE_SHA
RLR_REPAIR_SHA
LOOPX_SHA
MAINTENANCE_EVENT_ID
LOOPX_GOAL_ID
LOOPX_STATE_RECOVERY = PASS/FAIL
ROOT_CAUSE_CLASS
RED_REPRODUCTION = PASS/FAIL
PROTECTED_PATH_VIOLATION = YES/NO
TARGETED_VERIFICATION = PASS/FAIL
FULL_REGRESSION = PASS/FAIL
TAMPER_FAIL_CLOSED = PASS/FAIL
PROVIDER_INVOCATION_AFTER_TAMPER = <integer>
ROOT_RUN_LOOP_EXIT_CODE = <integer>
CODE_AUTO_MERGED = YES/NO
FINAL_META_RLR_PILOT = PASS/FAIL
ROOT_CAUSE
```

- [ ] **Step 6: Stop at the phase boundary**

Do not mark the PR ready or merge solely because the synthetic suite passes. The first real LoopX qualification is the pre-merge evidence gate for this feature.
