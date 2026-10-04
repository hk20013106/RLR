# Task 11B IL-22 Cumulative Corpus Acceptance — r4

**Verdict: `REAL_E2E=PASS` through Coverage.** The live path completed with real Europe PMC results, a 30-paper corpus, the pinned PaperQA2 worker, source verification, semantic admission, and scientific coverage. This verdict does not include L1 or later research execution.

## Scope and lineage

- Seed: existing IL-22 intestinal-repair acceptance seed.
- Fresh project: `D:\research_loop\paperqa2-task11b-il22-acceptance-20261003-r4d`
- Project ID: `PROJECT:5e7816c9-f5d7-51a5-a579-c3eb6fcfb67a`
- Candidate: `C20261003033007108830`
- Acquisition: `EPMC_ee13af8daa8911d5b3354826`
- Attempt: 1 of 3; terminal state `FROZEN`.
- This lineage has its own project readiness receipt, candidate, and acquisition checkpoint. It did not reuse r3's receipt, candidate, or checkpoint. The historical r3 report remains at `reports/2026-10-03-task11b-il22-cumulative-corpus-acceptance-r3.md`; its observed SHA-256 is `bb83d400391df4ade0ef6aa1e08ef40e5f88f6138dfb833ce6a4b6dd96f2a151`.

The RLR repository was `D:\research_loop\main`, branch `review/l05-p1-final-diff`, HEAD `c60632afdb3aabd6e7c55ffea8dd6a43c50c7982`. The worktree had existing dirty changes. This acceptance did not alter PaperQA2 or RLR production code, and no dirty changes were reset or discarded.

## Runtime and credential boundary

The effective PaperQA2 binding is `worker_mode=corpus-evidence-v1`, `timeout_seconds=600`, `evidence_k=60`, and `evidence_focus=null`. The worker interpreter was `D:\research_loop\paper-qa\.venv\Scripts\python.exe`. PaperQA2 reported version `2026.8.12`, upstream commit `57e89f7223b0960d5ee5ea048c69e3c47e088572`; embedding was `st-multi-qa-MiniLM-L6-cos-v1`, and the internal summary/relevance model was `deepseek/deepseek-flash`.

The authorized DeepSeek credential was made available only to the acceptance process and allowlisted host-submit/worker child environments. The current Codex session remained the sole host-cognition owner and used the existing `host-next` / `host-submit` protocol. `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` were forwarded to the relevant children. Credential-probe and host-submit forwarding/redaction tests passed. No credential value or derived identifier was intentionally persisted to the binding, task, result, checkpoint, or this report.

## Live acquisition and query quality

Europe PMC returned seven planned queries and 37 recorded HTTP request/response pairs. The acquisition selected 30 papers and wrote 30 source XML snapshots; an independent final check found all 30 files present with hashes matching the manifest. There were no paper-level acquisition failures.

| Query | Europe PMC hits |
| --- | ---: |
| Q001 `("epithelial repair") AND (il-22)` | 4,846 |
| Q002 `("barrier recovery") AND (il-22)` | 804 |
| Q003 `("epithelial cell states") AND (il-22)` | 120 |
| Q004 `(il-22) AND ("mammalian intestinal injury models")` | 0 |
| Q005 `("epithelial stat3-dependent proliferation") AND (il-22)` | 0 |
| Q006 `(il-22) AND ("regenerative transcription")` | 35 |
| Q007 `(il-22) AND ("injury context")` | 164 |

Q004 and Q005 remain recorded as seed-literal / zero-hit query-quality issues. No formal query was manually changed, and neither zero-hit query stopped this acceptance because the other queries produced a real corpus.

## PaperQA2 worker

The worker completed with return code 0, no terminal context errors, and no observed timeout or provider failure. It ingested 30 papers and 2,542 texts and returned 48 contexts; each returned context carried a contextual summary and relevance score. The task-file to completion-file timestamp interval was 148.526 seconds (timestamp-derived, not a monotonic runtime measurement).

**Exact summary/relevance API call counts were not captured by the persisted worker result or diagnostics.** The 48 returned summaries and 48 relevance scores are output counts, not proof of 48 API calls. The exact internal call counts therefore remain `NOT CAPTURED / NOT VERIFIED`.

The current bridge diagnostic schema records only diagnostic-capture state and `terminal_context_error_count`; the persisted result records runtime metadata, ingestion counts, and evidence outputs. The saved stdout/stderr contain no token-usage, API request, call-count, or request-ID telemetry from which exact internal calls could be reconstructed.

## Verification, admission, and coverage

- Source verification: 48 of 48 returned extracts were `LOCATED`; they span 6 unique papers and 47 unique source locators.
- Semantic verification: 48 records; all 48 had `source_fidelity=PASS` and `scope_match=true`. Verdicts were 46 `AMBIGUOUS` and 2 `PASS`.
- Semantic admission: 2 evidence items were admitted: `E_235b6219f534076f6bf4` and `E_f922eff3cbd5d99e6bb1`.
- Coverage: `PASS`, with `SCIENTIFIC_QUESTION` and `HYPOTHESIS_EVALUABILITY` both sufficient and no remaining gaps. The assessment supports the bounded intestinal contexts represented by the cited evidence; it does not establish universality across every injury model.
- Gap/focus/replan: no validated coverage gap remained, so there was no focus update or second attempt.
- L1 and later stages: `NOT ATTEMPTED`.

## Acceptance-driver verification

Focused driver-boundary checks were run with the canonical RLR interpreter:

```text
C:\Users\hk200\miniforge3\envs\rlr\python.exe -m pytest tests/test_l05_curie_corpus_integration.py -q -k "credential_probe_child_sees_authorized_key or actual_host_submit_child_forwards_key_and_offline_flags_to_worker or public_host_submit_process_receives_file_credential_and_offline_flags or file_loaded_credential_is_redacted_from_host_submit_artifacts or live_acceptance_child_environment_is_minimal or live_host_next_requires_explicit_authorized_credential_file or first_blocker_retains_both_output_streams_and_redacts_authorized_key"
```

Result: **7 passed, 27 deselected, 0 failed**. This was a focused driver test selection, not a full test-suite run. Tasks 1–10 were not rerun.

I also ran controlled counterfactual RED checks in isolated pytest processes: omitting `DEEPSEEK_API_KEY` from the host child produced the expected blocked assertion, and omitting `HF_HUB_OFFLINE` produced the expected offline-flag assertion. With the actual helper restored, the focused seven-test selection passed. These in-memory mutations changed no repository files.

## Receipt hashes

| Artifact | SHA-256 |
| --- | --- |
| `00_Preflight/deep_research_runtime.json` | `1511375dae2c7e96d548ded155374892215644d9c96ff4ef90653333421bf227` |
| `00_Preflight/preflight_receipt.json` | `076694d91fe3c491e842a464cafd71cdad0d4faf1b9e2b8872c3afb85e6df9a0` |
| `08_Audit/l05_acquisition/C20261003033007108830/EPMC_ee13af8daa8911d5b3354826/acquisition_manifest.json` | `70d741dae244b794e10858f07f57625bf8ded1c94b266cbf7347d6f2e98b5e7c` |
| `.../host_checkpoint.json` | `1bf1dde7f7c1b5e82fbf6d36ffe603bfd0f62a877507b2751058d539228bec4b` |
| `.../attempt_001/worker/task.json` | `3f96ccd0036c7af3157e14ff66c4e362748f51f06f4fc61ad239818cc4cf4945` |
| `.../attempt_001/worker/settings.json` | `56d69b8f75ab2d8abf4e54ee91742083a1971d6d089e96594f9c40a77fbfa797` |
| `.../attempt_001/worker/result.json` | `cdec6fe3c49ba17fec886e733eb3968378a70fddfa5f8532aac6e261446abfde` |
| `.../attempt_001/worker/completion.json` | `f7fe3c6c517c241bd45a708243df6c1ce5f63ecd80aa64fa3c87553ad6f0b128` |
| `.../coverage_001/assessment.json` | `610470ab0d82e91a08e21caa58fdfe84d047d41fdbaf95a8d89762346ee430c9` |
| `09_Literature_Database/evidence_packs/l05/C20261003033007108830/EP_C20261003033007108830_R1_v1.json` | `a8372dc45b9d7cdd7f45720ddda6f0ba0519ec3d5a3ac20ec0d7333450248fce` |

The EvidencePack content hash is `621d08e67ebd349ae0d730cb58b177afa5c4620b68dbbbcef6ea1d7708082efb`; the coverage request hash is `eed43028e896d2e02e414a8194cff95a5f7f4ea68ea767241bb3e13ddedfa6f6`.

## Final status

`REAL_E2E=PASS` for `Europe PMC → 30-paper corpus → PaperQA2 worker → SourceVerifier → SemanticVerifier → Coverage`.

- `SUMMARY_RELEVANCE_API_CALL_COUNTS=NOT CAPTURED / NOT VERIFIED`
- `L1=NOT ATTEMPTED`
- `TASKS_1_10=NOT RERUN`
- `PRODUCTION_CODE=UNCHANGED BY THIS ACCEPTANCE`
- `COMMIT/PUSH/MERGE=NOT PERFORMED`
