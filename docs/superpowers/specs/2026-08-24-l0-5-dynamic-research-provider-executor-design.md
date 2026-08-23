# L0.5 Dynamic Research and Provider Execution Design

## Goal

Close the three remaining architecture gaps as one coherent change:

1. Make literature discovery a first-class `L0.5` DAG node owned by Curie.
2. Remove project/domain-specific pre-research query literals from active runtime configuration and derive research/code-search queries from authoritative current state.
3. Route external provider/research process execution through one `ProviderExecutor` boundary while retaining the existing `RunReceipt/v1` provenance contract.

## Architecture

The canonical early-stage flow becomes:

`L0 (Linnaeus) -> L0.5 (Curie research) -> L1 (Einstein hypothesis generation)`

L0 remains the sole semantic authority for the scientific question/current-round hypothesis. L0.5 is a research node, not a cognitive-delta node: it consumes the canonical `ResearchSeed`, performs Deep Research, persists a validated immutable EvidencePack, and binds the exact ResearchSeed hash to the exact evidence-run hash. L1 has no direct literature/Knowledge Base authority and consumes only the frozen L0.5 evidence handoff.

The state machine does not gain a new candidate status. L0.5 executes while the candidate is `IDEA_PROPOSED`; completion is defined by a valid ResearchSeed -> L0.5 EvidencePack binding, not by a synthetic L0.5 delta. `next-step` therefore treats L0.5 as complete only when that authoritative artifact validates.

## L0.5 contract

Topology entry:

- `node`: `L0.5`
- `persona`: `Curie`
- `status_before`: `IDEA_PROPOSED`
- `node_kind`: `research`
- `research_required`: `true`
- `research_persona`: `Curie`
- `pre_research`: `deep_research`
- `context_inputs`: `L0`
- Knowledge Base authority: `read-write`
- No cognitive provider delta and no candidate-status transition.

The L1 topology entry no longer owns `pre_research`; it receives L0 + the validated frozen L0.5 evidence via context assembly.

Deep Research accepts `L0.5` as the discovery stage. New native runs are persisted under the L0.5 stage identity. Existing legacy L1 evidence remains readable only for compatibility; it is not the canonical path for new native runs.

## Dynamic query policy

`PRE_RESEARCH_MAP` is policy/configuration only. Active runtime entries must not contain project-specific query strings such as heart-rate, cardiac, WGCNA, bat, shrew, module-preservation, or ECM examples.

All active entries use `queries: []` and derive search intent at execution time:

- L0.5: canonical L0 scientific question + current-round hypothesis.
- L4: canonical question + selected hypotheses + method-design objective; the research agent derives methodology queries.
- L7: approved L6 strategy/scripts-needed + current project question; the code-search agent derives package/repository queries.
- L8.5: concrete L7 results + L8 evidence audit; the verification agent derives confirmation/contradiction queries.

The query log in the persisted research artifact remains the authority for what was actually searched. Zero-result searches must still be recorded.

## ProviderExecutor

Add one stdlib-only execution boundary under `research_loop.providers`:

- `ProviderExecutor.run(...)`
- consistent text-mode stdout/stderr capture
- explicit timeout handling
- explicit shell/cwd/env/stdin support
- fail-loud `ProviderExecutionError` with command, return code, stdout, stderr, and timeout context
- return a small immutable `ProviderExecutionResult`

The executor does not replace `RunReceipt`. `RunReceipt/v1` remains the durable provenance artifact for provider/node execution. ProviderExecutor standardizes process execution; RunReceipt records the scientific/runtime provenance of the resulting node call.

Core external model/tool subprocesses must route through ProviderExecutor, including command/headless providers and Deep Research CLI execution. Internal controller self-invocation may keep its EngineAPI boundary; it is not an external provider/tool call.

## Fail-closed rules

- L1 cannot run without a valid exact L0.5 evidence binding for the current ResearchSeed.
- A changed L0 contract invalidates the old L0.5 evidence binding.
- A changed/tampered evidence run invalidates the binding.
- L0.5 never silently falls back to candidate frontmatter question/claim.
- No hardcoded business-domain query may appear in active pre-research configuration.
- Provider timeout/non-zero exit/launch failure is normalized by ProviderExecutor and never silently treated as success.

## Compatibility

- Preserve existing public provider imports and `RunReceipt/v1`.
- Preserve current candidate statuses and downstream L1-L10 semantics.
- Legacy project artifacts may be read where existing compatibility code already permits it; new native runs use L0.5.
- No LoopX changes.

## Verification

Required regressions:

1. Native topology sequence contains `L0`, `L0.5`, `L1` in that order and L0.5 is a research node.
2. L1 no longer declares pre-research ownership or direct Knowledge Base authority.
3. `next-step` returns L0.5 after L0 until a valid exact L0.5 binding exists, then returns L1.
4. L0.5 Deep Research dispatch uses only canonical L0 ResearchSeed semantics.
5. L1 context/receipt gates validate the exact L0.5 evidence run.
6. Every active `PRE_RESEARCH_MAP` query list is empty and contains no project-specific literals.
7. L4/L7/L8.5 prompt generation instructs dynamic derivation from current authoritative artifacts/results rather than seed queries.
8. ProviderExecutor normalizes success, non-zero exit, timeout, and launch failure.
9. Command/headless provider and Deep Research execution paths call ProviderExecutor rather than `subprocess.run` directly.
10. Full regression suite and targeted Deep Research/provider/L4 tests pass; `git diff --check` passes.
