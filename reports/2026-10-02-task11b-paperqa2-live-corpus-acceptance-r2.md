# Task 11B — live PaperQA2 corpus-worker acceptance

Date: 2026-10-02 (Asia/Shanghai)<br>
Verdict: `REAL_E2E=BLOCKED`

## Final status

| Stage | Status | Evidence-based result |
|---|---|---|
| `LIFECYCLE` | `PASS` | Fresh native v2.1 project, authoritative `PROJECT_READY`, L0 accepted by the current Codex host, and L0.5 planner response accepted. This does not claim a full RLR DAG run. |
| `EUROPE_PMC` | `PASS` | Eight real searches; seven returned hits, one returned zero. Thirty distinct PMC full-text XML snapshots were acquired and their bytes matched all 30 frozen worker document hashes. |
| `RETRIEVAL_QUERY_QUALITY` | `BLOCKED` | Q007 used a full clause copied from the hypothesis and returned 0 hits. This meets the user-specified stop condition. The run had already proceeded to worker dispatch before I inspected this raw result; this is recorded as a process failure below. |
| `PAPERQA2_LIVE_WORKER` | `BLOCKED` | One real invocation timed out at the bound 300 seconds (`returncode=15`); no `result.json` or valid evidence result was produced. |
| `SOURCE_VERIFICATION` | `NOT_ATTEMPTED` | The approved SourceVerifier stage follows a validated PaperQA2 result. No result existed; `located_evidence` remained empty. XML byte/hash checks above are acquisition-integrity checks, not SourceVerifier admission. |
| `SEMANTIC_ADMISSION` | `NOT_ATTEMPTED` | No semantic request or verification was created. |
| `COVERAGE` | `NOT_ATTEMPTED` | No coverage request, assessment, or binding was created. |
| `REAL_E2E` | `BLOCKED` | Retrieval-query quality stop condition and PaperQA2 worker timeout; downstream scientific stages were not run. |

## Fresh lineage and frozen runtime

The acceptance project is `D:\research_loop\paperqa2-task11b-il22-acceptance-20261002-r2`, project ID `PROJECT:c3b09cbb-e4ae-5634-93c6-735b66c8477a`, store ID `STORE:171af4de-3e06-5b9b-8a96-e6a14fd434f6`, candidate `C20261002215203584345`. It used its own project-local HypothesisLedger store. No four-species r5 receipt, candidate, checkpoint, or acquisition artifact was reused.

The candidate used the user-provided question and hypothesis verbatim. Its strict intake contract is schema `1.1`; the authoritative L0 input validator returned no errors. Public `new-project`, `preflight`, `normalize-l0-input`, `host-next`, and `host-submit` paths were used. Preflight returned `PASS WITH WARNINGS`; the only warning was that the official PubMed MCP SDK is absent for a future PubMed consumer. The authoritative readiness validator returned `PASS / PROJECT_READY`.

The copied approved runtime SHA-256 is `8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d`. It bound `worker_mode=corpus-evidence-v1`, PaperQA2 interpreter `D:\research_loop\paper-qa\.venv\Scripts\python.exe`, embedding `st-multi-qa-MiniLM-L6-cos-v1`, `evidence_k=60`, and summary model `deepseek/deepseek-flash`. Approved flags and budgets were frozen: summary enabled, text-only fallback disabled, `use_doc_details=false`, `multimodal=false`, `defer_embedding=false`, `doc_filters=[]`, MMR lambda `1.0`, max concurrency `4`, at most 30 new papers per attempt, 3 attempts, and 90 cumulative papers.

A read-only postmortem check confirmed PaperQA2 `2026.8.12`, module under the bound repository, repository HEAD `57e89f7223b0960d5ee5ea048c69e3c47e088572`, exact tag `v2026.08.12`, and clean PaperQA2 worktree. Its import emitted a LiteLLM warning that a remote model-cost-map fetch failed through the configured SOCKS proxy because `socksio` is absent; LiteLLM fell back to its local map. No package was installed or changed.

`DEEPSEEK_API_KEY` was read only from its specifically authorized Hermes `.env` entry and temporarily set in the acceptance process so the bound PaperQA2 child inherited it. The child readiness probe returned `AVAILABLE`. No key value or derived value was printed or written to the runtime, Settings, task, result, checkpoint, or this report. The frozen settings contain the non-secret model configuration only. Whether a DeepSeek summary/relevance request actually occurred is `NOT VERIFIED`: the worker produced no result or context diagnostics.

## Europe PMC and XML evidence

The current Codex session submitted the planner response through the existing host protocol. The proposal used exact, unique spans from the frozen ResearchSeed and included a broad IL-22 intent plus scoped intents. The decoded Europe PMC `query` values, hit counts, returned record counts, and raw response hashes were:

| Query | `hitCount` | Returned | Raw response SHA-256 |
|---|---:|---:|---|
| `(il-22)` | 1,489,614 | 25 | `09d0fc0a3ab9a0e0a269628dac50ead4f7b0a98508bea18ad5ebd1ece4266929` |
| `(il-22) AND ("intestinal injury models")` | 76 | 25 | `931d4ff7ad7676868ce995b88e43b14efb381ba96022d3874241f48dd9490d55` |
| `("epithelial repair") AND (il-22)` | 4,846 | 25 | `e5dc2d97df13626a6047e7b843082e3e88eaee20fecfa9d953d5b6f818c7d235` |
| `("barrier recovery") AND (il-22)` | 804 | 25 | `94d78db74b3061e2eafe01a5cfef13fb8c2fcab9af2190828120eef2d56cfb96` |
| `("epithelial cell states") AND (il-22)` | 120 | 25 | `7a3f3d2dc092222a215f7f3206cd2d529d4df39c367cb1e562effbb4772b7435` |
| `(il-22) AND ("stat3-dependent proliferation")` | 23 | 23 | `05d541e619907f3bb1311483c21dcb5bc3ba311296a3e770b3091c1bb304bfe8` |
| `("barrier outcomes depend on injury context") AND (il-22)` | 0 | 0 | `440a590d45c024909dc0228182521e38fcf1cb2889811ff12783a1ae9c475c52` |
| `(il-22) AND ("regenerative transcription")` | 35 | 25 | `5720b77f65b108121983ae3f80d0beed0903d55fc250cae10f4d9648224a5e83` |

The Q007 phrase reproduces a complete clause from the hypothesis and is too narrow for discovery. The user had explicitly directed that such a zero-hit, seed-literal query be recorded as `RETRIEVAL_QUERY_QUALITY` and stop the run without manual query editing. The Q007 receipt was timestamped before worker dispatch; I should have avoided proposing that phrase and should have surfaced its zero-hit result before allowing this run to reach the worker. The formal query was not edited, and no replan or second attempt was performed after the run returned.

Before the worker timeout, RLR persisted 30 distinct `application/xml` source snapshots. The worker task held 30 distinct papers; all 30 document files existed and matched their frozen SHA-256 values. The derived corpus reference-set SHA-256 is `0797c1acfe7d28545c84225c828658a311435bdbce6ec14556244ca2c907e8a5`. Thus acquired-paper count and first-attempt cumulative corpus size were both 30. These facts do not mean that SourceVerifier admitted evidence.

## PaperQA2 worker result and stop point

There was exactly one PaperQA2 corpus invocation: task `PQA_05a68554fca4e398bb695481`, attempt 1, `evidence_k=60`. The frozen task contains 30 papers and `evidence_focus=null`. The bound worker process reached the 300-second timeout; RLR terminated the process tree and wrote a failure completion receipt with `process_terminal_state=timed_out`, `returncode=15`, `result_sha256=null`, and `terminal_context_error_count=null`. There is no `result.json`; stdout is 0 bytes and stderr is 366 bytes. Therefore:

- `Docs.aadd_texts` / `Docs.aget_evidence` completion: `NOT VERIFIED`;
- returned contexts: `NOT RETURNED` (not treated as a zero-context result);
- actual DeepSeek summary/relevance execution: `NOT VERIFIED`;
- PaperQA2 result validation and RLR SourceVerifier: `NOT ATTEMPTED`;
- semantic admission, scientific coverage, focus/replan, and attempt 2+: `NOT ATTEMPTED`.

The controller reported `CONTRACT_ERROR: corpus process timed_out`. The saved checkpoint remains at `phase=HTTP_IN_FLIGHT`; the attempt records `terminal_status=ERROR`. There is no final acquisition manifest or committed evidence pack. I did not call `host-next` after this failure or attempt recovery/replay.

## Receipt index

All paths below are under the r2 project unless marked otherwise.

| Artifact | SHA-256 / result |
|---|---|
| `00_Preflight/deep_research_runtime.json` | `8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d` |
| `00_Preflight/preflight_receipt.json` | `877de73097b18088639fb9990965b21126cc9c41f52779db9a1df87e86277773` |
| `01_Candidates/C20261002215203584345.l0_input.yaml` | `eadf2ec942293ff2ad42c985a2fa0ede10cadc91b5de2b03b20fa0e768911f53` |
| L0 host receipt | `ce4cfd60d15657c34371abbc4bbb50bc8a5a5df6268ad0d2ce530f3a38d16285` |
| Planner request | `66bd9f859a0e19f1f46ebe35af409ca1fbd2e776479203468842d5367daacca6` |
| Planner response | `b11ebd5d7d15791b4f2d5e27897210038c0fd1fbf534c2e3b0bd946ec3273ff6` |
| `attempt_001.json` | `9e001f8fde11149ff308603b1806f9832729a27f0777302cfdd85c1afa36ec57` |
| `host_checkpoint.json` | `8a874882d1d6c26116195c1f1187cb9eef122a7cc2e5ccc44dde741f82117915` |
| Worker `task.json` | `e2c8962bf7320bf76cca627af3cf88e656056bf18994aa66f760d52e1f50a4ce` |
| Worker `settings.json` | `56d69b8f75ab2d8abf4e54ee91742083a1971d6d089e96594f9c40a77fbfa797` |
| Worker `completion.json` | `7c01cb27920d4e16b600e5631937d060301f095e03b9db96c5f5e970cc0e1642` |

Evidence paths: `08_Audit/l05_acquisition/C20261002215203584345/EPMC_3013fb98864a28c6a05c3758/attempt_001/worker/` and `.../host_http/`. The raw query responses are under `EPMC_3013fb98864a28c6a05c3758_A1/`.

## Execution integrity notes

A preliminary r1 project (`D:\research_loop\paperqa2-task11b-il22-acceptance-20261002`, candidate `C20261002214836566825`) was preserved but not used: the low-level `new-candidate` path produced schema `1.0`, so I left its L0 request unsubmitted and created r2 through the strict schema `1.1` intake. During r2's L0 handoff, I initially wrote my response JSON into the reserved host receipt filename; after verifying that it was my exact response bytes, I moved it unchanged to `08_Audit/task11b_host_response_inbox/` and submitted it successfully through the public `host-submit` command. Neither incident changed production code or the authoritative validators.

No Task 1–10 implementation or pytest suite was rerun; no production code, dependency, Hermes file, four-species r5 artifact, or credential was changed; no commit, push, or merge occurred. The RLR checkout was `D:\research_loop\main`, branch `review/l05-p1-final-diff`, HEAD `c60632afdb3aabd6e7c55ffea8dd6a43c50c7982`; its pre-existing dirty state was preserved. This report is a new acceptance artifact and does not rewrite the earlier BLOCKED reports.