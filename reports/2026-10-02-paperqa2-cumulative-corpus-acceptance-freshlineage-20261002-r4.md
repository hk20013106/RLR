# Task 11 acceptance — fresh lineage r4

Date: 2026-10-02

REAL_E2E=BLOCKED

ARCHITECTURE_GAP=NONE

Blocker classification: MODEL CONTRACT

Stop stage: current-host L0.5 planner response admission, before Europe PMC acquisition or PaperQA2 corpus execution.

## Fresh-lineage lifecycle result

The existing public lifecycle supports a fresh acceptance lineage from the same four-species ResearchSeed. A new project was created through new-project, the approved non-secret runtime binding was copied, public preflight was run, a new candidate was created, and the authoritative readiness validator accepted the new candidate against the new receipt. No old PROJECT_READY receipt, candidate receipt pin, acquisition checkpoint, or candidate artifact was copied.

- Project: D:\research_loop\e2e_phase2c_20260925_clean_02\four-species-task11-freshlineage-20261002-r4
- Project ID: PROJECT:8c3e2f04-b3ab-5cee-869c-0d83468aa7a7
- Shared hypothesis store: D:\research_loop\e2e_phase2c_20260925_clean_02\hypothesis.sqlite
- Store ID: STORE:5e3439e4-5a30-5711-9615-52ef2348cb1f
- Candidate: C20261002192044807548
- Runtime binding SHA-256: 8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d
- New public preflight receipt SHA-256: 3060fcb4bc5636c2b4ecc2e13d04d216e25a520e9538aa1df3231e86aac10039
- Candidate frontmatter SHA-256: a6c65da4dcc9f42cab0fbce951db7f97a76b8ee7c54b4d07007c3441f3a96f96
- New L0 input contract SHA-256: edef8d6a34c7bbd348d179300dd209f1b23552aa81627939631155a2f17bd45a
- L0 receipt SHA-256: 3eeddefcb3172f1e5f36cc39d49df66539ce4c8347cd332db61c1620377a4be3

Public preflight exited successfully with PASS WITH WARNINGS; its warning was that the official PubMed MCP Python SDK is unavailable for a future PubMed MCP consumer. The authoritative readiness validator returned PASS / PROJECT_READY, and the new candidate's receipt pin matched the new preflight receipt.

The new candidate uses the same scientific question and hypothesis as the existing four-species input. Its source declaration points to D:\R-HK\yigene\newdata_260727. The five source artifacts were re-hashed during this lineage:

- FOUR_SPECIES_107SAMPLE_DATA_HANDOFF_CN.md — da4323e29f6257320cf7e3c4729b3e7a9d9f2ed37b6eda3e1c7fd1de3c1d98b4
- four_species_gene_ids_lengths.tsv — 223a0129b2f6fe4b916eae924d54de02c8af63db57f97ddc229d9cbf18c1dbc4
- four_species_length_scaled_counts.tsv — 2a15a1ab23eca5d8a98b9101db43c2a57332fcb51f8c5b5911db35ebcb33b9d1
- four_species_raw_counts.tsv — 0609c940d846ca353329ed269afb6b89957353a959a5b3d51b749aba8c31df64
- sample107_260716_with_AV_group.csv — 5aa35ffdb3e61c57660b915e77789cf1870b45160e1b3944c3fbf5c6a816fb45

## Host protocol and blocker evidence

The acceptance driver used the existing host-next protocol and returned NEEDS_HOST for L0, then for the planner. The current Codex session prepared the L0 response and the planner proposal. host-submit accepted L0 and created its receipt. The planner response was submitted once through the public host-submit owner; no second model was invoked.

- L0 request ID: 546036d5cfc33c2bfa00b522a45ff8d00712307935d0cc36b49e911ef8864fd4
- L0 request SHA-256: 842e091500889c274d06ee5c65a8a770a3fb0e650c34a862dc64abbdd051c5d1
- L0 raw response SHA-256: 50756a3642f112fe632eca0233d074300cd266593bbde3a9465a4345bf256477
- Planner request ID: c4cf628f915db18df6425dbdf8782ca46c7cccd16ab232059247a23560f431bd
- Planner request SHA-256: 9689aa28c532739a3f245f2a984490b2d85395c4b67b54fd798b9c9cd8d3a3c8
- Planner response-input SHA-256: fc4c55f9c4cf3d234a596cccb737f2d0f95ff2b46d328b1c17c5702b695cf3ca
- host-submit result: MODEL_CONTRACT_ERROR: planner host response rejected: scientific intent requires an exact seed span
- Submit command elapsed time: 15.9 seconds; exit code 3.

No planner-response retry or patch was made after this first blocker. The new r4 acquisition checkpoint is preserved at 08_Audit/l05_acquisition/C20261002192044807548/EPMC_e9bb5d0f3add06c5413ec405/host_checkpoint.json, SHA-256 55a6773ee7c73f46ad7aef8f0d51adc46eac52c2f8d32d8cd1e957af3a22a5ba. Its phase is REQUEST_PREPARED, attempt index is 1, http_responses is empty, and worker_attempts is empty. It is a new checkpoint bound to the r4 candidate and planner request.

## Provider and worker status

The authorized DEEPSEEK_API_KEY was read from the approved local source and held only in the acceptance PowerShell process environment. A child process using the bound PaperQA2 interpreter reported PAPERQA2_DEEPSEEK_CREDENTIAL=AVAILABLE. The value and all derivatives were excluded from output and artifacts; the process-scoped variable was removed after host-submit.

The r4 checkpoint freezes the approved non-secret PaperQA2 settings:

- Worker mode: corpus-evidence-v1
- Worker interpreter: D:\research_loop\paper-qa\.venv\Scripts\python.exe
- Embedding: st-multi-qa-MiniLM-L6-cos-v1, embedding_config={}
- Summary/relevance model: deepseek/deepseek-flash
- evidence_k=60; evidence_retrieval=true; evidence_skip_summary=false
- evidence_text_only_fallback=false; max_concurrent_requests=4
- use_doc_details=false; multimodal=false; defer_embedding=false; doc_filters=[]
- texts_index_mmr_lambda=1.0; timeout_seconds=300

The offline embedding preflight had previously loaded the configured local embedding and produced a 384-dimensional vector. It was not repeated for r4. The r4 PaperQA2 worker itself was not invoked, and no DeepSeek summary/relevance inference occurred.

## Acceptance stage accounting

- Fresh public project/preflight/candidate lifecycle: PASS
- Authoritative PROJECT_READY validation: PASS
- Current-host L0: PASS
- Current-host planner: BLOCKED by the rejected response contract
- Europe PMC acquisition: NOT ATTEMPTED
- PaperQA2 corpus worker and cumulative corpus: NOT ATTEMPTED; acquired-paper count is 0 in this run
- Actual retrieval evidence_k: NOT ATTEMPTED (configured value 60)
- PaperQA2 model/runtime execution and latency: NOT VERIFIED
- Paper source verification: NOT ATTEMPTED
- Semantic admission: NOT ATTEMPTED
- Scientific coverage: NOT ATTEMPTED
- Validated evidence gap, focus, replan, later attempts: NOT ATTEMPTED
- Scientific PASS: NOT established

## Preservation and scope

The consumed candidate C20260925211546881294, its old preflight receipt, and its receipt pin were not modified. Read-only post-run hashes still match the recorded baseline: old runtime 8aae5d38a60ae7fc67fc0a8fbe93762efd0d24137cb25d69dd7be3e9cd332f5d, old receipt 6ebff881411895db9e94db03cf7d7b5de976a3bb0138da96010a26bd4631e38a, and old candidate 7dcfbf8161e00f3e509c837bbf081808e6e9822f4db821c507f3c5094812f326. The r3 lineage report remains unchanged at SHA-256 f7538519429bef5064ac09435d443e5faa6f7100bf77b1c9affd6dc263d679c8.

Task 1–10 were not rerun. No production code, validator, dependency, old project, or prior report was modified. No commit, push, or merge was performed.
