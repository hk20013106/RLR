# Task 11 acceptance — fresh-lineage lifecycle review and host-submit conflict

Date: 2026-10-02

`FRESH_LINEAGE_LIFECYCLE=SUPPORTED_AND_ALREADY_USED`

`REAL_E2E=BLOCKED`

Blocker: `DRIVER / ACCEPTANCE STATE CONFLICT — HOST_HANDOFF_RESPONSE_BYTES`

## Scope and provenance boundary

This review did not modify the consumed candidate `C20260925211546881294`, its historical `preflight_receipt`, its receipt pin, any validator, or production code. It did not create another candidate or project, rerun Task 1–10, install dependencies, or commit/push/merge. The earlier r2 reports remain intact.

## Public lifecycle discovery

The existing native public lifecycle supports the fresh-lineage route:

1. `new-project` accepts `--knowledge-store` and binds an independent project to the same hypothesis store. It creates new project scaffolding and directs the caller to run preflight before candidate creation (`src/research_loop/cli.py`; `src/research_loop/commands/lifecycle.py:272-303`).
2. `preflight` runs the existing L0 dependency/readiness owner and persists a new project-local `preflight_receipt.json`. It explicitly refuses to rebind a readiness receipt once candidate artifacts have consumed it (`src/research_loop/commands/lifecycle.py:1067-1085,1290-1337`).
3. `new-candidate` requires `validate_project_ready(...) == PASS`, accepts the scientific question, claim/hypothesis, and input through its public arguments, then records the current receipt path and SHA-256 in the newly created candidate (`src/research_loop/commands/lifecycle.py:488-496` and the candidate creation path following it).

The inspected public CLI exposes no command that imports an old candidate's complete L0/ResearchSeed authority into another project. The supported path re-materializes the same scientific question, hypothesis, and permitted immutable source inputs as a new initial candidate; it does not copy the old `PROJECT_READY` authority, candidate receipt pin, or acquisition checkpoint. That is consistent with the requested fresh-lineage boundary.

The existing r2 project is already the result of that public workflow, so no duplicate project was created:

- Project: `D:\research_loop\e2e_phase2c_20260925_clean_02\four-species-task11-freshlineage-20261002-r2`
- Shared hypothesis store: `D:\research_loop\e2e_phase2c_20260925_clean_02\hypothesis.sqlite`
- Candidate: `C20261002174905060473`
- Runtime binding SHA-256: `8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d`
- New public preflight receipt SHA-256: `3cdcdf04d1c5c9603238900758a3801b0aa03f32bf100cbcecfb8ba513f77dfd`
- New L0 input contract SHA-256: `0ec904143490898f73492d87ee73edcdc7cce58212e5817c864c8df9595d2af1`
- The prior acceptance recorded public preflight and authoritative candidate/readiness validation as PASS. Current read-only hashes for the runtime, receipt, candidate, and input contract match that record.

The two prior r2 reports were re-hashed and remain unchanged:

- `2026-10-02-l05-paperqa2-cumulative-corpus-acceptance-freshlineage-20261002-r2.md` — SHA-256 `4ee72e609892b3fa39e74cc2b05388db9f1160f5f40d0be61ef1ba29e1d14ba4`
- `2026-10-02-l05-paperqa2-cumulative-corpus-acceptance-freshlineage-20261002-r2-host-contract.md` — SHA-256 `5f9aefc47de9ce575822c9dabdfc63da84742c86cb3bc9102e0a401cf41efc72`

## Current Task 11 stop

The resumed public driver reached `NEEDS_HOST` for L0 and made zero host-provider calls. Request ID is `6b5cd40e7020a77fbea8bd8656a0439ef39468af7bd44f9f68cc90d9b4ab560b`; request SHA-256 is `2ace2142c0d4c33c3b8dd54692512fae7c57c0e22283cf4e9a220f051aa4aa6c`.

The existing r2 host-contract report already records that the request asks the host to verify source hashes while its context is limited to `candidate_frontmatter` and `tools_policy=no-fs`; the output schema provides no declared shape for the requested binding/skill-plan fields. After that report, a 63-byte response artifact was present at `08_Audit\host_handoff\responses\6b5cd40e7020a77fbea8bd8656a0439ef39468af7bd44f9f68cc90d9b4ab560b.json` (SHA-256 `cc8da331855b6d6786d0effc1629ce6aab99860bfb4c13c57ff53d76faf41e36`). The public `host-submit` invocation exited 3 with:

`[run_loop] HOST SUBMIT BLOCKED: same request ID conflicts with previously submitted response bytes`

The current owner raises `HandoffConflict` when the same request ID is presented with response bytes whose hash differs from the previously persisted response receipt (`src/research_loop/host_handoff.py:398-412`). No response retry or mutation was performed after this failure. The response artifact remains as evidence of the attempted submission; the earlier host-contract report remains historical evidence of the preceding stop decision.

No Europe PMC acquisition, PaperQA2 live corpus/summary call, source verification, semantic admission, scientific coverage, focus/replan, or later attempt was reached. Their results are `NOT ATTEMPTED` / `NOT VERIFIED`.

Task 1–10 were not rerun. The current r2 runtime, readiness receipt, and candidate/input artifacts were only read and hashed during this review. No credentials were read or emitted in this review.
