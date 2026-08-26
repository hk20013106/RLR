# Phase B Atomic Retry Activation TDD Evidence

Source plan: [2026-08-26-atomic-retry.md](../superpowers/plans/2026-08-26-atomic-retry.md)

## User journeys

- As the L0.5 runtime, I want binding, retry consumption, and activation to
  become visible together so that a failure before commit cannot advance the
  active EvidencePack lineage.
- As a retry operator, I want an interrupted attempt to be replayable so that
  an incomplete attempt neither consumes the request nor creates an orphan
  active lineage.
- As an EvidencePack consumer, I want committed retry receipts to validate
  their sibling artifacts and hashes so that tampering or partial writes fail
  closed.

## RED evidence

Command:

```powershell
python -m pytest tests/test_l05_curie_native_runtime.py tests/test_l05_native_evidence_binding.py -q
```

Before implementation: `6 failed, 13 passed in 2.21s`.

The new tests exposed the intended old behavior: `run_authorized_retry` had no
transaction failure boundary, and replay after the old consumption write raised
`EvidenceGapRequest retry authorization was already consumed` instead of
recovering.

## GREEN and regression evidence

| # | What is guaranteed | Test file or command | Test type | Result | Evidence |
|---|---|---|---|---|---|
| 1 | Failure before staging, after binding, after consumption, during activation, and after writing the commit receipt but before directory rename leaves no committed retry transaction. | `tests/test_l05_curie_native_runtime.py::test_interrupted_retry_has_no_committed_intermediate_state` | integration/failure injection | PASS | Five parametrized boundaries passed in the 30-test Phase B suite. |
| 2 | Staging directories, including a staging `commit.json`, are ignored by active-lineage and consumption readers. | same test and transaction reader implementation | integration | PASS | Parent `CURIE001` remained active after each injected failure. |
| 3 | An interrupted retry can replay after the frozen pack already exists and creates exactly one final transaction. | `tests/test_l05_curie_native_runtime.py::test_interrupted_retry_replays_to_one_committed_transaction` | integration/recovery | PASS | Final transaction count was one and active run became `CURIE002`. |
| 4 | Exact committed replay is idempotent and a different acquisition run is rejected. | `tests/test_l05_curie_native_runtime.py::test_committed_retry_replay_is_idempotent_and_rejects_different_run` | integration | PASS | Replay result was equal; conflicting run failed closed. |
| 5 | Existing v1 binding, legacy direct consumption/activation, v2 lineage, and fullcycle context consumers remain compatible. | `tests/test_l05_curie_native_runtime.py tests/test_l05_native_evidence_binding.py tests/test_l05_curie_gap_loop.py tests/test_l05_curie_fullcycle.py` | integration | PASS | `30 passed in 3.78s`. |
| 6 | All L0.5 and ResearchSeed neighboring contracts remain green. | all `test_l05*`, `test_l05_native_l1_handoff.py`, `test_l1_research_seed_authority.py` | regression | PASS | `126 passed in 8.45s`. |
| 7 | The repository-wide regression suite remains green. | `python -m pytest -q --no-header -p no:cacheprovider --cov=src --cov-report=term-missing` | full regression | PASS | `1027 passed, 28 warnings in 1161.10s (0:19:21)`; total coverage `72%`. |

## Protocol guarantee

The new retry path writes canonical `binding.json`, `consumption.json`, and
`activation.json` below a uniquely named staging directory. It writes a
canonical `commit.json` containing sibling paths and SHA-256 hashes, then uses
`os.replace(staging_dir, final_dir)` as the only semantic commit point. Readers
enumerate only final transaction directories, validate every sibling and hash,
and derive active lineage from the validated activation receipt. Incomplete
staging directories are recoverable temporary state and do not count as
consumed or active.

Frozen EvidencePack files are never rewritten. On replay, the acquisition
callback may recover the already-frozen manifest; the retry transaction remains
idempotent and keyed by the deterministic authorization id.

## Coverage and known gaps

The correctly specified focused coverage command reported 73% across the three
Phase B modules (`gap_loop.py`, `native_runtime.py`, and
`l05_native_binding.py`), while the full repository run reported 72%. The
repository has no project-wide 80% threshold and contains substantial
pre-existing unexecuted compatibility/error branches. The Phase B behavioral
contract is covered by persisted-path and failure-injection tests above; a
separate follow-up could raise broad branch coverage without changing this
protocol.

The tests inject deterministic exceptions at filesystem transaction boundaries;
they do not simulate power loss at the operating-system level. The production
guarantee relies on the platform's atomic same-volume directory rename and the
receipt/hash validation performed on recovery.

