# RLR Agent-native Continuous Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Use TDD for each behavior change. The repository's `AGENTS.md` forbids commit/push without an explicit request, so the commit step in the generic skill does not apply here.

**Goal:** One instruction to the current Codex App/Hermes host drives the authorized RLR loop to a terminal state or a defined pause, with every cognitive response supplied by that same host session.

**Architecture:** Extend the existing `src/run_loop.py` controller and `EngineAPI` boundary with durable request/submit/continue operations. Keep `next-step`, context assembly, `emit-delta`, advance, L0.5 acquisition, evidence validation, and StopPolicy as the only authorities. The headless runner remains an explicit mode using the same controller decisions.

**Tech Stack:** Python, existing RLR CLI/EngineAPI, JSON artifacts with SHA-256, pytest, existing ledger and acquisition validators. No new model SDK, orchestration framework, or nested model process for agent-native cognition.

**Spec:** [`docs/superpowers/specs/2026-09-28-agent-native-continuous-loop-design.md`](../specs/2026-09-28-agent-native-continuous-loop-design.md)

## Global Constraints

- Work in the actual repository root; record branch, HEAD, worktree, and dirty files before editing. Preserve the pre-existing P1 strict-schema work and do not absorb it into this change.
- New runs use the native v2.1 contract. Existing v2.0 code remains read-only compatibility; do not silently upgrade old data.
- One DAG decision/advance owner, one validator per contract, and one L0.5 acquisition/manifest owner. Do not create a second runner or scientific validator.
- Agent-native cognition is exclusively the current host session. No `codex.CMD`, Claude CLI, other nested model subprocess, API key, or smoke-only model binding; never silently fall back to headless.
- Existing P0/P1 attempt limits, scientific planning, Boolean compilation, source fidelity, semantic verdict/admission, candidate/ledger/hash authority, and headless artifact meanings remain authoritative.
- Host requests are immutable and scoped to the current candidate, round, node, cursor, context/seed/feedback, and allowed tools. Hold locks only during short state reads/writes, never while the host thinks.
- A real blocker, approval-required high-risk/irreversible operation, protocol-required human decision, unknown HTTP outcome, or absent host handoff stops before dependent work.
- `ExternalReuseAudit/v1` is required in the implementation change set; use `tools/external_reuse_gate.py`. The approved spec's internal-owner and LangGraph source review are the starting evidence, not a new framework choice.
- This plan authorizes no live workflow, source edit, test execution, stage, commit, or push. Implementation requires a separate execution instruction; a live acceptance run requires separate authorization.

## Review Focus

These user-facing failure classes need explicit tests in the owning tasks:

1. The same request ID submitted twice with identical bytes must return the original receipt; changed bytes must conflict (Task 2).
2. A response for an old candidate/round/cursor or a changed context/persona/tool policy must fail before ledger emission (Tasks 2–3).
3. An L0.5 HTTP request sent without a durable response must pause as uncertain, without a second request (Task 5).
4. A `LOCATED` extract changed after a semantic request is prepared must fail before assessor verdict/admission (Task 5).
5. A reached pre-research/REVIEW/L7 cognitive step with no host handoff must stop before any model provider dispatch (Task 6).

## File and Authority Map

| File / owner | Planned responsibility |
| --- | --- |
| `src/run_loop.py` | Shared stage selection, deterministic work and advance, explicit mode, host-facing continuous loop contract; headless calls the same decisions. |
| `src/research_loop/api.py` | Reuse/extend typed calls into `next-step`, `assemble-context`, `emit-delta` and controller commands; no DAG table here. |
| `src/research_loop/host_handoff.py` (new, narrow) | One immutable host request/response store: identity/hash binding, atomic writes, idempotent submit, conflict detection. No state transitions or scientific judgments. |
| `src/research_loop/providers/base.py`, `src/research_loop/commands/ledger.py` | Versioned host-session `RunReceipt` variant and shared native emission validation. Headless v1/v2 receipts unchanged. |
| `src/research_loop/l05_curie/query_planner.py` | Split current planner into prepare and validate-submitted-proposal operations; headless invokes those around its existing structured model call. |
| `src/research_loop/l05_curie/europepmc_runtime.py`, `src/research_loop/l05_curie_cli.py` | Existing acquisition owner gains phase checkpoints, planner/semantic handoffs, exact resume and manifest receipt dispatch. |
| `src/research_loop/commands/research.py`, `src/research_loop/deep_research.py`, `src/research_loop/l4_evidence_bundle.py`, `src/research_loop/l85_literature_verification.py` | Expose only the host-cognitive seams actually reached by native L4/L8.5, using existing evidence persistence/audit owners. Do not duplicate the literature pipeline. |
| `docs/AGENT_CONTEXT.md`, `docs/AGENT_NATIVE_RUN.md` (new), project `AGENTS.md` | Short intent routing plus operational host contract; keep historical `MAIN_AGENT_RUN.md` retired. |
| `docs/architecture/external-reuse/2026-09-28-agent-native-continuous-loop.json` | Same-change reuse audit; decide `EXTEND` for existing RLR owners. |

Test files may be extended beside existing owners: `tests/test_engine_api.py`, `tests/test_run_loop_receipts.py`, `tests/test_run_loop_guards.py`, `tests/test_ledger_receipt_idempotency.py`, `tests/test_l05_curie_p1_planning.py`, `tests/test_l05_curie_europepmc_runtime.py`, `tests/test_l05_curie_semantic_verifier.py`, `tests/test_deep_research_persistence_integrity.py`, and new focused `tests/test_host_handoff.py` / `tests/test_agent_native_loop.py`. Add a new test file only when the existing file has no suitable owner.

---

### Task 1: Shared controller action and explicit execution mode

**Files:** Modify `src/run_loop.py`, `tests/test_run_loop_guards.py`, `tests/test_run_loop_receipts.py`; add the same-change external reuse audit above.

**Interfaces:** `current_action(project, cand, cfg, args, round_id, exec_state) -> dict` returns one of `terminal`, `l05`, `pre_research`, `cognitive`, `l7`, `report`, or `review`; it carries the exact `next-step` result and profile/cursor identity. `execute_deterministic_action(action, ...) -> dict` delegates to current engine commands. `run_round()` and later host operations consume these functions. Do not copy topology or advance mapping.

- [ ] **Step 1 — Write RED tests:** In `test_run_loop_guards.py`, prove both caller modes receive the same native v2.1 `next-step` action and L9a→L9b authorized ordering; a stale cursor is rejected. In `test_run_loop_receipts.py`, prove the existing headless L0.5/L7/L10c dispatch behavior is unchanged after extraction.
- [ ] **Step 2 — Confirm RED:** Run the new named tests; record behavior-specific failures before editing production code.
- [ ] **Step 3 — Implement:** Extract the stage decision from `run_round()` into `current_action()`; keep `advance()` and existing engine command calls as the sole transition path. Set explicit `mode: Literal['headless','agent_native']` at the runner entry; existing `run` remains the explicit headless command, and `main_agent` stays retired. Do not call `preflight_providers()` in the agent-native branch.
- [ ] **Step 4 — Confirm GREEN:** Run the Task 1 tests plus `tests/test_engine_api.py`; inspect assertions for the same headless outcomes and no second DAG map.

### Task 2: Immutable host handoff and receipt contract

**Files:** Create `src/research_loop/host_handoff.py`, `tests/test_host_handoff.py`; modify `src/research_loop/providers/base.py`, `src/research_loop/commands/ledger.py`, `src/research_loop/api.py`, `tests/test_ledger_receipt_idempotency.py`, `tests/test_run_loop_receipts.py`.

**Interfaces:** `prepare_request(project: Path, *, kind: str, identity: dict, inputs: dict, tools_policy: str, output_contract: dict) -> dict`; `submit_response(project: Path, request_id: str, response_path: Path, *, expected_cursor: str) -> dict`; `load_request(project: Path, request_id: str) -> dict`. The slot key is project/candidate/round/node/stage/attempt/cursor; request ID is the hash of canonical identity/input/contract fields, not a timestamp. Preparing the same slot with different inputs is a conflict. Request artifacts live under the existing candidate/round run-receipt or L0.5 audit root, as appropriate. `RunReceipt/v3-host` extends the existing `RunReceipt` owner with request path/hash, raw response path/hash, canonical delta path/hash, host session identifier plus `verified|declared|unavailable` source, and code/config state. `exit_code`, `timed_out`, subprocess command, and HTTP status must be null/absent unless a real corresponding event occurred.

- [ ] **Step 1 — Write RED tests:** In `test_host_handoff.py`, assert immutable prepare, changed-input conflict, exact raw-byte SHA-256, same-ID/same-byte submit idempotency, same-ID/different-byte conflict, old cursor/candidate/round rejection, rejection of a response path outside the project, and incomplete-write recovery. In receipt tests, assert host v3 accepted only with exact request/context/raw/canonical hash bindings; forged subprocess fields and changed persona/tool policy fail; v1/v2 still read unchanged.
- [ ] **Step 2 — Confirm RED:** Run the named new tests; record failures at the missing request/receipt boundary.
- [ ] **Step 3 — Implement:** Add atomic request/response writes and short-lock compare-and-set in `host_handoff.py`; no DAG or validator semantics there. Extend `RunReceipt.read()/validate()` and `_validate_native_receipts()` with version dispatch and common identity/hash checks; preserve the existing `emit-delta` commit path. Add only thin typed `EngineAPI` helpers needed to call this boundary, with no alternative CLI parser or DAG logic.
- [ ] **Step 4 — Confirm GREEN:** Run `tests/test_host_handoff.py`, `tests/test_ledger_receipt_idempotency.py`, `tests/test_run_loop_receipts.py`, `tests/test_engine_api.py`. Inspect a persisted host receipt and verify source bytes, request hash, canonical delta hash and the real provenance edge.

### Task 3: Ordinary cognitive nodes through one prepare/submit/advance path

**Files:** Modify `src/run_loop.py`, `src/research_loop/api.py`, `tests/test_agent_native_loop.py`, `tests/test_context_isolation.py`, `tests/test_run_loop_receipts.py`.

**Interfaces:** `prepare_host_step(project, cand, cfg, args, round_id, exec_state) -> dict` returns `terminal|deterministic|needs_host|blocked` with an immutable request path for `needs_host`; `submit_host_step(project, cand, request_id, response_path, *, session_identity=None) -> dict` validates and emits one native delta then calls the existing `advance()` owner. The host response is the raw output artifact; no provider instance is constructed.

- [ ] **Step 1 — Write RED tests:** Test `next-step → assemble-context → host request → raw response → RunReceipt/v3-host → emit-delta → advance → next-step`; assert `ContextManifest/v2`, rendered-context and persona/template hashes are bound. Use unique context sentinels: authorized node receives its sentinel, adjacent unauthorized node does not, and a response bound to the wrong node fails. Test already-committed delta resumes advance without a second host request and concurrent submissions have one winner.
- [ ] **Step 2 — Confirm RED:** Run the new ordinary-node tests and record the missing host-path failures.
- [ ] **Step 3 — Implement:** Add the host path beside `exec_cognitive()` but feed both modes through Task 1's action selection and the same `emit_delta()`/`advance()`. Keep L0 strict input revalidation immediately before request issuance and existing ledger checks immediately before emission. Do not reinterpret `step.advance_command` in host code.
- [ ] **Step 4 — Confirm GREEN:** Run `tests/test_agent_native_loop.py`, `tests/test_context_isolation.py`, `tests/test_run_loop_receipts.py`, and native L9a/L9b context tests. Verify no `AgentProvider.run_agent()` call in this host path.

### Task 4: L0.5 planner prepare and submit in the existing acquisition owner

**Files:** Modify `src/research_loop/l05_curie/query_planner.py`, `src/research_loop/l05_curie/europepmc_runtime.py`, `src/research_loop/l05_curie_cli.py`, `tests/test_l05_curie_p1_planning.py`, `tests/test_l05_curie_europepmc_runtime.py`.

**Interfaces:** `prepare_scientific_query_plan_request(seed: dict, *, reformulation_index: int, feedback: dict | None) -> dict` returns the current prompt, `_PROPOSAL_SCHEMA`, and exact seed/feedback/previous-plan hashes; `validate_scientific_query_plan_response(seed: dict, *, request: dict, raw_response: bytes) -> dict` yields `PLAN|NO_ADMISSIBLE_REPLAN|REPROPOSAL_REQUIRED` with RLR-owned provenance. `REPROPOSAL_REQUIRED` carries the existing enumerated candidate set and a separate next-request prompt. The existing `propose_scientific_query_plan()` remains the headless adapter around these shared pure functions. Acquisition `prepare/submit/continue` enters through the current first-acquisition owner, never an independent planner runner.

- [ ] **Step 1 — Write RED tests:** Test a complete host PLAN, feedback replan, valid `NO_ADMISSIBLE_REPLAN`, invalid initial no-plan, repeated plan/query, false model provenance, stale feedback hash, and missing required prompt/schema bytes. Assert current `validate_scientific_query_plan()`, `_validated_v2()` and `compile_scientific_query_plan()` determine the result; model payload cannot set RLR-owned identity/hash fields.
- [ ] **Step 2 — Confirm RED:** Run the new planner tests and record failures at the absent prepare/submit seam.
- [ ] **Step 3 — Implement:** Split prompt/transport construction from model invocation and scientific decision. Record one immutable planner request and raw response per proposal. An invalid no-plan requiring the existing second proposal becomes a separate request/submit checkpoint; retain the existing proposal budget and replan enumeration. Run the same validation and compiler in both modes. Preserve headless structured-execution receipts and their exact parser behavior.
- [ ] **Step 4 — Confirm GREEN:** Run `tests/test_l05_curie_p1_planning.py`, `tests/test_l05_curie_p1_structured_execution.py`, and planner-specific cases in `tests/test_l05_curie_europepmc_runtime.py`. Compare headless and host accepted PLAN/query content hashes using the same seed and proposal bytes.

### Task 5: L0.5 retrieval, semantic handoff, manifest, and exact recovery

**Files:** Modify `src/research_loop/l05_curie/europepmc_runtime.py`, `src/research_loop/l05_curie_cli.py`, `tests/test_l05_curie_europepmc_runtime.py`, `tests/test_l05_curie_semantic_verifier.py`, `tests/test_l05_curie_p1_wiring.py`.

**Interfaces:** The current first-acquisition owner exposes `prepare_acquisition_host_step(project, cand, *, run_id=None) -> dict`, `submit_acquisition_host_response(project, cand, request_id, response_path) -> dict`, and `continue_acquisition(project, cand, *, run_id=None) -> dict`. Each returns `needs_host|deterministic|FROZEN|INSUFFICIENT_STOP|blocked`. Checkpoints are versioned, reference exact immutable request/response/source artifacts, and use `REQUEST_PREPARED → RESPONSE_RECORDED → VALIDATED → COMMITTED`; the same owner validates both host and headless receipt variants.

- [ ] **Step 1 — Write RED tests:** Simulate interruption at each persisted phase and verify resume uses the same attempt and no duplicate committed query, HTTP request, source snapshot, semantic decision, or freeze. Assert old incomplete remnants without a valid versioned checkpoint still fail closed; owner/seed/feedback/source hash tampering fails. An active acquisition owner bound to headless cannot accept a host response (and vice versa). Test HTTP-sent/no-durable-response gives `blocked: uncertain_external_result` with zero automatic retry.
- [ ] **Step 2 — Write RED tests:** For one `LOCATED` extract, assert request binds exact extract/claim/source hash; host returns only `entailment`, `scope_match`, `context_preserved`, `qualification_preserved`, `reason`; current `SemanticEvidenceVerifier.verify()` and `admit_reasoning_evidence()` decide verdict/admission. Tampered extract and forbidden verdict/source-fidelity fields fail. No `LOCATED` extract produces no semantic request. Manifest validates exact planner, query, retrieval, source, verification and admission chain for both receipt versions.
- [ ] **Step 3 — Confirm RED:** Run the new acquisition/semantic tests and record the first relevant checkpoint or receipt-dispatch failure.
- [ ] **Step 4 — Implement:** Extend the existing attempt loop to return at handoff checkpoints and resume from explicit checkpoint references. Bind each active owner to one execution mode. Keep `_first_acquisition_writer`, owner identity, query compiler, recorded HTTP/source receipts, source verifier, semantic verifier, coverage and freeze paths. Make `_validate_acquisition_manifest()` dispatch receipt versions but share identity/hash rules. Do not infer checkpoint state by directory scan.
- [ ] **Step 5 — Confirm GREEN:** Run all `tests/test_l05_curie_*.py` and the L0.5 runner tests. Inspect checkpoint and manifest references. Ensure tests count actual `http_get` invocations rather than inferring exactly-once from a manifest.

### Task 6: Cover every remaining cognition seam before enabling agent-native

**Files:** Modify `src/run_loop.py`, `src/research_loop/commands/research.py`, `src/research_loop/deep_research.py`, `src/research_loop/l4_evidence_bundle.py`, `src/research_loop/l85_literature_verification.py` only where the native path invokes cognition; modify `tests/test_deep_research_persistence_integrity.py`, `tests/test_native_l4_evidence_authority.py`, `tests/test_run_loop_receipts.py`, `tests/test_agent_native_loop.py`.

**Interfaces:** Each reached L4/L8.5 literature, other pre-research text, L7 text/analysis preparation, ordinary L7 delta, and REVIEW cognition stage returns a Task 2 host request and has one submit boundary back into its existing persistence/validation owner. `agent_native_capabilities(profile_id: str) -> dict[str, bool]` enumerates every reachable cognitive stage of the bound native profile; entry fails before round mutation unless all required seams are implemented. `deep_research.persist_run()` currently requires real `exit_code`, `command_hash`, and `prompt_hash`; its receipt validator must gain a versioned host-session branch that binds the actual host request/response, while preserving the existing command branch unchanged.

- [ ] **Step 1 — Write RED tests:** Test a profile with every reachable cognition stage; capability gate fails if any stage is missing, before provider startup or first node mutation. Insert provider-call sentinels for L4/L8.5 `deep-research-run`, `run_text`, L7 and REVIEW: agent-native never invokes them. Test the existing L1 frozen binding and L9a/L9b serial context rules remain in force.
- [ ] **Step 2 — Write RED tests:** Test host literature and plain-text submissions flow through current `deep_research.persist_run()`/audit, native L4B/L8.5 validators, pre-research target, and REVIEW schema/StopPolicy. Host literature receipt must not fabricate `exit_code` or command hashes. A malformed REVIEW response is a blocker, not a silent skipped review; an optional review disabled by policy remains disabled. L7 must still use `execution-gate`, the controlled workspace, exact script/output manifest and `emit-delta` before `EXECUTED` decision.
- [ ] **Step 3 — Confirm RED:** Run the new capability/evidence/REVIEW/L7 tests and confirm failures are at missing host seams or receipt version dispatch.
- [ ] **Step 4 — Implement:** Move only model-calling seams behind request/submit. Extend the existing `deep_research.persist_run()` receipt validation and audit for a truthful versioned host receipt; preserve deterministic retrieval, evidence persistence, source audit, workspace preparation and reporting commands. Add the complete capability gate; do not enable agent-native with partial stage coverage or a model fallback.
- [ ] **Step 5 — Confirm GREEN:** Run the named Task 6 tests plus `tests/test_deep_research.py`, `tests/test_l45_context_binding.py`, `tests/test_l45_ledger_integration.py`, and L7/REVIEW runner tests. Inspect subprocess spies for zero nested model invocations in every reached host stage.

### Task 7: Continuous host protocol, resume, explicit headless mode, and documentation

**Files:** Modify `src/run_loop.py`, `src/research_loop/api.py`, `AGENTS.md`, `docs/AGENT_CONTEXT.md`; create `docs/AGENT_NATIVE_RUN.md`; modify `tests/test_agent_native_loop.py`, `tests/test_root_run_loop_entrypoint.py`, `tests/test_engine_api.py`, `tests/test_run_loop_guards.py`.

**Interfaces:** Add runner commands `host-next PROJECT CANDIDATE` and `host-submit PROJECT CANDIDATE REQUEST_ID RESPONSE_PATH` (with explicit `--config`, `--knowledge-store` and `--resume` as applicable). `host-next` returns exactly one typed action: `needs_host` with request path/hash, `continued` after deterministic commit, `terminal`, or `blocked` with reason. The host session repeats `host-next → cognition only for needs_host → host-submit` until terminal/blocked. Commands do not invoke a model themselves. Existing `run PROJECT CANDIDATE` remains the explicit headless path.

- [ ] **Step 1 — Write RED tests:** Test one instruction's protocol through at least two ordinary nodes, L0.5 handoffs, REVIEW and round-end StopPolicy; no per-node user prompt. Test interruption after response recording, after commit and before advance, and after round finalization: resume consults RLR state and does not duplicate a committed action. Test a real blocker, an approval-required action and a protocol-required human decision each stop before dependent work. Test explicit headless still launches its configured provider; agent-native ignores provider config except relevant deterministic settings and does not require model key/binding. Test no implicit `main_agent` alias.
- [ ] **Step 2 — Confirm RED:** Run the new host CLI/loop tests and record failures at the missing commands or resume path.
- [ ] **Step 3 — Implement:** Expose the two host commands over Task 1's shared controller/Task 2's handoff. Keep `run_round()`, `run_review_gate()`, StopPolicy, `create_child()`, and terminal record owners for both modes; route their cognition seams through the host contract where applicable. Document the host instruction in `AGENT_NATIVE_RUN.md` and add a short `AGENTS.md`/`AGENT_CONTEXT.md` pointer so “运行 RLR” selects this protocol. Document that current-session context separation is by authorized artifacts, not physical memory erasure, and that a dead host process needs reactivation.
- [ ] **Step 4 — Confirm GREEN:** Run CLI help and targeted Task 7 tests. Confirm `host-next` can be called repeatedly after a committed step without another host request, and its `terminal` output matches the persisted RLR/StopPolicy state.

## Final Validation and Stop Gates

Run from `D:\research_loop\main` with `C:\Users\hk200\miniforge3\envs\rlr\python.exe`; preserve each RED/GREEN result. Replace the interpreter path only if current project instructions explicitly changed it. Execute narrow tests after each task, then these gates in order:

```powershell
& 'C:\Users\hk200\miniforge3\envs\rlr\python.exe' -m pytest tests/test_host_handoff.py tests/test_agent_native_loop.py tests/test_engine_api.py tests/test_run_loop_receipts.py tests/test_ledger_receipt_idempotency.py -q
& 'C:\Users\hk200\miniforge3\envs\rlr\python.exe' -m pytest tests/test_l05_curie_p1_planning.py tests/test_l05_curie_p1_structured_execution.py tests/test_l05_curie_europepmc_runtime.py tests/test_l05_curie_semantic_verifier.py tests/test_l05_curie_p1_wiring.py -q
& 'C:\Users\hk200\miniforge3\envs\rlr\python.exe' -m pytest tests/test_context_isolation.py tests/test_native_l4_evidence_authority.py tests/test_deep_research_persistence_integrity.py tests/test_l45_context_binding.py tests/test_l45_ledger_integration.py tests/test_root_run_loop_entrypoint.py -q
& 'C:\Users\hk200\miniforge3\envs\rlr\python.exe' -m pytest -q
& 'C:\Users\hk200\miniforge3\envs\rlr\python.exe' tools/external_reuse_gate.py validate docs/architecture/external-reuse/2026-09-28-agent-native-continuous-loop.json
& 'C:\Users\hk200\miniforge3\envs\rlr\python.exe' tools/external_reuse_gate.py check --repo-root . --changed $ChangedPaths --diff-known true
git diff --check
git status --short
```

Before the governance check, set `$ChangedPaths` to a temporary UTF-8 file containing the **actual** implementation files plus the new audit artifact, including untracked files. Separate pre-existing P1 strict-schema changes from this change set. Use current repo instructions for any additional scope/closure gate; do not treat the earlier P1 strict-schema results as tests of this feature. Offline tests prove local behavior, not live external acceptance. Obtain separate authorization before one real agent-native workflow acceptance run; its evidence must include actual host-session receipts, no nested model processes, and truthful external retrieval/verification provenance.

Stop on the first failed RED explanation, invalid authority boundary, missing capability seam, unexpected model dispatch, uncertain HTTP outcome, failed required regression/governance gate, or worktree conflict. Report completed and unattempted phases accurately. Do not stage, commit, push, run a production DAG, or run live smoke while merely executing this plan unless the user separately authorizes those actions.
