# Atomic Retry Activation Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an authorized L0.5 retry a single crash-consistent commit whose active lineage and consumption state are derived only from one atomically renamed transaction directory.

**Architecture:** Keep frozen EvidencePacks immutable and keep the existing initial v1 binding path compatible. For retry v2+ operations, validate authorization, parent lineage, and the new frozen pack in memory, write binding/consumption/activation artifacts into a uniquely named staging directory, then atomically rename that directory into a final transaction directory. The final transaction receipt is the sole committed retry authority; incomplete staging directories are ignored, and replay of an already committed authorization returns the authenticated committed result.

**Tech Stack:** Python 3, pathlib/os atomic filesystem operations, JSON canonical serialization, pytest, immutable L05 EvidencePack contracts.

---

## Scope and state model

The authoritative committed retry fact is the presence of a validated final transaction directory:

```text
08_Audit/research_seed_bindings/native/<candidate>/<round>/retry_transactions/<authorization_id>/
  commit.json
  binding.json
  consumption.json
  activation.json
```

`commit.json` records the authorization identity, acquisition run, and SHA-256 hashes of the three sibling artifacts. The directory is created under a sibling staging name and committed with `os.replace(staging_dir, final_dir)`. Readers use only final transaction directories and legacy activation receipts; staging directories are recoverable temporary state and never establish active lineage.

The retry state transitions are:

```text
OPEN gap request
  -> deterministic authorization (read-only)
  -> frozen retry EvidencePack (immutable artifact)
  -> staged binding + staged consumption + staged activation
  -> atomic transaction-directory rename
  -> active lineage derived from committed activation receipt
```

Before the rename there is no committed consumption and no active retry lineage. After the rename all three receipts are present and validated, so replay is idempotent. The existing standalone `consume_gap_retry_authorization` and legacy direct binding/activation APIs remain compatible for existing callers, but `run_authorized_retry` no longer invokes the three-step sequence.

### Task 1: Add failure-injection regressions for the retry protocol

**Files:**

- Modify: `tests/test_l05_curie_native_runtime.py`
- Modify: `tests/test_l05_native_evidence_binding.py`
- Modify: `tests/test_l05_curie_gap_loop.py` only if authorization replay assertions need a focused helper

- [ ] **Step 1: Add a deterministic test hook and failure matrix tests before implementation**

Extend the existing native runtime fixtures with a helper that runs one valid v1-to-v2 retry and a failure injector that raises at named transaction steps. Add tests for:

```python
@pytest.mark.parametrize(
    "failure_step",
    ["before_stage", "after_binding", "after_consumption", "during_activation"],
)
def test_interrupted_retry_has_no_committed_intermediate_state(tmp_path, failure_step):
    seed, first, request = _initialized_retry_fixture(tmp_path)

    def acquire(auth):
        return _freeze_retry_pack(tmp_path, auth, run_id="CURIE002")

    with pytest.raises(curie.CurieContractError, match="injected"):
        run_authorized_retry(
            tmp_path, seed, first, request["request_id"], "CURIE002", acquire,
            failure_step=failure_step,
        )

    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE001"
    assert not list((tmp_path / "08_Audit" / "research_seed_bindings" / "native"
                     / "C001" / "1" / "retry_transactions").glob("*/commit.json"))
    with pytest.raises(curie.CurieContractError, match="missing|invalid"):
        curie.load_gap_retry_consumption(tmp_path, seed, request["authorization"], "CURIE002")

def test_interrupted_retry_replays_to_one_committed_transaction(tmp_path):
    seed, first, request = _initialized_retry_fixture(tmp_path)
    calls = iter(["after_consumption", None])

    def acquire(auth):
        return _freeze_retry_pack(tmp_path, auth, run_id="CURIE002")

    with pytest.raises(curie.CurieContractError, match="injected"):
        run_authorized_retry(
            tmp_path, seed, first, request["request_id"], "CURIE002", acquire,
            failure_step=next(calls),
        )
    result = run_authorized_retry(
        tmp_path, seed, first, request["request_id"], "CURIE002", acquire,
        failure_step=next(calls),
    )
    assert research_seed.active_l1_native_evidence_run_id(tmp_path, seed) == "CURIE002"
    assert len(list(transaction_root.glob("*/commit.json"))) == 1
    assert result["activation"]["evidence_pack_version"] == 2

def test_committed_retry_replay_is_idempotent_and_rejects_different_run(tmp_path):
    # First execution commits CURIE002. Repeating the exact request returns the
    # same receipt; changing acquisition_run_id fails without a second commit.
```

The tests must also assert that a staged directory may remain after an injected crash but cannot be discovered by active-lineage or consumption readers, that v1 remains immutable, and that the activation receipt has one parent and one next version.

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_l05_curie_native_runtime.py tests/test_l05_native_evidence_binding.py -q
```

Expected: the new failure-injection arguments are rejected or the old three-write path leaves a committed consumption/activation artifact for at least one injected boundary. This RED result must be caused by the missing atomic protocol, not test collection or import failure.

- [ ] **Step 3: Commit the RED checkpoint**

```powershell
git add tests/test_l05_curie_native_runtime.py tests/test_l05_native_evidence_binding.py tests/test_l05_curie_gap_loop.py
git commit -m "test: specify atomic l05 retry activation"
```

### Task 2: Implement one atomically committed retry transaction

**Files:**

- Modify: `src/research_loop/l05_curie/native_runtime.py`
- Modify: `src/research_loop/l05_native_binding.py`
- Modify: `src/research_loop/l05_curie/gap_loop.py` only where committed transaction consumption lookup must be recognized

- [ ] **Step 1: Add canonical transaction paths and atomic directory commit helpers**

In `l05_native_binding.py`, add helpers that derive a safe transaction id from `authorization_id`, build a sibling staging directory, write canonical JSON with exclusive deterministic paths, calculate artifact hashes, and commit with `os.replace`. A final transaction is valid only when `commit.json` agrees with all sibling bytes and all payload lineage checks pass. Never let a staging path participate in `_load_activations`, `active_l1_native_evidence_run_id`, or retry authorization consumption checks.

```python
def _retry_transaction_dir(project: Path, seed: dict, authorization_id: str) -> Path:
    return _binding_dir(project, seed) / "retry_transactions" / authorization_id

def _commit_retry_transaction(project_dir: str | Path, seed: dict,
                              pack_manifest: dict, acquisition_run_id: str,
                              authorization: dict, *, failure_hook=None) -> dict:
    # Validate the frozen pack and authorization, construct all three payloads
    # in memory, write them only below a unique staging directory, write the
    # commit receipt last, then os.replace(staging, final). If final exists,
    # validate its complete receipt and return it only when every identity field
    # matches the replay request.
```

The transaction commit receipt must include `schema_version`, `authorization_id`, `candidate_id`, `round_id`, `acquisition_run_id`, `authorization`, and the canonical SHA-256 hashes and relative paths for `binding.json`, `consumption.json`, and `activation.json`. The activation payload must reference the binding entry inside the same final transaction directory. All writes must use canonical bytes; a failure before rename must not create a final `commit.json`.

- [ ] **Step 2: Make retry readers derive state from committed transactions**

Update binding and activation readers to discover a committed retry transaction for a run id, validate its receipt and sibling files, and return the embedded canonical payload. Include committed transaction activations in `_load_activations` in version order, while retaining legacy v1 activation compatibility. Update `active_l1_native_evidence_run_id` and `unique_l1_native_evidence_run_id` to use the combined validated activation view.

Update `gap_loop.load_gap_retry_consumption` and `authorize_gap_retry` so a committed transaction is the authoritative source for consumption when the legacy `consumed/<request>.json` path is absent. A committed authorization cannot be authorized again; an incomplete staging directory does not count as consumed.

- [ ] **Step 3: Route `run_authorized_retry` through the transaction commit**

Replace the calls to `write_l1_native_evidence_binding`, `consume_gap_retry_authorization`, and `activate_l1_native_evidence_binding` with one call to the installed/native transaction commit API. Preserve the returned result shape (`authorization`, `consumption`, `activation`, `binding`, `evidence_pack`, and `evidence_pack_content_sha256`) so existing production callers remain compatible. The injected failure hook is test-only plumbing and defaults to `None` in production.

- [ ] **Step 4: Run the same tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_l05_curie_native_runtime.py tests/test_l05_native_evidence_binding.py tests/test_l05_curie_gap_loop.py -q
```

Expected: PASS, including every failure-injection point, replay idempotency, no false consumption, no orphan active lineage, and immutable v1 EvidencePack behavior.

- [ ] **Step 5: Commit the GREEN checkpoint**

```powershell
git add src/research_loop/l05_curie/native_runtime.py src/research_loop/l05_native_binding.py src/research_loop/l05_curie/gap_loop.py
git commit -m "fix: make l05 retry activation atomic"
```

### Task 3: Characterize recovery and preserve neighboring contracts

**Files:**

- Modify: `tests/test_l05_curie_native_runtime.py`
- Modify: `tests/test_l05_native_evidence_binding.py`
- Modify: `tests/test_l05_curie_fullcycle.py` only if a production retry path needs a characterization assertion
- Create: `docs/testing/2026-08-26-atomic-retry.tdd.md`

- [ ] **Step 1: Add recovery assertions for every crash boundary**

Verify after each interrupted attempt that the parent remains active, no committed transaction is visible, the retry request can be re-authorized, and no frozen historical pack bytes changed. Verify after successful replay that exactly one final transaction exists, `load_gap_retry_consumption` returns the same receipt, and a second identical call returns byte-equivalent binding/consumption/activation objects.

- [ ] **Step 2: Run the focused and neighboring suites**

```powershell
python -m pytest tests/test_l05_curie_native_runtime.py tests/test_l05_native_evidence_binding.py tests/test_l05_curie_gap_loop.py tests/test_l05_curie_fullcycle.py -q
```

Record the exact pass count and exit status in the TDD evidence report. Do not claim crash consistency from unit tests that do not inspect persisted paths.

- [ ] **Step 3: Write the TDD evidence report**

Document the plan path, RED output, GREEN output, each failure boundary, replay guarantee, persisted-state assertions, and known gap that a process-level power loss is represented by the filesystem atomic-rename contract plus deterministic injected failures.

- [ ] **Step 4: Commit the characterization/evidence checkpoint**

```powershell
git add tests/test_l05_curie_native_runtime.py tests/test_l05_native_evidence_binding.py tests/test_l05_curie_fullcycle.py docs/testing/2026-08-26-atomic-retry.tdd.md
git commit -m "test: document l05 retry recovery guarantees"
```

### Task 4: Review and complete the Phase B gate

**Files:**

- Review: `src/research_loop/l05_curie/native_runtime.py`
- Review: `src/research_loop/l05_native_binding.py`
- Review: `src/research_loop/l05_curie/gap_loop.py`
- Review: all Phase B tests and the TDD evidence report

- [ ] **Step 1: Run full pytest and integrity checks**

```powershell
python -m pytest -q
git diff --check origin/main...HEAD
python research_loop_v04.py --help
python run_loop.py --help
```

Record exact exit status, pass/fail/skip counts, and any warnings.

- [ ] **Step 2: Perform separate correctness and thermo-nuclear reviews**

Correctness review must confirm: one final transaction directory is the only committed retry authority; every failure boundary leaves the parent active; committed replay is idempotent; no retry can consume twice; activation lineage is contiguous; frozen EvidencePacks are read-only; and legacy v1 paths remain compatible.

Thermo-nuclear review must ask whether the change actually removes the semantic three-write commit, whether temporary artifacts can accidentally become active, whether readers have two competing retry authorities, whether a generic transaction layer was added without need, and whether the static authority graph is simpler.

- [ ] **Step 3: Commit any review-only correction and re-run relevant tests**

If review identifies a defect, add a narrowly scoped correction commit, rerun the affected focused suite and full pytest, and update the evidence report with actual output. Do not weaken a test or silently classify a failure as environmental.

- [ ] **Step 4: Push and verify exact-head CI**

```powershell
git status --short
git push -u origin codex/l05-atomic-retry
```

Create one Draft PR from `codex/l05-atomic-retry` to `main` if one does not already exist. Verify every required CI check against the exact pushed SHA, including both Windows full checks and any live smoke. If an external service fails, classify and rerun only when appropriate; do not call it an implementation pass.

- [ ] **Step 5: Stop and report Phase B**

Report branch, commits, files, state-machine before/after, atomic commit mechanism, failure-injection results, focused suite, full pytest, exact-head CI, remaining risks, and explicitly state that Phase C has not started.

## Plan self-review

- Spec coverage: the failure matrix covers before first durable write, after binding, after consumption, during activation, and interrupted replay; tests inspect active lineage, consumption, duplicate commit count, and frozen pack bytes.
- Scope: only Phase B retry/activation code and its tests/evidence are changed; no Phase C installer decomposition or P2 cleanup is included.
- Authority: final transaction receipt and directory rename are the only semantic retry commit; staging artifacts are temporary and ignored.
- Compatibility: initial v1 and legacy direct APIs remain available while the production retry orchestration uses the atomic protocol.
- No frozen artifact migration: existing EvidencePack files are validated and never rewritten.
