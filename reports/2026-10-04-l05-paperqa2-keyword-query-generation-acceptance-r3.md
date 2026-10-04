# L0.5 PaperQA2 Keyword Query Generation — Task 3 Live Acceptance r3

**QUERY_GENERATION_ACCEPTANCE = PASS**<br>
**REAL_E2E = PASS**

This report records the verified terminal state of the existing Task 3 fresh lineage. Historical r1 and r2 reports remain unchanged. Tasks 1–2, the full regression suite, and the reuse gate were not rerun.

## Current protocol state

The prompt said the run was at `NEEDS_HOST`; the persisted acquisition checkpoint and public protocol showed that the Task 3 request had already been answered and committed. The current `host_checkpoint.json` is `COMMITTED`, `current_request_id` is null, its committed result is `FROZEN`, and its coverage verdict is `PASS`. Public `host-next --resume`, run with the project-bound `RLR_HYPOTHESIS_STORE` in the child process environment, passed formal runtime preflight and returned `continued/FROZEN`. No response was resubmitted, and this continuation did not advance to L1.

The first `host-next` invocation in this continuation omitted `RLR_HYPOTHESIS_STORE` and returned `PROJECT_NOT_READY`. The value was taken from the existing project preflight receipt and used only in the command process; no project binding or secret was changed. The corrected public call passed. This was a recovered driver-environment omission, not a production blocker.

## Fresh lineage and binding

- Project: `D:\research_loop\paperqa2-keyword-query-il22-acceptance-20261004-r1`
- Project ID: `PROJECT:3b8219f3-1a64-5e32-bc5f-5ad425196d25`
- Candidate: `C20261004002500163109`
- Acquisition: `EPMC_d423b7ba5a2277816c3b68ea`
- ResearchSeed SHA-256: `d423b7ba5a2277816c3b68ea81645c4cd3b04249d59d33076dad0788e77fc450`
- Runtime binding SHA-256: `f7870668b717b54535f2e05d61908119fb5f57f453469be4ecbed72c5e44e17d`
- Preflight receipt SHA-256: `9b2b547fa96d2a1c21d9dacd99a5a6fd63d95480bfcecccc772596565fa7c038`
- PaperQA2 runtime: `paper-qa 2026.8.12`, commit `57e89f7223b0960d5ee5ea048c69e3c47e088572`; the bound checkout was clean. The actual summary model was `deepseek/deepseek-flash`; embedding was `st-multi-qa-MiniLM-L6-cos-v1`.

The planner request was `0ad90bea97cebe91f2fd1bd773ba034f92b6dfb56bdf90bcae97f7238e012ff3`, with request SHA-256 `55cb847b7ce2c9fe45c4ffafb58b39bbf3585b5d390d7830b860f3c325cadb22`. Its accepted raw response SHA-256 is `fbee803f4bcfca171a4981563a40ca17c845571b33aae11825d5b9eb76ab8531`; the host receipt cursor binds the same project, candidate, round, and hypothesis store as the fresh preflight.

## Native query generation and Europe PMC

One PaperQA2 helper process requested `count=3`; it completed with return code zero, untruncated stdout/stderr, and clean process-tree cleanup. It returned three proposals, and the three QueryPlan query rows match their validated proposal query strings. The helper runtime and actual bridge hash match the pinned binding. No query was manually edited, no compiler fallback was used, and no second helper call or top-up was made.

The persisted plan is `L05QueryPlan/v2`, `QP_MULTI_21e44dccf127895e`. Its SHA-256, the checkpoint reference, and the manifest attempt reference all match: `3d404097d7e203c64626211bd91b110a199970ace513100cef8427fa90c02e99`.

The accepted queries and Europe PMC hit counts were:

1. `IL-22 intestinal epithelial repair barrier recovery mammalian injury models` — 2,616 hits.
2. `IL-22 STAT3 epithelial proliferation regenerative transcription intestinal organoids` — 576 hits.
3. `IL-22 barrier recovery epithelial cell states colitis irradiation graft-versus-host disease` — 449 hits.

Europe PMC remained the only discovery/acquisition owner. The run recorded 3 discovery batches and 33 HTTP request records, acquired 30 papers, and froze 30 source snapshots. The manifest SHA-256 is `157d17359f2ef1cfc37cd10ebb5f04d4dcec99d4ed748db200c584566805c00f`.

## Corpus worker, source verification, semantic admission, and coverage

The unchanged cumulative corpus worker received 30 papers with `evidence_k=60`. Its task, Settings, result, and completion hashes match the manifest/checkpoint references. PaperQA2 `2026.8.12` returned 49 evidence contexts; the process completed with return code zero, no terminal context errors, complete stdout/stderr, and clean process-tree cleanup.

Source verification produced 49 `LOCATED` extracts. Semantic verification assessed all 49: 17 were `PASS` / `SUPPORTED` with source fidelity `PASS` and were admitted; 32 remained `AMBIGUOUS` and were not admitted. The coverage request was `c6b0c7e864d04e4b112603274ad6948b4d4fa29b3029ea22ae85dcbdff58f706`, request SHA-256 `63863a5c515528fd3141cf1712004ffed0b888caf223f75fd6221e44e9dfc5d4`. Its accepted raw response hash matches the host receipt: `848ce0d075a4d688f53ebc7acb86f34c2842a68b50c62b78a42e395f33ba36e2`.

Coverage passed for `SCIENTIFIC_QUESTION` and `HYPOTHESIS_EVALUABILITY`, with zero gaps. The existing evidence pack is `EP_C20261004002500163109_R1_v1.json`, SHA-256 `13d1b7a95565ed959019b110bea5addb38a84b475a9dfb65b436e4265edc52da`. The normal terminal state is `FROZEN`; no replan was needed.

## Limits and stop point

Helper and corpus-worker elapsed durations are not recorded in the persisted receipts, so both are `NOT RECORDED`. Provider API-call counts are `NOT VERIFIED`. This run reached scientific coverage PASS at the 30-paper corpus; 60/90-paper scale and later replans were not attempted or forced. These limits do not change the verified real-path result above, but no performance or scale claim is made.

```text
CURRENT_NEEDS_HOST = NO (the Task 3 coverage request is already committed)
QUERY_GENERATION_ACCEPTANCE = PASS
REAL_E2E = PASS
TASK_1_2 = NOT RERUN
FULL_REGRESSION = NOT RERUN
REUSE_GATE = NOT RERUN
L1 = NOT ATTEMPTED
TASK_3_TERMINAL = FROZEN / COVERAGE PASS
COMMIT_PUSH_MERGE = NOT PERFORMED
```
