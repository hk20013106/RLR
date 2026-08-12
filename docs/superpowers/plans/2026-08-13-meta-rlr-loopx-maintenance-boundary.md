# Meta-RLR LoopX Maintenance Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral maintenance boundary that turns authoritative RLR software/runtime failures into durable maintenance events, validates repair classes against RLR-native invariants, and exchanges maintenance state with LoopX through its documented CLI JSON boundary without changing the scientific DAG or creating a second state owner.

**Architecture:** Add a separate `rlr_maintenance` namespace beside `research_loop`. It owns only observation normalization, maintenance contracts, verification profiles, and an external LoopX CLI adapter. `research_loop` must never import `rlr_maintenance` or LoopX. RLR/GitHub remain authoritative for research state, software contracts, source revisions, CI, and acceptance; LoopX owns only maintenance goal/todo/evidence/monitor/replan state.

**Tech Stack:** Python 3.13, stdlib-only production code, pytest, LoopX 0.4.5 pinned at `80877982216577174e3e7c7cca9804c5a3a3148b` for the first real pilot.

## Global Constraints

- Base lineage: `d6352c0ceeb649efa892e36acc66f209d33920be`; branch: `feat/meta-rlr-loopx-adapter`.
- Do not modify RLR DAG, L0/L4/L10c semantics, candidate state, or scientific data.
- Do not modify or vendor `hk20013106/loopx` in Phase 1; use external CLI JSON only.
- Do not create a second database, scheduler, manifest, or scientific source of truth.
- Do not depend on open PR #16 round-data-continuity code; read only stable receipts/contract outcomes/CI facts on the base line.
- Do not auto-merge. Stop after verified Draft PR and real local qualification.
- Never weaken validators, convert FAIL to WARN, rewrite expected hashes, skip required tests, or add parallel state ownership to make a repair pass.
- TDD: RED before each production behavior, then minimal GREEN, then focused review/commit.

## File Map

```text
src/rlr_maintenance/
├── __init__.py
├── contracts.py
├── observer.py
├── profiles.py
├── verification.py
└── loopx_cli.py

tests/
├── test_meta_rlr_contracts.py
├── test_meta_rlr_observer.py
├── test_meta_rlr_profiles.py
├── test_meta_rlr_verification.py
├── test_meta_rlr_loopx_cli.py
├── test_meta_rlr_architecture.py
└── test_meta_rlr_historical_case.py
```

Do not add a file under `src/research_loop/` unless a failing test proves the existing public read surfaces are insufficient. If that occurs, stop and re-audit ownership first.

---

### Task 1: Maintenance event contract

**Files:** create `src/rlr_maintenance/__init__.py`, `src/rlr_maintenance/contracts.py`; test `tests/test_meta_rlr_contracts.py`.

**Produces:** `MaintenanceContractError`, `build_maintenance_event(...)`, `validate_maintenance_event(...)`, `canonical_json(...)`.

- [ ] Write RED tests:

```python
import pytest
from rlr_maintenance.contracts import MaintenanceContractError, build_maintenance_event, validate_maintenance_event


def test_event_id_ignores_observation_time():
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


def test_absolute_rlr_artifact_ref_is_rejected():
    with pytest.raises(MaintenanceContractError, match="relative"):
        build_maintenance_event(
            event_type="runtime_failure", component="runner", severity="blocking",
            rlr_revision="a" * 40, observed={"exit_code": 3},
            expected_contract="runner_nonzero_propagation",
            evidence_refs=[{"kind": "rlr_artifact", "ref": "D:/private/data.csv"}],
            observed_at="2026-08-13T00:00:00Z",
        )
```

- [ ] Run RED: `rtk proxy python -m pytest tests\test_meta_rlr_contracts.py -q`.
- [ ] Implement pure stdlib contract with schema `RLRMaintenanceEvent/v1`, enums for the five Phase-1 event types, relative-path validation for `rlr_artifact`, canonical JSON, SHA-256 dedup payload excluding `observed_at`, and `event_id="rme-" + fingerprint[:20]`.
- [ ] Run GREEN with the same command.
- [ ] Commit: `feat(meta): add maintenance event contract`.

---

### Task 2: Failure observation normalization

**Files:** create `src/rlr_maintenance/observer.py`; test `tests/test_meta_rlr_observer.py`.

**Produces:** `observe_contract_failure`, `observe_process_failure`, `observe_verification_failure`, `observe_acceptance_failure`.

- [ ] RED tests prove contract error codes and exit codes are preserved, no `fix` field is emitted, and raw stdout/stderr are not copied.

```python
from rlr_maintenance.observer import observe_contract_failure, observe_process_failure


def test_contract_failure_is_fact_not_patch_proposal():
    event = observe_contract_failure(
        component="l0_restore", error_code="L0_RESTORE_ARTIFACT_HASH_MISMATCH",
        detail="03_Source_Data/input.csv", expected_contract="l0_restore_fail_closed",
        rlr_revision="a" * 40, evidence_refs=[], observed_at="2026-08-13T00:00:00Z")
    assert event["observed"]["error_code"] == "L0_RESTORE_ARTIFACT_HASH_MISMATCH"
    assert "fix" not in event


def test_process_failure_does_not_copy_raw_log():
    event = observe_process_failure(
        component="root_entrypoint", command=["python", "run_loop.py"], exit_code=3,
        expected_contract="runner_nonzero_propagation", rlr_revision="a" * 40,
        observed_at="2026-08-13T00:00:00Z")
    assert event["observed"]["exit_code"] == 3
    assert "stderr" not in event["observed"]
```

- [ ] Run RED: `rtk proxy python -m pytest tests\test_meta_rlr_observer.py -q`.
- [ ] Implement thin constructors only. Do not import `research_loop.l0_state`, PR #16 modules, or LoopX.
- [ ] Run `tests\test_meta_rlr_contracts.py` + observer GREEN.
- [ ] Commit: `feat(meta): normalize maintenance observations`.

---

### Task 3: Verification profile catalog

**Files:** create `src/rlr_maintenance/profiles.py`; test `tests/test_meta_rlr_profiles.py`.

**Produces:** immutable `VerificationStep`, `VerificationProfile`, `get_profile`, `all_profiles`.

- [ ] RED tests require durable invariant names and anti-patch rules:

```python
from rlr_maintenance.profiles import get_profile


def test_l0_profile_protects_architecture_not_incident_number():
    p = get_profile("l0_state_integrity")
    assert "l0_restore_fail_closed" in p.protected_contracts
    assert "provider_after_restore_only" in p.protected_contracts
    assert all("PR15" not in x for x in p.protected_contracts)
    assert {"weaken_validator", "convert_fail_to_warn", "rewrite_expected_hash"} <= set(p.forbidden_success_shortcuts)
```

- [ ] Run RED: `rtk proxy python -m pytest tests\test_meta_rlr_profiles.py -q`.
- [ ] Implement frozen dataclasses with schema `RLRVerificationProfile/v1` and profiles `l0_state_integrity`, `l4_frozen_corpus_integrity`, `l10c_finalization_integrity`.
- [ ] `l0_state_integrity` steps must include exact argv tuples for Meta contract tests, `pytest -q -k "l0_state or l0_input_contract or cross_round"`, and full `pytest -q`. No shell strings or mutating commands.
- [ ] Run GREEN.
- [ ] Commit: `feat(meta): define RLR verification profiles`.

---

### Task 4: Verification execution and receipt

**Files:** create `src/rlr_maintenance/verification.py`; test `tests/test_meta_rlr_verification.py`.

**Produces:** `VerificationStepResult`, `VerificationReceipt`, `run_profile(profile_id, repo_root, runner=subprocess.run)`.

- [ ] RED test uses call order rather than nonexistent step ids in argv:

```python
from types import SimpleNamespace
from rlr_maintenance.verification import run_profile


def test_required_failure_makes_receipt_fail(tmp_path):
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        rc = 1 if len(calls) == 3 else 0
        return SimpleNamespace(returncode=rc, stdout="ok", stderr="")
    receipt = run_profile("l0_state_integrity", tmp_path, runner=fake_run)
    assert receipt.passed is False
    assert len(receipt.steps) == 3
    assert receipt.steps[-1].returncode == 1
```

Also assert explicit `cwd`, `shell=False`, UTF-8, and that receipts store stdout/stderr byte length + SHA-256 rather than raw logs.

- [ ] Run RED: `rtk proxy python -m pytest tests\test_meta_rlr_verification.py -q`.
- [ ] Implement ordered deterministic execution; no retry and no repair inside verifier.
- [ ] Run profiles + verification GREEN.
- [ ] Commit: `feat(meta): execute verification profiles`.

---

### Task 5: External LoopX CLI JSON boundary

**Files:** create `src/rlr_maintenance/loopx_cli.py`; test `tests/test_meta_rlr_loopx_cli.py`.

**Produces:** `LoopXError`, `LoopXCli.run_json`, `LoopXCli.agent_onboard`, `LoopXCli.quota_should_run`.

- [ ] RED tests use a temporary fake executable that records `sys.argv[1:]` and emits one JSON object. Assert `quota_should_run` sends `--format json quota should-run ...`; nonzero exit, invalid JSON, or more than one JSON document must raise `LoopXError`.
- [ ] Run RED: `rtk proxy python -m pytest tests\test_meta_rlr_loopx_cli.py -q`.
- [ ] Implement `subprocess.run([...], shell=False, text=True, encoding="utf-8", capture_output=True)` and optional `--registry`.
- [ ] High-level methods are limited to documented LoopX 0.4.5 custom-runner commands:
  - `agent-onboard --agent-type other-agent --project ... --goal-id ... --agent-id ... --task-text ... --available-capability shell`
  - `quota should-run --goal-id ... --agent-id ... --available-capability shell`
- [ ] Do not guess undocumented todo/writeback commands. Real pilot must read fresh LoopX packets and use the pinned executable's returned/current contract for writeback.
- [ ] Run GREEN.
- [ ] Commit: `feat(meta): add LoopX CLI boundary`.

---

### Task 6: Architecture guards

**Files:** create `tests/test_meta_rlr_architecture.py`.

- [ ] Add tests that scan `src/research_loop/**/*.py` and fail if it imports `rlr_maintenance` or LoopX; scan `src/rlr_maintenance/**/*.py` and fail on Python imports from LoopX.
- [ ] Add a git-aware scope test against base SHA `d6352c0ceeb649efa892e36acc66f209d33920be`. When `.git` exists, changed implementation files are restricted to `src/rlr_maintenance/**`, `tests/test_meta_rlr_*.py`, and the approved spec/plan docs. Explicitly reject changes to L0, L7 data continuity owners, L4 pipeline owners, and L10c finalization owners. If `.git` is absent, skip only this history assertion.
- [ ] Run all Meta-RLR tests; expected PASS.
- [ ] Commit: `test(meta): enforce maintenance ownership boundaries`.

---

### Task 7: Historical fail-closed qualification case

**Files:** create `tests/test_meta_rlr_historical_case.py`; no RLR core modifications.

- [ ] Build a disposable seeded bad wrapper that returns OS 0 while a canonical stub returns 3; characterize the failure chain `hash mismatch → provider count 0 → canonical 3 → bad wrapper 0`.
- [ ] Prove the generic observer emits maintenance events and selects `l0_state_integrity`; no production code may branch on PR #15 or the historical commit id.
- [ ] Execute the current repository-root `run_loop.py` through the existing subprocess-style contract and assert the fixed path propagates nonzero fail-closed status; do not modify `run_loop.py`.
- [ ] Run: `rtk proxy python -m pytest tests\test_meta_rlr_historical_case.py -q` and `rtk proxy python -m pytest -q -k "l0_state or l0_input_contract or cross_round or root_run_loop"`.
- [ ] Commit: `test(meta): qualify historical fail-closed repair case`.

---

### Task 8: Full verification, Draft PR, real LoopX pilot

- [ ] Run `rtk proxy python -m pytest -q`, `rtk git diff --check`, and `python run_loop.py --help`.
- [ ] Audit `git diff --name-only d6352c0ceeb649efa892e36acc66f209d33920be...HEAD`; any RLR core path means stop and re-audit architecture.
- [ ] Open Draft PR against `codex/l4a-source-metadata-contract`; state scientific DAG unchanged, LoopX fork unchanged, PR #16 untouched, no auto-merge, exact LoopX SHA, exact test results, and local real pilot pending.
- [ ] Classify any CI failure before editing: product bug / fixture defect / environment-dependency / external tool / insufficient evidence.
- [ ] After CI is green, run a real local pilot with `hk20013106/loopx@80877982216577174e3e7c7cca9804c5a3a3148b`, a disposable RLR worktree seeded with the historical exit-code defect, fresh LoopX JSON packets each turn, and Codex as the bounded repair worker.

Acceptance chain:

```text
seeded real RLR failure
→ RLRMaintenanceEvent/v1
→ LoopX state survives fresh process/session
→ one bounded Codex repair todo
→ RED reproduction before edit
→ minimal repair
→ RLRVerificationProfile/v1 passes
→ tampered restore still fails closed
→ provider invocation after tamper = 0
→ root exit code = 3
→ Draft PR/evidence writeback
→ STOP before merge
```

Required report:

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

- [ ] Stop at the phase boundary. Do not mark ready or merge until the real LoopX qualification passes and the user explicitly authorizes the next promotion step.
