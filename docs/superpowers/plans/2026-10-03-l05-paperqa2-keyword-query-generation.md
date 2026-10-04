# L0.5 PaperQA2 Keyword Queries — Simplified Plan

**Status:** Revised review draft. This turn authorizes plan review only; it does not authorize implementation or live acceptance.

**Goal:** For a fresh L0.5 acquisition attempt, keep scientific intent and replan authority in RLR/current host, ask the pinned PaperQA2 helper for keyword-search proposals, validate them in RLR, then let Europe PMC alone discover and acquire papers.

**Fixed boundaries:** Do not invoke PaperQA2 PaperSearch or its agent loop. Do not copy its prompt, add a local keyword/synonym/reranking algorithm, change provider ownership, or modify the cumulative corpus worker. Preserve historical `L05QueryPlan/v1` interpretation and replay.

## Design

### One native batch per acquisition attempt

RLR deterministically builds one helper question from the frozen ResearchSeed question and hypothesis, the current validated scientific plan, and the current validated coverage gaps. Round one has no gaps. The helper receives the whole plan once; generated strings are batch proposals, not one proposal assigned to each intent.

Call the pinned `paperqa.agents.helpers.litellm_get_search_query(question, count=3, template=None, llm=settings.get_summary_llm())` once per attempt. This preserves PaperQA2’s own broad/narrow multi-search prompt and postprocessing. The requested count is three; accept one to three non-empty, unique, structurally valid proposals in native order. Zero, more than three, or an invalid proposal fails closed. Do not top up, repair, reorder, retry, or map proposals back to individual intents.

RLR still owns scientific questions, hypotheses, validated gaps, finite replan decisions, proposal admission, persistence, and state advancement. Europe PMC remains the only discovery/acquisition provider. A missing or mismatched PaperQA2 binding blocks a fresh generated plan; there is no compiler, provider, or agent-loop fallback.

### Reuse the existing transaction

Use the existing PaperQA2 subprocess backend, bridge dispatcher, `ProcessRunner`, acquisition writer lock, and hash-protected `L05AcquisitionCheckpoint/v2`. Add one strict bridge operation variant, `search-query-v1`, to the existing bridge file. Do not create a bridge script, Task/Result/Completion family, provider registry, or query-specific recovery engine. The corpus bridge branch, corpus Task/Result/Completion, worker slot, Settings, and `evidence_k=60` remain unchanged.

The native helper result is admitted only after the existing `ProcessResult` proves a completed process, return code zero, complete output, and clean process-tree shutdown; the returned runtime must match the already-bound PaperQA2 runtime and summary Settings. The corpus completion validator is not reused: its terminal `ContextError` diagnostics belong to the corpus worker.

Use `L05QueryPlan/v2` only for newly helper-generated plans. V1 remains validated and replayed under its existing compiler-query semantics. V2 retains the existing scientific plan and host planning receipt, identifies the helper planner, stores the accepted query rows and their query hashes, and adds one `invocation_sha256`. That hash binds the deterministic helper input, seed/attempt, validated planner/coverage receipt, fixed count of three, non-secret summary Settings and runtime binding, and current bridge bytes. The plan’s query rows are the returned proposals; do not store a duplicate proposals array or a separate `QueryGenerationBinding`.

Persist the validated v2 plan in the existing checkpoint’s append-only per-attempt plan map. `_save_acquisition_checkpoint` supplies the durable checkpoint hash. Only after that write succeeds may Europe PMC run. The same plan is copied into the existing immutable attempt/manifest artifacts at the normal commit point. This avoids a second `query_plan.json` artifact and a second checkpoint pointer/hash table.

Before invoking the helper, record `external_state=QUERY_IN_FLIGHT` in the existing checkpoint. If a valid plan for the attempt is already present, replay it and make zero helper calls. If a prior process left `QUERY_IN_FLIGHT` without a committed plan, mark the result uncertain and stop; never dispatch the helper again automatically. Record known process or model-contract failures through the existing checkpoint failure owner using a non-sensitive category, then stop before Europe PMC. Do not add a duplicated `external_request` snapshot: the attempt is already identified by the checkpoint and the committed plan’s invocation hash is recomputed from frozen owners.

For finite replans, keep existing host/coverage feedback and derive intent-repetition checks from the already-persisted validated scientific plans using the existing compiler only as an intent fingerprint. Do not persist a second `intent_query_content_hashes` list. The compiler no longer supplies executable Europe PMC queries in the new v2 path.

## Implementation tasks for later approval

### Task 1 — Native batch boundary and QueryPlan/v2

Extend the existing owners only:

- `src/research_loop/l05_curie/query_planner.py`: deterministic whole-plan question materialization, proposal admission, and existing replan uniqueness checks derived from prior validated plans.
- `src/research_loop/l05_curie/contracts.py`: preserve v1 validation and add v2 validation for helper-generated query rows and the invocation hash.
- `src/research_loop/l05_curie/multisource.py`: build the v2 plan from the validated scientific plan and accepted batch; no per-intent helper loop.
- `scripts/paperqa2_rlr_bridge.py` and `src/research_loop/l05_curie/paperqa2_runtime.py`: add the query operation to the existing dispatcher/backend using the bound interpreter and `ProcessRunner`.

Write targeted tests first. Verify one helper call with `count=3`, whole-plan input, the explicit frozen summary model, and no `Docs`, `PaperSearch`, or agent-loop call. Cover 1–3 accepted proposals; zero, over-count, malformed, duplicate, or process-failure responses block. Verify v1 fixtures still validate with their original semantics.

### Task 2 — Existing checkpoint and replay path

Extend only `src/research_loop/l05_curie/europepmc_runtime.py` for the transaction ordering: checkpoint in-flight marker → native helper → RLR validation → checkpointed QueryPlan/v2 plus checkpoint hash → Europe PMC. Reuse current writer lock, checkpoint v2, failure recording, and manifest/attempt owner. No new retry/recovery state machine and no corpus-worker edits.

Targeted integration/replay tests must prove that Europe PMC is not called before a valid plan is hash-persisted; a committed plan replays without the helper; an in-flight call without a committed plan blocks; known and uncertain failures do not redispatch; and terminal v1/v2 manifests validate through their corresponding contract paths. Add assertions that the cumulative corpus task/worker contract is untouched.

After the implementation tasks are separately authorized, run their targeted tests, the required regression/reuse gate, and review the resulting diff. This plan review runs none of those checks.

### Task 3 — Separately authorized live acceptance

Use the existing public lifecycle and acceptance driver with a fresh, normally preflighted acceptance lineage. Current Codex remains the only host cognition owner through `host-next` / `host-submit`; do not substitute another model. Use the already-approved PaperQA2 binding, summary model, timeout, corpus settings, and paper budgets from the governing acceptance plan. Do not synthesize papers, queries, gaps, or replans, and do not modify formal queries to force hits.

Verify one count=3 helper call per reached attempt → RLR proposal validation → hash-bound checkpoint plan → Europe PMC → unchanged corpus worker → source verification → semantic admission → coverage. Record actual PaperQA2 version/model, requested and returned query counts, elapsed time, discovery/corpus/source/semantic counts, coverage/replan outcome, and any failure/recovery. Report `QUERY_GENERATION_ACCEPTANCE` separately from `REAL_E2E`; unreached stages are `NOT VERIFIED`. This task remains unauthorized by the present review.

## Change inventory

**FILES_CHANGED this review:** only this plan document. No production code, tests, runtime binding, or acceptance artifact was changed.

**Planned implementation files:**

- Production: `src/research_loop/l05_curie/query_planner.py`, `src/research_loop/l05_curie/contracts.py`, `src/research_loop/l05_curie/multisource.py`, `src/research_loop/l05_curie/paperqa2_runtime.py`, `scripts/paperqa2_rlr_bridge.py`, `src/research_loop/l05_curie/europepmc_runtime.py`.
- Existing tests to extend: `tests/test_l05_curie_p1_planning.py`, `tests/test_l05_curie_corpus_contracts.py`, `tests/test_paperqa2_bridge_transport.py`, `tests/test_l05_curie_corpus_integration.py`, `tests/test_l05_curie_corpus_replay.py`.
- Documentation: `docs/AGENT_NATIVE_RUN.md`.

**NEW_FILES:** 0 source/test/doc files and 0 new runtime artifact paths. The already-existing immutable attempt/manifest artifact receives the validated QueryPlan at its normal commit point; before that point the checkpoint itself carries and hashes the plan.

**NEW_SCHEMAS:** 1 — `L05QueryPlan/v2`. It is unavoidable because v1 consumers require exact equality with RLR’s compiled Boolean queries; reinterpreting v1 would corrupt historical replay. The `search-query-v1` bridge mode is a closed operation variant inside the existing bridge transport, not a new persistent Task/Result/Completion schema. The per-attempt query map and `QUERY_IN_FLIGHT` value extend the current hash-protected corpus checkpoint v2; they do not create a separate attempts contract or recovery engine.

**Why the retained additions are necessary:** the v2 distinction protects v1 replay; one invocation hash binds accepted query output to the exact frozen input/runtime; one checkpointed plan is required before Europe PMC so a resume cannot silently regenerate different searches; the bridge operation is required to execute the pinned helper in its bound PaperQA2 interpreter. All other standalone contracts, duplicate hashes/outputs, new scripts, and parallel state machines are removed.

## Self-review and stop

Checked that the plan uses one native count=3 batch, keeps the upstream prompt and broad/narrow behavior, retains RLR and Europe PMC ownership, preserves v1 replay, commits validated proposals before discovery, and adds no corpus-worker behavior. No code was run, no tests were run, and no live acceptance was attempted. Stop here for user review.
