# Task 11B IL-22 PaperQA2 acceptance — fresh lineage r3

日期：2026-10-03（Asia/Shanghai）
REAL_E2E=BLOCKED
BLOCKER_CLASSIFICATION=DRIVER / ACCEPTANCE CONFIGURATION — worker credential forwarding was not established; PaperQA2 returned an HTTP 401 authentication signal.

## Scope and lineage

This run continued approved Task 11 only. Tasks 1–10 were not rerun. No PaperQA2 or RLR production code was modified, no package was installed or upgraded, and no commit, push, or merge was made.

A new native project was created at `D:\research_loop\paperqa2-task11b-il22-acceptance-20261002-r3` from the same IL-22 question, hypothesis, and seed file. Only the scientific seed and approved non-secret runtime binding were carried forward. The old preflight authority, candidate receipt pin, and acquisition checkpoint were not copied. The new candidate is `C20261002234146319523`.

The RLR checkout was `review/l05-p1-final-diff` at `c60632afdb3aabd6e7c55ffea8dd6a43c50c7982`; its pre-existing dirty files were preserved. PaperQA2 was clean at `v2026.08.12`, commit `57e89f7223b0960d5ee5ea048c69e3c47e088572`. A direct import check reported PaperQA2 2026.8.12 from `D:\research_loop\paper-qa\src\paperqa\__init__.py`, using `D:\research_loop\paper-qa\.venv\Scripts\python.exe`.

## Runtime and readiness

The r3 binding differs from the source binding only at `paperqa2.timeout_seconds: 300 -> 600`; a parsed comparison confirmed all other runtime fields were equal. `evidence_k` remained 60.

| Artifact | SHA-256 |
|---|---|
| Source r2 runtime, unchanged | `8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d` |
| New r3 runtime | `1511375dae2c7e96d548ded155374892215644d9c96ff4ef90653333421bf227` |
| New r3 preflight receipt | `66595d63b06a96091cda8fed9b39e8d8caeb9bc9ab2f18cb62e0f0b97ad4cf2f` |
| New candidate L0 input | `22250badaf36ee8ff5f08b3cc573c2906759f2717ff3c38338e787f9ce0f2103` |
| Source r2 preflight receipt, unchanged | `877de73097b18088639fb9990965b21126cc9c41f52779db9a1df87e86277773` |
| Source r2 candidate input, unchanged | `eadf2ec942293ff2ad42c985a2fa0ede10cadc91b5de2b03b20fa0e768911f53` |

The new public preflight returned readiness PASS / overall PASS_WITH_WARNINGS, and the new candidate pinned that receipt. The warning was an unavailable PubMed MCP SDK probe; it was advisory and the live Europe PMC HTTP path did run.

## Europe PMC and query quality

The current Codex session handled the L0 and L0.5 planner requests through the existing host-next / host-submit protocol. The host-next driver reported `host_provider_calls=0`; no other model simulated the host. The planner response used exact spans from the supplied ResearchSeed and was not manually edited afterward.

Europe PMC completed three search responses with hit counts `4, 0, 0`, then fetched four unique full-text source snapshots. The PaperQA2 corpus task was built with four sources, below the per-attempt maximum of 30. No pagination or artificial papers were added. The two zero-hit exact-span intents are recorded as an independent query-quality issue; they did not stop corpus construction or the worker invocation.

## PaperQA2 worker

| Field | Observed value |
|---|---|
| Worker mode | `corpus-evidence-v1` |
| Bound interpreter | `D:\research_loop\paper-qa\.venv\Scripts\python.exe` |
| PaperQA2 version | `2026.8.12` |
| Embedding setting | `st-multi-qa-MiniLM-L6-cos-v1` |
| Summary/relevance model setting | `deepseek/deepseek-flash` |
| Configured API base | `https://api.deepseek.com` |
| Corpus sources | 4 |
| `evidence_k` | 60 |
| Configured worker timeout | 600 seconds |
| Approximate task-to-completion wall time | 31.151 seconds, based on task and completion file timestamps |
| Worker return code | 1 |
| Completion result hash | Absent |

The task and settings hashes recorded by completion match their files. The worker attempt is `KNOWN_FAILURE`; stderr contains an HTTP 401 / authentication signal. No usable PaperQA2 result was produced. This was an authentication failure, not a timeout. The configured 600-second limit was not reached, so this run does not verify 600-second performance.

A separate pre-run credential probe had reported `PAPERQA2_DEEPSEEK_CREDENTIAL=AVAILABLE` for the PaperQA2 child. However, the later planner `host-submit` ran in a separate process without explicitly loading the authorized `.env` key. That submit synchronously advanced into acquisition and the worker. Credential presence in the actual worker environment was therefore not established. This is classified as an acceptance-driver configuration failure; the 401 does not establish a general DeepSeek provider outage. No credential value or derivative is included here.

## Downstream stages and final state

- Europe PMC search and four source snapshots: completed.
- Corpus task construction: completed with four sources.
- PaperQA2 worker: blocked by authentication failure; no result artifact.
- Evidence-level SourceVerifier: not attempted; `located_evidence=0`.
- Semantic admission: not attempted; `semantic_verifications=0`.
- Scientific coverage: no result and not completed.
- Attempt 1 focus: null. No validated gap or replan was produced.
- Persisted checkpoint phase at inspection: `HTTP_IN_FLIGHT`; the worker attempt is recorded as `KNOWN_FAILURE`. This state was preserved and not repaired or replayed.

The earlier controlled replay of the frozen r2 30-paper corpus completed in 169.988 seconds with 60/60 summary/relevance calls. That is separate historical evidence. This fresh Europe PMC lineage contained four sources and ended on authentication, so it neither reproduces the old timeout nor verifies a 30-paper run under the 600-second setting.

## Execution notes and remaining verification

The first L0 host-submit did not receive the HF/Transformers offline flags and printed a Transformers “Fetching 4 files” progress message. Available evidence does not distinguish cache hits from network fetches. No package installation or upgrade occurred. Subsequent acceptance calls set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. A later package-version import also emitted a LiteLLM remote cost-map warning and fell back to its local backup; cost remains unknown.

Not verified by this lineage: successful embedding and retrieval metrics, successful summary/relevance calls, 30-paper worker completion within 600 seconds, evidence-level SourceVerifier, semantic admission, coverage, validated-gap focus/replan, 60/90-paper scale, or scientific PASS. The run stopped at the first worker blocker; no retry or further host-next call was made.

## Evidence paths

- New runtime and preflight: `D:\research_loop\paperqa2-task11b-il22-acceptance-20261002-r3\00_Preflight\`
- New candidate: `D:\research_loop\paperqa2-task11b-il22-acceptance-20261002-r3\01_Candidates\C20261002234146319523.l0_input.yaml`
- Acquisition and checkpoint: `D:\research_loop\paperqa2-task11b-il22-acceptance-20261002-r3\08_Audit\l05_acquisition\C20261002234146319523\EPMC_e91d3f9e9eb21af594593179\`
- Worker task SHA-256: `7cf8d2e84389dc54ec1dc4fa83fb6bd52ba7226e34232c3fb9c68e27b88d20ea`
- Worker settings SHA-256: `56d69b8f75ab2d8abf4e54ee91742083a1971d6d089e96594f9c40a77fbfa797`
- Worker completion SHA-256: `b89e5977f4db786fbbabc26dbca47577b986d1f6d02c6b756943490b979dc0b6`
- Worker stderr SHA-256: `d329a7108d34566fb5225bc89cce560c973cf83743bbdc7237fe38879e64a229`

REAL_E2E=BLOCKED