# Task 11 acceptance — fresh lineage r6

Date: 2026-10-03 (Asia/Shanghai)

`REAL_E2E=BLOCKED`

`BLOCKER_CLASSIFICATION=MODEL CONTRACT FAILURE / L0 HOST OUTPUT CONTRACT MISMATCH`

Stop stage: current-host L0 (Linnaeus), before Europe PMC acquisition.

## Acceptance target and prior diagnostic

This fresh acceptance was intended to validate the real path:

`Europe PMC → 30-paper corpus → PaperQA2 worker → SourceVerifier → SemanticVerifier → Coverage`

The user-provided diagnostic for the prior frozen 30-paper corpus reported 169.988 seconds of worker wall time, 60/60 summary/relevance calls, 0.088 seconds retrieval, no reproduction of the 300-second timeout, and no evidence of a production deadlock or provider failure. Those measurements remain prior diagnostic evidence; this r6 acceptance did not reach the worker and does not independently reproduce them.

The r6 runtime uses `timeout_seconds=600`. The 300→600 change is the only byte-level runtime change relative to r5; evidence_k remains 60 and the approved PaperQA2 configuration is otherwise unchanged. No formal worker query was generated in r6, so query hit quality and the zero-hit rule were not exercised. No query was manually changed.

## Fresh lineage and readiness

A new native project was created through the public `new-project` lifecycle using the existing shared hypothesis store and the same four-species scientific question, claim, and declared source directory. No old PROJECT_READY receipt, candidate receipt pin, L0 output, acquisition checkpoint, or candidate output was copied.

- Project: `D:\research_loop\main\four-species-task11-freshlineage-20261003-r6`
- Project ID: `PROJECT:41d85b07-4411-5625-9ff8-e4dac2c00ad8`
- Shared store: `D:\research_loop\e2e_phase2c_20260925_clean_02\hypothesis.sqlite`
- Candidate: `C20261003044242140346`
- Scientific question: “Do cardiac RNA-seq profiles from Sk and Sm share expression patterns that differ from Mmus and Rn, and what orthology and sample-design checks are needed before interpreting those associations?”
- Claim: “The cardiac expression profiles of Sk and Sm include at least one shared pattern distinct from Mmus and Rn; any such pattern requires orthology and sample-design validation before biological interpretation.”
- Declared source directory: `D:\R-HK\yigene\newdata_260727`

Runtime provenance:

- r5 source runtime: 1,643 bytes; SHA-256 `8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d`
- r6 runtime: 1,643 bytes; SHA-256 `1511375dae2c7e96d548ded155374892215644d9c96ff4ef90653333421bf227`
- Exact JSON change: `paperqa2.timeout_seconds: 300 → 600`; a normalized byte comparison confirmed every other runtime byte is identical.
- New public preflight: `PASS WITH WARNINGS`; the only warning was the non-blocking PubMed MCP SDK readiness probe.
- Authoritative `validate_project_ready(..., expected_backend="codex")`: `PASS / PROJECT_READY`.
- New preflight receipt SHA-256: `bb1bc2ab226d945d027595bbcf438ed83e6f83321b577a8c97ddd5b97b46c5cd`
- Candidate receipt pin matched that receipt hash.
- Candidate frontmatter SHA-256: `1b3cd8bbcf9f67e45a16e0ec015f161df0d67a0041814ee6fedb5b0ca8b30110`
- L0 input contract SHA-256: `866f187263da816ccb97164d9e2ffdf7286d10ad19b510baa2d71415792b7f2a`

The pinned PaperQA2 native identity and diagnostics checks passed with the bound PaperQA2 2026.8.12 interpreter. These were controlled native checks, not real summary inference. During import, LiteLLM attempted to read its remote public model-cost map; that request failed under the local proxy and LiteLLM used its local fallback. No package was installed or changed.

The authorized credential readiness probe returned `PAPERQA2_DEEPSEEK_CREDENTIAL=AVAILABLE`. The key was read only by the acceptance process, passed transiently to its child, and was not written to project artifacts, environment settings, receipts, or this report. The live host-next child also exited before any PaperQA2 worker was started.

## First blocker: L0 current-host contract

The public acceptance driver called the existing `host-next` owner and received `NEEDS_HOST`; `host_provider_calls=0`. It created request `0012eca4b2e05438b0f82a82f6c3cfd215bc76914b05729d39b161603a939c11` (SHA-256 `36fb7e1695bd1e707fb931482c457e4009bbdfd07a60eb0a2915161268073d07`). The request and its context manifest/rendered-context hashes were verified before review.

The assembled L0 context sets `tools_policy=no-fs` and allows only `candidate_frontmatter`. It states that L0 must verify current-round inputs and freeze a `CurrentRoundDataBinding`, but the provided L0 input contract declares a directory with `files: []`; no current source-file identities or hashes are in the context. The output contract requires only `schema_version` (with `candidate_id` optional), and provides no schema for `CurrentRoundDataBinding` or the required `skill_use_plan`.

The current Codex session therefore could not truthfully verify the source directory contents or submit a contract-valid binding. No host response was fabricated or submitted. The pending request remains available in the new lineage. This is a host contract blocker; it is not an Europe PMC, PaperQA2 runtime, provider, or production deadlock failure.

## Stage results

| Stage | Result |
|---|---|
| New project, public preflight, candidate receipt pin | PASS |
| Pinned PaperQA2 identity / controlled diagnostics | PASS |
| Authorized credential readiness | AVAILABLE |
| Current-host L0 | BLOCKED; no host-submit |
| Europe PMC live acquisition | NOT ATTEMPTED |
| Europe PMC query hit quality / zero-hit issue | NOT ASSESSED; no query was generated |
| Corpus size / evidence_k used | 0 papers / retrieval not attempted; configured evidence_k=60 |
| PaperQA2 worker / actual summary calls / worker wall time | NOT ATTEMPTED / 0 / NOT APPLICABLE |
| SourceVerifier | NOT ATTEMPTED |
| SemanticVerifier admission | NOT ATTEMPTED |
| Scientific coverage | NOT ATTEMPTED |
| Focus/replan and further attempts | NOT ATTEMPTED |

## Preservation and scope

The earlier r5 project, its receipt and candidate, and historical BLOCKED reports were not modified. The r6 project was created and bound to the shared hypothesis store through the public lifecycle; this report records the new run. Task 1–10 were not rerun. No PaperQA2 or RLR production code, dependency, provider, model, embedding, evidence_k, or coverage rule was changed. No commit, push, or merge was performed.